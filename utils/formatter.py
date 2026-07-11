"""Formatacao de numeros e datas (espelha helpers WDL do fluxo)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta


def to_float(valor: object) -> float:
    if valor is None:
        return 0.0
    s = str(valor).strip().replace(",", ".")
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        limpo = "".join(c for c in s if c.isdigit() or c in ".-")
        try:
            return float(limpo) if limpo not in {"", ".", "-"} else 0.0
        except ValueError:
            return 0.0


def format_number(valor: object, casas: int = 2) -> str:
    return f"{to_float(valor):.{casas}f}"


def data_br_para_iso(data_br: object) -> str:
    s = str(data_br or "").strip()
    partes = s.split("/")
    if len(partes) != 3:
        return ""
    d, m, y = (p.strip() for p in partes)
    if not (d.isdigit() and m.isdigit() and y.isdigit()):
        return ""
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def data_iso_para_br(data_iso: object) -> str:
    s = str(data_iso or "").strip()[:10]
    partes = s.split("-")
    if len(partes) != 3:
        return ""
    y, m, d = partes
    return f"{d.zfill(2)}/{m.zfill(2)}/{y}"


def _parse_iso(data_iso: str) -> datetime | None:
    try:
        return datetime.strptime(data_iso[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def add_dias_br(data_br: object, dias: int) -> str:
    base = _parse_iso(data_br_para_iso(data_br))
    if base is None:
        return str(data_br or "")
    return (base + timedelta(days=dias)).strftime("%d/%m/%Y")


def add_meses_br(data_br: object, meses: int) -> str:
    base = _parse_iso(data_br_para_iso(data_br))
    if base is None:
        return str(data_br or "")
    return (base + relativedelta(months=meses)).strftime("%d/%m/%Y")


def dias_ate(data_iso_alvo: str, data_iso_base: str) -> int:
    a, b = _parse_iso(data_iso_alvo), _parse_iso(data_iso_base)
    if a is None or b is None:
        return 9999
    return (a - b).days


def agora(tz: str = "America/Sao_Paulo") -> datetime:
    return datetime.now(ZoneInfo(tz))


def hoje_br(tz: str = "America/Sao_Paulo") -> str:
    return agora(tz).strftime("%d/%m/%Y")


def hoje_iso(tz: str = "America/Sao_Paulo") -> str:
    return agora(tz).strftime("%Y-%m-%d")


def disparo_data_hora(tz: str = "America/Sao_Paulo") -> str:
    return agora(tz).strftime("%d/%m/%Y %H:%M:%S")


def id_disparo(tz: str = "America/Sao_Paulo") -> str:
    return "lancamentoCLN_GoLive_" + agora(tz).strftime("%Y%m%d_%H%M%S")


def datetime_disparo_formatado(tz: str = "America/Sao_Paulo") -> str:
    """Retorna data/hora formatada para exibição no Teams (ex: 10/07/2026 21:36:57)."""
    return agora(tz).strftime("%d/%m/%Y %H:%M:%S")
