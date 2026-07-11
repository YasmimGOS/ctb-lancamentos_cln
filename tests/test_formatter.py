from lancamento_cln.utils import formatter as fmt


def test_to_float_virgula_e_vazio():
    assert fmt.to_float("13,00") == 13.0
    assert fmt.to_float("") == 0.0
    assert fmt.to_float(None) == 0.0


def test_format_number():
    assert fmt.format_number("13,5") == "13.50"
    assert fmt.format_number(0) == "0.00"


def test_datas_br_iso():
    assert fmt.data_br_para_iso("29/06/2026") == "2026-06-29"
    assert fmt.data_br_para_iso("") == ""
    assert fmt.data_iso_para_br("2026-06-29") == "29/06/2026"


def test_add_dias_meses():
    assert fmt.add_dias_br("29/06/2026", 30) == "29/07/2026"
    assert fmt.add_meses_br("29/06/2026", 1) == "29/07/2026"
