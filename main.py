"""Entry point: DISPARO do lote (espelha o gatilho de recorrencia do fluxo).

    python main.py
Agende externamente (cron / Task Scheduler / Airflow) no intervalo desejado.
"""
from __future__ import annotations

import sys

from config import get_settings
from controllers import LancamentoController
from utils import get_logger

log = get_logger("main")


def main() -> int:
    s = get_settings()
    log.info("Disparo LancamentoCLN (modo_teste=%s, limite=%s)", s.modo_teste, s.limite_pedidos)
    try:
        resultados = LancamentoController(s).executar_lote()
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha geral no lote: %s", exc)
        return 1
    lancados = sum(1 for r in resultados if r.lancado)
    log.info("Lote concluido: %s pedido(s), %s lancado(s).", len(resultados), lancados)
    for r in resultados:
        log.info("  pedido=%s status=%s tipoDoc=%s doc=%s", r.pedido, r.status, r.tipoDocFiscal, r.num_doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
