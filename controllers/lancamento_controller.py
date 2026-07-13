"""Orquestracao do fluxo LancamentoCLN (pipeline de 5-7 etapas).

Espelha a arvore do Power Automate, com bloqueios ANTES do lancamento
(reembolso, APOLICE, CNPJ, 7 dias) - mais robusto que tratar no erro 400.

LOGS DETALHADOS: Cada etapa do processamento é logada para facilitar debug.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from config import CNPJ_VIBRA_ENERGIA, get_settings
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
IMAGENS = (".png", ".jpg", ".jpeg")


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

        for idx, anexo in enumerate(anexos, 1):
            log.info("  ┌─ Anexo %d/%d", idx, len(anexos))
            nome = str(anexo.get("nomeArquivo", ""))
            log.info("  ├─ Arquivo: %s", nome)

            # Verificar se é imagem
            if nome.lower().endswith(IMAGENS):
                log.warning(sanitize_emoji("  ├─ ⚠️  Arquivo é imagem, só aceita PDF"))
                detalhes_img = {"Arquivo": nome}
                self.teams.aviso("Arquivo é imagem, só aceita PDF para leitura pela IA", pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_img)
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

            # Consolidar resposta IA
            log.info(sanitize_emoji("  ├─ 🔄 Consolidando respostas IA..."))
            ia_final, cnpj_emit, cnpj_tom, tipo_doc = etl.consolidar_resposta_ia(ia_raw, extra_raw, pdc)
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
            payload, bloq7 = etl.montar_payload(pedido, dados_pedido_filtrado, ia_final, cnpj_emit, tipo_doc, acao_conta, "", self.s.timezone)
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
                "data_documento": ia_final.get("dataDocumento", ""),
                "cond_pagto": payload.get("condPagto", ""),
                "data_vencimento": ia_final.get("dataVencimento", ""),
                "almoxarifado": ia_final.get("almoxarifado", ""),
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
                                           cnpjs_emitente_pedido, tomador_candidatos_pedido)
            for payload in payloads_para_lancar
        ]
        return resultados

    def _validar_e_lancar_payload(self, payload: dict, pdc: Any, filial: Any, cnpj_forn: str,
                                   cnpj_filial: str, num_pedido_bd: str,
                                   data_vencimento_boleto: str = "", boletos: list[dict] | None = None,
                                   fantasia_pedido: str = "", cnpjs_emitente_pedido: list[str] | None = None,
                                   tomador_candidatos_pedido: list[tuple[str, str]] | None = None) -> ResultadoPedido:
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
        tomador_ok = br.valida_tomador_x_filial(contexto["cnpj_tomador"], contexto["nome_tomador"], filial, cnpj_filial)
        candidatos_tomador = tomador_candidatos_pedido or [(contexto["cnpj_tomador"], contexto["nome_tomador"])]
        if not tomador_ok and br.valida_tomador_x_filial_multi(candidatos_tomador, filial, cnpj_filial):
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

        # Validação: Condição de Pagamento ≤ 7 dias
        log.info("  ├─ Validação 5: Condição de Pagamento ≤ 7 dias...")
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
        log.info("  ├─ Validação 6: Condição de Pagamento x Vencimento do Boleto...")
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
        log.info("  ├─ Validação 7: Parcelas por Boleto...")
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