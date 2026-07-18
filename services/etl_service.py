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


def _impostos_retidos(ia: dict) -> float:
    """Soma dos tributos retidos usada para reconstituir o valor bruto (valorMercadoria) a partir
    do valor liquido (valorTotalDocumento): valorMercadoria = liquido + impostos retidos."""
    return (
        fmt.to_float(ia.get("valorISS", "0")) +
        fmt.to_float(ia.get("valorPIS", "0")) +
        fmt.to_float(ia.get("valorCOFINS", "0")) +
        fmt.to_float(ia.get("totalCSLL", "0")) +
        fmt.to_float(ia.get("totalIRRF", "0")) +
        fmt.to_float(ia.get("totalINSS", "0"))
    )


def consolidar_resposta_ia(ia: dict, extra: dict, pdc_codigo: Any) -> tuple[dict, str, str, str]:
    """Aplica a cadeia de refinamento. Retorna (ia_final, cnpj_emit, cnpj_tom, tipo_doc)."""
    ia = dict(ia)
    ia = br.corrigir_total_iss_por_valor_iss(ia)

    # Consolidar e sanitizar numNota: usar a leitura mais completa entre primária e extra (a IA
    # truncar dígitos de um numNota composto, ex. "1/77" -> "1", é mais provável do que ela inventar
    # dígitos a mais - por isso comparamos pelo tamanho já sanitizado, não só se a primária veio vazia).
    num_nota_primaria = str(ia.get("numNota", "")).strip()
    num_nota_extra = str(extra.get("numNota", "")).strip()
    sanit_primaria = br.sanitiza_num_nota(num_nota_primaria)
    sanit_extra = br.sanitiza_num_nota(num_nota_extra)
    if len(sanit_extra) > len(sanit_primaria):
        ia["numNota"] = sanit_extra
    else:
        ia["numNota"] = sanit_primaria

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


def montar_item(grupo: list[dict], ia: dict, num_nota: str, cnpj_emitente: str,
                total_nota: str, is_servico: bool, multi_item: bool,
                is_equatorial: bool = False) -> tuple[dict, float]:
    """grupo: linhas de dados_pedido com o mesmo ITEM_SEQUENCIA - representam UM item de fato,
    rateado entre um ou mais centros de custo/projetos (uma linha por rateio).

    is_equatorial: teste isolado (17/07/2026, pedido 25998/nota 198531151) - NÃO altera o
    comportamento de nenhum outro fornecedor/documento (default False preserva 100% da lógica
    anterior). Ver docs/REGRAS_PROJETO.md secao 3.13."""
    dado_pedido = grupo[0]
    is_aluguel = cnpj_emitente == CNPJ_ALUGUEL_IR
    is_vibra = cnpj_emitente == CNPJ_VIBRA_ENERGIA
    vtip = fmt.to_float(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))

    # O Mega valida o item do recebimento contra o valor original do pedido de compra ("Origem" x
    # "Recebimento" no Valor Unitário) - não é possível substituir pelo bruto reconstruído da NF
    # quando ele diverge do pedido; a parcela é que se ajusta para bater com os itens (ver
    # montar_payload), nunca o contrário.
    if not multi_item:
        if is_vibra:
            # VIBRA ENERGIA: sempre usar valorTotalDocumento (bruto) da IA
            valor_merc = str(ia.get("valorTotalDocumento", total_nota or "0"))
        elif is_servico and vtip > 0:
            valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))
        elif is_equatorial and vtip > 0:
            # TESTE (17/07/2026): valorMercadoria do item precisa bater com a soma das parcelas
            # ("Total da Fatura" x "Soma dos Valores das Parcelas", validado pelo próprio Mega -
            # caso real pedido 25998/nota 198531151, rejeitado quando o item usava o bruto
            # totalFornecimento=128,49 e a parcela usava soma(pedido)=27,34). O bruto/fiscal
            # (totalFornecimento) continua correto para a base de cálculo dos tributos, ver abaixo.
            valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))
        elif fmt.to_float(ia.get("valorMercadoria", "0")) > 0:
            valor_merc = str(ia.get("valorMercadoria"))
        elif fmt.to_float(total_nota) > 0:
            valor_merc = str(total_nota)
        elif vtip > 0:
            valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", "VALOR_CONFERIDO", default="0"))
        else:
            valor_merc = "0.00"
    else:
        valor_merc = str(_g(dado_pedido, "VALOR_TOTAL_ITEM_PEDIDO", default=""))

    base_dec = vtip

    # Base fiscal (tributos) - TESTE isolado para Equatorial: usar o bruto da fatura
    # (ia["valorMercadoria"] = totalFornecimento, ex.: 128,49) como base de cálculo de
    # ICMS/ISS/PIS/COFINS/IRRF/INSS/CSLL/IPI, em vez de vtip (soma do pedido, 27,34) - o
    # totalFornecimento é o valor realmente sujeito a tributação na fatura de energia, o desconto/
    # compensação é um ajuste financeiro à parte que não deveria reduzir a base de cálculo.
    # `base_dec` (usado no rateio de centro de custo/projeto e devolvido para compor `soma`/
    # valorParcela) NÃO muda - continua = vtip. Para qualquer outro fornecedor (is_equatorial=False),
    # base_fiscal_dec = base_dec, comportamento idêntico ao anterior.
    base_fiscal_dec = base_dec
    if is_equatorial:
        valor_merc_ia = fmt.to_float(ia.get("valorMercadoria", "0"))
        if valor_merc_ia > 0:
            base_fiscal_dec = valor_merc_ia

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

    valor_iss = valor_ou_calc("valorISS", "percentualISS", base_fiscal_dec)

    if is_aluguel:
        valor_irff = fmt.format_number(ia.get("totalIRRF", "0"))
        perc_irff = "0.00"
    else:
        valor_irff = valor_ou_calc("totalIRRF", "percentualIRFF", base_fiscal_dec)
        perc_irff = perc_ou_calc("totalIRRF", "percentualIRFF", base_fiscal_dec)

    base_fmt = fmt.format_number(base_fiscal_dec)
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
        "percIPI": perc_ou_calc("valorIPI", "percIPI", base_fiscal_dec),
        "valorIPI": valor_ou_calc("valorIPI", "percIPI", base_fiscal_dec),
        "valorIsentoIPI": "0",
        "valorOutrosIPI": "0",
        "valorRecuperadoIPI": "0",
        "baseIcms": base_icms,
        "percentualIcms": perc_ou_calc("valorICMS", "percentualIcms", base_fiscal_dec),
        "valorIcms": valor_ou_calc("valorICMS", "percentualIcms", base_fiscal_dec),
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
        "percentualISS": perc_ou_calc("valorISS", "percentualISS", base_fiscal_dec),
        "valorISS": valor_iss,
        "baseISSDevido": str(ia.get("baseISSDevido", "0.00")),
        "percentualISSDevido": str(ia.get("percentualISSDevido", "0.00")),
        "valorISSDevido": str(ia.get("valorISSDevido", "0.00")),
        "baseIRFF": base_fmt,
        "percentualIRFF": perc_irff,
        "valorIRFF": valor_irff,
        "baseINSS": base_fmt,
        "percentualINSS": perc_ou_calc("valorINSS", "percentualINSS", base_fiscal_dec),
        "valorINSS": valor_ou_calc("valorINSS", "percentualINSS", base_fiscal_dec),
        "basePIS": base_fmt,
        "percentualPIS": perc_ou_calc("valorPIS", "percentualPIS", base_fiscal_dec),
        "valorPIS": valor_ou_calc("valorPIS", "percentualPIS", base_fiscal_dec),
        "baseCofins": base_fmt,
        "percentualCofins": perc_ou_calc("valorCofins", "percentualCofins", base_fiscal_dec),
        "valorCofins": valor_ou_calc("valorCofins", "percentualCofins", base_fiscal_dec),
        "baseCSLL": base_fmt,
        "percentualCSLL": perc_ou_calc("valorCSLL", "percentualCSLL", base_fiscal_dec),
        "valorCSLL": valor_ou_calc("valorCSLL", "percentualCSLL", base_fiscal_dec),
        "sitTribIPI": "49",
        "codEnquadramentoIPI": "999",
    }

    centros_custo = []
    for dp_rateio in grupo:
        prct = fmt.to_float(_g(dp_rateio, "PRCT_CC", default="0"))
        valor_rateio = fmt.format_number(base_dec * prct / 100)
        prct_fmt = f"{prct:.4f}"
        centros_custo.append({
            "numNota": str(num_nota),
            "itemSequencia": str(_g(dp_rateio, "ITEM_SEQUENCIA", default="")),
            "centroCustoReduzido": str(_g(dp_rateio, "CC_RATEIO", "CC_PADRAO", default="")),
            "tipoClasse": str(_g(dp_rateio, "TIPO_CLASSE", default="")),
            "prctRateio": prct_fmt,
            "valorRateio": valor_rateio,
            "operacao": "I",
            "projetos": [{
                "numNota": str(num_nota),
                "itemSequencia": str(_g(dp_rateio, "ITEM_SEQUENCIA", default="")),
                "projetoReduzido": str(_g(dp_rateio, "PROJETO", "PROJ_PADRAO", default="")),
                "tipoClasse": str(_g(dp_rateio, "TIPO_CLASSE", default="")),
                "prctRateio": prct_fmt,
                "valorRateio": valor_rateio,
                "operacao": "I",
            }],
        })
    item["centrosCusto"] = centros_custo
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


def _agrupar_por_item(dados_pedido: list[dict]) -> list[list[dict]]:
    """Agrupa as linhas de dados_pedido por ITEM_SEQUENCIA. Cada grupo é UM item de fato; quando
    o pedido tem o mesmo item rateado entre vários centros de custo/projetos, essas linhas vêm
    repetidas com o mesmo ITEM_SEQUENCIA (só variando CC_RATEIO/PROJETO/PRCT_CC) e não devem virar
    itensReceb separados - o Mega rejeita (Constraint PK_EST_ITENSRECEB) por chave duplicada."""
    grupos: dict[str, list[dict]] = {}
    ordem: list[str] = []
    for dp in dados_pedido:
        chave = str(_g(dp, "ITEM_SEQUENCIA", default=""))
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(dp)
    return [grupos[chave] for chave in ordem]


def montar_payload(pedido_lista: dict, dados_pedido: list[dict], ia: dict, cnpj_emitente: str,
                   tipo_doc: str, acao_conta: dict, varacao_fallback: str, tz: str,
                   is_equatorial: bool = False) -> tuple[dict, bool, dict | None]:
    is_aluguel = cnpj_emitente == CNPJ_ALUGUEL_IR
    is_servico = br.eh_documento_servico(tipo_doc, TIPOS_DOC_SERVICO)
    # Agrupa linhas de rateio (mesmo ITEM_SEQUENCIA) num único item - qualquer pedido rateado entre
    # vários centros de custo/projetos vem com uma linha de dados_pedido por rateio, e virar um
    # itensReceb por linha gera chave duplicada no Mega (Constraint PK_EST_ITENSRECEB). Não é
    # específico da Equatorial: pedido 320588 (fornecedor Arquivolff, 9 rateios do mesmo item)
    # reproduziu o mesmo erro.
    grupos_item = _agrupar_por_item(dados_pedido)
    multi_item = len(grupos_item) > 1

    # Sanitizar e limpar número da nota
    num_nota_raw = ia.get("numNota", "")
    num_nota_sanitizado = br.sanitiza_num_nota(num_nota_raw)
    num_nota = br.remove_zeros_a_esquerda(num_nota_sanitizado)

    total_nota_ia = ia.get("valorTotalDocumento", "0")

    itens: list[dict] = []
    soma = 0.0
    bloqueia_7d = False
    for grupo in grupos_item:
        item, base_dec = montar_item(grupo, ia, num_nota, cnpj_emitente, total_nota_ia, is_servico, multi_item,
                                      is_equatorial=is_equatorial)
        itens.append(item)
        soma += base_dec
        cond = str(_g(grupo[0], "COND_PAGTO", default="")) or str(pedido_lista.get("COND_ST_CODIGO", ""))
        bloqueia_7d = bloqueia_7d or br.bloqueia_por_cond_pagto_7dias(cond)

    # totalNota = valor líquido (bruto - descontos - retenções); é o que efetivamente compõe o
    # título/parcela em condições normais.
    total_nota = total_nota_ia if fmt.to_float(total_nota_ia) > 0 else fmt.format_number(soma)

    # Para serviços, valorMercadoria = bruto ("Valor Total do Serviço"). Antes reconstruíamos esse
    # bruto somando líquido + tributos extraídos da NF (_impostos_retidos), mas isso falha quando a
    # NF traz PIS/COFINS apenas INFORMATIVOS (não retidos - comum em NFS-e, ver nota no rodapé tipo
    # "Informações preenchidas nos campos de PIS e COFINS são referentes aos valores totais sobre a
    # operação") junto com tributos de fato retidos (IRRF/CSLL): a soma superestima o bruto e diverge
    # do valor cadastrado no pedido de compra, causando rejeição do Mega ("Soma dos Valores das
    # Parcelas não confere com o Total da Fatura"). Caso real: pedido 320921/nota 5473 (Electric
    # Mobility) - bruto real R$90,00 (bate com o pedido), reconstrução antiga dava R$92,65.
    # Preferir o valor já usado no item (soma = VALOR_TOTAL_ITEM_PEDIDO do pedido de compra) - é a
    # mesma fonte que o Mega valida como "Total da Fatura", elimina a divergência interna entre
    # item e raiz. Cai para a reconstrução por tributos só quando o pedido não tiver esse valor.
    # DIVERGÊNCIA PEDIDO x NF (ver docs/REGRAS_PROJETO.md secao 3.10): usar "soma" (pedido de
    # compra) como valorMercadoria evita a rejeicao do Mega quando ele bate com o pedido (caso
    # Electric Mobility, secao 3.9), mas isso SILENCIA a checagem do Mega quando o PROBLEMA
    # real e o pedido de compra estar cadastrado com um total diferente do bruto real da NF (caso
    # Rapido Araguaia, pedido 320868/nota 193: NF "Valor dos Servicos" = 480.00, pedido cadastrado
    # com soma = 456.89 - o robo lancou usando 456.89, e o lancamento foi aceito pelo Mega porque
    # bate com o proprio pedido, mas o valor registrado ficou ERRADO em relacao a nota real).
    # Por isso comparamos aqui o bruto lido DIRETO do documento pela IA (ia["valorMercadoria"], o
    # campo "Valor Total do Servico"/"Valor dos Servicos" impresso na NF) contra "soma": se
    # divergirem alem da tolerancia de arredondamento, sinalizamos para o controller BLOQUEAR o
    # lancamento e pedir correcao manual do pedido, em vez de lancar silenciosamente com o valor
    # do pedido (que pode estar errado).
    divergencia_pedido_nf = None
    if is_servico:
        if soma > 0:
            valor_mercadoria = fmt.format_number(soma)
            valor_nf_bruto = fmt.to_float(ia.get("valorMercadoria", "0"))
            if valor_nf_bruto > 0 and abs(valor_nf_bruto - soma) > 0.05:
                divergencia_pedido_nf = {
                    "valor_nf_bruto": fmt.format_number(valor_nf_bruto),
                    "valor_pedido": fmt.format_number(soma),
                }
        else:
            total_nota_dec = fmt.to_float(total_nota)
            valor_mercadoria = fmt.format_number(total_nota_dec + _impostos_retidos(ia))
    elif is_aluguel:
        valor_mercadoria = str(ia.get("valorMercadoria", "0"))
    else:
        # Preferir o "VALOR TOTAL DOS PRODUTOS" (bruto) lido pela IA; só cair para a soma dos
        # itens do pedido (já líquida) quando a IA não tiver identificado esse valor.
        valor_merc_ia = fmt.to_float(ia.get("valorMercadoria", "0"))
        valor_mercadoria = fmt.format_number(valor_merc_ia) if valor_merc_ia > 0 else fmt.format_number(soma)

    # valorParcela = soma (valor cadastrado no pedido de compra, VALOR_TOTAL_ITEM_PEDIDO), NÃO
    # valorMercadoria (correção de 17/07/2026 - a regra "valorParcela = valorMercadoria sempre"
    # criada mais cedo hoje, a partir do caso pedido 872/nota 199225903, se mostrou incompleta:
    # nesse caso soma(pedido)=284,46 coincidia com valorMercadoria(FORNECIMENTO)=284,46, então
    # "usar valorMercadoria" e "usar soma" davam o mesmo resultado. Mas no pedido 25998/nota
    # 198531151 (também Equatorial, mas com uma compensação/desconto grande de -105,44),
    # valorMercadoria(FORNECIMENTO bruto)=128,49 e soma(pedido)=27,34 SÃO DIFERENTES - o
    # lançamento saiu com valorParcela=128,49 (ACEITO pelo Mega sem rejeição, mas
    # CONTABILMENTE ERRADO: a parcela deve refletir o que de fato será pago, que é o valor
    # líquido após a compensação, e é exatamente o que está cadastrado no pedido de compra:
    # 27,34). A soma do pedido é a referência correta e universal - é a mesma fonte que o Mega
    # valida como "Total da Fatura"/pedido em outros tipos de documento (ver Validação 9, secao
    # 3.10), e reflete a decisão de quem cadastrou o pedido sobre o que efetivamente será pago,
    # independente de ser igual a valorMercadoria (bruto) ou a totalNota (líquido da NF) - isso
    # varia caso a caso e não pode ser assumido como sempre um ou sempre outro.
    valor_parcela = fmt.format_number(soma) if soma > 0 else valor_mercadoria

    cond_raw = str(_g(pedido_lista, "COND_ST_CODIGO", default="")) or str(_g(dados_pedido[0] if dados_pedido else {}, "COND_PAGTO", default=""))
    cond_norm = br.normaliza_cond_pagto(cond_raw)
    data_doc = str(ia.get("dataDocumento", ""))
    venc = br.vencimento_parcela_1(data_doc, cond_norm)

    parcela = {
        "numNota": str(num_nota), "numDocumento": str(num_nota), "numParcela": "1",
        "dataVencimento": venc, "valorParcela": str(valor_parcela),
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
        # TESTE EM VALIDACAO (docs/REGRAS_PROJETO.md 3.7): campo existia no template original do
        # fluxo Power Automate (docs/Json pac.txt, "Compor - template_raiz") e foi perdido na
        # reescrita em Python - nunca chegou a ser preenchido com valor real no fluxo original,
        # mas restaurado aqui por paridade estrutural com o payload que o Mega recebia antes.
        "valorMercadoriaEmpenhada": "",
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
        # TESTE EM VALIDACAO (docs/REGRAS_PROJETO.md 3.7): os 3 campos abaixo tambem existiam no
        # template original ("Compor - template_raiz") e sumiram na reescrita em Python. Hipotese:
        # o Mega Integrador/middleware pode depender da PRESENCA dessas chaves no JSON pra rotear
        # corretamente a retencao combinada de PIS/COFINS/CSLL pro agente consolidador (ex.: 505),
        # mesmo que o valor venha vazio - por isso restaurados vazios, igual ao fluxo original.
        "tragnCodigo": "",
        "tipoTrans": "",
        "icmsStreRecupera": "",
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
    return payload, bloqueia_7d, divergencia_pedido_nf
