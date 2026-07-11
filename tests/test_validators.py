from lancamento_cln.utils import validators as val


def test_normaliza_cnpj():
    assert val.normaliza_cnpj("61.074.175/0001-38") == "61074175000138"


def test_mesma_raiz():
    assert val.mesma_raiz("02866969000125", "02866969000630") is True
    assert val.mesma_raiz("02866969000125", "11111111000111") is False
