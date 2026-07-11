"""Orquestracao do fluxo LancamentoCLN (pipeline de 5-7 etapas).

Espelha a arvore do Power Automate, com bloqueios ANTES do lancamento
(reembolso, APOLICE, CNPJ, 7 dias) - mais robusto que tratar no erro 400.

LOGS DETALHADOS: Cada etapa do processamento é logada para facilitar debug.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from config import get_settings
from models import ResultadoPedido
from services import business_rules as br
from services import etl_service as etl
from services import power_flow
from services.ia_service import IaService
from services.integra_bpms_service import IntegraBpmsService
from services.integra_megaintegrador_service import IntegraMegaIntegradorService
from services.notification_service import NotificationService
from utils import formatter as fmt
from utils import get_logger
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
        log.info("🚀 Iniciando obtenção de lista de pedidos...")
        try:
            lista = self.bpms.obter_lista_pedidos()
        except Exception as exc:  # noqa: BLE001
            log.exception("❌ Falha ao obter lista de pedidos: %s", exc)
            self.teams.erro_obter_pedidos()
            return []

        if not lista:
            log.info("ℹ️  Nenhum pedido aguardando CLN.")
            return []

        log.info("✓ Lista de pedidos obtida: %d pedido(s) disponível(is)", len(lista))

        pedidos = power_flow.selecionar_pedidos(lista, self.s.filtro_pedidos_list, self.s.limite_pedidos)
        log.info("📋 Pedidos selecionados para processamento: %d", len(pedidos))

        workers = max(1, int(self.s.max_workers))
        if workers == 1 or len(pedidos) <= 1:
            return [self._processar_seguro(p) for p in pedidos]

        log.info("🔀 Processando %s pedido(s) em paralelo (max_workers=%s).", len(pedidos), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._processar_seguro, pedidos))

    def _processar_seguro(self, pedido: dict) -> ResultadoPedido:
        """Isola falhas: um pedido com erro nao derruba o lote inteiro."""
        try:
            return self.processar_pedido(pedido)
        except Exception as exc:  # noqa: BLE001
            pdc = pedido.get("PDC_IN_CODIGO")
            log.exception("💥 Erro inesperado ao processar pedido %s: %s", pdc, exc)
            return ResultadoPedido(pedido=pdc, filial=pedido.get("FIL_IN_CODIGO"),
                                   deve_lancar=False, status="Excecao", mensagem=str(exc))

    def processar_pedido(self, pedido: dict) -> ResultadoPedido:
        pdc = pedido.get("PDC_IN_CODIGO")
        filial = pedido.get("FIL_IN_CODIGO")
        agente = pedido.get("AGN_IN_CODIGO")
        fantasia = pedido.get("AGN_ST_FANTASIA", "")
        cond_pagto = pedido.get("COND_ST_CODIGO", "")

        log.info("")
        log.info("╔" + "═" * 98 + "╗")
        log.info("║" + f" PROCESSANDO PEDIDO {pdc}".center(98) + "║")
        log.info("╠" + "═" * 98 + "╣")
        log.info("║ Filial: %-87s ║", filial)
        log.info("║ Agente: %-87s ║", agente)
        log.info("║ Fantasia: %-85s ║", fantasia)
        log.info("║ Cond. Pagto: %-82s ║", cond_pagto)
        log.info("╚" + "═" * 98 + "╝")

        res = ResultadoPedido(pedido=pdc, filial=filial)

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 1: Verificar REEMBOLSO
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 1/7] 🔍 Verificando se é REEMBOLSO...")
        if br.eh_reembolso(fantasia):
            log.warning("  ⚠️  Pedido %s identificado como REEMBOLSO - bloqueio ativado", pdc)
            self.teams.aviso("Pedido identificado como REEMBOLSO. NÃO será lançado automaticamente", pedido=pdc, tipo_negocio=True)
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro="Reembolso: lancamento manual.")
            res.deve_lancar = False
            res.status = "Reembolso"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info("  ✓ Não é reembolso")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 2: Obter Dados do Pedido
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 2/7] 📦 Obtendo dados detalhados do pedido...")
        try:
            dados_pedido = self.bpms.obter_dados_pedido(filial, pdc)
        except Exception as exc:  # noqa: BLE001
            log.exception("  ❌ Erro ao obter dados do pedido %s: %s", pdc, exc)
            self.teams.erro("Falha ao obter dados detalhados do pedido", pedido=pdc, tecnico=True)
            res.status = "ErroDadosPedido"
            log.info("  └─ Status final: %s", res.status)
            return res

        if not dados_pedido:
            log.error("  ❌ Dados do pedido %s não encontrados", pdc)
            self.teams.erro("Dados do pedido não encontrados", pedido=pdc, tecnico=True)
            res.status = "ErroDadosPedido"
            log.info("  └─ Status final: %s", res.status)
            return res

        log.info("  ✓ Dados do pedido obtidos: %d item(ns)", len(dados_pedido))
        log.info("  ├─ Item 1: Produto=%s, Qtd=%s, Valor=%s",
                 dados_pedido[0].get("PRODUTO", ""),
                 dados_pedido[0].get("QUANTIDADE_PEDIDO", ""),
                 dados_pedido[0].get("VALOR_TOTAL_ITEM_PEDIDO", ""))
        log.info("  ├─ Centro Custo: %s", dados_pedido[0].get("CC_PADRAO", ""))
        log.info("  └─ Projeto: %s", dados_pedido[0].get("PROJ_PADRAO", ""))

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 3: Consultar Anexos
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 3/7] 📎 Consultando anexos do pedido...")
        try:
            anexos = self.bpms.consultar_anexos(filial, agente, pdc, fmt.hoje_br(self.s.timezone))
        except Exception as exc:  # noqa: BLE001
            log.exception("  ❌ Erro ao consultar anexos do pedido %s: %s", pdc, exc)
            self.teams.erro_consultar_anexos(pdc)
            res.status = "ErroAnexos"
            log.info("  └─ Status final: %s", res.status)
            return res

        log.info("  ✓ Anexos consultados: %d arquivo(s)", len(anexos))

        cnpj_forn = val.normaliza_cnpj(dados_pedido[0].get("CNPJ_CPF_FORNECEDOR", ""))
        cnpj_filial = val.normaliza_cnpj(dados_pedido[0].get("CNPJ_CPF_FILIAL", ""))
        log.info("  ├─ CNPJ Fornecedor (esperado): %s", cnpj_forn)
        log.info("  └─ CNPJ Filial (esperado): %s", cnpj_filial)

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 4: Processar Anexos com IA
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 4/7] 🤖 Processando anexos com IA...")
        payloads: list[dict] = []
        contexto: dict[str, Any] = {}

        for idx, anexo in enumerate(anexos, 1):
            log.info("  ┌─ Anexo %d/%d", idx, len(anexos))
            cod_bd = f"{anexo.get('filial')}-{anexo.get('pedido')}"
            nome = str(anexo.get("nomeArquivo", ""))
            log.info("  ├─ Arquivo: %s", nome)

            # Verificar se já foi processado
            if self.bpms.consultar_bd(cod_bd):
                log.info("  ├─ ⏭️  Pedido %s já processado (BD não vazio). Pulando anexo.", cod_bd)
                log.info("  └─")
                continue

            # Verificar se é imagem
            if nome.lower().endswith(IMAGENS):
                log.warning("  ├─ ⚠️  Arquivo é imagem, só aceita PDF")
                detalhes_img = {"Arquivo": nome}
                self.teams.aviso("Arquivo é imagem, só aceita PDF para leitura pela IA", pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_img)
                self.bpms.registrar(self.id_disparo, "Sucesso", str(pdc), erro="Anexo imagem, ignorado.")
                log.info("  └─")
                continue

            base64_pdf = anexo.get("anexoBase64", "")
            log.info("  ├─ Base64 PDF: %d caracteres", len(base64_pdf))

            # Extração primária
            log.info("  ├─ 🧠 Executando extração primária (IA 1ª chamada)...")
            try:
                ia_raw = self.ia.extrair_primaria(base64_pdf)
                log.info("  │  ✓ Extração primária concluída")
                log.info("  │  ├─ tipoDocFiscal: %s", ia_raw.get("tipoDocFiscal", ""))
                log.info("  │  ├─ numNota: %s", ia_raw.get("numNota", ""))
                log.info("  │  ├─ valorTotalDocumento: %s", ia_raw.get("valorTotalDocumento", ""))
                log.info("  │  ├─ cnpjEmitente: %s", ia_raw.get("cnpjEmitente", ""))
                log.info("  │  └─ JSON completo da IA (primária):")
                log.info("  │     %s", json.dumps(ia_raw, indent=2, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                log.exception("  │  ❌ Erro ao enviar Base64 para IA (pedido %s): %s", pdc, exc)
                self.teams.erro_ia_envio(pdc, nome)
                log.info("  └─")
                continue

            # Extração extra
            log.info("  ├─ 🧠 Executando extração extra (IA 2ª chamada)...")
            try:
                extra_raw = self.ia.extrair_extra(base64_pdf)
                log.info("  │  ✓ Extração extra concluída")
                log.info("  │  ├─ issRetido: %s", extra_raw.get("issRetido", False))
                log.info("  │  ├─ valorISSRetido: %s", extra_raw.get("valorISSRetido", "0.00"))
                log.info("  │  ├─ cnpjCpfTomador: %s", extra_raw.get("cnpjCpfTomador", ""))
                log.info("  │  └─ JSON completo da IA (extra):")
                log.info("  │     %s", json.dumps(extra_raw, indent=2, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                log.exception("  │  ❌ Erro ao capturar resultado da IA (pedido %s): %s", pdc, exc)
                self.teams.erro_ia_resultado(pdc)
                log.info("  └─")
                continue

            # Consolidar resposta IA
            log.info("  ├─ 🔄 Consolidando respostas IA...")
            ia_final, cnpj_emit, cnpj_tom, tipo_doc = etl.consolidar_resposta_ia(ia_raw, extra_raw, pdc)
            log.info("  │  ✓ Consolidação concluída")
            log.info("  │  ├─ Tipo Doc Final: %s", tipo_doc)
            log.info("  │  ├─ CNPJ Emitente: %s", cnpj_emit)
            log.info("  │  ├─ CNPJ Tomador: %s", cnpj_tom)
            log.info("  │  ├─ Num Nota Final: %s", ia_final.get("numNota", ""))
            log.info("  │  └─ JSON consolidado final (ia_final):")
            log.info("  │     %s", json.dumps(ia_final, indent=2, ensure_ascii=False))

            # Calcular ação e conta
            acao_conta = br.calcular_acao_e_conta(tipo_doc, cond_pagto)
            log.info("  ├─ 💼 Ação e Conta calculadas")
            log.info("  │  ├─ contasPagarTipoDoc: %s", acao_conta.get("contasPagarTipoDoc", ""))
            log.info("  │  └─ acao: %s", acao_conta.get("acao", ""))

            # Montar payload
            log.info("  ├─ 📝 Montando payload de recebimento...")
            payload, bloq7 = etl.montar_payload(pedido, dados_pedido, ia_final, cnpj_emit, tipo_doc, acao_conta, "", self.s.timezone)
            log.info("  │  ✓ Payload montado")
            log.info("  │  ├─ Bloqueio 7 dias: %s", bloq7)
            log.info("  │  ├─ Total Nota: %s", payload.get("totalNota", ""))
            log.info("  │  ├─ Num Itens: %d", len(payload.get("itensReceb", [])))
            log.info("  │  └─ Chave Acesso: %s", payload.get("chaveAcesso", "")[:20] + "..." if payload.get("chaveAcesso") else "")

            payloads.append(payload)
            contexto = {
                "cnpj_emitente": cnpj_emit,
                "cnpj_tomador": cnpj_tom,
                "nome_tomador": ia_final.get("nomeTomador", ""),
                "tipo_doc": tipo_doc,
                "bloqueia_7d": bloq7,
                "data_documento": ia_final.get("dataDocumento", ""),
                "cond_pagto": payload.get("condPagto", ""),
            }
            log.info("  └─ Anexo processado com sucesso")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 5: Priorizar Payload
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 5/7] 🎯 Priorizando payload...")
        payload = power_flow.priorizar_payload(payloads)
        if not payload:
            log.error("  ❌ Nenhum payload válido gerado")
            self.teams.erro_definir_payload(pdc)
            res.status = "SemPayload"
            log.info("  └─ Status final: %s", res.status)
            return res

        log.info("  ✓ Payload selecionado: tipoDocFiscal=%s", payload.get("tipoDocFiscal", ""))
        res.tipoDocFiscal = contexto.get("tipo_doc", "")
        res.num_doc = payload.get("numNota", "")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 6: Validações de Negócio
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 6/7] ✅ Executando validações de negócio...")

        # Validação: Apólice
        log.info("  ├─ Validação 1: Verificando se é APÓLICE...")
        if br.eh_apolice(contexto.get("tipo_doc", "")):
            log.warning("  │  ⚠️  Documento é APÓLICE - bloqueio ativado")
            self.teams.aviso("Documento identificado como Apólice de Seguro. NÃO será lançado automaticamente", pedido=pdc, tipo_negocio=True)
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro="Apolice de seguro: lancamento manual.")
            res.deve_lancar = False
            res.status = "Apolice"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info("  │  ✓ Não é apólice")

        # Validação: CNPJ Emitente x Fornecedor
        log.info("  ├─ Validação 2: CNPJ Emitente x Fornecedor...")
        log.info("  │  ├─ CNPJ Documento: %s", contexto["cnpj_emitente"])
        log.info("  │  └─ CNPJ Esperado: %s", cnpj_forn)
        if not br.valida_emitente_x_fornecedor(contexto["cnpj_emitente"], cnpj_forn):
            log.warning("  │  ⚠️  CNPJ do emitente divergente - bloqueio ativado")
            msg = "CNPJ do emitente não bate com o esperado"
            detalhes = {
                "CNPJ do fornecedor do pedido": cnpj_forn,
                "CNPJ do emitente identificado no documento fiscal": contexto["cnpj_emitente"]
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            det = f"Fornecedor cadastrado: {cnpj_forn} | CNPJ do documento: {contexto['cnpj_emitente']}"
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro=f"CNPJ emitente divergente: {det}")
            res.deve_lancar = False
            res.status = "CNPJEmitente"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info("  │  ✓ CNPJ emitente válido")

        # Validação: CNPJ Tomador x Filial
        log.info("  ├─ Validação 3: CNPJ Tomador x Filial...")
        log.info("  │  ├─ CNPJ Documento: %s", contexto["cnpj_tomador"])
        log.info("  │  ├─ Nome Tomador: %s", contexto["nome_tomador"])
        log.info("  │  └─ CNPJ Esperado: %s", cnpj_filial)
        if not br.valida_tomador_x_filial(contexto["cnpj_tomador"], contexto["nome_tomador"], filial, cnpj_filial):
            log.warning("  │  ⚠️  CNPJ do tomador divergente - bloqueio ativado")
            msg = "CNPJ do tomador não bate com o esperado"
            detalhes = {
                "CNPJ da filial": cnpj_filial,
                "CNPJ do tomador identificado no documento fiscal": contexto["cnpj_tomador"],
                "Nome do tomador": contexto["nome_tomador"]
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            det = f"Filial: {cnpj_filial} | Tomador do documento: {contexto['cnpj_tomador']}"
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro=f"CNPJ tomador divergente: {det}")
            res.deve_lancar = False
            res.status = "CNPJTomador"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info("  │  ✓ CNPJ tomador válido")

        # Validação: Condição de Pagamento ≤ 7 dias
        log.info("  ├─ Validação 4: Condição de Pagamento ≤ 7 dias...")
        log.info("  │  ├─ Data Documento: %s", contexto["data_documento"])
        log.info("  │  ├─ Cond. Pagamento: %s", contexto["cond_pagto"])
        log.info("  │  └─ Bloqueio 7d (item): %s", contexto["bloqueia_7d"])
        deve_por_venc = br.calcular_deve_lancar_por_vencimento(
            contexto["cnpj_emitente"], contexto["data_documento"], contexto["cond_pagto"], self.s.timezone)
        if contexto["bloqueia_7d"] or not deve_por_venc:
            log.warning("  │  ⚠️  Condição de pagamento ≤ 7 dias - bloqueio ativado")
            msg = "Condição de pagamento ≤ 7 dias. Lançamento bloqueado"
            detalhes = {
                "Data do documento": contexto["data_documento"],
                "Condição de pagamento": contexto["cond_pagto"]
            }
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro="Cond. pagamento <= 7 dias.")
            res.deve_lancar = False
            res.status = "CondPagto7Dias"
            log.info("  └─ Status final: %s", res.status)
            return res
        log.info("  │  ✓ Condição de pagamento válida (> 7 dias)")
        log.info("  └─ Todas as validações passaram")

        # ═══════════════════════════════════════════════════════════════════
        # ETAPA 7: Lançamento no Mega Integrador
        # ═══════════════════════════════════════════════════════════════════
        log.info("[ETAPA 7/7] 🚀 Lançando no Mega Integrador...")
        log.info("  ├─ Payload a ser enviado:")
        log.info("  │  %s", json.dumps(payload, indent=2, ensure_ascii=False)[:2000] + "..." if len(json.dumps(payload)) > 2000 else json.dumps(payload, indent=2, ensure_ascii=False))

        return self._lancar(payload, pdc, res)

    def _lancar(self, payload: dict, pdc: Any, res: ResultadoPedido) -> ResultadoPedido:
        status_code, body = self.mega.lancar_recebimento(payload)
        num_nota = payload.get("numNota", "")

        if status_code == 200:
            data = (body or {}).get("data", {}) if isinstance(body, dict) else {}
            cod_trans = data.get('codTransacao', '')
            pk_mega = data.get('pkMega', '')
            log.info("  ✓ Lançamento realizado com SUCESSO")
            log.info("  ├─ Nota Fiscal: %s", num_nota)
            log.info("  ├─ Código Transação: %s", cod_trans)
            log.info("  └─ PK Mega: %s", pk_mega)
            msg = "Lançado com sucesso no Mega Integrador"
            self.teams.sucesso(msg, pedido=pdc, num_nota=num_nota, cod_transacao=cod_trans, pk_mega=pk_mega)
            self.bpms.registrar(self.id_disparo, "Sucesso", str(pdc), num_doc=num_nota)
            res.lancado = True
            res.status = "Sucesso"
            log.info("╰─ Status final: %s", res.status)
            return res

        erros = ""
        if isinstance(body, dict):
            erros = str(body.get("errors") or body.get("mensagem") or body.get("title") or body)

        if status_code == 400 and "já foi cadastrada" in erros:
            log.warning("  ⚠️  Nota Fiscal já cadastrada no sistema")
            msg = "Nota Fiscal já foi cadastrada no sistema"
            detalhes_nf = {"Nota Fiscal": num_nota}
            self.teams.aviso(msg, pedido=pdc, tipo_negocio=False, detalhes_extra=detalhes_nf)
            self.bpms.registrar(self.id_disparo, "Sucesso", str(pdc), erro=erros)
            res.status = "JaCadastrada"
            log.info("╰─ Status final: %s", res.status)
            return res

        if status_code == 415:
            log.error("  ❌ Erro 415 - Unsupported Media Type")
            msg = "Erro 415 - Unsupported Media Type ao lançar recebimento"
            detalhes = {
                "Nota Fiscal": num_nota,
                "Erro retornado": erros
            }
            self.teams.erro(msg, pedido=pdc, tecnico=True, detalhes_extra=detalhes)
            self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro=erros)
            res.status = "ErroLancamento_415"
            res.mensagem = erros
            log.info("╰─ Status final: %s", res.status)
            return res

        log.error("  ❌ Falha ao lançar recebimento | Status HTTP: %d", status_code)
        log.error("  └─ Erro: %s", erros)
        msg = "Falha ao realizar lançamento de recebimento"
        detalhes = {
            "Status HTTP": str(status_code),
            "Nota Fiscal": num_nota,
            "Erro retornado": erros
        }
        self.teams.erro(msg, pedido=pdc, tecnico=True, detalhes_extra=detalhes)
        self.bpms.registrar(self.id_disparo, "Falha", str(pdc), erro=erros)
        res.status = f"ErroLancamento_{status_code}"
        res.mensagem = erros
        log.info("╰─ Status final: %s", res.status)
        return res