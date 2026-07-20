"""Validacoes e normalizacoes (CNPJ/CPF, digitos)."""
from __future__ import annotations


def somente_digitos(valor: object) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def normaliza_cnpj(valor: object) -> str:
    """Normaliza CNPJ/CPF removendo caracteres especiais e corrigindo zeros extras.

    Resolve problemas comuns de leitura de IA:
    - "002661843000164" (15 dígitos) -> "02661843000164" (14 dígitos)
    - "0012345678901" (13 dígitos) -> "00012345678901" (14 dígitos)

    Args:
        valor: CNPJ/CPF com ou sem formatação

    Returns:
        String com apenas dígitos, tamanho correto (11 para CPF, 14 para CNPJ)
    """
    # Remove caracteres especiais
    s = str(valor or "").strip()
    for ch in (".", "-", "/", " "):
        s = s.replace(ch, "")

    # Remove tudo que não é dígito
    s = "".join(c for c in s if c.isdigit())

    # Se vazio, retorna vazio
    if not s:
        return ""

    # Remove zeros à esquerda
    s = s.lstrip("0")

    # Se ficou vazio (era só zeros), retorna "0"
    if not s:
        return "0"

    # Determina se é CPF ou CNPJ pelo tamanho após remover zeros
    # CPF: até 11 dígitos, CNPJ: 12-14 dígitos
    if len(s) <= 11:
        # É CPF - preenche até 11 dígitos
        return s.zfill(11)
    else:
        # É CNPJ - preenche até 14 dígitos
        return s.zfill(14)


def normaliza_texto(valor: object) -> str:
    """Normaliza texto para comparacao de nomes: colapsa qualquer sequencia de espacos
    (incl. tabs e espaco nao-quebravel \xa0) em um unico espaco, remove espacos nas
    pontas e converte para maiusculas.

    Resolve falsos negativos quando o mesmo nome vem da IA com espacamento diferente
    do cadastrado (ex.: espacos duplos ou nao-quebraveis entre palavras).
    """
    s = str(valor or "").replace("\xa0", " ")
    return " ".join(s.split()).upper()


def mesma_raiz(cnpj_a: str, cnpj_b: str) -> bool:
    a, b = normaliza_cnpj(cnpj_a), normaliza_cnpj(cnpj_b)
    return len(a) == 14 and len(b) == 14 and a[:8] == b[:8]


def tamanho_valido(doc: str) -> bool:
    d = somente_digitos(doc)
    return len(d) in (11, 14)


def chave_acesso_valida(chave: object) -> bool:
    """Valida chave de acesso de NF-e/NFC-e/CT-e/NFS-e: 44 dígitos numéricos + dígito
    verificador (módulo 11, mesmo algoritmo usado pela SEFAZ) sobre os 43 primeiros dígitos.

    Uma leitura de IA pode ter exatamente 44 dígitos e ainda estar errada (dígitos trocados
    ou um grupo de 4 dígitos substituído por outro parecido) - o dígito verificador pega esse
    caso, que a checagem antiga (só tamanho == 44) deixava passar.
    """
    s = somente_digitos(chave)
    if len(s) != 44:
        return False
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for i, c in enumerate(reversed(s[:43])):
        total += int(c) * pesos[i % 8]
    resto = total % 11
    dv_calculado = 0 if resto in (0, 1) else 11 - resto
    return dv_calculado == int(s[43])
