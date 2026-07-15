"""Configuracoes (le o .env do projeto) + tabelas de dominio.

Compativel com o .env real do projeto (pasta config/.env). Nenhum segredo fica
hardcoded: tudo vem do ambiente. Tokens ja vem com o prefixo 'Bearer'.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_CANDIDATOS = [
    os.getenv("LANCAMENTO_ENV_FILE", ""),
    str(Path(__file__).resolve().parent / ".env"),
    str(Path.cwd() / "config" / ".env"),
    str(Path.cwd() / ".env"),
]
try:
    from dotenv import load_dotenv

    for _p in _CANDIDATOS:
        if _p and Path(_p).is_file():
            load_dotenv(_p)
            break
except Exception:
    pass


def _bearer(valor: str) -> str:
    v = (valor or "").strip()
    if not v:
        return ""
    return v if v.lower().startswith("bearer ") else f"Bearer {v}"


def _bool(valor: str, padrao: bool = False) -> bool:
    return (valor or str(padrao)).strip().lower() in {"1", "true", "sim", "yes"}


class Settings(BaseModel):
    # IA / PDF Intelligence
    ia_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    ia_submit_url: str = os.getenv(
        "ANTHROPIC_API_URL", os.getenv("AI_PDF_INTELLIGENCE_BASE_URL", "") + "/pdf/async"
    )
    ia_status_url: str = os.getenv("AI_PDF_INTELLIGENCE_STATUS_URL", "")
    ia_model: str = os.getenv("ANTHROPIC_MODEL", "")
    ia_max_tokens: int = int(os.getenv("MAX_TOKENS", "4096") or "4096")

    # INTEGRA - BPMS
    bpms_pedanexorpa_url: str = os.getenv("INTEGRA_BPMS_PEDANEXORPA_URL", "")
    bpms_pedidodadosreceb_url: str = os.getenv("INTEGRA_BPMS_PEDIDODADOSRECEB_URL", "")
    bpms_tabpedidosrpaconsulta_url: str = os.getenv("INTEGRA_BPMS_TABPEDIDOSRPACONSULTA_URL", "")
    bpms_tabpedidosrpainsert_url: str = os.getenv("INTEGRA_BPMS_TABPEDIDOSRPAINSERT_URL", "")
    bpms_getdadosfornecedorvdois_url: str = os.getenv(
        "INTEGRA_BPMS_GETDADOSFORNECEDORVDOIS_URL",
        "https://integra.odilonsantos.com/api/Bpms/getdadosfornecedorvdois",
    )
    bpms_base_url: str = os.getenv("INTEGRA_BPMS_BASE_URL", "")
    bpms_token: str = _bearer(os.getenv("INTEGRA_BPMS_TOKEN", ""))

    # INTEGRA - Servicos
    servicos_mega_anexo_url: str = os.getenv("INTEGRA_SERVICOS_MEGA_ANEXO_URL", "")
    servicos_base_url: str = os.getenv("INTEGRA_SERVICOS_BASE_URL", "")
    servicos_token: str = _bearer(os.getenv("INTEGRA_SERVICOS_TOKEN", ""))

    # INTEGRA - Mega Integrador
    mega_recebimento_url: str = os.getenv("INTEGRA_MEGAINTEGRADOR_RECEBIMENTO_URL", "")
    mega_base_url: str = os.getenv("INTEGRA_MEGAINTEGRADOR_BASE_URL", "")
    mega_token: str = _bearer(os.getenv("INTEGRA_MEGAINTEGRADOR_TOKEN", ""))

    # Webhook
    webhook_url: str = os.getenv("POWER_AUTOMATE_WEBHOOK_URL", "").strip().strip('"')

    # Controle de execucao/testes
    modo_teste: bool = _bool(os.getenv("MODO_TESTE", "false"))
    codigo_teste: str = os.getenv("CODIGO_TESTE", "").strip()
    enviar_webhook_em_teste: bool = _bool(os.getenv("ENVIAR_WEBHOOK_EM_TESTE", "false"))
    usar_pdf_mock: bool = _bool(os.getenv("USAR_PDF_MOCK", "false"))

    # Selecao de pedidos
    filtro_pedidos: str = os.getenv("FILTRO_PEDIDOS", "")
    limite_pedidos: int = int(os.getenv("LIMITE_PEDIDOS", "1") or "0")
    max_workers: int = int(os.getenv("MAX_WORKERS", "1") or "1")

    # Logging / ambiente
    timezone: str = os.getenv("TIMEZONE", "America/Sao_Paulo")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_retention_days: int = int(os.getenv("LOG_RETENTION_DAYS", "60") or "0")

    # IA polling / performance
    ia_poll_intervalo_inicial_s: int = int(os.getenv("IA_POLL_INTERVALO_INICIAL_S", "2") or "2")
    ia_poll_intervalo_maximo_s: int = int(os.getenv("IA_POLL_INTERVALO_MAXIMO_S", "15") or "15")
    ia_poll_max_tentativas: int = int(os.getenv("IA_POLL_MAX_TENTATIVAS", "30") or "30")
    ia_poll_usar_backoff: bool = _bool(os.getenv("IA_POLL_USAR_BACKOFF", "true"))

    @property
    def filtro_pedidos_list(self) -> list[int]:
        """Filtro por PDC_IN_CODIGO (equivalente ao 'Matriz do filtro' do fluxo).

        Prioridade: CODIGO_TESTE (um codigo) > FILTRO_PEDIDOS (lista CSV).
        Vazio => sem filtro; nesse caso o controller processa os primeiros
        LIMITE_PEDIDOS (o 'Selecionar primeiros pedidos').
        """
        base = self.codigo_teste if self.codigo_teste.strip() else self.filtro_pedidos
        out: list[int] = []
        for p in (base or "").split(","):
            p = p.strip()
            if p.isdigit():
                out.append(int(p))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()


DEPARA_FILIAIS: dict[str, dict[str, str]] = {
    "3": {"nome": "RAPIDO ARAGUAIA", "cnpj": "01657436000110"},
    "35": {"nome": "RAPIDO ARAGUAIA", "cnpj": "01657436000463"},
    "36": {"nome": "CREMMY", "cnpj": "00693410000165"},
    "40": {"nome": "VIACAO ARAGUARINA", "cnpj": "01552504000187"},
    "15519": {"nome": "AGROPASTORIL", "cnpj": "02737815000426"},
    "15535": {"nome": "ODILON SANTOS", "cnpj": "06992809000123"},
    "15537": {"nome": "PONTAL", "cnpj": "07258201000132"},
    "150103": {"nome": "RAPIDO ARAGUAIA", "cnpj": "01657436000625"},
    "221461": {"nome": "MOTO FOR", "cnpj": "02862548000176"},
}

TABELA_DEPARA_TIPODOC: dict[str, dict[str, object]] = {
    "NF-E": {"contasPagarTipoDoc": "NFC", "acao_vista": 295, "acao_prazo": 82},
    "NFSTE": {"contasPagarTipoDoc": "NFSTE", "acao_vista": 295, "acao_prazo": 82},
    "NF3E": {"contasPagarTipoDoc": "NFFEE", "acao_vista": 295, "acao_prazo": 82},
    "CT-E": {"contasPagarTipoDoc": "CF", "acao_vista": 295, "acao_prazo": 82},
    "CT-EOS": {"contasPagarTipoDoc": "CF", "acao_vista": 295, "acao_prazo": 82},
    "NFS-EG": {"contasPagarTipoDoc": "NFS", "acao_vista": 295, "acao_prazo": 82},
    "NFS-E": {"contasPagarTipoDoc": "NFS", "acao_vista": 295, "acao_prazo": 82},
    "NFF": {"contasPagarTipoDoc": "NFF", "acao_vista": 295, "acao_prazo": 82},
    "BOLP": {"contasPagarTipoDoc": "BOLP", "acao_vista": 771, "acao_prazo": 768},
    "BOLP-DETRAN": {"contasPagarTipoDoc": "BOLP", "acao_vista": 770, "acao_prazo": 770},
    "BOLP-DETRAN-IPVA-ANTT": {"contasPagarTipoDoc": "BOLP", "acao_vista": 768, "acao_prazo": 771},
    "RECIBO": {"contasPagarTipoDoc": "REC", "acao_vista": 771, "acao_prazo": 768},
    "NFSC": {"contasPagarTipoDoc": "NFF", "acao_vista": 295, "acao_prazo": 82},
    "DANFCom": {"contasPagarTipoDoc": "NFF", "acao_vista": 295, "acao_prazo": 82},
}

TIPO_DOC_POR_EMITENTE: dict[str, str] = {"61074175000138": "BOLP"}
CNPJ_ALUGUEL_IR = "03397056000110"
CNPJ_VIBRA_ENERGIA = "34274233030605"
CNPJ_APLICACAO_281 = "04554425000120"
CNPJ_EQUATORIAL = "00316622501205"

# TEMPORÁRIO: de-para Almoxarifado -> Localização, usado só para AVISO/bloqueio manual hoje
# (ver services/business_rules.py::resolver_localizacao_almoxarifado e
# controllers/lancamento_controller.py, validação "Almoxarifado"). O Mega Integrador ainda não
# tem campo de Almoxarifado/Localização no payload de recebimento; quando a TI adicionar esse
# campo, trocar o bloqueio manual por preenchimento automático usando este de-para.
ALMOXARIFADO_LOCALIZACAO: dict[str, str] = {
    "1": "25001",
    "146": "32001",
}
COND_PAGTO_A_VISTA = {"ADIANT", "TESOURARIA", "A VISTA", "AVISTA", "CREDITO"}
TIPOS_DOC_SERVICO = {"NFS-EG", "NFS-E", "NFF", "NFSTE", "NFSC"}

# Fornecedores cuja fatura de serviço foge do padrão de documento previsto para o RPA (ex.: Sitpass,
# fatura da CIA METROPOLITANA DE TRANSPORTE COLETIVO) - bloqueia ANTES de qualquer processamento,
# nunca deve ir para execução automática; sempre lançamento manual.
FANTASIAS_EXECUCAO_MANUAL = {"CIA METROPOLITANA DE TRANSPORTE COLETIVO"}
