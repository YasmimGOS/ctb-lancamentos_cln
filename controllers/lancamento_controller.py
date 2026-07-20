"""Orquestracao do fluxo LancamentoCLN (pipeline de 5-7 etapas).

Espelha a arvore do Power Automate, com bloqueios ANTES do lancamento
(reembolso, APOLICE, CNPJ, 7 dias) - mais robusto que tratar no erro 400.

LOGS DETALHADOS: Cada etapa do processamento é logada para facilitar debug.

PALIATIVO PROVISÓRIO ATIVO (ver "Validação 10: PIS/COFINS reconhecidos" em
_validar_e_lancar_payload): pedidos com PIS/COFINS reconhecidos NÃO são lançados - vão para
lançamento manual e ficam registrados no BD com status "Provisorio" para não reprocessar.
Isso existe só porque ainda não há solução técnica confiável para lançar PIS/COFINS corretamente.
Quando a TI resolver, remover esse bloco e services/business_rules.py::eh_pis_cofins_reconhecido.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from config import (
    ARQUIVOS_PROTEGIDOS_SENHA, CNPJ_CORRETO_POR_FANTASIA, CNPJ_TOMADOR_CORRETO_POR_FANTASIA,
    CNPJ_VIBRA_ENERGIA, FANTASIAS_EXECUCAO_MANUAL, FANTASIAS_PROVAVEL_SENHA, get_settings,
)
from models import ResultadoPedido
from services import business_rules as br
from services import etl_service as etl
from services import power_flow
from services.ia_service import IaService
from services.integra_bpms_service import IntegraBpmsService
from services.integra_megaintegrador_service import IntegraMegaIntegradorService
from services.notification_service import NotificationService
from utils import formatter as fmt
from utils import get_logger, sanitize_emoji
from utils import validators as val

log = get_logger("controller")
IMAGENS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif")


class LancamentoController:
    def __init__(self, settings=None, bpms=None, mega=None, ia=None, teams=None):
        self.s = settings or get_settings()
        self.id_disparo = fmt.id_disparo(self.s.timezone)
        self.bpms = bpms or IntegraBpmsService(self.s)
        self.mega = mega or IntegraMegaIntegradorService(self.s)
        self.ia = ia or IaService(self.s)
        self.teams = teams or NotificationService(self.s, self.id_disparo)

    def executar_lote(self) -> list[ResultadoPedido]:
        log.info(sanitize_emoji("🚀 Iniciando obtenção de lista de pedidos..."))
        try:
            lista = self.bpms.obter_lista_pedidos()
        except Exception as exc:  # noqa: BLE001
            log.exception(sanitize_emoji("❌ Falha ao obter lista de pedidos: %s"), exc)
            self.teams.erro_obter_pedidos()
            return []

        if not lista:
            log.info(sanitize_emoji("ℹ️  Nenhum pedido aguardando CLN."))
            return []

        log.info(sanitize_emoji("✓ Lista de pedidos obtida: %d pedido(s) disponível(is)"), len(lista))

        pedidos = power_flow.selecionar_pedidos(lista, self.s.filtro_pedidos_list, self.s.limite_pedidos)
        log.info(sanitize_emoji("📋 Pedidos selecionados para processamento: %d"), len(pedidos))

        workers = max(1, int(self.s.max_workers))
        if workers == 1 or len(pedidos) <= 1:
            resultados_por_pedido = [self._processar_seguro(p) for p in pedidos]
        else:
            log.info(sanitize_emoji("🔀 Processando %s pedido(s) em paralelo (max_workers=%s)."), len(pedidos), workers)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                resultados_por_pedido = list(pool.map(self._processar_seguro, pedidos))

        return [r for lote in resultados_por_pedido for r in lote]

    def _processar_seguro(self, pedido: dict) -> list[ResultadoPedido]:
        """Isola falhas: um pedido com erro nao derruba o lote inteiro."""
        try:
            return self.processar_pedido(pedido)
        except Exception as exc:  # noqa: BLE001
            pdc = pedido.get("PDC_IN_CODIGO")
            log.exception(sanitize_emoji("💥 Erro inesperado ao processar pedido %s: %s"), pdc, exc)
            return [ResultadoPedido(pedido=pdc, filial=pedido.get("FIL_IN_CODIGO"),
                                   deve_lancar=False, status="Excecao", mensagem=str(exc))]

    def processar_pedido(self, pedido: dict) -> list[ResultadoPedido]:
        pdc = pedido.get("PDC_IN_CODIGO")
        filial = pedido.get("FIL_IN_CODIGO")
        agente = pedido.get("AGN_IN_CODIGO")
        organizacao = pedido.get("ORG_IN_CODIGO")
        fantasia = pedido.get("AGN_ST_FANTASIA", "")
        nome_filial_pedido = pedido.get("FIL_ST_FANTASIA", "")
        cond_pagto = pedido.get("COND_ST_CODIGO", "")

        # Criar identificador completo para registro no BD: ORG-PDC-AGN
        num_pedido_bd = f"{organizacao}-{pdc}-{agente}"

        log.info("")
        log.info("╔" + "═" * 98 + "╗")
        log.info("║" + f" PROCESSANDO PEDIDO {pdc}".center(98) + "║")
        log.info("╠" + "═" * 98 + "╣")
        log.info("║ ID BD: %-89s ║", num_pedido_bd)
        log.info("║ Filial: %-87s ║", filial)
        log.info("║ Agente: %-87s ║", agente)
        log.info("║ Fantasia: %-85s ║", fantasia)
        log.info("║ Cond. Pagto: %-82s ║", cond_pagto)
        log.info("╚" + "═" * 98 + "╝")

        res = ResultadoPedido(pedido=pdc, filial=filial)

        # ═══════════════════════════════════════════════════════════════════
        # VERIFICAÇÃO INICIAL: Consultar se pedido já foi processado
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[VERIFICAÇÃO PRÉVIA] 🔍 Consultando se pedido %s já foi processado no BD..."), num_pedido_bd)
        try:
            registros_bd = self.bpms.consultar_bd(num_pedido_bd)
            if registros_bd:
                log.info(sanitize_emoji("  ⏭️  Pedido %s já consta no BD. Pulando processamento."), num_pedido_bd)
                res.status = "JaProcessado"
                res.deve_lancar = False
                log.info("  └─ Status final: %s", res.status)
                return [res]
            log.info(sanitize_emoji("  ✓ Pedido não encontrado no BD. Prosseguindo com processamento."))
        except Exception as exc:  # noqa: BLE001
            log.exception(sanitize_emoji("  ⚠️  Erro ao consultar BD para pedido %s: %s. Prosseguindo mesmo assim."), num_pedido_bd, exc)

        # ═══════════════════════════════════════════════════════════════════
        # VERIFICAÇÃO PRÉVIA: Fornecedor com fatura fora do padrão (execução manual)
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[VERIFICAÇÃO PRÉVIA] 🔍 Verificando se fornecedor exige execução manual..."))
        if br.eh_fatura_execucao_manual(fantasia, FANTASIAS_EXECUCAO_MANUAL):
            log.warning(sanitize_emoji("  ⚠️  Fornecedor %s foge do padrão de documento do RPA - bloqueio ativado"), fantasia)
            msg = "Fatura de serviço desse fornecedor foge do padrão de documento previsto para o RPA - requer lançamento manual"
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra={"Fornecedor": fantasia})
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro=f"Motivo: Fornecedor {fantasia} foge do padrao de documento do RPA - lancamento manual")
            res.deve_lancar = False
            res.status = "ExecucaoManual"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return [res]
        log.info(sanitize_emoji("  ✓ Fornecedor dentro do padrão"))

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 1: Verificar REEMBOLSO
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 1/7] 🔍 Verificando se é REEMBOLSO..."))
        if br.eh_reembolso(fantasia):
            log.warning(sanitize_emoji("  ⚠️  Pedido %s identificado como REEMBOLSO - bloqueio ativado"), pdc)
            self.teams.aviso("Pedido identificado como REEMBOLSO. NÃO será lançado automaticamente", pedido=pdc, tipo_negocio=True)
            res.deve_lancar = False
            res.status = "Reembolso"
            log.info("  └─ Status final: %s", res.status)
            return [res]
        log.info(sanitize_emoji("  ✓ Não é reembolso"))

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 2: Obter Dados do Pedido
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 2/7] 📦 Obtendo dados detalhados do pedido..."))
        try:
            dados_pedido = self.bpms.obter_dados_pedido(filial, pdc)
        except Exception as exc:  # noqa: BLE001
            log.exception(sanitize_emoji("  ❌ Erro ao obter dados do pedido %s: %s"), pdc, exc)
            self.teams.erro("Falha ao obter dados detalhados do pedido", pedido=pdc, tecnico=True)
            res.status = "ErroDadosPedido"
            log.info("  └─ Status final: %s", res.status)
            return [res]

        if not dados_pedido:
            log.error(sanitize_emoji("  ❌ Dados do pedido %s não encontrados"), pdc)
            self.teams.erro("Dados do pedido não encontrados", pedido=pdc, tecnico=True)
            res.status = "ErroDadosPedido"
            log.info("  └─ Status final: %s", res.status)
            return [res]

        log.info(sanitize_emoji("  ✓ Dados do pedido obtidos: %d item(ns)"), len(dados_pedido))
        log.info("  ├─ Item 1: Produto=%s, Qtd=%s, Valor=%s",
                 dados_pedido[0].get("PRODUTO", ""),
                 dados_pedido[0].get("QUANTIDADE_PEDIDO", ""),
                 dados_pedido[0].get("VALOR_TOTAL_ITEM_PEDIDO", ""))
        log.info("  ├─ Centro Custo: %s", dados_pedido[0].get("CC_PADRAO", ""))
        log.info("  └─ Projeto: %s", dados_pedido[0].get("PROJ_PADRAO", ""))

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 3: Consultar Anexos
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 3/7] 📎 Consultando anexos do pedido..."))
        try:
            anexos = self.bpms.consultar_anexos(filial, agente, pdc, fmt.hoje_br(self.s.timezone))
        except Exception as exc:  # noqa: BLE001
            log.exception(sanitize_emoji("  ❌ Erro ao consultar anexos do pedido %s: %s"), pdc, exc)
            self.teams.erro_consultar_anexos(pdc)
            res.status = "ErroAnexos"
            log.info("  └─ Status final: %s", res.status)
            return [res]

        log.info(sanitize_emoji("  ✓ Anexos consultados: %d arquivo(s)"), len(anexos))

        cnpj_forn = val.normaliza_cnpj(dados_pedido[0].get("CNPJ_CPF_FORNECEDOR", ""))
        cnpj_filial = val.normaliza_cnpj(dados_pedido[0].get("CNPJ_CPF_FILIAL", ""))
        log.info("  ├─ CNPJ Fornecedor (esperado): %s", cnpj_forn)
        log.info("  └─ CNPJ Filial (esperado): %s", cnpj_filial)

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 4: Processar Anexos com IA
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 4/7] 🤖 Processando anexos com IA..."))
        payloads: list[dict] = []
        contexto: dict[str, Any] = {}
        anexos_imagem: list[str] = []
        anexos_protegidos: list[str] = []

        for idx, anexo in enumerate(anexos, 1):
            log.info("  ┌─ Anexo %d/%d", idx, len(anexos))
            nome = str(anexo.get("nomeArquivo", ""))
            log.info("  ├─ Arquivo: %s", nome)

            # Verificar se é anexo com padrão conhecido de PDF protegido por senha (a IA nunca
            # consegue ler, então nem tenta - evita esperar o timeout de ~7min para só então falhar)
            if br.eh_anexo_protegido_por_senha(nome, ARQUIVOS_PROTEGIDOS_SENHA):
                log.warning(sanitize_emoji("  ├─ ⚠️  Arquivo protegido por senha, leitura pela IA não é possível"))
                anexos_protegidos.append(nome)
                self.teams.erro_anexo_protegido_senha(pdc, nome)
                log.info("  └─")
                continue

            # Verificar se é imagem
            if nome.lower().endswith(IMAGENS):
                log.warning(sanitize_emoji("  ├─ ⚠️  Arquivo com extensão de imagem, não é processado pelo RPA"))
                anexos_imagem.append(nome)
                detalhes_img = {"Arquivo": nome}
                self.teams.aviso("Arquivo com extensão de imagem não é processado pelo RPA - requer execução manual",
                                  pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_img)
                log.info("  └─")
                continue

            base64_pdf = anexo.get("anexoBase64", "")
            log.info("  ├─ Base64 PDF: %d caracteres", len(base64_pdf))

            # Extração primária
            log.info(sanitize_emoji("  ├─ 🧠 Executando extração primária (IA 1ª chamada)..."))
            try:
                ia_raw = self.ia.extrair_primaria(base64_pdf)
                log.info(sanitize_emoji("  │  ✓ Extração primária concluída"))
                log.info("  │  ├─ tipoDocFiscal: %s", ia_raw.get("tipoDocFiscal", ""))
                log.info("  │  ├─ numNota: %s", ia_raw.get("numNota", ""))
                log.info("  │  ├─ valorTotalDocumento: %s", ia_raw.get("valorTotalDocumento", ""))
                log.info("  │  ├─ cnpjEmitente: %s", ia_raw.get("cnpjEmitente", ""))
                log.info("  │  └─ JSON completo da IA (primária):")
                log.info("  │     %s", json.dumps(ia_raw, indent=2, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                if br.eh_fornecedor_provavel_senha(fantasia, FANTASIAS_PROVAVEL_SENHA):
                    # Não é falha de execução do nosso código - fornecedor cujas faturas quase
                    # sempre vêm protegidas por senha (ex.: TIM S/A), mesmo quando o nome do
                    # arquivo não bateu com nenhum termo de ARQUIVOS_PROTEGIDOS_SENHA.
                    log.warning(sanitize_emoji("  │  ⚠️  Falha ao ler anexo do fornecedor %s "
                                                "(provável PDF protegido por senha): %s"), fantasia, exc)
                    anexos_protegidos.append(nome)
                    self.teams.erro_anexo_protegido_senha(pdc, nome)
                else:
                    log.exception(sanitize_emoji("  │  ❌ Erro ao enviar Base64 para IA (pedido %s): %s"), pdc, exc)
                    self.teams.erro_ia_envio(pdc, nome)
                log.info("  └─")
                continue

            # Extração extra
            log.info(sanitize_emoji("  ├─ 🧠 Executando extração extra (IA 2ª chamada)..."))
            try:
                extra_raw = self.ia.extrair_extra(base64_pdf)
                log.info(sanitize_emoji("  │  ✓ Extração extra concluída"))
                log.info("  │  ├─ issRetido: %s", extra_raw.get("issRetido", False))
                log.info("  │  ├─ valorISSRetido: %s", extra_raw.get("valorISSRetido", "0.00"))
                log.info("  │  ├─ cnpjCpfTomador: %s", extra_raw.get("cnpjCpfTomador", ""))
                log.info("  │  └─ JSON completo da IA (extra):")
                log.info("  │     %s", json.dumps(extra_raw, indent=2, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                log.exception(sanitize_emoji("  │  ❌ Erro ao capturar resultado da IA (pedido %s): %s"), pdc, exc)
                self.teams.erro_ia_resultado(pdc)
                log.info("  └─")
                continue

            # Extração Equatorial (3a chamada, condicional) - só para faturas de energia elétrica
            # do fornecedor Equatorial (ver docs/REGRAS_PROJETO.md secao 3.11). Extrai os valores
            # individuais das seções FORNECIMENTO e ITENS FINANCEIROS da fatura, usados para
            # calcular valorMercadoria/totalDespesa/valorDescontoGeral corretamente (o template
            # genérico da extração primária não tem esses campos e deixa valorMercadoria = 0.00
            # para esse tipo de documento).
            equatorial_raw: dict = {}
            if br.eh_fornecedor_equatorial(fantasia):
                log.info(sanitize_emoji("  ├─ 🧠 Executando extração Equatorial (IA 3ª chamada, FORNECIMENTO/ITENS FINANCEIROS)..."))
                try:
                    equatorial_raw = self.ia.extrair_equatorial(base64_pdf)
                    log.info(sanitize_emoji("  │  ✓ Extração Equatorial concluída"))
                    log.info("  │  ├─ totalFornecimento: %s", equatorial_raw.get("totalFornecimento", ""))
                    log.info("  │  └─ itensFinanceiros: %s", equatorial_raw.get("itensFinanceiros", []))
                except Exception as exc:  # noqa: BLE001
                    log.exception(sanitize_emoji("  │  ⚠️  Erro na extração Equatorial (pedido %s): %s - "
                                                 "seguindo sem essa correção"), pdc, exc)
                    equatorial_raw = {}

            # Consolidar resposta IA
            log.info(sanitize_emoji("  ├─ 🔄 Consolidando respostas IA..."))
            ia_final, cnpj_emit, cnpj_tom, tipo_doc = etl.consolidar_resposta_ia(ia_raw, extra_raw, pdc)

            # Corrigir CNPJ do emitente para fornecedores que a IA erra com frequência (de-para
            # fixo em config/settings.py::CNPJ_CORRETO_POR_FANTASIA)
            cnpj_emit_corrigido = br.resolver_cnpj_emitente_corrigido(fantasia, cnpj_emit, CNPJ_CORRETO_POR_FANTASIA)
            if cnpj_emit_corrigido != cnpj_emit:
                log.info(sanitize_emoji("  │  ℹ️  CNPJ emitente corrigido via de-para (fornecedor %s): %s -> %s"),
                         fantasia, cnpj_emit, cnpj_emit_corrigido)
                cnpj_emit = cnpj_emit_corrigido
                ia_final["cnpjEmitente"] = cnpj_emit

            # Corrigir CNPJ do tomador para fornecedores que a IA erra com frequência (de-para
            # fixo em config/settings.py::CNPJ_TOMADOR_CORRETO_POR_FANTASIA - ex.: fatura de
            # energia sem seção "Tomador" explícita, caso real Energisa Tocantins/pedido 25997)
            cnpj_tom_corrigido = br.resolver_cnpj_tomador_corrigido(fantasia, cnpj_tom, CNPJ_TOMADOR_CORRETO_POR_FANTASIA)
            if cnpj_tom_corrigido != cnpj_tom:
                log.info(sanitize_emoji("  │  ℹ️  CNPJ tomador corrigido via de-para (fornecedor %s): %s -> %s"),
                         fantasia, cnpj_tom, cnpj_tom_corrigido)
                cnpj_tom = cnpj_tom_corrigido
                ia_final["cnpjCpfTomador"] = cnpj_tom

            # Corrigir emitente/tomador invertidos pela IA (comum em RECIBO/termo assinado por
            # pessoa física prestadora - ver services/business_rules.py::corrigir_emitente_tomador_invertidos)
            ia_final_corrigido = br.corrigir_emitente_tomador_invertidos(ia_final, cnpj_forn, cnpj_filial)
            if ia_final_corrigido is not ia_final:
                log.info(sanitize_emoji("  │  ℹ️  Emitente/Tomador invertidos pela IA - corrigido: "
                                        "emitente %s -> %s | tomador %s -> %s"),
                         cnpj_emit, ia_final_corrigido.get("cnpjEmitente", ""),
                         cnpj_tom, ia_final_corrigido.get("cnpjCpfTomador", ""))
                ia_final = ia_final_corrigido
                cnpj_emit = ia_final.get("cnpjEmitente", "")
                cnpj_tom = ia_final.get("cnpjCpfTomador", "")

            # Equatorial não deve mais ter PIS/COFINS retidos no lançamento (decisão de negócio,
            # não é o paliativo provisório da Validação 9 - aqui zeramos antes de montar o payload,
            # então o documento segue para lançamento automático normalmente).
            if br.eh_fornecedor_equatorial(fantasia):
                ia_final = br.zerar_pis_cofins(ia_final)
                log.info(sanitize_emoji("  │  ℹ️  Fornecedor Equatorial: PIS/COFINS zerados (não retidos no lançamento)"))
                org_fantasia = str(pedido.get("ORG_ST_FANTASIA", ""))
                if br.eh_filial_rapido_araguaia(org_fantasia):
                    ia_final = br.zerar_icms(ia_final)
                    log.info(sanitize_emoji("  │  ℹ️  Filial Rápido Araguaia + Equatorial: ICMS também zerado"))
                # Ver docs/REGRAS_PROJETO.md secao 3.11: valorMercadoria = totalFornecimento (lido
                # pronto da linha TOTAL da tabela "Itens da Fatura", nao mais somado linha a linha -
                # ver ATUALIZACAO 6); totalDespesa = soma dos ITENS FINANCEIROS positivos;
                # valorDescontoGeral = soma (em modulo) dos ITENS FINANCEIROS negativos.
                total_fornecimento = equatorial_raw.get("totalFornecimento", "")
                itens_financeiros = equatorial_raw.get("itensFinanceiros", [])
                if not total_fornecimento:
                    log.warning(sanitize_emoji("  │  ⚠️  Equatorial: extração de totalFornecimento veio vazia - "
                                               "valorMercadoria pode ficar incorreto"))
                ia_final = br.aplicar_valores_equatorial(ia_final, total_fornecimento, itens_financeiros)
                log.info("  │  ℹ️  Equatorial: valorMercadoria=%s (totalFornecimento), totalDespesa=%s, "
                         "valorDescontoGeral=%s", ia_final.get("valorMercadoria", ""),
                         ia_final.get("totalDespesa", ""), ia_final.get("valorDescontoGeral", ""))

                # Conferência obrigatória (ver docs/REGRAS_PROJETO.md secao 3.11): a extração das
                # seções FORNECIMENTO/ITENS FINANCEIROS já se mostrou pouco confiável em uma fatura
                # real (misturou a tabela "Itens da Fatura" com a caixa "Tributos" - valorMercadoria
                # saiu R$623,62 quando o correto era R$284,46). Nunca lançar automaticamente sem
                # essa reconciliação bater com o TOTAL da fatura.
                reconciliado, detalhe_reconciliacao = br.reconciliacao_equatorial(ia_final)
                if not reconciliado:
                    log.warning(sanitize_emoji("  │  ⚠️  Equatorial: extração FORNECIMENTO/ITENS FINANCEIROS "
                                               "não reconcilia com o total da fatura - %s"), detalhe_reconciliacao)
                    detalhes_equatorial = {
                        "Nota Fiscal": ia_final.get("numNota", ""),
                        "Motivo": detalhe_reconciliacao,
                        "totalFornecimento (extraído)": total_fornecimento,
                        "itensFinanceiros (extraídos)": json.dumps(itens_financeiros, ensure_ascii=False),
                    }
                    self.teams.aviso(
                        "Fatura de energia elétrica (Equatorial): a extração automática das seções "
                        "FORNECIMENTO/ITENS FINANCEIROS não bateu com o total da fatura - requer "
                        "conferência e lançamento manual (não lançado automaticamente por segurança)",
                        pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_equatorial)
                    log.info("  └─")
                    continue
            log.info(sanitize_emoji("  │  ✓ Consolidação concluída"))
            log.info("  │  ├─ Tipo Doc Final: %s", tipo_doc)
            log.info("  │  ├─ CNPJ Emitente: %s", cnpj_emit)
            log.info("  │  ├─ CNPJ Tomador: %s", cnpj_tom)
            log.info("  │  ├─ Num Nota Final: %s", ia_final.get("numNota", ""))
            log.info("  │  └─ JSON consolidado final (ia_final):")
            log.info("  │     %s", json.dumps(ia_final, indent=2, ensure_ascii=False))

            # Calcular ação e conta
            acao_conta = br.calcular_acao_e_conta(tipo_doc, cond_pagto)
            log.info(sanitize_emoji("  ├─ 💼 Ação e Conta calculadas"))
            log.info("  │  ├─ contasPagarTipoDoc: %s", acao_conta.get("contasPagarTipoDoc", ""))
            log.info("  │  └─ acao: %s", acao_conta.get("acao", ""))

            # Filtrar dados_pedido para VIBRA ENERGIA (1 PDF = 1 item do pedido)
            dados_pedido_filtrado = dados_pedido
            if cnpj_emit == CNPJ_VIBRA_ENERGIA and len(anexos) > 1:
                # Match pelo valorTotalDocumento da nota com VALOR_TOTAL_ITEM_PEDIDO
                valor_nota = fmt.to_float(ia_final.get("valorTotalDocumento", "0"))
                item_match = None

                # Criar lista de itens ainda não usados (rastreamento por índice)
                if not hasattr(res, '_itens_usados_vibra'):
                    res._itens_usados_vibra = set()

                for idx, dp in enumerate(dados_pedido):
                    if idx in res._itens_usados_vibra:
                        continue  # Item já usado em outro PDF

                    valor_item = fmt.to_float(dp.get("VALOR_TOTAL_ITEM_PEDIDO", "0"))
                    # Tolerância de 0.01 para comparação de floats
                    if abs(valor_nota - valor_item) < 0.01:
                        item_match = dp
                        res._itens_usados_vibra.add(idx)
                        log.info(sanitize_emoji("  │  ✓ Match VIBRA: Nota R$ %s -> Item %s (Pedido R$ %s)"),
                                fmt.format_number(valor_nota),
                                dp.get("ITEM_SEQUENCIA", ""),
                                fmt.format_number(valor_item))
                        break

                if item_match:
                    dados_pedido_filtrado = [item_match]
                else:
                    log.warning(sanitize_emoji("  │  ⚠️  VIBRA: Nenhum item do pedido match com valor R$ %s"),
                               fmt.format_number(valor_nota))

            # Montar payload
            log.info(sanitize_emoji("  ├─ 📝 Montando payload de recebimento..."))
            payload, bloq7, diverge_pedido_nf = etl.montar_payload(
                pedido, dados_pedido_filtrado, ia_final, cnpj_emit, tipo_doc, acao_conta, "", self.s.timezone,
                is_equatorial=br.eh_fornecedor_equatorial(fantasia))
            log.info(sanitize_emoji("  │  ✓ Payload montado"))
            log.info("  │  ├─ Bloqueio 7 dias: %s", bloq7)
            log.info("  │  ├─ Total Nota: %s", payload.get("totalNota", ""))
            log.info("  │  ├─ Valor Mercadoria: %s", payload.get("valorMercadoria", ""))
            log.info("  │  ├─ Num Itens: %d", len(payload.get("itensReceb", [])))
            if len(payload.get("itensReceb", [])) > 0:
                log.info("  │  ├─ Item[0] valorMercadoria: %s", payload["itensReceb"][0].get("valorMercadoria", ""))
            log.info("  │  └─ Chave Acesso: %s", payload.get("chaveAcesso", "")[:20] + "..." if payload.get("chaveAcesso") else "")

            # Armazenar payload com seu contexto correspondente
            contexto_payload = {
                "cnpj_emitente": cnpj_emit,
                "cnpj_tomador": cnpj_tom,
                "nome_tomador": ia_final.get("nomeTomador", ""),
                "tipo_doc": tipo_doc,
                "bloqueia_7d": bloq7,
                "diverge_pedido_nf": diverge_pedido_nf,
                "data_documento": ia_final.get("dataDocumento", ""),
                "cond_pagto": payload.get("condPagto", ""),
                "data_vencimento": ia_final.get("dataVencimento", ""),
                "almoxarifado": ia_final.get("almoxarifado", ""),
                # Guardados só para diagnostico/Teams da Validação 5B (Chave de Acesso) - não vão
                # para o payload do Mega.
                "chave_primaria_raw": str(ia_raw.get("chaveAcesso", "")).strip(),
                "chave_extra_raw": str(extra_raw.get("chaveAcesso", "")).strip(),
            }
            # Adicionar contexto ao payload para recuperação posterior
            payload["_contexto"] = contexto_payload
            payloads.append(payload)
            log.info("  └─ Anexo processado com sucesso")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 5: Selecionar Payloads a Lançar
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 5/7] 🎯 Processando payloads..."))

        # Log dos tipos de documentos encontrados
        if len(payloads) > 1:
            tipos = [p.get("tipoDocFiscal", "?") for p in payloads]
            log.info("  │  Tipos de documentos detectados: %s", ", ".join(tipos))

        # Pegar CNPJ emitente do primeiro payload (todos devem ter o mesmo emitente)
        cnpj_emit_final = payloads[0].get("_contexto", {}).get("cnpj_emitente", "") if payloads else ""

        if cnpj_emit_final == CNPJ_VIBRA_ENERGIA and len(payloads) > 1:
            # VIBRA ENERGIA: cada anexo é um lançamento independente (sem fusão)
            log.info(sanitize_emoji("  ✓ VIBRA ENERGIA com múltiplos anexos: %d lançamento(s) independente(s)"), len(payloads))
            payloads_para_lancar = payloads
        else:
            payload_priorizado = power_flow.priorizar_payload(payloads)
            payloads_para_lancar = [payload_priorizado] if payload_priorizado else []

        if not payloads_para_lancar:
            if anexos_imagem and len(anexos_imagem) == len(anexos):
                log.warning(sanitize_emoji("  ⚠️  Anexos são imagem - execução manual necessária"))
                self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                    erro="Arquivo com extensão de imagem")
                res.deve_lancar = False
                res.status = "ImagemManual"
                log.info("  └─ Status final: %s (registrado no BD)", res.status)
                return [res]
            if anexos_protegidos and len(anexos_protegidos) == len(anexos):
                # Não é falha de execução do nosso código - é um impedimento do próprio arquivo.
                # Já notificado no Teams (erro_anexo_protegido_senha) no momento em que o anexo
                # protegido foi detectado - não repetir com um segundo erro genérico aqui, só
                # registrar no BD (como Sucesso) para não reprocessar.
                log.warning(sanitize_emoji("  ⚠️  Anexos protegidos por senha - execução manual necessária"))
                erro_bd = ("Arquivo protegido por senha - não é possível a leitura pela IA. "
                           f"Arquivo: {', '.join(anexos_protegidos)}")
                self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd, erro=erro_bd)
                res.deve_lancar = False
                res.status = "SenhaProtegidaManual"
                log.info("  └─ Status final: %s (registrado no BD)", res.status)
                return [res]
            log.error(sanitize_emoji("  ❌ Nenhum payload válido gerado"))
            self.teams.erro_definir_payload(pdc)
            res.status = "SemPayload"
            log.info("  └─ Status final: %s", res.status)
            return [res]

        # Boletos anexos ao pedido (cada um pode ser uma parcela real do pagamento rateado)
        boletos = [
            {
                "valorTotalDocumento": p.get("totalNota", "0"),
                "dataVencimento": p.get("_contexto", {}).get("data_vencimento", ""),
            }
            for p in payloads if str(p.get("contasPagarTipoDoc", "")).startswith("BOLP")
        ]
        data_vencimento_boleto = next((b["dataVencimento"] for b in boletos if b["dataVencimento"]), "")

        # Candidatos de CNPJ emitente/tomador entre TODOS os anexos do pedido (redundância entre
        # NF + boletos da mesma transação, usada para tolerar erro de leitura da IA em um deles)
        cnpjs_emitente_pedido = [p.get("_contexto", {}).get("cnpj_emitente", "") for p in payloads]
        tomador_candidatos_pedido = [
            (p.get("_contexto", {}).get("cnpj_tomador", ""), p.get("_contexto", {}).get("nome_tomador", ""))
            for p in payloads
        ]

        resultados = [
            self._validar_e_lancar_payload(payload, pdc, filial, cnpj_forn, cnpj_filial, num_pedido_bd,
                                           data_vencimento_boleto, boletos, fantasia,
                                           cnpjs_emitente_pedido, tomador_candidatos_pedido,
                                           nome_filial_pedido)
            for payload in payloads_para_lancar
        ]
        return resultados

    def _validar_e_lancar_payload(self, payload: dict, pdc: Any, filial: Any, cnpj_forn: str,
                                   cnpj_filial: str, num_pedido_bd: str,
                                   data_vencimento_boleto: str = "", boletos: list[dict] | None = None,
                                   fantasia_pedido: str = "", cnpjs_emitente_pedido: list[str] | None = None,
                                   tomador_candidatos_pedido: list[tuple[str, str]] | None = None,
                                   nome_filial_pedido: str = "") -> ResultadoPedido:
        res = ResultadoPedido(pedido=pdc, filial=filial)
        contexto = payload.get("_contexto", {})
        log.info(sanitize_emoji("  ✓ Payload selecionado: tipoDocFiscal=%s"), payload.get("tipoDocFiscal", ""))
        res.tipoDocFiscal = contexto.get("tipo_doc", "")
        res.num_doc = payload.get("numNota", "")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 6: Validações de Negócio
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 6/7] ✅ Executando validações de negócio..."))

        # Validação: Apólice
        log.info("  ├─ Validação 1: Verificando se é APÓLICE...")
        if br.eh_apolice(contexto.get("tipo_doc", "")):
            log.warning(sanitize_emoji("  │  ⚠️  Documento é APÓLICE - bloqueio ativado"))
            self.teams.aviso("Documento identificado como Apólice de Seguro. NÃO será lançado automaticamente", pedido=pdc, tipo_negocio=True)
            res.deve_lancar = False
            res.status = "Apolice"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Não é apólice"))

        # Validação: Almoxarifado (TEMPORÁRIO - ver nota abaixo)
        # O Mega Integrador ainda não tem campo de Almoxarifado/Localização no payload de
        # recebimento. Enquanto a TI não adiciona esse campo, só avisamos e bloqueamos para
        # lançamento manual quando o documento menciona um Almoxarifado. Referência para quando
        # isso for resolvido: config/settings.py::ALMOXARIFADO_LOCALIZACAO e
        # services/business_rules.py::resolver_localizacao_almoxarifado - trocar este bloqueio por
        # preenchimento automático do campo correspondente no payload.
        log.info("  ├─ Validação 2: Verificando menção a Almoxarifado no documento...")
        almoxarifado = contexto.get("almoxarifado", "")
        if almoxarifado:
            localizacao = br.resolver_localizacao_almoxarifado(almoxarifado)
            log.warning(sanitize_emoji("  │  ⚠️  Documento menciona Almoxarifado %s - bloqueio manual ativado"), almoxarifado)
            msg = "Documento indica situação de Almoxarifado - lançamento requer análise manual"
            detalhes = {
                "Almoxarifado identificado no documento": almoxarifado,
                "Localização correspondente": localizacao or "não mapeada - revisar manualmente",
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro=f"Motivo: Almoxarifado {almoxarifado} identificado (localizacao={localizacao or 'nao mapeada'}) - lancamento manual")
            res.deve_lancar = False
            res.status = "AlmoxarifadoManual"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Sem menção a Almoxarifado"))

        # Validação: CNPJ Emitente x Fornecedor
        log.info("  ├─ Validação 3: CNPJ Emitente x Fornecedor...")
        log.info("  │  ├─ CNPJ Documento: %s", contexto["cnpj_emitente"])
        log.info("  │  └─ CNPJ Esperado: %s", cnpj_forn)
        emitente_ok = br.valida_emitente_x_fornecedor(contexto["cnpj_emitente"], cnpj_forn)
        cnpjs_pedido = cnpjs_emitente_pedido or [contexto["cnpj_emitente"]]

        # Se o documento selecionado não bateu, tenta a redundância entre os anexos do pedido
        # (ex: NF leu errado, mas os boletos da mesma transação leram o CNPJ certo)
        if not emitente_ok and br.valida_emitente_x_fornecedor_multi(cnpjs_pedido, cnpj_forn):
            log.info(sanitize_emoji("  │  ℹ️  CNPJ do documento selecionado divergente, mas outro anexo do pedido confirma o fornecedor"))
            emitente_ok = True

        # Se ainda não bateu, consulta o cadastro de fornecedor por CNPJ (nome fantasia) pra cada
        # CNPJ distinto lido entre os anexos - confirma se algum deles é realmente o fornecedor
        cnpj_confirmado_via_api = ""
        if not emitente_ok:
            candidatos_distintos = {val.normaliza_cnpj(c) for c in cnpjs_pedido if val.normaliza_cnpj(c)}
            for candidato in candidatos_distintos:
                dados_forn = self.bpms.consultar_fornecedor_por_cnpj(candidato)
                nomes = [d.get("AGN_ST_FANTASIA", "") for d in dados_forn] + [d.get("AGN_ST_NOME", "") for d in dados_forn]
                if br.nome_fornecedor_confere(nomes, fantasia_pedido):
                    emitente_ok = True
                    cnpj_confirmado_via_api = candidato
                    log.info(sanitize_emoji("  │  ℹ️  CNPJ %s confirmado via cadastro de fornecedor (nome fantasia bate: %s)"), candidato, fantasia_pedido)
                    break

        # Última medida: consulta o cadastro de fornecedor pelo CNPJ do PRÓPRIO pedido
        # (cnpj_forn) - se o nome fantasia retornado bater com o do pedido, confia no CNPJ
        # cadastrado no pedido (provavelmente a leitura do documento é que está errada)
        if not emitente_ok:
            cnpj_forn_norm = val.normaliza_cnpj(cnpj_forn)
            dados_forn_pedido = self.bpms.consultar_fornecedor_por_cnpj(cnpj_forn_norm) if cnpj_forn_norm else []
            nomes_pedido = [d.get("AGN_ST_FANTASIA", "") for d in dados_forn_pedido] + [d.get("AGN_ST_NOME", "") for d in dados_forn_pedido]
            if br.nome_fornecedor_confere(nomes_pedido, fantasia_pedido):
                num_cnpj_cadastro = val.normaliza_cnpj(dados_forn_pedido[0].get("NUM_CNPJ", "")) if dados_forn_pedido else ""
                if num_cnpj_cadastro:
                    emitente_ok = True
                    cnpj_confirmado_via_api = num_cnpj_cadastro
                    log.info(sanitize_emoji("  │  ℹ️  CNPJ do pedido (%s) confirmado via cadastro de fornecedor (nome fantasia bate: %s)"), num_cnpj_cadastro, fantasia_pedido)

        if not emitente_ok:
            log.warning(sanitize_emoji("  │  ⚠️  CNPJ do emitente divergente - bloqueio ativado"))
            msg = "CNPJ do emitente não bate com o esperado"
            detalhes = {
                "CNPJ do fornecedor do pedido": cnpj_forn,
                "CNPJ do emitente identificado no documento fiscal": contexto["cnpj_emitente"],
                "Outros CNPJs lidos nos anexos do pedido": ", ".join(sorted(set(cnpjs_pedido))),
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            res.deve_lancar = False
            res.status = "CNPJEmitente"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ CNPJ emitente válido"))

        # Validação: CNPJ Tomador x Filial
        log.info("  ├─ Validação 4: CNPJ Tomador x Filial...")
        log.info("  │  ├─ CNPJ Documento: %s", contexto["cnpj_tomador"])
        log.info("  │  ├─ Nome Tomador: %s", contexto["nome_tomador"])
        log.info("  │  └─ CNPJ Esperado: %s", cnpj_filial)
        tomador_ok = br.valida_tomador_x_filial(contexto["cnpj_tomador"], contexto["nome_tomador"], filial, cnpj_filial,
                                                 nome_filial_pedido)
        candidatos_tomador = tomador_candidatos_pedido or [(contexto["cnpj_tomador"], contexto["nome_tomador"])]
        if not tomador_ok and br.valida_tomador_x_filial_multi(candidatos_tomador, filial, cnpj_filial, nome_filial_pedido):
            log.info(sanitize_emoji("  │  ℹ️  CNPJ do documento selecionado divergente, mas outro anexo do pedido confirma a filial"))
            tomador_ok = True
        if not tomador_ok:
            log.warning(sanitize_emoji("  │  ⚠️  CNPJ do tomador divergente - bloqueio ativado"))
            msg = "CNPJ do tomador não bate com o esperado"
            detalhes = {
                "CNPJ da filial": cnpj_filial,
                "CNPJ do tomador identificado no documento fiscal": contexto["cnpj_tomador"],
                "Nome do tomador": contexto["nome_tomador"]
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            res.deve_lancar = False
            res.status = "CNPJTomador"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ CNPJ tomador válido"))

        # Validação: Data do Documento válida (dd/MM/yyyy completo)
        log.info("  ├─ Validação 5: Data do Documento válida...")
        if not fmt.data_br_para_iso(contexto["data_documento"]):
            log.warning(sanitize_emoji("  │  ⚠️  Data do documento inválida ou incompleta - bloqueio ativado"))
            msg = "Data do documento não pôde ser identificada corretamente no anexo - requer conferência manual"
            detalhes = {
                "Data do documento extraída": contexto["data_documento"] or "(vazia)",
                "Nota Fiscal": payload.get("numNota", ""),
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro=f"Motivo: Data do documento invalida ou incompleta ({contexto['data_documento']})")
            res.deve_lancar = False
            res.status = "DataDocumentoInvalida"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Data do documento válida"))

        # Validação 5B: Chave de Acesso válida (ver docs\REGRAS_PROJETO.md secao 3.16).
        # Mega valida a chave de acesso na rotina adm_pck_nfe.F_ValidaChaveNFE - se enviarmos ""
        # ou uma chave com dígito verificador incorreto, o pedido é rejeitado lá com um erro
        # Oracle genérico ("Chave de Acesso não encontrada"). Bloqueamos antes, com contexto
        # claro para conferência manual, para os tipos de documento que exigem chave.
        tipos_com_chave = ("NF-E", "NFSC", "NFSTE", "NF3E")
        if contexto["tipo_doc"] in tipos_com_chave and not val.chave_acesso_valida(payload.get("chaveAcesso", "")):
            log.warning(sanitize_emoji("  │  ⚠️  Chave de acesso ausente ou inválida - bloqueio ativado"))
            msg = "Chave de acesso não pôde ser lida/validada automaticamente - requer conferência manual"
            detalhes = {
                "Nota Fiscal": payload.get("numNota", ""),
                "Chave lida (extração principal)": contexto.get("chave_primaria_raw", "") or "(vazia)",
                "Chave lida (extração extra)": contexto.get("chave_extra_raw", "") or "(vazia)",
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro="Motivo: Chave de acesso ausente ou com digito verificador invalido")
            res.deve_lancar = False
            res.status = "ChaveAcessoInvalida"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Chave de acesso válida (ou não exigida para este tipo de documento)"))

        # Validação: Condição de Pagamento ≤ 7 dias
        log.info("  ├─ Validação 6: Condição de Pagamento ≤ 7 dias...")
        log.info("  │  ├─ Data Documento: %s", contexto["data_documento"])
        log.info("  │  ├─ Cond. Pagamento: %s", contexto["cond_pagto"])
        log.info("  │  └─ Bloqueio 7d (item): %s", contexto["bloqueia_7d"])
        deve_por_venc = br.calcular_deve_lancar_por_vencimento(
            contexto["cnpj_emitente"], contexto["data_documento"], contexto["cond_pagto"], self.s.timezone)
        if contexto["bloqueia_7d"] or not deve_por_venc:
            log.warning(sanitize_emoji("  │  ⚠️  Condição de pagamento ≤ 7 dias - bloqueio ativado"))
            msg = "Condição de pagamento ≤ 7 dias. Lançamento bloqueado"
            detalhes = {
                "Data do documento": contexto["data_documento"],
                "Condição de pagamento": contexto["cond_pagto"]
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            # Registrar no BD como sucesso para não reprocessar
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd, erro="Motivo: Condição de pagamento ≤ 7")
            res.deve_lancar = False
            res.status = "CondPagto7Dias"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Condição de pagamento válida (> 7 dias)"))

        # Validação: Condição de Pagamento x Vencimento do Boleto
        log.info("  ├─ Validação 7: Condição de Pagamento x Vencimento do Boleto...")
        cond_ok, cond_esperada = br.valida_cond_pagto_por_vencimento(
            contexto["cond_pagto"], contexto["data_documento"], data_vencimento_boleto)
        if not cond_ok:
            log.warning(sanitize_emoji("  │  ⚠️  Condição de pagamento divergente do vencimento do boleto - bloqueio ativado"))
            msg = "Condição de pagamento do pedido não confere com o vencimento do boleto anexado"
            detalhes = {
                "Condição de pagamento cadastrada no pedido": contexto["cond_pagto"],
                "Condição de pagamento calculada pelo vencimento do boleto": cond_esperada,
                "Data do documento": contexto["data_documento"],
                "Data de vencimento do boleto": data_vencimento_boleto,
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            # Registrar no BD como sucesso para não reprocessar
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro=f"Motivo: Condição de pagamento divergente (cadastrada={contexto['cond_pagto']}, calculada={cond_esperada})")
            res.deve_lancar = False
            res.status = "CondPagtoDivergente"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Condição de pagamento confere (ou sem boleto/código especial para comparar)"))

        # Validação: Parcelas por Boleto (pagamento rateado em múltiplos boletos)
        log.info("  ├─ Validação 8: Parcelas por Boleto...")
        parcelas_boleto, soma_ok, soma_calculada = br.montar_parcelas_por_boletos(
            payload.get("numNota", ""), boletos or [], payload.get("totalNota", "0"))
        if parcelas_boleto and not soma_ok:
            log.warning(sanitize_emoji("  │  ⚠️  Soma dos boletos não confere com o Total da Fatura - bloqueio ativado"))
            msg = "Soma dos valores dos boletos anexados não confere com o Total da Fatura"
            detalhes = {
                "Total da Fatura (NF)": payload.get("totalNota", "0"),
                "Soma dos boletos anexados": soma_calculada,
                "Quantidade de boletos": str(len(parcelas_boleto)),
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd,
                                erro=f"Motivo: Soma dos boletos ({soma_calculada}) diverge do Total da Fatura ({payload.get('totalNota', '0')})")
            res.deve_lancar = False
            res.status = "ParcelasBoletoDivergente"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        if parcelas_boleto:
            payload["parcelas"] = parcelas_boleto
            log.info(sanitize_emoji("  │  ✓ %d parcela(s) montada(s) a partir dos boletos anexados"), len(parcelas_boleto))
        else:
            log.info(sanitize_emoji("  │  ✓ Parcela única (0 ou 1 boleto anexado)"))

        # ═══════════════════════════════════════════════════════════════════
        # Validação 9: Valor do pedido de compra x Nota Fiscal (bruto, documentos de serviço)
        # ═══════════════════════════════════════════════════════════════════
        # Ver docs/REGRAS_PROJETO.md secao 3.10. etl.montar_payload usa o valor do pedido de
        # compra (soma) como valorMercadoria para nao divergir do que o Mega tem cadastrado -
        # mas se o PROPRIO pedido de compra estiver cadastrado com um total diferente do bruto
        # real da NF, o lancamento passaria no Mega (bate com o pedido) e registraria um valor
        # ERRADO em relacao a nota fiscal real, sem nenhum aviso. Esta validacao reproduz, de
        # forma proativa (antes de enviar ao Mega), a mesma protecao que antes vinha da rejeicao
        # 400 do Mega ("Soma dos Valores das Parcelas x Total da Fatura").
        log.info("  ├─ Validação 9: Valor do pedido de compra x Nota Fiscal (bruto)...")
        diverge = contexto.get("diverge_pedido_nf")
        if diverge:
            log.warning(sanitize_emoji("  │  ⚠️  Valor do pedido de compra não confere com o bruto da Nota Fiscal - bloqueio ativado"))
            msg = "Valor cadastrado no pedido de compra não confere com a Nota Fiscal - requer correção manual do pedido no Mega"
            detalhes = {
                "Nota Fiscal": payload.get("numNota", ""),
                "Valor da Nota Fiscal (bruto)": diverge.get("valor_nf_bruto", ""),
                "Valor cadastrado no pedido de compra": diverge.get("valor_pedido", ""),
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Falha", num_pedido_bd,
                                erro=f"Motivo: Valor da NF (bruto)={diverge.get('valor_nf_bruto', '')} diverge do "
                                     f"valor cadastrado no pedido de compra={diverge.get('valor_pedido', '')}")
            res.status = "PedidoValorDivergente"
            log.info("  └─ Status final: %s (registrado no BD)", res.status)
            return res
        log.info(sanitize_emoji("  │  ✓ Valor do pedido de compra confere com o bruto da Nota Fiscal (ou sem valor extraído para comparar)"))

        # ═══════════════════════════════════════════════════════════════════
        # Validação 10: PIS/COFINS reconhecidos
        # ═══════════════════════════════════════════════════════════════════
        # ┌──────────────────────────────────────────────────────────────────────────────────┐
        # │ >>> PALIATIVO PROVISÓRIO - NÃO É REGRA DE NEGÓCIO DEFINITIVA <<<                  │
        # │ Motivo: ainda não há controle confiável do lançamento correto de PIS/COFINS.      │
        # │ Enquanto a TI não resolver, preferimos NÃO lançar (força lançamento manual do      │
        # │ pedido) a lançar com PIS/COFINS errado e precisar excluir o lançamento no Mega.    │
        # │ REMOVER assim que a TI resolver: apagar este bloco e                               │
        # │ services/business_rules.py::eh_pis_cofins_reconhecido.                            │
        # └──────────────────────────────────────────────────────────────────────────────────┘
        if not self.s.bloqueio_pis_cofins_ativo:
            log.info("  ├─ Validação 10: PIS/COFINS - paliativo DESATIVADO (BLOQUEIO_PIS_COFINS_ATIVO=False no .env), pulando")
        else:
            log.info("  ├─ Validação 10: PIS/COFINS reconhecidos no documento (bloqueio PROVISÓRIO)...")
            if br.eh_pis_cofins_reconhecido(payload):
                log.warning(sanitize_emoji("  │  ⚠️  PIS/COFINS reconhecidos no documento - bloqueio PROVISÓRIO (paliativo) ativado"))
                msg = ("Documento possui valores de PIS/COFINS reconhecidos. Por problema técnico "
                       "ainda em resolução no lançamento desses tributos, este pedido não será lançado "
                       "automaticamente e requer lançamento manual. Ação PROVISÓRIA até ajuste da TI")
                detalhes = {
                    "Nota Fiscal": payload.get("numNota", ""),
                    "valorPIS": payload.get("valorPIS", "0.00"),
                    "valorCOFINS": payload.get("valorCOFINS", "0.00"),
                }
                self.teams.aviso(msg, pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes)
                self.bpms.registrar(self.id_disparo, "Provisorio", num_pedido_bd,
                                    erro=f"Motivo: PIS/COFINS reconhecidos (valorPIS={payload.get('valorPIS', '0.00')}, "
                                         f"valorCOFINS={payload.get('valorCOFINS', '0.00')}) - bloqueio PROVISORIO "
                                         f"(paliativo), lancamento manual ate ajuste da TI")
                res.deve_lancar = False
                res.status = "ProvisorioPisCofins"
                log.info("  └─ Status final: %s (registrado no BD como Provisorio)", res.status)
                return res
            log.info(sanitize_emoji("  │  ✓ Sem PIS/COFINS reconhecidos"))
        log.info("  └─ Todas as validações passaram")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 7: Lançamento no Mega Integrador
        # ═══════════════════════════════════════════════════════════════════
        log.info(sanitize_emoji("[ETAPA 7/7] 🚀 Lançando no Mega Integrador..."))

        # Limpar campos internos antes de enviar
        payload.pop("_contexto", None)

        log.info("  ├─ Payload a ser enviado:")
        log.info("  │  %s", json.dumps(payload, indent=2, ensure_ascii=False)[:2000] + "..." if len(json.dumps(payload)) > 2000 else json.dumps(payload, indent=2, ensure_ascii=False))

        return self._lancar(payload, pdc, num_pedido_bd, res)

    def _lancar(self, payload: dict, pdc: Any, num_pedido_bd: str, res: ResultadoPedido) -> ResultadoPedido:
        status_code, body = self.mega.lancar_recebimento(payload)
        num_nota = payload.get("numNota", "")

        if status_code == 200:
            data = (body or {}).get("data", {}) if isinstance(body, dict) else {}
            cod_trans = data.get('codTransacao', '')
            pk_mega = data.get('pkMega', '')
            log.info(sanitize_emoji("  ✓ Lançamento realizado com SUCESSO"))
            log.info("  ├─ Nota Fiscal: %s", num_nota)
            log.info("  ├─ Código Transação: %s", cod_trans)
            log.info("  └─ PK Mega: %s", pk_mega)
            msg = "Lançado com sucesso no Mega Integrador"
            self.teams.sucesso(msg, pedido=pdc, num_nota=num_nota, cod_transacao=cod_trans, pk_mega=pk_mega)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd, num_doc=num_nota)
            res.lancado = True
            res.status = "Sucesso"
            log.info("╰─ Status final: %s", res.status)
            return res

        erros = ""
        if isinstance(body, dict):
            erros = str(body.get("errors") or body.get("mensagem") or body.get("title") or body)

        if status_code == 400 and "já foi cadastrada" in erros:
            log.warning(sanitize_emoji("  ⚠️  Nota Fiscal já cadastrada no sistema"))
            msg = "Nota Fiscal já foi cadastrada no sistema"
            detalhes_nf = {"Nota Fiscal": num_nota}
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_nf)
            self.bpms.registrar(self.id_disparo, "Sucesso", num_pedido_bd, erro=erros)
            res.status = "JaCadastrada"
            log.info("╰─ Status final: %s", res.status)
            return res

        if status_code == 400 and "Total da Fatura" in erros and "Soma dos Valores das Parcelas" in erros:
            log.warning(sanitize_emoji("  ⚠️  Valor do pedido de compra não confere com a Nota Fiscal"))
            msg = "Valor cadastrado no pedido de compra não confere com a Nota Fiscal - requer correção manual do pedido no Mega"
            # "Parcelas[X]" = Soma dos Valores das Parcelas = valorParcela, montado a partir do
            # pedido de compra (soma); "Fatura[Y]" = Total da Fatura = totalNota, o valor real do
            # documento/NF. Ou seja: group(1) = pedido de compra, group(2) = nota fiscal.
            match = re.search(r"Parcelas\[([\d.,]+)\].*Fatura\[([\d.,]+)\]", erros)
            detalhes = {
                "Nota Fiscal": num_nota,
                "Valor da Nota Fiscal (bruto)": match.group(2) if match else "",
                "Valor cadastrado no pedido de compra": match.group(1) if match else "",
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Falha", num_pedido_bd, erro=erros)
            res.status = "PedidoValorDivergente"
            res.mensagem = erros
            log.info("╰─ Status final: %s", res.status)
            return res

        # Mega valida o item do recebimento (valorMercadoria) contra o "Valor Unitário" registrado
        # no pedido de compra - quando o pedido de compra foi cadastrado com um valor diferente do
        # total da fatura (ex.: só a base de ICMS, em vez da soma de todos os itens da fatura), o
        # lançamento é rejeitado. Isso é um problema de cadastro do PEDIDO DE COMPRA no Mega, não
        # do valor calculado pelo RPA - requer correção manual do pedido, não do código.
        # NÃO registrar no BD: depois que o pedido de compra for ajustado no Mega, o pedido deve
        # voltar a ser processado normalmente na próxima execução (sem exigir reset manual do BD).
        if status_code == 400 and "Valor Unitário" in erros and "Origem" in erros and "Recebimento" in erros:
            log.warning(sanitize_emoji("  ⚠️  Valor Unitário do pedido de compra não confere com o total da fatura"))
            match = re.search(r"Item:\s*\((\d+)\).*Origem:\s*\(([\d.,]+)\).*Recebimento\s*\(([\d.,]+)\)", erros)
            origem = match.group(2) if match else ""
            recebimento = match.group(3) if match else ""
            msg = (f"Pedido de compra está com valor de R$ {origem} no Mega, e a Nota Fiscal está "
                   f"com valor de R$ {recebimento}. Necessário solicitar ajuste do pedido de compra")
            detalhes = {
                "Nota Fiscal": num_nota,
                "Item": match.group(1) if match else "",
                "Valor cadastrado no pedido de compra (Origem)": origem,
                "Valor da fatura calculado pelo RPA (Recebimento)": recebimento,
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            res.status = "PedidoValorUnitarioDivergente"
            res.mensagem = erros
            log.info("╰─ Status final: %s (NÃO registrado no BD - pedido pode ser reprocessado após ajuste)", res.status)
            return res

        if status_code == 415:
            log.error(sanitize_emoji("  ❌ Erro 415 - Unsupported Media Type"))
            msg = "Erro 415 - Unsupported Media Type ao lançar recebimento"
            detalhes = {
                "Nota Fiscal": num_nota,
                "Erro retornado": erros
            }
            self.teams.erro(msg, pedido=pdc, tecnico=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Falha", num_pedido_bd, erro=erros)
            res.status = "ErroLancamento_415"
            res.mensagem = erros
            log.info("╰─ Status final: %s", res.status)
            return res

        log.error(sanitize_emoji("  ❌ Falha ao lançar recebimento | Status HTTP: %d"), status_code)
        log.error("  └─ Erro: %s", erros)
        msg = "Falha ao realizar lançamento de recebimento"
        detalhes = {
            "Status HTTP": str(status_code),
            "Nota Fiscal": num_nota,
            "Erro retornado": erros
        }
        self.teams.erro(msg, pedido=pdc, tecnico=True, detalhes_extra=detalhes)
        self.bpms.registrar(self.id_disparo, "Falha", num_pedido_bd, erro=erros)
        res.status = f"ErroLancamento_{status_code}"
        res.mensagem = erros
        log.info("╰─ Status final: %s", res.status)
        return res