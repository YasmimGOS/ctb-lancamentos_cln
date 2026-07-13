"""Camada ETL: transforma dados do pedido + IA na carga do recebimento."""
from __future__ import annotations

from typing import Any

from config import CNPJ_ALUGUEL_IR, CNPJ_APLICACAO_281, CNPJ_VIBRA_ENERGIA, TIPOS_DOC_SERVICO
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

    # Consolidar e sanitizar numNota
    num_nota_primaria = str(ia.get("numNota", "")).strip()
    num_nota_extra = str(extra.get("numNota", "")).strip()
    num_nota_final = num_nota_primaria if num_nota_primaria else num_nota_extra
    ia["numNota"] = br.sanitiza_num_nota(num_nota_final)

    # Consolidar chave de acesso: priorizar extração extra se tiver 44 dígitos
    chave_primaria = str(ia.get("chaveAcesso", "")).strip()
    chave_extra = str(extra.get("chaveAcesso", "")).strip()
    if len(chave_extra) == 44 and chave_extra.isdigit():
        ia["chaveAcesso"] = chave_extra
    elif len(chave_primaria) != 44 or not chave_primaria.isdigit():
        # Se nenhuma das duas tem 44 dígitos, limpar para evitar erro
        ia["chaveAcesso"] = ""

    ia = br.aplicar_iss_do_valor_retido(ia, extra)
    if br.precisa_retificar_iss_nao_retido(ia, extra):
        ia = br.retificar_iss_nao_retido(ia)
    cnpj_emitente = val.normaliza_cnpj(ia.get("cnpjEmitente", ""))

    # Consolidar CNPJ tomador: priorizar extra, mas validar tamanho (14 dígitos CNPJ ou 11 CPF)
    cnpj_tom_extra = val.normaliza_cnpj(_g(extra, "cnpjCpfTomador"))
    cnpj_tom_primaria = val.normaliza_cnpj(ia.get("cnpjCpfTomador", ""))

    # Usar extra se tiver tamanho válido, senão usar primária
    if len(cnpj_tom_extra) in (11, 14):
        cnpj_tomador = cnpj_tom_extra
    elif len(cnpj_tom_primaria) in (11, 14):
        cnpj_tomador = cnpj_tom_primaria
    else:
        # Nenhum dos dois é válido, usar o que tiver (pode ficar vazio ou inválido)
        cnpj_tomador = cnpj_tom_extra or cnpj_tom_primaria
    ia["numNota"] = br.num_nota_por_pedido(ia.get("numNota", ""), pdc_codigo)
    ia = br.calcular_percentuais_por_valor_e_base(ia)
    tipo_doc = br.resolver_tipo_doc_por_emitente(ia.get("tipoDocFiscal", ""), cnpj_emitente)
    ia["tipoDocFiscal"] = tipo_doc
    return ia, cnpj_emitente, cnpj_tomador, tipo_doc


def montar_item(dado_pedido: dict, ia: dict, num_nota: str, cnpj_emitente: str,
                total_nota: str, is_servico: bool, multi_item: bool) -> tuple[dict, float]:
    is_aluguel = cnpj_emitente == CNPJ_ALUGUEL_IR
    is_vibra = cnpj_emitente == CNPJ_VIBRA_ENERGIA
    vtip = fmt.to_float(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))

    if not multi_item:
        # VIBRA ENERGIA: sempre usar valorTotalDocumento (bruto) da IA
        if is_vibra:
            valor_merc = str(ia.get("valorTotalDocumento", total_nota or "0"))
        elif fmt.to_float(ia.get("valorMercadoria", "0")) > 0:
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

    def valor_ou_calc(campo_valor: str, campo_perc: str, base: float) -> str:
        """Retorna valor absoluto da IA se disponível, senão calcula pelo percentual."""
        valor_abs = fmt.to_float(ia.get(campo_valor, "0"))
        if valor_abs > 0:
            return fmt.format_number(valor_abs)
        return fmt.format_number(base * perc(campo_perc) / 100)

    def perc_ou_calc(campo_valor: str, campo_perc: str, base: float) -> str:
        """Retorna percentual da IA ou calcula baseado no valor absoluto."""
        perc_ia = perc(campo_perc)
        if perc_ia > 0:
            return fmt.format_number(perc_ia)
        # Se não tem percentual mas tem valor, calcular percentual reverso
        valor_abs = fmt.to_float(ia.get(campo_valor, "0"))
        if valor_abs > 0 and base > 0:
            return fmt.format_number((valor_abs * 100) / base)
        return "0.00"

    valor_iss = valor_ou_calc("valorISS", "percentualISS", base_dec)

    if is_aluguel:
        valor_irff = fmt.format_number(ia.get("totalIRRF", "0"))
        perc_irff = "0.00"
    else:
        valor_irff = valor_ou_calc("totalIRRF", "percentualIRFF", base_dec)
        perc_irff = perc_ou_calc("totalIRRF", "percentualIRFF", base_dec)

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
        "percIPI": perc_ou_calc("valorIPI", "percIPI", base_dec),
        "valorIPI": valor_ou_calc("valorIPI", "percIPI", base_dec),
        "valorIsentoIPI": "0",
        "valorOutrosIPI": "0",
        "valorRecuperadoIPI": "0",
        "baseIcms": base_icms,
        "percentualIcms": perc_ou_calc("valorICMS", "percentualIcms", base_dec),
        "valorIcms": valor_ou_calc("valorICMS", "percentualIcms", base_dec),
        "valorIsentoIcms": "0",
        "valorOutrosIcms": "0",
        "valorIcmsRecupera": "0",
        "valorIcmsRetido": fmt.format_number(ia.get("valorIcmsRetido", "0")),
        "baseSubTrib": "0",
        "aplicacao": "281" if cnpj_emitente == CNPJ_APLICACAO_281 else str(_g(dado_pedido, "APLICACAO", default="")),
        "tipoClasse": str(_g(dado_pedido, "TIPO_CLASSE", default="")),
        "sitTribICMSA": "0",
        "sitTribICMSB": "90",
        "sitTribPIS": "70",
        "sitTribCofins": "70",
        "calculaValores": "N",
        "baseISS": base_fmt,
        "percentualISS": perc_ou_calc("valorISS", "percentualISS", base_dec),
        "valorISS": valor_iss,
        "baseISSDevido": str(ia.get("baseISSDevido", "0.00")),
        "percentualISSDevido": str(ia.get("percentualISSDevido", "0.00")),
        "valorISSDevido": str(ia.get("valorISSDevido", "0.00")),
        "baseIRFF": base_fmt,
        "percentualIRFF": perc_irff,
        "valorIRFF": valor_irff,
        "baseINSS": base_fmt,
        "percentualINSS": perc_ou_calc("valorINSS", "percentualINSS", base_dec),
        "valorINSS": valor_ou_calc("valorINSS", "percentualINSS", base_dec),
        "basePIS": base_fmt,
        "percentualPIS": perc_ou_calc("valorPIS", "percentualPIS", base_dec),
        "valorPIS": valor_ou_calc("valorPIS", "percentualPIS", base_dec),
        "baseCofins": base_fmt,
        "percentualCofins": perc_ou_calc("valorCofins", "percentualCofins", base_dec),
        "valorCofins": valor_ou_calc("valorCofins", "percentualCofins", base_dec),
        "baseCSLL": base_fmt,
        "percentualCSLL": perc_ou_calc("valorCSLL", "percentualCSLL", base_dec),
        "valorCSLL": valor_ou_calc("valorCSLL", "percentualCSLL", base_dec),
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

    # Sanitizar e limpar número da nota
    num_nota_raw = ia.get("numNota", "")
    num_nota_sanitizado = br.sanitiza_num_nota(num_nota_raw)
    num_nota = br.remove_zeros_a_esquerda(num_nota_sanitizado)

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

    # Para serviços, valorMercadoria = valor líquido + impostos retidos (valor bruto)
    if is_servico:
        total_nota_dec = fmt.to_float(total_nota)
        impostos_retidos = (
            fmt.to_float(ia.get("valorPIS", "0")) +
            fmt.to_float(ia.get("valorCOFINS", "0")) +
            fmt.to_float(ia.get("valorCSLL", "0")) +
            fmt.to_float(ia.get("totalIRRF", "0")) +
            fmt.to_float(ia.get("totalINSS", "0"))
        )
        valor_mercadoria = fmt.format_number(total_nota_dec + impostos_retidos)
    elif is_aluguel:
        valor_mercadoria = str(ia.get("valorMercadoria", "0"))
    else:
        # Preferir o "VALOR TOTAL DOS PRODUTOS" (bruto) lido pela IA; só cair para a soma dos
        # itens do pedido (já líquida) quando a IA não tiver identificado esse valor.
        valor_merc_ia = fmt.to_float(ia.get("valorMercadoria", "0"))
        valor_mercadoria = fmt.format_number(valor_merc_ia) if valor_merc_ia > 0 else fmt.format_number(soma)

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

    tipo_preco = str(_g(dados_pedido[0] if dados_pedido else {}, "TIPO_PRECO", default=""))
    centro_custo = str(_g(dados_pedido[0] if dados_pedido else {}, "CC_RATEIO", "CC_PADRAO", default=""))
    projeto = str(_g(dados_pedido[0] if dados_pedido else {}, "PROJETO", "PROJ_PADRAO", default=""))

    payload = {
        "filial": str(_g(pedido_lista, "FIL_IN_CODIGO", default="")),
        "acao": str(acao_conta.get("acao", varacao_fallback or "")),
        "contasPagarTipoDoc": str(acao_conta.get("contasPagarTipoDoc", "")),
        "agente": str(_g(pedido_lista, "AGN_IN_CODIGO", default="")),
        "tipoPreco": tipo_preco,
        "centroCustoReduzido": centro_custo,
        "projetoReduzido": projeto,
        "numNota": str(num_nota),
        "serie": serie,
        "tipoDocFiscal": tipo_doc_final,
        "dataDocumento": data_doc,
        "dataMovimento": fmt.hoje_br(tz),
        "condPagto": cond_raw,
        "valorMercadoria": valor_mercadoria,
        "totalMaoObra": str(ia.get("totalMaoObra", "0.00")),
        "totalFrete": str(ia.get("totalFrete", "0.00")),
        "totalSeguro": str(ia.get("totalSeguro", "0.00")),
        "totalDespesa": str(ia.get("totalDespesa", "0.00")),
        "totalNota": str(total_nota),
        "chaveAcesso": chave,
        "totalImportacao": str(ia.get("totalImportacao", "0.00")),
        "despesaNaoTributada": str(ia.get("despesaNaoTributada", "0.00")),
        "valorAcrescimoGeral": str(ia.get("valorAcrescimoGeral", "0.00")),
        "valorDescontoGeral": str(ia.get("valorDescontoGeral", "0.00")),
        "baseICMS": base_icms_raiz,
        "valorICMS": str(ia.get("valorICMS", "0.00")),
        "valorIPI": str(ia.get("valorIPI", "0.00")),
        "totalISS": str(ia.get("totalISS", "0.00")),
        "totalISSDevido": str(ia.get("totalISSDevido", "0.00")),
        "totalIRRF": str(ia.get("totalIRRF", "0.00")),
        "totalINSS": str(ia.get("totalINSS", "0.00")),
        "valorSestSenat": str(ia.get("valorSestSenat", "0.00")),
        "baseSubstTributaria": str(ia.get("baseSubstTributaria", "0.00")),
        "valorICMSRetido": str(ia.get("valorICMSRetido", "0.00")),
        "valorPIS": str(ia.get("valorPIS", "0.00")),
        "valorCOFINS": str(ia.get("valorCOFINS", "0.00")),
        "totalCSLL": str(ia.get("totalCSLL", "0.00")),
        "baseFunRural": str(ia.get("baseFunRural", "0.00")),
        "valorFunRural": str(ia.get("valorFunRural", "0.00")),
        "valorICMSDesonera": str(ia.get("valorICMSDesonera", "0.00")),
        "valorPisRecupera": str(ia.get("valorPisRecupera", "0.00")),
        "valorCofinsRecupera": str(ia.get("valorCofinsRecupera", "0.00")),
        "valorBaseIPI": base_ipi_raiz,
        "operacao": "I",
        "calculaValores": "N",
        "itensReceb": itens,
        "parcelas": [parcela],
    }
    return payload, bloqueia_7d
