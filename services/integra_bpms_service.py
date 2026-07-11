"""Integracao com a API BPMS/Servicos (integra.odilonsantos.com)."""
from __future__ import annotations

from typing import Any

from config import get_settings
from utils import get_logger
from services.http_client import request_json

log = get_logger("integra_bpms")


class IntegraBpmsService:
    def __init__(self, settings=None):
        self.s = settings or get_settings()

    def obter_lista_pedidos(self) -> list[dict]:
        resp = request_json("GET", self.s.bpms_pedanexorpa_url,
                            headers={"Authorization": self.s.bpms_token})
        resp.raise_for_status()
        return (resp.json() or {}).get("data", []) or []

    def obter_dados_pedido(self, filial: Any, pedido: Any) -> list[dict]:
        resp = request_json("POST", self.s.bpms_pedidodadosreceb_url,
                            headers={"Authorization": self.s.bpms_token},
                            json_body={"Filial": str(filial), "Pedido": str(pedido)})
        resp.raise_for_status()
        return (resp.json() or {}).get("data", []) or []

    def consultar_anexos(self, filial: Any, agente: Any, pedido: Any, data_documento: str) -> list[dict]:
        resp = request_json("POST", self.s.servicos_mega_anexo_url,
                            headers={"Authorization": self.s.servicos_token},
                            json_body={"filial": filial, "agente": agente,
                                       "pedido": pedido, "dataDocumento": data_documento})
        resp.raise_for_status()
        return (resp.json() or {}).get("data", []) or []

    def consultar_bd(self, num_pedido: str) -> list[dict]:
        resp = request_json("POST", self.s.bpms_tabpedidosrpaconsulta_url,
                            headers={"Authorization": self.s.bpms_token},
                            json_body={"num_pedido": str(num_pedido)})
        resp.raise_for_status()
        return (resp.json() or {}).get("data", []) or []

    def registrar(self, register_id: str, status: str, num_pedido: str, num_doc: str = "", erro: str = "") -> None:
        if self.s.modo_teste:
            log.info("[MODO_TESTE] registrar BD status=%s pedido=%s doc=%s", status, num_pedido, num_doc)
            return
        resp = request_json("POST", self.s.bpms_tabpedidosrpainsert_url,
                            headers={"Authorization": self.s.bpms_token},
                            json_body={"register_id": register_id, "status": status,
                                       "num_pedido": str(num_pedido), "num_doc": str(num_doc), "error": erro})
        resp.raise_for_status()
