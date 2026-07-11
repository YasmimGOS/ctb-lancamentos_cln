"""Servico de IA multimodal (extracao assincrona de PDFs)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import get_settings
from utils import get_logger
from services.http_client import request_json

log = get_logger("ia")


def _carregar_prompt(nome: str) -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    return (prompts_dir / nome).read_text(encoding="utf-8")


def _limpar_json(texto: str) -> dict:
    s = (texto or "{}").strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        log.error("intel_answer nao e JSON valido: %.200s", s)
        return {}


class IaService:
    PROMPT_PRIMARIA = "prompt_1a_ia.txt"
    PROMPT_EXTRA = "prompt_2a_ia.txt"

    def __init__(self, settings=None):
        self.s = settings or get_settings()

    def _extrair(self, base64_pdf: str, prompt: str) -> dict:
        headers = {"X-API-Key": self.s.ia_api_key}
        corpo = {"base64_pdf": base64_pdf, "prompt": prompt}
        if self.s.ia_model:
            corpo["model"] = self.s.ia_model
        if self.s.ia_max_tokens:
            corpo["max_tokens"] = self.s.ia_max_tokens

        log.info("📤 Enviando PDF para IA (tamanho: %d caracteres)...", len(base64_pdf))
        resp = request_json("POST", self.s.ia_submit_url, headers=headers, json_body=corpo,
                            timeout=120, tentativas=3, intervalo_s=30)
        resp.raise_for_status()
        job_id = resp.json().get("job_id")
        if not job_id:
            raise RuntimeError("IA nao retornou job_id")

        log.info("⏳ Job IA iniciado: %s | Aguardando processamento...", job_id)
        status_base = self.s.ia_status_url.rstrip("/")

        # Polling com backoff exponencial (opcional)
        intervalo_atual = self.s.ia_poll_intervalo_inicial_s
        tempo_total = 0

        for tentativa in range(1, self.s.ia_poll_max_tentativas + 1):
            time.sleep(intervalo_atual)
            tempo_total += intervalo_atual

            log.info("🔍 Verificando status IA [%d/%d] (%.1fs decorridos)...",
                     tentativa, self.s.ia_poll_max_tentativas, tempo_total)

            st = request_json("GET", f"{status_base}/{job_id}", headers=headers, timeout=60)
            st.raise_for_status()
            body = st.json()
            status = body.get("status", "UNKNOWN")

            if status == "COMPLETED":
                log.info("✅ Job IA concluído com sucesso em %.1fs", tempo_total)
                return _limpar_json(body.get("intel_answer", "{}"))

            log.info("   Status atual: %s", status)

            # Backoff exponencial: duplica o intervalo até o máximo
            if self.s.ia_poll_usar_backoff and intervalo_atual < self.s.ia_poll_intervalo_maximo_s:
                intervalo_atual = min(intervalo_atual * 2, self.s.ia_poll_intervalo_maximo_s)
                log.info("   Próxima verificação em %ds...", intervalo_atual)

        raise TimeoutError(f"Job IA {job_id} nao concluiu apos {tempo_total}s ({self.s.ia_poll_max_tentativas} tentativas)")

    def extrair_primaria(self, base64_pdf: str) -> dict:
        return self._extrair(base64_pdf, _carregar_prompt(self.PROMPT_PRIMARIA))

    def extrair_extra(self, base64_pdf: str) -> dict:
        return self._extrair(base64_pdf, _carregar_prompt(self.PROMPT_EXTRA))
