"""Helpers de nivel de fluxo (espelham construcoes do Power Automate)."""
from __future__ import annotations


def selecionar_pedidos(lista: list[dict], filtro: list[int], limite: int) -> list[dict]:
    """Filtra por PDC_IN_CODIGO (se houver filtro) e aplica take(limite) (0=todos)."""
    itens = lista
    if filtro:
        itens = [p for p in lista if p.get("PDC_IN_CODIGO") in filtro]
    if limite and limite > 0:
        itens = itens[:limite]
    return itens


def priorizar_payload(payloads: list[dict]) -> dict | None:
    """Prioriza NF > CF > REC > BOLP; senao o primeiro."""
    if not payloads:
        return None
    for prefixo in ("NF", "CF", "REC", "BOLP"):
        for p in payloads:
            if str(p.get("contasPagarTipoDoc", "")).startswith(prefixo):
                return p
    return payloads[0]
