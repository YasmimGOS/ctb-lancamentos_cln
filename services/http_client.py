"""Wrapper HTTP fino sobre requests (timeouts, logging, retry simples)."""
from __future__ import annotations

import json as json_lib
import time
from typing import Any

import requests

from utils import get_logger

log = get_logger("http")


def _safe_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Remove tokens/senhas dos headers para logging seguro."""
    if not headers:
        return {}
    safe = dict(headers)
    for key in list(safe.keys()):
        if key.lower() in ("authorization", "x-api-key", "api-key", "token"):
            safe[key] = "***REDACTED***"
    return safe


def _truncar_base64(data: Any, max_len: int = 200) -> Any:
    """Trunca campos base64 muito longos para logging."""
    if isinstance(data, dict):
        resultado = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 1000 and (
                k.lower().endswith("base64") or k.lower() == "anexobase64" or "base64" in k.lower()
            ):
                resultado[k] = f"<base64 truncado: {len(v)} caracteres>"
            elif isinstance(v, (dict, list)):
                resultado[k] = _truncar_base64(v, max_len)
            else:
                resultado[k] = v
        return resultado
    elif isinstance(data, list):
        return [_truncar_base64(item, max_len) for item in data]
    return data


def _format_json(data: Any, truncar: bool = True) -> str:
    """Formata JSON para logging legivel."""
    if data is None:
        return "None"
    try:
        if isinstance(data, (dict, list)):
            if truncar:
                data = _truncar_base64(data)
            texto = json_lib.dumps(data, indent=2, ensure_ascii=False)
            if len(texto) > 5000:
                return texto[:5000] + f"\n... (truncado, total: {len(texto)} caracteres)"
            return texto
        return str(data)
    except Exception:
        return str(data)


def request_json(method: str, url: str, *, headers: dict[str, str] | None = None,
                 json_body: Any = None, timeout: int = 60, tentativas: int = 1,
                 intervalo_s: int = 30) -> requests.Response:
    ultimo_erro: Exception | None = None

    # Log da request (detalhado)
    log.info("=" * 100)
    log.info("HTTP REQUEST | %s %s", method.upper(), url)
    log.info("Headers: %s", _safe_headers(headers))
    if json_body:
        log.info("Request Body:\n%s", _format_json(json_body))

    for tentativa in range(1, tentativas + 1):
        try:
            inicio = time.time()
            response = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
            duracao = time.time() - inicio

            # Log da response (detalhado)
            log.info("HTTP RESPONSE | Status: %s | Tempo: %.2fs", response.status_code, duracao)

            # Tentar parsear response body
            try:
                response_data = response.json() if response.content else None
                if response_data:
                    log.info("Response Body:\n%s", _format_json(response_data))
            except Exception:
                # Se nao for JSON, logar o texto bruto (primeiros 1000 chars)
                text = response.text[:1000] if response.text else ""
                if text:
                    log.info("Response Body (texto):\n%s%s", text, "..." if len(response.text) > 1000 else "")

            log.info("=" * 100)
            return response

        except requests.RequestException as exc:
            ultimo_erro = exc
            log.warning("Falha HTTP (%s/%s) em %s: %s", tentativa, tentativas, url, exc)
            if tentativa < tentativas:
                log.info("Aguardando %ss antes de tentar novamente...", intervalo_s)
                time.sleep(intervalo_s)

    log.error("=" * 100)
    raise RuntimeError(f"Falha ao chamar {url}: {ultimo_erro}")
