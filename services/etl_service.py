"""Camada ETL: transforma dados do pedido + IA na carga do recebimento."""
from __future__ import annotations

from typing import Any

from config import CNPJ_ALUGUEL_IR, TIPOS_DOC_SERVICO
from utils import formatter as fmt
from utils import validators as val
from services import business_rules as br


def _g(d: dict, *chaves: str, default: Any = "") -> Any:
    for c in chaves:
        v = d.get(c)
        if v not in (None, ""):
            return v
    return default


def consolidar_resposta_ia(ia: dict, extra: dict, pdc_codigo: Any) -> tuple[dict, str, str, str]:
    """Aplica a cadeia de refinamento. Retorna (ia_final, cnpj_emit, cnpj_tom, tipo_doc)."""
    ia = dict(ia)
    ia = br.corrigir_total_iss_por_valor_iss(ia)
    if str(ia.get("numNota", "")).strip() == "":
        ia["numNota"] = str(extra.get("numNota", "") or "")
    ia = br.aplicar_iss_do_valor_retido(ia, extra)
    if br.precisa_retificar_iss_nao_retido(ia, extra):
        ia = br.retificar_iss_nao_retido(ia)
    cnpj_emitente = val.normaliza_cnpj(ia.get("cnpjEmitente", ""))
    cnpj_tomador = val.normaliza_cnpj(_g(extra, "cnpjCpfTomador") or ia.get("cnpjCpfTomador", ""))
    ia["numNota"] = br.num_nota_por_pedido(ia.get("numNota", ""), pdc_codigo)
    ia = br.calcular_percentuais_por_valor_e_base(ia)
    tipo_doc = br.resolver_tipo_doc_por_emitente(ia.get("tipoDocFiscal", ""), cnpj_emitente)
    ia["tipoDocFiscal"] = tipo_doc
    return ia, cnpj_emitente, cnpj_tomador, tipo_doc


def montar_item(dado_pedido: dict, ia: dict, num_nota: str, cnpj_emitente: str,
                total_nota: str, is_servico: bool, multi_item: bool) -> tuple[dict, float]:
    is_aluguel = cnpj_emitente == CNPJ_ALUGUEL_IR
    vtip = fmt.to_float(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))

    if not multi_item:
        if fmt.to_float(ia.get("valorMercadoria", "0")) > 0:
            valor_merc = str(ia.get("valorMercadoria"))
        elif vtip > 0:
            valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))
        else:
            valor_merc = str(total_nota or "0.00")
    else:
        valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", default=""))

    base_dec = vtip

    def perc(campo: str) -> float:
        return fmt.to_float(ia.get(campo, "0"))

    if fmt.to_float(ia.get("valorISS", "0")) > 0:
        valor_iss = fmt.format_number(ia.get("valorISS", "0"))
    else:
        valor_iss = fmt.format_number(base_dec * perc("percentualISS") / 100)

    if is_aluguel:
        valor_irff = fmt.format_number(ia.get("totalIRRF", "0"))
        perc_irff = "0.00"
    else:
        valor_irff = fmt.format_number(base_dec * perc("percentualIRFF") / 100)
        perc_irff = fmt.format_number(perc("percentualIRFF")) if str(ia.get("percentualIRFF", "")).strip() else "0.00"

    base_fmt = fmt.format_number(base_dec)
    base_icms = "0" if is_servico else base_fmt
    base_ipi = "0" if is_servico else base_fmt

    # Template completo de itensReceb (segue o Power Automate Cloud)
    item = {
        "documento": str(num_nota),
        "itemSequencia": str(_g(dado_pedido, "ITEM_SEQUENCIA", default="")),
        "produto": str(_g(dado_pedido, "PRODUTO", default="")),
        "produtoCodAlternativo": str(_g(dado_pedido, "PRODUTO", default="")),
        "unidade": str(_g(dado_pedido, "UNIDADE", default="")),
        "unidadeRecebimento": "",
        "codConversor": "",
        "qtdeRecebimento": str(_g(dado_pedido, "QUANTIDADE_PEDIDO", default="")),
        "valorConverter": "0",
        "valorMercadoria": valor_merc,
        "percDesconto": "0",
        "valorDesconto": "0",
        "valorMaoObra": "0",
        "valorMercadoriaEmpr": "0",
        "valorBaseIPI": base_ipi,
        "percIPI": fmt.format_number(perc("percIPI")),
        "valorIPI": fmt.format_number(base_dec * perc("percIPI") / 100),
        "valorIsentoIPI": "0",
        "valorOutrosIPI": "0",
        "valorRecuperadoIPI": "0",
        "baseIcms": base_icms,
        "percentualIcms": fmt.format_number(perc("percentualIcms")),
        "valorIcms": fmt.format_number(base_dec * perc("percentualIcms") / 100),
        "valorIsentoIcms": "0",
        "valorOutrosIcms": "0",
        "valorIcmsRecupera": "0",
        "valorIcmsRetido": fmt.format_number(ia.get("valorIcmsRetido", "0")),
        "baseSubTrib": "0",
        "aplicacao": str(_g(dado_pedido, "APLICACAO", default="")),
        "tipoClasse": str(_g(dado_pedido, "TIPO_CLASSE", default="")),
        "sitTribICMSA": "0",
        "sitTribICMSB": "90",
        "sitTribPIS": "70",
        "sitTribCofins": "70",
        "calculaValores": "N",
        "baseISS": base_fmt,
        "percentualISS": fmt.format_number(perc("percentualISS")),
        "valorISS": valor_iss,
        "baseIRFF": base_fmt,
        "percentualIRFF": perc_irff,
        "valorIRFF": valor_irff,
        "baseINSS": base_fmt,
        "percentualINSS": fmt.format_number(perc("percentualINSS")),
        "valorINSS": fmt.format_number(base_dec * perc("percentualINSS") / 100),
        "basePIS": base_fmt,
        "percentualPIS": fmt.format_number(perc("percentualPIS")),
        "valorPIS": fmt.format_number(base_dec * perc("percentualPIS") / 100),
        "baseCofins": base_fmt,
        "percentualCofins": fmt.format_number(perc("percentualCofins")),
        "valorCofins": fmt.format_number(base_dec * perc("percentualCofins") / 100),
        "baseCSLL": base_fmt,
        "percentualCSLL": fmt.format_number(perc("percentualCSLL")),
        "valorCSLL": fmt.format_number(base_dec * perc("percentualCSLL") / 100),
        "sitTribIPI": "49",
        "codEnquadramentoIPI": "999",
    }

    prct = fmt.to_float(_g(dado_pedido, "PRCT_CC", default="0"))
    valor_rateio = fmt.format_number(base_dec * prct / 100)
    prct_fmt = f"{prct:.4f}"
    item["centrosCusto"] = [{
        "numNota": str(num_nota),
        "itemSequencia": str(_g(dado_pedido, "ITEM_SEQUENCIA", default="")),
        "centroCustoReduzido": str(_g(dado_pedido, "CC_RATEIO", "CC_PADRAO", default="")),
        "tipoClasse": str(_g(dado_pedido, "TIPO_CLASSE", default="")),
        "prctRateio": prct_fmt,
        "valorRateio": valor_rateio,
        "operacao": "I",
        "projetos": [{
            "numNota": str(num_nota),
            "itemSequencia": str(_g(dado_pedido, "ITEM_SEQUENCIA", default="")),
            "projetoReduzido": str(_g(dado_pedido, "PROJETO", "PROJ_PADRAO", default="")),
            "tipoClasse": str(_g(dado_pedido, "TIPO_CLASSE", default="")),
            "prctRateio": prct_fmt,
            "valorRateio": valor_rateio,
            "operacao": "I",
        }],
    }]
    item["pedidos"] = [{
        "numNota": str(num_nota),
        "dataDocumento": str(ia.get("dataDocumento", "")),
        "itemSequencia": str(_g(dado_pedido, "ITEM_SEQUENCIA", default="")),
        "serieSequencia": str(_g(dado_pedido, "SERIE_SEQUENCIA", default="")),
        "codPedido": str(_g(dado_pedido, "PEDIDO", default="")),
        "sequenciaItemPedido": str(_g(dado_pedido, "ITEM_SEQUENCIA", default="")),
        "quantidade": str(_g(dado_pedido, "QUANTIDADE_PEDIDO", default="")),
        "dataEntrega": str(_g(dado_pedido, "DATA_ENTREGA", default="")),
        "qtdeConvertida": str(_g(dado_pedido, "QUANTIDADE_PEDIDO", default="")),
        "operacao": "I",
    }]
    return item, base_dec


def montar_payload(pedido_lista: dict, dados_pedido: list[dict], ia: dict, cnpj_emitente: str,
                   tipo_doc: str, acao_conta: dict, varacao_fallback: str, tz: str) -> tuple[dict, bool]:
    is_aluguel = cnpj_emitente == CNPJ_ALUGUEL_IR
    is_servico = br.eh_documento_servico(tipo_doc, TIPOS_DOC_SERVICO)
    multi_item = len(dados_pedido) > 1
    num_nota = br.remove_zeros_a_esquerda(ia.get("numNota", ""))
    total_nota_ia = ia.get("valorTotalDocumento", "0")

    itens: list[dict] = []
    soma = 0.0
    bloqueia_7d = False
    for dp in dados_pedido:
        item, base_dec = montar_item(dp, ia, num_nota, cnpj_emitente, total_nota_ia, is_servico, multi_item)
        itens.append(item)
        soma += base_dec
        cond = str(_g(dp, "COND_PAGTO", default="")) or str(pedido_lista.get("COND_ST_CODIGO", ""))
        bloqueia_7d = bloqueia_7d or br.bloqueia_por_cond_pagto_7dias(cond)

    total_nota = total_nota_ia if fmt.to_float(total_nota_ia) > 0 else fmt.format_number(soma)
    valor_mercadoria = str(ia.get("valorMercadoria", "0")) if is_aluguel else fmt.format_number(soma)

    cond_raw = str(_g(pedido_lista, "COND_ST_CODIGO", default="")) or str(_g(dados_pedido[0] if dados_pedido else {}, "COND_PAGTO", default=""))
    cond_norm = br.normaliza_cond_pagto(cond_raw)
    data_doc = str(ia.get("dataDocumento", ""))
    venc = br.vencimento_parcela_1(data_doc, cond_norm)

    parcela = {
        "numNota": str(num_nota), "numDocumento": str(num_nota), "numParcela": "1",
        "dataVencimento": venc, "valorParcela": str(total_nota),
    }

    tipo_doc_final = br.ajustar_bolp_detran(tipo_doc)
    serie = br.resolver_serie(tipo_doc, ia.get("serie", ""), ia.get("chaveAcesso", ""), cnpj_emitente)
    chave = br.resolver_chave_acesso(tipo_doc, ia.get("chaveAcesso", ""))
    base_icms_raiz = "0" if is_servico else str(ia.get("baseICMS", "0.00"))
    base_ipi_raiz = "0" if is_servico else str(ia.get("valorBaseIPI", "0.00"))

    payload = {
        "filial": str(_g(pedido_lista, "FIL_IN_CODIGO", default="")),
        "acao": str(acao_conta.get("acao", varacao_fallback or "")),
        "contasPagarTipoDoc": str(acao_conta.get("contasPagarTipoDoc", "")),
        "agente": str(_g(pedido_lista, "AGN_IN_CODIGO", default="")),
        "numNota": str(num_nota),
        "serie": serie,
        "tipoDocFiscal": tipo_doc_final,
        "dataDocumento": data_doc,
        "dataMovimento": fmt.hoje_br(tz),
        "condPagto": cond_raw,
        "valorMercadoria": valor_mercadoria,
        "totalNota": str(total_nota),
        "chaveAcesso": chave,
        "valorDescontoGeral": "0.00",
        "baseICMS": base_icms_raiz,
        "valorICMS": str(ia.get("valorICMS", "0.00")),
        "valorIPI": str(ia.get("valorIPI", "0.00")),
        "totalISS": str(ia.get("totalISS", "0.00")),
        "totalIRRF": str(ia.get("totalIRRF", "0.00")),
        "totalINSS": str(ia.get("totalINSS", "0.00")),
        "valorPIS": str(ia.get("valorPIS", "0.00")),
        "valorCOFINS": str(ia.get("valorCOFINS", "0.00")),
        "totalCSLL": str(ia.get("totalCSLL", "0.00")),
        "valorBaseIPI": base_ipi_raiz,
        "operacao": "I",
        "calculaValores": "N",
        "itensReceb": itens,
        "parcelas": [parcela],
    }
    return payload, bloqueia_7d
