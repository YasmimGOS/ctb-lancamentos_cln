"""Regras de negocio puras (stateless, testaveis) do LancamentoCLN.

Cada funcao traduz uma regra do fluxo Power Automate. Nenhuma faz I/O.
"""
from __future__ import annotations

from config import (
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


def valida_tomador_x_filial(cnpj_tomador: str, nome_tomador: str, filial_cod: str, cnpj_filial_pedido: str) -> bool:
    tomador = val.normaliza_cnpj(cnpj_tomador)
    nome = (nome_tomador or "").strip().upper()
    if tomador == "" and nome == "":
        return True
    filial = DEPARA_FILIAIS.get(str(filial_cod or "").strip(), {})
    cnpj_ref = val.normaliza_cnpj(filial.get("cnpj", ""))
    nome_ref = (filial.get("nome", "") or "").strip().upper()
    if cnpj_ref and tomador == cnpj_ref:
        return True
    if nome_ref and nome_ref in nome:
        return True
    if not cnpj_ref and tomador == val.normaliza_cnpj(cnpj_filial_pedido):
        return True
    if val.mesma_raiz(tomador, cnpj_filial_pedido):
        return True
    return False


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
    if not fmt.data_br_para_iso(data_documento_br) or not dias_txt.isdigit():
        return True
    venc_iso = fmt.data_br_para_iso(fmt.add_dias_br(data_documento_br, int(dias_txt)))
    return not fmt.dias_ate(venc_iso, fmt.hoje_iso(tz)) <= 7


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
