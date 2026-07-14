"""Notificacoes ao Teams via webhook (Power Automate). Sem URL -> apenas loga.

Formato de mensagens:
- Emojis: ✅ (sucesso), ⚠️ (aviso), ❌ (erro)
- Texto simples (sem HTML)
- Data/hora do disparo
- Informações detalhadas do pedido
"""
from __future__ import annotations

from typing import Any

from config import get_settings
from utils import get_logger, formatter as fmt, sanitize_emoji
from services.http_client import request_json

log = get_logger("teams")


class NotificationService:
    def __init__(self, settings=None, id_disparo: str = ""):
        self.s = settings or get_settings()
        self.id_disparo = id_disparo or fmt.id_disparo(self.s.timezone)
        self.data_hora_disparo = fmt.datetime_disparo_formatado(self.s.timezone)

    def _construir_mensagem(self, emoji: str, titulo: str, detalhes: dict = None, tipo: str = "") -> str:
        """Constrói mensagem em texto simples para o Power Automate Cloud.

        Args:
            emoji: ✅, ⚠️ ou ❌
            titulo: Mensagem principal
            detalhes: Dicionário com informações adicionais (opcional)
            tipo: 'tecnico' ou 'negocio' para adicionar rodapé explicativo
        """
        linhas = []

        # Linha 1: emoji + título + data/hora
        linhas.append(f"{emoji} {titulo}. {self.data_hora_disparo}")

        # Rodapé explicativo
        if tipo == "tecnico":
            linhas.append("É necessário inspecionar os detalhes técnicos de execução do fluxo.")
        elif tipo == "negocio":
            linhas.append("Esta é uma regra de negócio que impede o lançamento.")

        # Detalhes adicionais
        if detalhes:
            linhas.append("")  # Linha em branco
            for chave, valor in detalhes.items():
                if valor:  # Só adiciona se tiver valor
                    linhas.append(f"{chave}: {valor}")

        return "\n".join(linhas)

    def _post(self, mensagem: str) -> None:
        """Envia mensagem em texto simples para o webhook do Power Automate."""
        pode_enviar = (not self.s.modo_teste) or self.s.enviar_webhook_em_teste

        if not self.s.webhook_url or not pode_enviar:
            log.info("━" * 100)
            log.info(sanitize_emoji("📢 MENSAGEM TEAMS (não enviada - webhook desabilitado%s)"), " | MODO TESTE" if self.s.modo_teste else "")
            log.info("   %s", mensagem)
            log.info("━" * 100)
            return

        log.info("━" * 100)
        log.info(sanitize_emoji("📢 ENVIANDO MENSAGEM PARA TEAMS"))
        log.info("   %s", mensagem)
        log.info("━" * 100)

        body = {
            "messageBody": mensagem
        }

        try:
            request_json("POST", self.s.webhook_url, json_body=body, timeout=30)
            log.info(sanitize_emoji("✓ Mensagem Teams enviada com sucesso"))
        except Exception as exc:  # noqa: BLE001
            log.warning(sanitize_emoji("❌ Falha ao notificar Teams: %s"), exc)

    def sucesso(self, msg: str, pedido: Any = None, num_nota: str = "", cod_transacao: str = "", pk_mega: str = "") -> None:
        """Notificação de sucesso (✅).

        Args:
            msg: Mensagem principal
            pedido: Código do pedido
            num_nota: Número da nota fiscal
            cod_transacao: Código da transação no Mega
            pk_mega: PK retornada pelo Mega
        """
        detalhes = {}
        if pedido:
            detalhes["Número do pedido"] = str(pedido)
        if num_nota:
            detalhes["Doc. Fiscal"] = num_nota
        if cod_transacao:
            detalhes["Código Transação"] = cod_transacao
        if pk_mega:
            detalhes["PK Mega"] = pk_mega

        mensagem = self._construir_mensagem("✅", msg, detalhes)
        self._post(mensagem)

    def aviso(self, msg: str, pedido: Any = None, tipo_negocio: bool = True, detalhes_extra: dict = None) -> None:
        """Notificação de aviso/alerta (⚠️).

        Args:
            msg: Mensagem de aviso
            pedido: Código do pedido
            tipo_negocio: Se True, adiciona texto de regra de negócio
            detalhes_extra: Detalhes adicionais (opcional)
        """
        detalhes = {}
        if pedido:
            detalhes["Número do pedido"] = str(pedido)
        if detalhes_extra:
            detalhes.update(detalhes_extra)

        tipo = "negocio" if tipo_negocio else ""
        mensagem = self._construir_mensagem("⚠️", msg, detalhes, tipo)
        self._post(mensagem)

    def erro(self, msg: str, pedido: Any = None, detalhes_texto: str = "", tecnico: bool = True, detalhes_extra: dict = None) -> None:
        """Notificação de erro (❌).

        Args:
            msg: Mensagem de erro
            pedido: Código do pedido
            detalhes_texto: Detalhes adicionais do erro (texto livre)
            tecnico: Se True, adiciona texto de inspeção técnica
            detalhes_extra: Detalhes adicionais estruturados (opcional)
        """
        detalhes = {}
        if pedido:
            detalhes["Número do pedido"] = str(pedido)
        if detalhes_texto:
            detalhes["Detalhes do erro"] = detalhes_texto
        if detalhes_extra:
            detalhes.update(detalhes_extra)

        tipo = "tecnico" if tecnico else ""
        mensagem = self._construir_mensagem("❌", msg, detalhes, tipo)
        self._post(mensagem)

    def erro_ia_envio(self, pedido: Any, anexo: str = "") -> None:
        """Erro ao enviar Base64 para IA."""
        msg = "Falha ao enviar Base64 para IA"
        detalhes = {}
        if anexo:
            detalhes["Arquivo"] = anexo
        self.erro(msg, pedido, tecnico=True, detalhes_extra=detalhes)

    def erro_ia_resultado(self, pedido: Any) -> None:
        """Erro ao capturar resultado da IA."""
        msg = "Falha ao capturar resultado da IA"
        self.erro(msg, pedido, tecnico=True)

    def erro_consultar_anexos(self, pedido: Any) -> None:
        """Erro ao consultar anexos do pedido."""
        msg = "Falha ao consultar anexos do pedido"
        self.erro(msg, pedido, tecnico=True)

    def erro_definir_payload(self, pedido: Any) -> None:
        """Erro ao determinar dados para lançamento."""
        msg = "Falha ao determinar dados para lançamento"
        self.erro(msg, pedido, tecnico=True)

    def erro_obter_pedidos(self) -> None:
        """Erro ao obter lista de pedidos."""
        msg = "Falha ao obter lista de pedidos para processamento"
        self.erro(msg, tecnico=True)