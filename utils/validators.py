"""Validacoes e normalizacoes (CNPJ/CPF, digitos)."""
from __future__ import annotations


def somente_digitos(valor: object) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def normaliza_cnpj(valor: object) -> str:
    s = str(valor or "").strip()
    for ch in (".", "-", "/", " "):
        s = s.replace(ch, "")
    return s


def mesma_raiz(cnpj_a: str, cnpj_b: str) -> bool:
    a, b = normaliza_cnpj(cnpj_a), normaliza_cnpj(cnpj_b)
    return len(a) == 14 and len(b) == 14 and a[:8] == b[:8]


def tamanho_valido(doc: str) -> bool:
    d = somente_digitos(doc)
    return len(d) in (11, 14)
