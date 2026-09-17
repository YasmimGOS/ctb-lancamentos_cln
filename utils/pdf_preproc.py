"""Pre-processamento de PDFs antes do envio a IA multimodal.

Motivacao (caso real - DANFSe v2.0):
    Notas de servico no padrao nacional (DANFSe v2.0) sao frequentemente geradas
    com o texto desenhado como vetor, sem camada de texto e sem fontes
    embarcadas. Enviadas cruas, a IA precisa "enxergar" o documento na resolucao
    em que o servico decidir rasterizar, o que degrada a leitura de digitos
    (CNPJ, chave de acesso, valores em fonte pequena).

    Este modulo detecta esse caso e rasteriza o PDF a 300 DPI antes do envio,
    garantindo resolucao suficiente. PDFs que ja possuem camada de texto sao
    devolvidos intactos - nao ha ganho em rasterizar o que a IA ja le bem.

Degradacao segura:
    PyMuPDF e uma dependencia opcional. Se nao estiver instalado, ou se qualquer
    etapa falhar, o conteudo ORIGINAL e devolvido sem alteracao. O modulo nunca
    levanta excecao para o chamador - ele so pode melhorar o payload, nunca
    quebrar o fluxo.
"""
from __future__ import annotations

import base64

from utils.logger import get_logger

log = get_logger("pdf_preproc")

try:
    import fitz  # PyMuPDF
    PYMUPDF_DISPONIVEL = True
except ImportError:  # pragma: no cover - depende do ambiente
    PYMUPDF_DISPONIVEL = False
    log.warning("PyMuPDF (fitz) nao instalado - pre-processamento de PDF desabilitado. "
                "Instale com: pip install pymupdf")

# Minimo de caracteres extraiveis por pagina para considerar que o PDF ja tem
# camada de texto util. Abaixo disso, tratamos como imagem/vetor e rasterizamos.
MIN_CHARS_POR_PAGINA = 50

# 300 DPI e o minimo para leitura confiavel de digitos em documentos fiscais
# densos. Uma A4 completa a 300 DPI em JPEG 85% gera ~750 KB (~1 MB em base64).
DPI_PADRAO = 300

# Degraus de reducao caso o payload estoure o teto (documentos com muitas paginas).
DPI_FALLBACK = (300, 200, 150)

# Teto de payload em Base64. A API de IA aceita ~10 MB; deixamos folga para o
# restante do corpo JSON (prompt, metadados).
LIMITE_BASE64_MB = 9.0

# Qualidade JPEG usada na rasterizacao. 85% e visualmente equivalente ao original
# para leitura de texto e gera arquivos ~5-10x menores que PNG.
QUALIDADE_JPEG = 85


def tem_camada_de_texto(pdf_bytes: bytes) -> bool:
    """Indica se o PDF possui texto extraivel suficiente.

    Returns:
        True se o PDF tem camada de texto util; False se for imagem, vetor puro
        ou se a deteccao falhar (nesse caso rasterizar e o caminho seguro).
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            total = sum(len(pagina.get_text().strip()) for pagina in doc)
            media = total / max(len(doc), 1)
        finally:
            doc.close()
        tem_texto = media >= MIN_CHARS_POR_PAGINA
        log.info("Deteccao de tipo de PDF: media de %.0f chars/pagina -> %s",
                 media, "TEXTO" if tem_texto else "IMAGEM/VETOR")
        return tem_texto
    except Exception as e:
        log.warning("Falha ao detectar camada de texto do PDF: %s. Tratando como imagem.", e)
        return False


def _rasterizar(pdf_bytes: bytes, dpi: int) -> bytes:
    """Renderiza todas as paginas na resolucao informada e remonta um novo PDF."""
    zoom = dpi / 72.0  # 72 DPI e a unidade interna do PDF
    matriz = fitz.Matrix(zoom, zoom)

    origem = fitz.open(stream=pdf_bytes, filetype="pdf")
    destino = fitz.open()
    try:
        for pagina in origem:
            pix = pagina.get_pixmap(matrix=matriz, alpha=False)
            img = pix.tobytes("jpeg", jpg_quality=QUALIDADE_JPEG)
            nova = destino.new_page(width=pix.width, height=pix.height)
            nova.insert_image(nova.rect, stream=img)
        return destino.tobytes()
    finally:
        origem.close()
        destino.close()


def preparar_pdf_para_ia(base64_conteudo: str, nome_arquivo: str = "") -> str:
    """Prepara o Base64 de um PDF para envio a IA.

    Devolve o Base64 original quando o PDF ja tem camada de texto, quando o
    PyMuPDF nao esta disponivel ou quando qualquer etapa falha. Caso contrario,
    devolve o Base64 de uma versao rasterizada a 300 DPI (reduzindo a resolucao
    se necessario para caber no limite de payload).

    Args:
        base64_conteudo: Base64 do PDF original.
        nome_arquivo: Nome do arquivo, usado apenas em log.

    Returns:
        str: Base64 pronto para envio (original ou rasterizado).
    """
    if not PYMUPDF_DISPONIVEL or not base64_conteudo:
        return base64_conteudo

    rotulo = nome_arquivo or "anexo"

    try:
        pdf_bytes = base64.b64decode(base64_conteudo)
    except Exception as e:
        log.warning("Base64 de '%s' nao pode ser decodificado (%s). Enviando original.", rotulo, e)
        return base64_conteudo

    try:
        if tem_camada_de_texto(pdf_bytes):
            log.info("PDF '%s' ja possui camada de texto - enviado sem alteracao.", rotulo)
            return base64_conteudo

        log.info("PDF '%s' sem camada de texto (imagem/vetor). Rasterizando para a IA...", rotulo)

        resultado = base64_conteudo
        for dpi in DPI_FALLBACK:
            novo_bytes = _rasterizar(pdf_bytes, dpi)
            novo_b64 = base64.b64encode(novo_bytes).decode("utf-8")
            tamanho_mb = len(novo_b64) / 1024 / 1024
            resultado = novo_b64

            if tamanho_mb <= LIMITE_BASE64_MB:
                log.info("PDF '%s' rasterizado a %d DPI: %d bytes -> Base64 de %.2f MB (limite %.1f MB).",
                         rotulo, dpi, len(novo_bytes), tamanho_mb, LIMITE_BASE64_MB)
                return novo_b64

            if dpi == DPI_FALLBACK[-1]:
                log.warning("PDF '%s' continua com %.2f MB mesmo a %d DPI (limite %.1f MB). "
                            "Enviando o ORIGINAL para nao arriscar HTTP 413.",
                            rotulo, tamanho_mb, dpi, LIMITE_BASE64_MB)
                return base64_conteudo

            log.warning("PDF '%s' ficou com %.2f MB a %d DPI (acima do limite). Reduzindo resolucao...",
                        rotulo, tamanho_mb, dpi)

        return resultado

    except Exception as e:
        log.warning("Falha ao pre-processar o PDF '%s': %s. Enviando o original.", rotulo, e)
        return base64_conteudo
