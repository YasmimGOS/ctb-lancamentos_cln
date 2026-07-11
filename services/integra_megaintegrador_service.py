"""Integracao com o MegaIntegrador (lancamento do recebimento)."""
from __future__ import annotations

from typing import Any

from config import get_settings
from utils import get_logger
from services.http_client import request_json

log = get_logger("mega")


class IntegraMegaIntegradorService:
    def __init__(self, settings=None):
        self.s = settings or get_settings()

    def lancar_recebimento(self, payload: dict) -> tuple[int, Any]:
        if self.s.modo_teste:
            log.info("[MODO_TESTE] lancar_recebimento numNota=%s", payload.get("numNota"))
            return 200, {"data": {"codTransacao": "TESTE", "pkMega": "0;0;0;0;0;0;TESTE"}}
        resp = request_json("POST", self.s.mega_recebimento_url,
                            headers={"Authorization": self.s.mega_token, "Content-Type": "application/json"},
                            json_body=payload, timeout=120)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        return resp.status_code, body
