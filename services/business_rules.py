"""Regras de negocio puras (stateless, testaveis) do LancamentoCLN.

Cada funcao traduz uma regra do fluxo Power Automate. Nenhuma faz I/O.
"""
from __future__ import annotations

from config import (
    ALMOXARIFADO_LOCALIZACAO,
    CNPJ_ALUGUEL_IR,
    COND_PAGTO_A_VISTA,
    DEPARA_FILIAIS,
    TABELA_DEPARA_TIPODOC,
    TIPO_DOC_POR_EMITENTE,
)
from utils import formatter as fmt
from utils import validators as val


def eh_apolice(tipo_doc: str) -> bool:
    return (tipo_doc or "").strip().upper() == "APOLICE"


def resolver_tipo_doc_por_emitente(tipo_doc_ia: str, cnpj_emitente: str) -> str:
    """De-para de tipoDocFiscal por CNPJ do emitente.

    APOLICE tem precedencia absoluta (correcao: MAPFRE apolice nao vira BOLP).
    """
    tipo = (tipo_doc_ia or "").strip()
    if eh_apolice(tipo):
        return tipo
    return TIPO_DOC_POR_EMITENTE.get(val.normaliza_cnpj(cnpj_emitente), tipo)


def ajustar_bolp_detran(tipo_doc: str) -> str:
    if tipo_doc in ("BOLP-DETRAN", "BOLP-DETRAN-IPVA-ANTT"):
        return "BOLP"
    return tipo_doc


def calcular_acao_e_conta(tipo_doc: str, cond_pagto: str) -> dict:
    entrada = TABELA_DEPARA_TIPODOC.get((tipo_doc or "").strip())
    if not entrada:
        return {"contasPagarTipoDoc": "", "acao": 0}
    a_vista = (cond_pagto or "").strip().upper() in COND_PAGTO_A_VISTA
    acao = entrada["acao_vista"] if a_vista else entrada["acao_prazo"]
    return {"contasPagarTipoDoc": entrada["contasPagarTipoDoc"], "acao": int(acao)}


def eh_documento_servico(tipo_doc: str, tipos_servico: set[str]) -> bool:
    return (tipo_doc or "").strip() in tipos_servico


def iss_extra_retido(extra: dict) -> bool:
    flag = extra.get("issRetido") is True
    return flag or fmt.to_float(extra.get("valorISSRetido", "0")) > 0


def aplicar_iss_do_valor_retido(ia: dict, extra: dict) -> dict:
    retido = fmt.to_float(extra.get("valorISSRetido", "0"))
    if retido <= 0:
        return ia
    base = fmt.to_float(ia.get("valorTotalDocumento", "0"))
    perc = fmt.format_number((retido * 100 / base)) if base > 0 else "0.00"
    ia = dict(ia)
    ia["valorISS"] = fmt.format_number(retido)
    ia["totalISS"] = fmt.format_number(retido)
    ia["baseISS"] = fmt.format_number(base)
    ia["percentualISS"] = perc
    ia["valorISSDevido"] = fmt.format_number(retido)
    ia["totalISSDevido"] = fmt.format_number(retido)
    return ia


def precisa_retificar_iss_nao_retido(ia: dict, extra: dict) -> bool:
    if iss_extra_retido(extra):
        return False
    return fmt.to_float(ia.get("valorISS", "0")) > 0 or fmt.to_float(ia.get("totalISS", "0")) > 0


def retificar_iss_nao_retido(ia: dict) -> dict:
    ia = dict(ia)
    for campo in ("valorISS", "totalISS", "percentualISS", "baseISS"):
        ia[campo] = "0.00"
    return ia


def corrigir_total_iss_por_valor_iss(ia: dict) -> dict:
    if fmt.to_float(ia.get("valorISS", "0")) > 0 and fmt.to_float(ia.get("totalISS", "0")) <= 0:
        ia = dict(ia)
        ia["totalISS"] = ia.get("valorISS", "0.00") or "0.00"
    return ia


_PARES_PERC = [
    ("percentualISS", "valorISS", "baseISS"),
    ("percentualIRFF", "valorIRFF", "baseIRFF"),
    ("percentualINSS", "valorINSS", "baseINSS"),
    ("percentualPIS", "valorPIS", "basePIS"),
    ("percentualCofins", "valorCofins", "baseCofins"),
    ("percentualCSLL", "valorCSLL", "baseCSLL"),
    ("percentualIcms", "valorICMS", "baseICMS"),
    ("percIPI", "valorIPI", "valorBaseIPI"),
]


def calcular_percentuais_por_valor_e_base(ia: dict) -> dict:
    ia = dict(ia)
    for p_campo, v_campo, b_campo in _PARES_PERC:
        if str(ia.get(p_campo, "")).strip() != "":
            continue
        base = fmt.to_float(ia.get(b_campo, "0"))
        ia[p_campo] = fmt.format_number(fmt.to_float(ia.get(v_campo, "0")) * 100 / base) if base > 0 else "0.00"
    return ia


def valida_emitente_x_fornecedor(cnpj_emitente: str, cnpj_fornecedor: str) -> bool:
    if val.normaliza_cnpj(cnpj_emitente) == "":
        return True
    emit = val.normaliza_cnpj(cnpj_emitente)
    forn = val.normaliza_cnpj(cnpj_fornecedor)
    return emit == forn or val.mesma_raiz(emit, forn)


def valida_emitente_x_fornecedor_multi(cnpjs_emitente: list[str], cnpj_fornecedor: str) -> bool:
    """Confere se PELO MENOS UM dos CNPJs emitente lidos entre os anexos do pedido bate com o
    fornecedor cadastrado.

    Usa a redundância de documentos da mesma transação (NF + boletos) para tolerar erro de
    leitura da IA em um dos anexos, sem afrouxar o critério de comparação (ainda exige CNPJ
    igual ou mesma raiz - só amplia a evidência disponível).
    """
    return any(valida_emitente_x_fornecedor(c, cnpj_fornecedor) for c in cnpjs_emitente)


def nome_fornecedor_confere(nomes_candidatos: list[str], nome_fantasia_pedido: str) -> bool:
    """Confere se algum dos nomes retornados pela consulta de fornecedor (fantasia/razão social)
    bate com o nome fantasia do pedido - usado para confirmar um CNPJ emitente via cadastro
    quando a leitura do documento não bate com o fornecedor esperado."""
    alvo = val.normaliza_texto(nome_fantasia_pedido)
    if not alvo:
        return False
    for nome in nomes_candidatos:
        candidato = val.normaliza_texto(nome)
        if not candidato:
            continue
        if alvo in candidato or candidato in alvo:
            return True
    return False


def valida_tomador_x_filial(cnpj_tomador: str, nome_tomador: str, filial_cod: str, cnpj_filial_pedido: str,
                            nome_filial_pedido: str = "") -> bool:
    tomador = val.normaliza_cnpj(cnpj_tomador)
    nome = val.normaliza_texto(nome_tomador)
    if tomador == "" and nome == "":
        return True
    filial = DEPARA_FILIAIS.get(str(filial_cod or "").strip(), {})
    cnpj_ref = val.normaliza_cnpj(filial.get("cnpj", ""))
    nome_ref = val.normaliza_texto(filial.get("nome", ""))
    if cnpj_ref and tomador == cnpj_ref:
        return True
    if nome_ref and nome_ref in nome:
        return True
    if not cnpj_ref and tomador == val.normaliza_cnpj(cnpj_filial_pedido):
        return True
    if val.mesma_raiz(tomador, cnpj_filial_pedido):
        return True
    # Regra: nome do tomador bate com o nome da filial cadastrada na base (FIL_ST_FANTASIA), mesmo
    # que o CNPJ do tomador tenha sido lido errado pela IA (ex.: erro de OCR em documento
    # escaneado) - caso real pedido 5777, CNPJ lido "03255577000124" em vez de "24357174000174",
    # mas nome extraído batia com "CONDOMINIO SHOPPING CENTER CERRADO - MATRIZ".
    nome_filial_ref = val.normaliza_texto(nome_filial_pedido)
    if nome_filial_ref and nome and (nome_filial_ref in nome or nome in nome_filial_ref):
        return True
    return False


def valida_tomador_x_filial_multi(candidatos: list[tuple[str, str]], filial_cod: str, cnpj_filial_pedido: str,
                                   nome_filial_pedido: str = "") -> bool:
    """Confere se PELO MENOS UM dos pares (cnpj_tomador, nome_tomador) lidos entre os anexos do
    pedido bate com a filial esperada - mesma lógica de redundância usada para o emitente."""
    return any(
        valida_tomador_x_filial(cnpj, nome, filial_cod, cnpj_filial_pedido, nome_filial_pedido)
        for cnpj, nome in candidatos
    )


def normaliza_cond_pagto(cond: str) -> str:
    s = (cond or "").strip().upper()
    if s and s[0].isdigit() and " " in s:
        return s.split(" ")[0]
    return s


def unidade_cond_pagto(cond_norm: str) -> str:
    return cond_norm[-1:] if cond_norm else ""


def quantidade_cond_pagto(cond_norm: str) -> int:
    unidade = unidade_cond_pagto(cond_norm)
    if unidade not in ("D", "M") or len(cond_norm) <= 1:
        return 0
    prefixo = cond_norm[:-1]
    return int(prefixo) if prefixo.isdigit() else 0


def vencimento_parcela_1(data_documento_br: str, cond_norm: str) -> str:
    unidade = unidade_cond_pagto(cond_norm)
    qtd = quantidade_cond_pagto(cond_norm)
    if unidade == "M":
        return fmt.add_meses_br(data_documento_br, qtd)
    if unidade == "D":
        return fmt.add_dias_br(data_documento_br, qtd)
    return str(data_documento_br or "")


def bloqueia_por_cond_pagto_7dias(cond_pagto_raw: str) -> bool:
    s = (cond_pagto_raw or "").strip().upper()
    if not s or s[-1] != "D" or len(s) <= 1:
        return False
    prefixo = s[:-1]
    return prefixo.isdigit() and int(prefixo) <= 7


def calcular_deve_lancar_por_vencimento(cnpj_emitente: str, data_documento_br: str, cond_pagto_raw: str, tz: str) -> bool:
    if val.normaliza_cnpj(cnpj_emitente) == CNPJ_ALUGUEL_IR:
        return True
    s = (cond_pagto_raw or "").strip().upper()
    dias_txt = s[:-1] if (len(s) > 1 and s[-1] == "D") else ""
    if not dias_txt.isdigit():
        return True
    # Sem data de emissão extraída do documento, usar hoje como referência.
    data_base_br = data_documento_br if fmt.data_br_para_iso(data_documento_br) else fmt.hoje_br(tz)
    data_base_iso = fmt.data_br_para_iso(data_base_br)
    venc_iso = fmt.data_br_para_iso(fmt.add_dias_br(data_base_br, int(dias_txt)))
    return not fmt.dias_ate(venc_iso, data_base_iso) <= 7


def calcular_cond_pagto_por_vencimento(data_documento_br: str, data_vencimento_br: str) -> str:
    """Calcula a condição de pagamento ("NND") a partir da diferença exata em dias corridos
    entre a data de vencimento do boleto e a data de emissão do documento."""
    ini = fmt.data_br_para_iso(data_documento_br)
    fim = fmt.data_br_para_iso(data_vencimento_br)
    if not ini or not fim:
        return ""
    return f"{fmt.dias_ate(fim, ini):02d}D"


def valida_cond_pagto_por_vencimento(cond_pagto_raw: str, data_documento_br: str,
                                      data_vencimento_boleto_br: str) -> tuple[bool, str]:
    """Confere se a condição de pagamento do pedido bate com o vencimento do boleto anexado.

    Pula a validação (retorna ok=True) quando não há boleto com vencimento extraído, ou quando a
    condição de pagamento é um código especial sem contagem de dias (ADIANT, CREDITO, etc.) -
    nesses casos o robo confia no cadastro do pedido, sem bloquear por falta de dado.
    """
    if not str(data_vencimento_boleto_br or "").strip():
        return True, ""
    cond_norm = normaliza_cond_pagto(cond_pagto_raw)
    if cond_norm in COND_PAGTO_A_VISTA or unidade_cond_pagto(cond_norm) != "D" or quantidade_cond_pagto(cond_norm) <= 0:
        return True, ""
    esperada = calcular_cond_pagto_por_vencimento(data_documento_br, data_vencimento_boleto_br)
    if not esperada:
        return True, ""
    return esperada == cond_norm, esperada


def resolver_localizacao_almoxarifado(almoxarifado: str) -> str:
    """TEMPORÁRIO: só usado para aviso/bloqueio manual (ver ALMOXARIFADO_LOCALIZACAO em
    config/settings.py). Retorna "" quando o almoxarifado não está no de-para conhecido."""
    return ALMOXARIFADO_LOCALIZACAO.get(str(almoxarifado or "").strip(), "")


def montar_parcelas_por_boletos(num_nota: str, boletos: list[dict], total_nota: str) -> tuple[list[dict], bool, str]:
    """Monta uma parcela por boleto anexado ao pedido (cada boleto = uma parcela real do
    pagamento rateado), usando o valor e o vencimento de cada boleto individual.

    Só atua quando há 2 ou mais boletos com valor e vencimento extraídos; com 0 ou 1 boleto,
    retorna lista vazia (o chamador mantém a parcela única já calculada por vencimento_parcela_1).

    Retorna (parcelas, soma_ok, soma_calculada). soma_ok=False quando a soma dos valores dos
    boletos não bate com o total da nota (tolerância de 0.01) - quem chama decide se bloqueia.
    """
    validos = [
        b for b in boletos
        if str(b.get("dataVencimento") or "").strip() and fmt.to_float(b.get("valorTotalDocumento", "0")) > 0
    ]
    if len(validos) < 2:
        return [], True, ""

    ordenados = sorted(validos, key=lambda b: fmt.data_br_para_iso(b["dataVencimento"]) or "9999-99-99")
    soma = sum(fmt.to_float(b["valorTotalDocumento"]) for b in ordenados)

    parcelas = [
        {
            "numNota": str(num_nota),
            "numDocumento": str(num_nota),
            "numParcela": str(idx),
            "dataVencimento": b["dataVencimento"],
            "valorParcela": fmt.format_number(fmt.to_float(b["valorTotalDocumento"])),
        }
        for idx, b in enumerate(ordenados, start=1)
    ]
    ok = abs(soma - fmt.to_float(total_nota)) <= 0.01
    return parcelas, ok, fmt.format_number(soma)


def sanitiza_num_nota(num_nota: str) -> str:
    """Remove caracteres inválidos do número da nota.

    Trata casos como:
    - "1/77" -> "177" (IA confundiu, remover barra que é artefato visual)
    - "12345-A" -> "12345" (remove sufixo não numérico)
    - "NF 123" -> "123" (remove prefixo não numérico)
    - "1 77" -> "177" (remove espaços)
    """
    s = str(num_nota or "").strip()

    # Remover prefixos comuns
    s = s.replace("NF", "").replace("NFE", "").replace("Nº", "").replace("No", "").strip()

    # Remover TODOS os caracteres não numéricos (incluindo barras, hífens, espaços)
    # Isso transforma "1/77" em "177", "1 77" em "177", "123-A" em "123"
    s = "".join(c for c in s if c.isdigit())

    return s


def remove_zeros_a_esquerda(num_nota: str) -> str:
    s = str(num_nota or "").strip()
    while s.startswith("0") and len(s) > 1:
        s = s[1:]
    return s


def num_nota_por_pedido(num_nota_ia: str, pdc_codigo) -> str:
    return str(num_nota_ia).strip() if str(num_nota_ia or "").strip() else str(pdc_codigo or "")


def resolver_serie(tipo_doc: str, serie_atual: str, chave_acesso: str, cnpj_emitente: str) -> str:
    from config import CNPJ_VIBRA_ENERGIA
    if tipo_doc not in ("NF-E", "NFSC", "NFSTE", "NF3E"):
        return "UN"
    if val.normaliza_cnpj(cnpj_emitente) == CNPJ_VIBRA_ENERGIA:
        return "0"
    if str(serie_atual or "").strip() != "":
        return str(serie_atual)
    chave = str(chave_acesso or "").strip()
    if len(chave) == 44:
        return str(int(chave[22:25]))
    return ""


def resolver_chave_acesso(tipo_doc: str, chave_atual: str) -> str:
    if tipo_doc in ("NFS-EG", "NFS-E", "BOLP", "BOLP-DETRAN", "BOLP-DETRAN-IPVA-ANTT"):
        return ""
    return str(chave_atual or "")


def eh_reembolso(agn_st_fantasia: str) -> bool:
    return "REEMBOLSO" in (agn_st_fantasia or "").strip().upper()


def eh_fatura_execucao_manual(agn_st_fantasia: str, fantasias_manuais: set[str]) -> bool:
    """Fornecedores cuja fatura de serviço foge do padrão de documento previsto para o RPA (ex.:
    Sitpass) - nunca deve ir para execução automática, sempre lançamento manual."""
    return (agn_st_fantasia or "").strip().upper() in {f.upper() for f in fantasias_manuais}


def eh_anexo_protegido_por_senha(nome_arquivo: str, termos_protegidos: set[str]) -> bool:
    """Nome do arquivo contém termo conhecido de PDF protegido por senha (ex.: faturas Tim,
    padrão "Tim -Val-...") - nesses casos a IA nunca consegue ler o conteúdo, então nem vale a
    pena tentar (evita esperar o timeout de ~7min só para falhar)."""
    nome_upper = (nome_arquivo or "").strip().upper()
    return any(termo.upper() in nome_upper for termo in termos_protegidos)


def eh_fornecedor_provavel_senha(agn_st_fantasia: str, fantasias_provavel_senha: set[str]) -> bool:
    """Fornecedor cujas faturas quase sempre vêm em PDF protegido por senha (ex.: TIM S/A), usado
    como rede de segurança: se a IA falhar ao ler o anexo desse fornecedor mesmo quando o nome do
    arquivo não bateu com nenhum termo de ARQUIVOS_PROTEGIDOS_SENHA (variação de nomenclatura),
    trata a falha como "protegido por senha" em vez de erro técnico genérico."""
    return (agn_st_fantasia or "").strip().upper() in {f.upper() for f in fantasias_provavel_senha}


def eh_fornecedor_equatorial(agn_st_fantasia: str) -> bool:
    """Fornecedor Equatorial Goiás Distribuidora de Energia - a Equatorial não deve mais ter
    PIS/COFINS retidos no lançamento (decisão de negócio, confirmada em 16/07/2026), mesmo quando
    o documento traz esses valores. Ver zerar_pis_cofins."""
    return "EQUATORIAL" in (agn_st_fantasia or "").strip().upper()


def zerar_pis_cofins(ia: dict) -> dict:
    """Zera PIS/COFINS (campos de raiz e de item) na resposta consolidada da IA - usado para
    fornecedores que não devem mais ter esses tributos retidos no lançamento (ex.: Equatorial)."""
    ia = dict(ia)
    for campo in ("valorPIS", "percentualPIS", "basePIS", "valorCOFINS", "valorCofins",
                  "percentualCofins", "baseCofins"):
        ia[campo] = "0.00"
    return ia


def _valor_linha_financeira(item) -> float:
    """Extrai o valor de uma linha de ITENS FINANCEIROS - normalmente só 1 número em `valores`.
    Aceita formatos antigos (`valorReais` ou string simples) por compatibilidade."""
    if isinstance(item, dict):
        if "valores" in item:
            valores = [fmt.to_float(v) for v in (item.get("valores") or [])]
            return valores[0] if valores else 0.0
        return fmt.to_float(item.get("valorReais", "0"))
    return fmt.to_float(item)


def _valores_reais(itens: list) -> list[float]:
    """Extrai os valores numericos (em R$) de uma lista de itens de ITENS FINANCEIROS da extracao
    Equatorial (ver _valor_linha_financeira). Ignora silenciosamente entradas malformadas."""
    return [_valor_linha_financeira(item) for item in (itens or [])]


def aplicar_valores_equatorial(ia: dict, total_fornecimento, itens_financeiros: list) -> dict:
    """Faturas de energia elétrica (Equatorial) não preenchem o campo genérico "valorMercadoria"
    do template padrão (não é um documento de mercadoria/serviço comum) - o próprio Mega valida o
    item do recebimento contra o valor da seção FORNECIMENTO da fatura, não contra o total da
    fatura. Ver docs/REGRAS_PROJETO.md secao 3.11 e caso real: pedido 872/nota 199225903, rejeitado
    pelo Mega com "Origem: (284,46) - Recebimento (328,64)" - 284,46 é a soma de FORNECIMENTO,
    328,64 e o TOTAL da fatura (FORNECIMENTO 284,46 + ITENS FINANCEIROS 44,18).

    - `valorMercadoria` (raiz e item) = `total_fornecimento` - lido PRONTO da linha "TOTAL" da
      tabela "Itens da Fatura" (3ª coluna, ver prompt_3a_equatorial_ia.txt), não mais somado a
      partir da transcrição linha a linha de FORNECIMENTO. Motivo da mudança (17/07/2026): a
      transcrição/soma linha a linha (6 a 9 linhas x 6 a 8 números cada) errou repetidas vezes de
      formas diferentes (colunas trocadas, linhas desalinhadas/duplicadas/perdidas) mesmo após
      várias rodadas de ajuste de prompt - ver docs/REGRAS_PROJETO.md secao 3.11. A fatura já
      imprime esse total pronto na linha "TOTAL", então basta ler um único número em vez de somar
      dezenas deles.
    - `totalDespesa` ("despesas acessórias") = soma dos valores POSITIVOS de `itensFinanceiros`.
    - `valorDescontoGeral` = soma (em módulo, sem sinal) dos valores NEGATIVOS de
      `itensFinanceiros` (créditos/descontos/estornos).

    `total_fornecimento`: string/número já pronto (não uma lista). `itens_financeiros`: lista de
    `{"descricao": str, "valores": [str, ...]}` (ver prompt_3a_equatorial_ia.txt).

    Se `total_fornecimento` vier vazio/zero, não sobrescreve `valorMercadoria` (mantém o valor que
    a extração primária/fallback já tiver produzido) - evita zerar um documento por falha pontual
    desta extração extra. A confiabilidade do resultado deve ser conferida separadamente com
    `reconciliacao_equatorial` (soma deve bater com o valorTotalDocumento da fatura) ANTES de usar
    este payload para lançamento."""
    ia = dict(ia)
    valor_fornecimento = fmt.to_float(total_fornecimento) if total_fornecimento not in (None, "") else 0.0
    valores_financeiros = _valores_reais(itens_financeiros)

    if valor_fornecimento:
        ia["valorMercadoria"] = fmt.format_number(valor_fornecimento)

    soma_despesas = sum(v for v in valores_financeiros if v > 0)
    soma_descontos = sum(-v for v in valores_financeiros if v < 0)
    ia["totalDespesa"] = fmt.format_number(soma_despesas)
    ia["valorDescontoGeral"] = fmt.format_number(soma_descontos)
    return ia


def reconciliacao_equatorial(ia: dict, tolerancia: float = 0.05) -> tuple[bool, str]:
    """Confere se a extração Equatorial (FORNECIMENTO/ITENS FINANCEIROS, ver
    aplicar_valores_equatorial) é internamente consistente: valorMercadoria (FORNECIMENTO) +
    totalDespesa (itens financeiros positivos) - valorDescontoGeral (itens financeiros negativos,
    em módulo) deve bater com valorTotalDocumento (o TOTAL impresso na fatura, extraído de forma
    independente na extração primária). Se não bater, a extração das seções da tabela "Itens da
    Fatura" está errada (ex.: misturou colunas ou incluiu valores da caixa "Tributos" por engano -
    caso real 17/07/2026, pedido 872/nota 199225903) e NÃO deve ser usada para lançamento.

    Retorna (ok, detalhe) - `detalhe` é uma mensagem pronta para log/Teams quando ok=False."""
    soma_calculada = (fmt.to_float(ia.get("valorMercadoria", "0"))
                       + fmt.to_float(ia.get("totalDespesa", "0"))
                       - fmt.to_float(ia.get("valorDescontoGeral", "0")))
    total_esperado = fmt.to_float(ia.get("valorTotalDocumento", "0"))
    if total_esperado <= 0:
        # Sem total confiável para comparar - não bloqueia, mas também não há como validar.
        return True, ""
    diferenca = soma_calculada - total_esperado
    if abs(diferenca) <= tolerancia:
        return True, ""
    detalhe = (f"FORNECIMENTO ({ia.get('valorMercadoria', '0')}) + despesas "
               f"({ia.get('totalDespesa', '0')}) - descontos ({ia.get('valorDescontoGeral', '0')}) "
               f"= {fmt.format_number(soma_calculada)}, mas o TOTAL da fatura é "
               f"{ia.get('valorTotalDocumento', '0')} (diferença de {fmt.format_number(abs(diferenca))})")
    return False, detalhe


def eh_filial_rapido_araguaia(org_ou_fil_fantasia: str) -> bool:
    """Filial/organização Rápido Araguaia - quando compradora de energia da Equatorial, também
    não deve ter ICMS retido no lançamento (decisão de negócio, confirmada em 16/07/2026). Ver
    zerar_icms."""
    return "RAPIDO ARAGUAIA" in (org_ou_fil_fantasia or "").strip().upper()


def zerar_icms(ia: dict) -> dict:
    """Zera ICMS (campos de raiz e de item) na resposta consolidada da IA - usado para pedidos da
    filial Rápido Araguaia com fornecedor Equatorial, que não deve ter ICMS retido no lançamento."""
    ia = dict(ia)
    for campo in ("valorICMS", "percentualIcms", "baseICMS"):
        ia[campo] = "0.00"
    return ia


def resolver_cnpj_emitente_corrigido(agn_st_fantasia: str, cnpj_emitente_ia: str, de_para: dict[str, str]) -> str:
    """Corrige o CNPJ do emitente lido pela IA para fornecedores que ela erra com frequência (ex.:
    lê um CNPJ incompleto/truncado em vez do CNPJ real do emitente).

    Usa o fornecedor cadastrado no PEDIDO (AGN_ST_FANTASIA), não o nome lido pela IA, porque é a
    fonte confiável. Retorna o CNPJ correto cadastrado em `de_para` quando o fornecedor está lá,
    senão devolve `cnpj_emitente_ia` sem alteração."""
    de_para_upper = {f.strip().upper(): cnpj for f, cnpj in de_para.items()}
    correto = de_para_upper.get((agn_st_fantasia or "").strip().upper())
    return val.normaliza_cnpj(correto) if correto else cnpj_emitente_ia


def resolver_cnpj_tomador_corrigido(agn_st_fantasia: str, cnpj_tomador_ia: str, de_para: dict[str, str]) -> str:
    """Corrige o CNPJ do tomador lido pela IA para fornecedores que ela erra com frequência (ex.:
    fatura de energia elétrica sem seção "Tomador" explícita, onde a IA pode confundir outro
    número de 11 dígitos - CPF de produtor rural, registro de imóvel etc. - com o CNPJ do
    tomador). Mesmo padrão de `resolver_cnpj_emitente_corrigido`, mas para o tomador.

    Usa o fornecedor cadastrado no PEDIDO (AGN_ST_FANTASIA), não o nome lido pela IA. Retorna o
    CNPJ correto cadastrado em `de_para` quando o fornecedor está lá, senão devolve
    `cnpj_tomador_ia` sem alteração."""
    de_para_upper = {f.strip().upper(): cnpj for f, cnpj in de_para.items()}
    correto = de_para_upper.get((agn_st_fantasia or "").strip().upper())
    return val.normaliza_cnpj(correto) if correto else cnpj_tomador_ia


def corrigir_emitente_tomador_invertidos(ia: dict, cnpj_forn_esperado: str, cnpj_filial_esperado: str) -> dict:
    """Corrige quando a IA troca emitente e tomador (comum em RECIBO/TERMO assinado por pessoa
    fisica prestadora de servico, onde a IA confunde quem pagou com quem recebeu o pagamento).

    Sinal de troca: `cnpjEmitente` extraido bate com o CNPJ da FILIAL (quem pagou, deveria ser o
    tomador) e `cnpjCpfTomador` extraido bate com o CNPJ do FORNECEDOR cadastrado no pedido (quem
    prestou o servico, deveria ser o emitente) - exatamente invertido do esperado. Corrige caso
    real: pedido 320931, RECIBO/termo de SERGIO GLEIK DAVID (CPF) lido com nomeEmitente/
    cnpjEmitente = RAPIDO ARAGUAIA (filial) e nomeTomador/cnpjCpfTomador = SERGIO GLEIK (o
    prestador de fato)."""
    cnpj_forn_esperado = val.normaliza_cnpj(cnpj_forn_esperado)
    cnpj_filial_esperado = val.normaliza_cnpj(cnpj_filial_esperado)
    if not cnpj_forn_esperado or not cnpj_filial_esperado or cnpj_forn_esperado == cnpj_filial_esperado:
        return ia
    cnpj_emit = val.normaliza_cnpj(ia.get("cnpjEmitente", ""))
    cnpj_tom = val.normaliza_cnpj(ia.get("cnpjCpfTomador", ""))
    if cnpj_emit != cnpj_filial_esperado or cnpj_tom != cnpj_forn_esperado:
        return ia
    ia = dict(ia)
    ia["cnpjEmitente"], ia["cnpjCpfTomador"] = ia.get("cnpjCpfTomador", ""), ia.get("cnpjEmitente", "")
    ia["nomeEmitente"], ia["nomeTomador"] = ia.get("nomeTomador", ""), ia.get("nomeEmitente", "")
    return ia


# ══════════════════════════════════════════════════════════════════════════════
# >>> PALIATIVO PROVISÓRIO - PIS/COFINS (ver controllers/lancamento_controller.py) <<<
# Motivo: sem controle confiável do lançamento correto de PIS/COFINS hoje. Enquanto a TI não
# resolve, bloqueamos ANTES de lançar (em vez de lançar errado e precisar excluir depois).
# REMOVER esta função e a chamada correspondente no controller assim que a TI resolver.
# ══════════════════════════════════════════════════════════════════════════════
def eh_pis_cofins_reconhecido(payload: dict) -> bool:
    """TEMPORÁRIO/PALIATIVO: True se o payload tem valor de PIS ou COFINS reconhecido (raiz ou em
    algum item de itensReceb). Usado para bloquear o lançamento automático enquanto não há solução
    técnica confiável para lançar esses tributos corretamente."""
    if fmt.to_float(payload.get("valorPIS", "0")) > 0 or fmt.to_float(payload.get("valorCOFINS", "0")) > 0:
        return True
    for item in payload.get("itensReceb", []) or []:
        if fmt.to_float(item.get("valorPIS", "0")) > 0 or fmt.to_float(item.get("valorCofins", "0")) > 0:
            return True
    return False
