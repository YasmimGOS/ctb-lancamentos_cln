"""Servico de IA multimodal (extracao assincrona de PDFs)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from config import get_settings
from utils import get_logger, sanitize_emoji
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
    PROMPT_EQUATORIAL = "prompt_3a_equatorial_ia.txt"

    def __init__(self, settings=None):
        self.s = settings or get_settings()

    def verificar_servico_ia(self) -> "tuple[bool, str]":
        """Verifica se o servico de IA esta operacional antes de processar arquivos.

        Distingue dois cenarios de falha:
        - Deploy quebrado: Cloud Run retorna HTML 404 (instantaneo) -> TI precisa agir
        - Cold start (scale-to-zero): container esta acordando -> warm-up resolve

        Returns:
            (True, "")          -- servico operacional
            (False, "motivo")   -- servico fora do ar, com descricao do problema
        """
        if not self.s.ia_submit_url:
            return False, "URL de submissao da IA nao configurada"

        base_url = self.s.ia_submit_url.rsplit('/pdf', 1)[0]
        health_url = f"{base_url}/health"
        log.info("Verificando saude do servico de IA: %s", health_url)

        try:
            r = requests.get(health_url, timeout=15)
            content_type = r.headers.get('Content-Type', '')

            if r.status_code == 200:
                log.info("Servico de IA operacional (HTTP 200).")
                return True, ""

            if 'text/html' in content_type:
                return False, (
                    f"Servico retornou {r.status_code} HTML - deploy quebrado ou fora do ar. "
                    "Acione a TI para verificar o Cloud Run 'ai-pdf-intelligence' em us-central1."
                )

            log.info("Servico respondeu com %s JSON - container ativo, assumindo operacional.", r.status_code)
            return True, ""

        except requests.exceptions.Timeout:
            return False, "Timeout de 15s ao verificar o servico - pode estar sobrecarregado ou inicializando."
        except requests.exceptions.RequestException as e:
            return False, f"Falha de conexao ao verificar o servico: {e}"

    def aquecer_servico_ia(self) -> bool:
        """Envia um ping leve para acordar o container em caso de cold start (scale-to-zero).

        Returns:
            True  -- container esta ativo (ou acabou de acordar)
            False -- servico esta quebrado (nao e cold start, e falha de deploy)
        """
        operacional, motivo = self.verificar_servico_ia()
        if not operacional:
            log.warning("Warm-up falhou - servico nao esta acessivel: %s", motivo)
            return False

        log.info("Warm-up concluido - servico de IA pronto para receber documentos.")
        return True

    def _extrair(self, conteudo_base64: str, prompt: str, model_tier: str = "medio",
                 eh_imagem: bool = False) -> dict:
        headers = {"X-API-Key": self.s.ia_api_key}
        campo_conteudo = "base64_image" if eh_imagem else "base64_pdf"
        corpo = {campo_conteudo: conteudo_base64, "prompt": prompt, "model_tier": model_tier}
        if self.s.ia_model:
            corpo["model"] = self.s.ia_model
        if self.s.ia_max_tokens:
            corpo["max_tokens"] = self.s.ia_max_tokens

        log.info(sanitize_emoji("📤 Enviando %s para IA (tamanho: %d caracteres, tier: %s)..."),
                 "imagem" if eh_imagem else "PDF", len(conteudo_base64), model_tier)
        resp = request_json("POST", self.s.ia_submit_url, headers=headers, json_body=corpo,
                            timeout=120, tentativas=3, intervalo_s=30)
        resp.raise_for_status()
        job_id = resp.json().get("job_id")
        if not job_id:
            raise RuntimeError("IA nao retornou job_id")

        log.info(sanitize_emoji("⏳ Job IA iniciado: %s | Aguardando processamento..."), job_id)
        status_base = self.s.ia_status_url.rstrip("/")

        # Polling com backoff exponencial (opcional)
        intervalo_atual = self.s.ia_poll_intervalo_inicial_s
        tempo_total = 0
        tentativas_404_consecutivas = 0
        MAX_404_CONSECUTIVOS = 5

        for tentativa in range(1, self.s.ia_poll_max_tentativas + 1):
            time.sleep(intervalo_atual)
            tempo_total += intervalo_atual

            log.info(sanitize_emoji("🔍 Verificando status IA [%d/%d] (%.1fs decorridos)..."),
                     tentativa, self.s.ia_poll_max_tentativas, tempo_total)

            st = request_json("GET", f"{status_base}/{job_id}", headers=headers, timeout=60)

            if st.status_code == 404:
                tentativas_404_consecutivas += 1
                if tentativas_404_consecutivas >= MAX_404_CONSECUTIVOS:
                    raise RuntimeError(
                        f"Job IA {job_id} nao encontrado no servico de IA (404) apos "
                        f"{tentativas_404_consecutivas} tentativas consecutivas em {tempo_total:.1f}s "
                        "- job provavelmente nao foi criado/persistido"
                    )
                # O job pode ainda não estar visível na instância que atendeu esta
                # verificação (propagação entre instâncias do serviço de IA).
                # Trata como "ainda não pronto" em vez de abortar a extração, mas
                # só por um numero limitado de tentativas (ver MAX_404_CONSECUTIVOS acima).
                log.warning(
                    sanitize_emoji("⚠️ Job %s ainda não encontrado no serviço de IA (404) "
                                   "[%d/%d]. Tentando novamente..."),
                    job_id, tentativas_404_consecutivas, MAX_404_CONSECUTIVOS)
                if self.s.ia_poll_usar_backoff and intervalo_atual < self.s.ia_poll_intervalo_maximo_s:
                    intervalo_atual = min(intervalo_atual * 2, self.s.ia_poll_intervalo_maximo_s)
                continue

            tentativas_404_consecutivas = 0
            st.raise_for_status()
            body = st.json()
            status = body.get("status", "UNKNOWN")

            if status == "COMPLETED":
                log.info(sanitize_emoji("✅ Job IA concluído com sucesso em %.1fs"), tempo_total)
                return _limpar_json(body.get("intel_answer", "{}"))

            if status in ("FAILED", "EXPIRED"):
                # Curto-circuito: a IA ja sinalizou que o job nao vai completar -
                # esperar o timeout inteiro (ate ~7min) so adia um erro que ja e certo.
                log.error(sanitize_emoji("❌ Job IA %s terminou com status '%s' apos %.1fs - "
                                          "abortando sem esperar o timeout completo"),
                          job_id, status, tempo_total)
                raise RuntimeError(
                    f"Job IA {job_id} terminou com status '{status}' apos {tempo_total:.1f}s "
                    "(status terminal, nao e recuperavel via nova tentativa de polling)"
                )

            log.info("   Status atual: %s", status)

            # Backoff exponencial: duplica o intervalo até o máximo
            if self.s.ia_poll_usar_backoff and intervalo_atual < self.s.ia_poll_intervalo_maximo_s:
                intervalo_atual = min(intervalo_atual * 2, self.s.ia_poll_intervalo_maximo_s)
                log.info("   Próxima verificação em %ds...", intervalo_atual)

        raise TimeoutError(f"Job IA {job_id} nao concluiu apos {tempo_total}s ({self.s.ia_poll_max_tentativas} tentativas)")

    def extrair_primaria(self, conteudo_base64: str, model_tier: str = "medio", eh_imagem: bool = False) -> dict:
        return self._extrair(conteudo_base64, _carregar_prompt(self.PROMPT_PRIMARIA),
                              model_tier=model_tier, eh_imagem=eh_imagem)

    def extrair_extra(self, conteudo_base64: str, model_tier: str = "medio", eh_imagem: bool = False) -> dict:
        return self._extrair(conteudo_base64, _carregar_prompt(self.PROMPT_EXTRA),
                              model_tier=model_tier, eh_imagem=eh_imagem)

    def extrair_equatorial(self, conteudo_base64: str, model_tier: str = "medio", eh_imagem: bool = False) -> dict:
        """3a chamada, condicional - só para faturas de energia eletrica (fornecedor Equatorial,
        ver services/business_rules.py::eh_fornecedor_equatorial). Extrai os valores individuais
        das secoes FORNECIMENTO e ITENS FINANCEIROS (ver docs/REGRAS_PROJETO.md secao 3.11)."""
        return self._extrair(conteudo_base64, _carregar_prompt(self.PROMPT_EQUATORIAL),
                              model_tier=model_tier, eh_imagem=eh_imagem)
