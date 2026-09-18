# -*- coding: utf-8 -*-
"""
utils/pdf_preflight.py

Blindagem do fluxo contra anexos rasterizados.

Alguns fornecedores geram notas/faturas com o texto desenhado como vetor, sem
camada de texto e sem fontes embarcadas (ex.: DANFSe v2.0), ou anexam
digitalizacoes (scan) as vezes rotacionadas 90 graus. Este projeto nao integra
com o Zeev (usa BPMS + Mega Integrador), entao a deteccao de pagina-carimbo do
Zeev abaixo e um no-op seguro aqui — nunca vai casar com o marcador.

Esse modulo faz o pre-voo antes de qualquer chamada a IA:

  1. Valida que o base64 e realmente um PDF (tolera prefixo data-URI e padding torto).
  2. Descarta a pagina-carimbo do Zeev, se houver (no-op nos fluxos que nao usam Zeev).
  3. Mede a camada de texto. PDF nativo passa direto, sem reprocessamento.
  4. PDF rasterizado: re-renderiza em DPI controlado, detecta se o texto esta
     na vertical (perfil de projecao de tinta) e endireita a pagina.
  5. Devolve, no laudo, a rotacao alternativa — a heuristica distingue
     "texto vertical" de "texto horizontal", mas nao 90 de 270 graus. Quem
     resolve o empate e o portao de qualidade no controller, reenviando na
     outra orientacao se a extracao vier fraca.

Uso:
    conteudo, laudo = pdf_preflight.normalizar_documento(base64_doc, "documento")
    registrar_laudo(laudo)
    if laudo["bloqueio"]:
        ...  # nao envia para a IA

Dependencias: pymupdf, pillow, numpy. Se faltarem, o modulo NAO quebra o
fluxo: devolve o documento original e registra o aviso no laudo.
"""

import base64
import io
import logging
import re

_DEPS_OK = True
_ERRO_DEPS = ""
try:
    import fitz  # PyMuPDF
    import numpy as np
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    _DEPS_OK = False
    _ERRO_DEPS = str(exc)

# Carimbo que o visualizador do Zeev estampa em toda pagina que ele renderiza.
# Este projeto nao usa Zeev — a deteccao abaixo e um no-op seguro.
MARCA_ZEEV = "Identificacao interna do documento"
MARCA_ZEEV_ACENTUADA = "Identificação interna do documento"

# Abaixo disso, a pagina nao tem camada de texto util — e imagem.
LIMIAR_TEXTO_POR_PAGINA = 150

# Renderizacao: DPI alvo e teto do lado maior, para nao estourar o payload.
DPI_RENDER = 300
LADO_MAXIMO_PX = 2200
QUALIDADE_JPEG = 80

# Quanto o perfil de uma direcao precisa superar o da outra para decidir.
FATOR_DECISAO_ORIENTACAO = 1.3

# Rotacao aplicada quando o texto esta na vertical. Sentido anti-horario (PIL).
ROTACAO_PADRAO = 90
ROTACAO_ALTERNATIVA = -90


def _laudo_vazio(doc_type):
    return {
        "doc_type": doc_type,
        "valido": False,
        "rasterizado": False,
        "paginas_originais": 0,
        "paginas_enviadas": 0,
        "paginas_descartadas": 0,
        "chars_texto": 0,
        "rotacao_aplicada": 0,
        "rotacoes_alternativas": [],
        "bytes_enviados": 0,
        "acoes": [],
        "bloqueio": None,
    }


def _decodificar(base64_doc):
    """Decodifica o base64 e garante que o conteudo e mesmo um PDF."""
    if not isinstance(base64_doc, str) or not base64_doc.strip():
        raise ValueError("Conteudo base64 ausente ou vazio.")

    limpo = base64_doc.strip()
    if limpo.startswith("data:"):
        limpo = limpo.split(",", 1)[-1]
    limpo = re.sub(r"\s+", "", limpo)

    resto = len(limpo) % 4
    if resto:
        limpo += "=" * (4 - resto)

    try:
        dados = base64.b64decode(limpo)
    except Exception as exc:
        raise ValueError(f"base64 invalido: {exc}")

    if not dados.startswith(b"%PDF"):
        raise ValueError(
            f"O conteudo decodificado nao e um PDF (inicia com {dados[:8]!r})."
        )
    return dados


def _eh_pagina_carimbo(pagina):
    """Identifica a pagina final que o Zeev anexa so com o carimbo interno."""
    texto = pagina.get_text() or ""
    if MARCA_ZEEV not in texto and MARCA_ZEEV_ACENTUADA not in texto:
        return False
    if len(texto) > 800:
        return False
    maior_imagem = 0
    for info in pagina.get_images(full=True):
        maior_imagem = max(maior_imagem, info[2], info[3])
    return maior_imagem < 400


def _score_perfil(vetor):
    """Dispersao relativa do perfil de tinta. Linhas de texto geram picos."""
    media = float(vetor.mean())
    if media <= 0:
        return 0.0
    return float(vetor.var()) / (media * media)


def _classificar_orientacao(imagem):
    """Diz se o texto corre na horizontal ou na vertical.

    Linhas de texto criam alternancia forte (tinta/branco) no eixo
    perpendicular a sua direcao. Comparando a dispersao do perfil por linha
    com a do perfil por coluna, descobre-se o eixo do texto sem OCR.
    Nao distingue 90 de 270 — essa duvida vai no laudo.
    """
    cinza = imagem.convert("L")
    cinza.thumbnail((1200, 1200))
    matriz = np.asarray(cinza, dtype=np.uint8)
    tinta = (matriz < 160).astype(np.float32)

    if tinta.sum() < 500:
        return "indefinida", 0.0, 0.0

    score_linhas = _score_perfil(tinta.sum(axis=1))
    score_colunas = _score_perfil(tinta.sum(axis=0))

    if score_colunas > score_linhas * FATOR_DECISAO_ORIENTACAO:
        return "vertical", score_linhas, score_colunas
    return "horizontal", score_linhas, score_colunas


def _renderizar(pagina):
    """Rasteriza a pagina em DPI controlado, limitando o lado maior."""
    zoom = DPI_RENDER / 72.0
    largura_pt = pagina.rect.width or 1
    altura_pt = pagina.rect.height or 1
    maior_pt = max(largura_pt, altura_pt)
    if maior_pt * zoom > LADO_MAXIMO_PX:
        zoom = LADO_MAXIMO_PX / maior_pt
    pixmap = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pixmap.tobytes("png")))


def _montar_pdf(imagens):
    """Remonta um PDF a partir das imagens ja tratadas."""
    documento = fitz.open()
    for imagem in imagens:
        buffer = io.BytesIO()
        imagem.convert("L").save(buffer, format="JPEG", quality=QUALIDADE_JPEG, optimize=True)
        dados = buffer.getvalue()
        largura_pt = imagem.width * 72.0 / DPI_RENDER
        altura_pt = imagem.height * 72.0 / DPI_RENDER
        pagina = documento.new_page(width=largura_pt, height=altura_pt)
        pagina.insert_image(pagina.rect, stream=dados)
    saida = documento.tobytes(deflate=True, garbage=3)
    documento.close()
    return saida


def normalizar_documento(base64_doc, doc_type="documento", rotacao_forcada=None):
    """Prepara o documento para a IA.

    Args:
        base64_doc: conteudo do anexo em base64.
        doc_type: rotulo do documento, so para log.
        rotacao_forcada: graus (sentido anti-horario) a aplicar em todas as
            paginas rasterizadas, ignorando a heuristica. Usado na segunda
            tentativa, quando a primeira orientacao deu extracao fraca.

    Returns:
        (base64_tratado, laudo). Em qualquer erro nao fatal, devolve o
        conteudo original — o pre-voo nunca derruba o fluxo sozinho.
    """
    laudo = _laudo_vazio(doc_type)

    if not _DEPS_OK:
        laudo["acoes"].append(
            f"Dependencias de pre-voo ausentes ({_ERRO_DEPS}). "
            "Rode: pip install pymupdf pillow numpy. Documento enviado sem tratamento."
        )
        return base64_doc, laudo

    try:
        bruto = _decodificar(base64_doc)
    except ValueError as exc:
        laudo["bloqueio"] = str(exc)
        return base64_doc, laudo

    laudo["valido"] = True

    try:
        documento = fitz.open(stream=bruto, filetype="pdf")
    except Exception as exc:
        laudo["bloqueio"] = f"PDF ilegivel: {exc}"
        return base64_doc, laudo

    try:
        if documento.needs_pass:
            laudo["bloqueio"] = "PDF protegido por senha."
            return base64_doc, laudo

        laudo["paginas_originais"] = documento.page_count

        indices_uteis = []
        for indice in range(documento.page_count):
            if _eh_pagina_carimbo(documento[indice]):
                laudo["paginas_descartadas"] += 1
            else:
                indices_uteis.append(indice)

        if not indices_uteis:
            laudo["bloqueio"] = "O PDF so contem a pagina de carimbo do Zeev, sem documento."
            return base64_doc, laudo

        if laudo["paginas_descartadas"]:
            laudo["acoes"].append(
                f"{laudo['paginas_descartadas']} pagina(s) de carimbo do Zeev descartada(s)."
            )

        laudo["chars_texto"] = sum(
            len(documento[i].get_text() or "") for i in indices_uteis
        )
        limite = LIMIAR_TEXTO_POR_PAGINA * len(indices_uteis)

        # --- Caminho rapido: PDF com camada de texto nativa ---
        if laudo["chars_texto"] >= limite:
            laudo["paginas_enviadas"] = len(indices_uteis)
            laudo["acoes"].append(
                f"PDF nativo ({laudo['chars_texto']} chars de texto). Enviado sem reprocessamento."
            )
            if not laudo["paginas_descartadas"]:
                laudo["bytes_enviados"] = len(bruto)
                return base64_doc, laudo
            documento.select(indices_uteis)
            saida = documento.tobytes(deflate=True, garbage=3)
            laudo["bytes_enviados"] = len(saida)
            return base64.b64encode(saida).decode("utf-8"), laudo

        # --- Caminho lento: documento rasterizado ---
        laudo["rasterizado"] = True
        laudo["acoes"].append(
            f"Documento RASTERIZADO ({laudo['chars_texto']} chars de texto em "
            f"{len(indices_uteis)} pagina(s)). Re-renderizado a {DPI_RENDER} DPI."
        )

        imagens = []
        verticais = 0
        for indice in indices_uteis:
            imagem = _renderizar(documento[indice])
            if rotacao_forcada:
                imagem = imagem.rotate(rotacao_forcada, expand=True)
                laudo["rotacao_aplicada"] = rotacao_forcada
            else:
                orientacao, s_lin, s_col = _classificar_orientacao(imagem)
                logging.debug(
                    f"[pre-voo][{doc_type}] pag {indice + 1}: orientacao={orientacao} "
                    f"score_linhas={s_lin:.3f} score_colunas={s_col:.3f}"
                )
                if orientacao == "vertical":
                    verticais += 1
                    imagem = imagem.rotate(ROTACAO_PADRAO, expand=True)
                    laudo["rotacao_aplicada"] = ROTACAO_PADRAO
            imagens.append(imagem)

        if verticais:
            laudo["acoes"].append(
                f"{verticais} pagina(s) com texto na vertical endireitada(s) em {ROTACAO_PADRAO} graus."
            )
            # A heuristica nao separa 90 de 270: guarda a alternativa para retentativa.
            laudo["rotacoes_alternativas"] = [ROTACAO_ALTERNATIVA]

        saida = _montar_pdf(imagens)
        laudo["paginas_enviadas"] = len(imagens)
        laudo["bytes_enviados"] = len(saida)
        return base64.b64encode(saida).decode("utf-8"), laudo

    except Exception as exc:
        logging.warning(f"[pre-voo][{doc_type}] Falha no tratamento: {exc}", exc_info=True)
        laudo["acoes"].append(f"Falha no pre-voo ({exc}). Documento enviado sem tratamento.")
        return base64_doc, laudo
    finally:
        try:
            documento.close()
        except Exception:
            pass


def registrar_laudo(laudo):
    """Escreve o laudo do pre-voo no log, em uma linha por acao."""
    doc_type = laudo.get("doc_type", "documento")
    logging.info(
        f"[pre-voo][{doc_type}] paginas={laudo['paginas_originais']} "
        f"enviadas={laudo['paginas_enviadas']} descartadas={laudo['paginas_descartadas']} "
        f"texto={laudo['chars_texto']} chars rasterizado={laudo['rasterizado']} "
        f"rotacao={laudo['rotacao_aplicada']} bytes={laudo['bytes_enviados']:,}"
    )
    for acao in laudo.get("acoes", []):
        logging.info(f"[pre-voo][{doc_type}] {acao}")
    if laudo.get("bloqueio"):
        logging.error(f"[pre-voo][{doc_type}] BLOQUEIO: {laudo['bloqueio']}")
