"""Helpers de nivel de fluxo (espelham construcoes do Power Automate)."""
from __future__ import annotations


def selecionar_pedidos(lista: list[dict], filtro: list[int], limite: int) -> list[dict]:
    """Filtra por PDC_IN_CODIGO (se houver filtro) e aplica take(limite) (0=todos).

    IMPORTANTE: Agrupa por PDC_IN_CODIGO para retornar apenas 1 entrada por pedido,
    pois a API retorna 1 linha por item do pedido.
    """
    # Agrupar por PDC_IN_CODIGO (pegar apenas a primeira linha de cada pedido)
    pedidos_unicos = {}
    for item in lista:
        pdc = item.get("PDC_IN_CODIGO")
        if pdc is not None and pdc not in pedidos_unicos:
            pedidos_unicos[pdc] = item

    # Converter para lista ordenada por PDC_IN_CODIGO
    itens = [pedidos_unicos[pdc] for pdc in sorted(pedidos_unicos.keys())]

    # Aplicar filtro
    if filtro:
        itens = [p for p in itens if p.get("PDC_IN_CODIGO") in filtro]

    # Aplicar limite
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
