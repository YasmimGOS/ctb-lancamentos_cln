"""Integracao com a API BPMS/Servicos (integra.odilonsantos.com)."""
from __future__ import annotations

from typing import Any

from config import get_settings
from utils import get_logger, sanitize_emoji
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

    def consultar_fornecedor_por_cnpj(self, cnpj: str) -> list[dict]:
        """Consulta o cadastro de fornecedor pelo CNPJ (validação de leitura de CNPJ da IA).

        Falha aberta: em qualquer erro (rede, timeout, CNPJ não encontrado), retorna [] e quem
        chama deve tratar como "sem confirmação disponível", sem bloquear o fluxo por isso.
        """
        try:
            resp = request_json("POST", self.s.bpms_getdadosfornecedorvdois_url,
                                headers={"Authorization": self.s.bpms_token},
                                json_body={"cnpj": str(cnpj)})
            resp.raise_for_status()
            return (resp.json() or {}).get("data", []) or []
        except Exception as exc:  # noqa: BLE001
            log.warning(sanitize_emoji("⚠️  Falha ao consultar fornecedor por CNPJ %s: %s"), cnpj, exc)
            return []

    def registrar(self, register_id: str, status: str, num_pedido: str, num_doc: str = "", erro: str = "") -> None:
        if self.s.modo_teste:
            log.info("[MODO_TESTE] registrar BD status=%s pedido=%s doc=%s", status, num_pedido, num_doc)
            return

        # Sanitizar campo erro: remover caracteres problemáticos e limitar tamanho
        erro_sanitizado = erro.replace("'", "").replace('"', "").replace("[", "(").replace("]", ")")
        if len(erro_sanitizado) > 500:
            erro_sanitizado = erro_sanitizado[:497] + "..."

        try:
            resp = request_json("POST", self.s.bpms_tabpedidosrpainsert_url,
                                headers={"Authorization": self.s.bpms_token},
                                json_body={"register_id": register_id, "status": status,
                                           "num_pedido": str(num_pedido), "num_doc": str(num_doc), "error": erro_sanitizado})
            resp.raise_for_status()
            log.info(sanitize_emoji("✓ Registro BD enviado: status=%s pedido=%s doc=%s"), status, num_pedido, num_doc)
        except Exception as exc:  # noqa: BLE001
            log.error(sanitize_emoji("❌ Falha ao registrar no BD (pedido %s): %s"), num_pedido, exc)
            log.error("   Dados que tentaram ser enviados: status=%s, num_doc=%s, erro=%s", status, num_doc, erro_sanitizado[:100])
