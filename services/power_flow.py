"""Helpers de nivel de fluxo (espelham construcoes do Power Automate)."""
from __future__ import annotations

from config import CNPJ_VIBRA_ENERGIA
from utils import formatter as fmt


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


def agregar_payloads_vibra_energia(payloads: list[dict], cnpj_emitente: str) -> list[dict]:
    """Agrega múltiplas notas da VIBRA ENERGIA em um único payload consolidado.

    Args:
        payloads: Lista de payloads gerados para cada PDF
        cnpj_emitente: CNPJ do emitente normalizado

    Returns:
        Lista com 1 payload consolidado se for VIBRA com múltiplas NF-e,
        ou a lista original caso contrário
    """
    # Só agrega se:
    # 1. Tiver mais de 1 payload
    # 2. For VIBRA ENERGIA
    # 3. TODOS os payloads forem NF-e (não pode ter mistura com Boleto)
    if len(payloads) <= 1 or cnpj_emitente != CNPJ_VIBRA_ENERGIA:
        return payloads

    # Verificar se TODOS são NF-e (tipos aceitos para agregação)
    tipos_nf = {"NF-E", "NFSC", "NFSTE", "NF3E"}
    tipos_documentos = {p.get("tipoDocFiscal", "") for p in payloads}

    # Se houver algum tipo diferente de NF-e (ex: BOLP), não agrega
    if not tipos_documentos.issubset(tipos_nf):
        return payloads

    # Usar o primeiro payload como base
    base = dict(payloads[0])

    # Campos numéricos que precisam ser somados
    campos_soma = [
        "totalNota", "valorDescontoGeral",
        "baseICMS", "valorICMS", "valorIPI", "totalISS", "totalIRRF",
        "totalINSS", "valorPIS", "valorCOFINS", "totalCSLL", "valorBaseIPI"
    ]

    # Somar valores de todos os payloads
    for campo in campos_soma:
        total = sum(fmt.to_float(p.get(campo, "0")) for p in payloads)
        base[campo] = fmt.format_number(total)

    # Consolidar itensReceb (mesclar todos os itens e renumerar sequências)
    # Para evitar violação de PK_EST_ITENSRECEB (numNota + itemSequencia),
    # renumeramos todos os itens sequencialmente: 1, 2, 3, 4...
    todos_itens = []
    for p in payloads:
        todos_itens.extend(p.get("itensReceb", []))

    # Renumerar itemSequencia de todos os itens
    num_nota_consolidado = base.get("numNota", "")
    for idx, item in enumerate(todos_itens, start=1):
        nova_seq = str(idx)

        # Atualizar itemSequencia do item
        item["itemSequencia"] = nova_seq
        item["documento"] = num_nota_consolidado

        # Atualizar itemSequencia em centrosCusto
        for cc in item.get("centrosCusto", []):
            cc["itemSequencia"] = nova_seq
            cc["numNota"] = num_nota_consolidado

            # Atualizar itemSequencia em projetos dentro de centrosCusto
            for proj in cc.get("projetos", []):
                proj["itemSequencia"] = nova_seq
                proj["numNota"] = num_nota_consolidado

        # Atualizar itemSequencia em pedidos
        for ped in item.get("pedidos", []):
            ped["itemSequencia"] = nova_seq
            ped["numNota"] = num_nota_consolidado

    base["itensReceb"] = todos_itens

    # Recalcular valorMercadoria baseado na soma dos itens agregados
    # (não podemos somar o valorMercadoria dos payloads porque cada um já tem o total)
    valor_merc_total = sum(fmt.to_float(item.get("valorMercadoria", "0")) for item in todos_itens)
    base["valorMercadoria"] = fmt.format_number(valor_merc_total)

    # Consolidar parcelas (somar valores, manter data da primeira)
    if payloads[0].get("parcelas"):
        parcela_base = dict(payloads[0]["parcelas"][0])
        total_parcelas = sum(fmt.to_float(p["parcelas"][0].get("valorParcela", "0"))
                           for p in payloads if p.get("parcelas"))
        parcela_base["valorParcela"] = fmt.format_number(total_parcelas)
        base["parcelas"] = [parcela_base]

    # Consolidar numNota (juntar os números separados por vírgula para logging)
    nums_nota = [p.get("numNota", "") for p in payloads if p.get("numNota")]
    notas_consolidadas = ", ".join(nums_nota)

    # Manter apenas o primeiro numNota no payload (regra de negócio)
    base["numNota"] = nums_nota[0] if nums_nota else ""

    # Log informativo (será exibido no controller)
    base["_notas_agregadas"] = notas_consolidadas
    base["_total_notas_agregadas"] = len(payloads)

    return [base]


def priorizar_payload(payloads: list[dict]) -> dict | None:
    """Prioriza NF > CF > REC > BOLP; senao o primeiro."""
    if not payloads:
        return None
    for prefixo in ("NF", "CF", "REC", "BOLP"):
        for p in payloads:
            if str(p.get("contasPagarTipoDoc", "")).startswith(prefixo):
                return p
    return payloads[0]
