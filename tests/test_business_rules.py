from lancamento_cln.services import business_rules as br


def test_apolice_precede_override_emitente_mapfre():
    assert br.resolver_tipo_doc_por_emitente("APOLICE", "61.074.175/0001-38") == "APOLICE"


def test_override_emitente_quando_nao_apolice():
    assert br.resolver_tipo_doc_por_emitente("BOLP-DETRAN", "61074175000138") == "BOLP"


def test_sem_override_mantem_tipo():
    assert br.resolver_tipo_doc_por_emitente("NF-E", "99999999000199") == "NF-E"


def test_ajustar_bolp_detran():
    assert br.ajustar_bolp_detran("BOLP-DETRAN") == "BOLP"
    assert br.ajustar_bolp_detran("BOLP-DETRAN-IPVA-ANTT") == "BOLP"
    assert br.ajustar_bolp_detran("NF-E") == "NF-E"


def test_acao_a_vista_e_prazo():
    assert br.calcular_acao_e_conta("BOLP", "ADIANT")["acao"] == 771
    assert br.calcular_acao_e_conta("BOLP", "30D")["acao"] == 768
    assert br.calcular_acao_e_conta("APOLICE", "30D") == {"contasPagarTipoDoc": "", "acao": 0}


def test_normaliza_cond_pagto():
    assert br.normaliza_cond_pagto("20D M") == "20D"
    assert br.normaliza_cond_pagto("30/60") == "30/60"
    assert br.normaliza_cond_pagto("28D") == "28D"


def test_quantidade_cond_pagto_blindada():
    assert br.quantidade_cond_pagto("28D") == 28
    assert br.quantidade_cond_pagto("2M") == 2
    assert br.quantidade_cond_pagto("30/60") == 0
    assert br.quantidade_cond_pagto("D") == 0


def test_bloqueio_7_dias():
    assert br.bloqueia_por_cond_pagto_7dias("7D") is True
    assert br.bloqueia_por_cond_pagto_7dias("5D") is True
    assert br.bloqueia_por_cond_pagto_7dias("30D") is False
    assert br.bloqueia_por_cond_pagto_7dias("30/60") is False


def test_valida_emitente_mesma_raiz():
    assert br.valida_emitente_x_fornecedor("02866969000125", "02866969000630") is True


def test_valida_emitente_divergente():
    assert br.valida_emitente_x_fornecedor("11111111000111", "22222222000122") is False


def test_valida_tomador_por_depara_filial():
    assert br.valida_tomador_x_filial("07258201000132", "PONTAL LTDA", "15537", "") is True


def test_valida_tomador_por_nome():
    assert br.valida_tomador_x_filial("", "PONTAL ADMINISTRACAO", "15537", "") is True


def test_valida_tomador_ccp_cerrado_filial_235758():
    assert br.valida_tomador_x_filial(
        "13619137000251", "CCP CERRADO EMPREENDIMENTOS IMOBILIARIOS S.A.", "235758", "24357174000174"
    ) is True
    assert br.valida_tomador_x_filial("13619137000251", "CCP CERRADO", "3", "01657436000110") is False


def test_remove_zeros_a_esquerda():
    assert br.remove_zeros_a_esquerda("000002331") == "2331"
    assert br.remove_zeros_a_esquerda("0") == "0"
    assert br.remove_zeros_a_esquerda("100") == "100"


def test_reembolso():
    assert br.eh_reembolso("REEMBOLSO DESPESAS") is True
    assert br.eh_reembolso("Reembolso Fulano") is True
    assert br.eh_reembolso("MAPFRE SEGUROS") is False


def test_corrigir_total_iss():
    assert br.corrigir_total_iss_por_valor_iss({"valorISS": "13.00", "totalISS": "0.00"})["totalISS"] == "13.00"


def test_retificar_iss_nao_retido():
    ia = {"valorISS": "13.00", "totalISS": "13.00", "percentualISS": "2.00", "baseISS": "650.00"}
    extra = {"issRetido": False, "valorISSRetido": "0.00"}
    assert br.precisa_retificar_iss_nao_retido(ia, extra) is True
    ret = br.retificar_iss_nao_retido(ia)
    assert ret["valorISS"] == "0.00" and ret["totalISS"] == "0.00"


def test_pis_cofins_reconhecido_na_raiz():
    assert br.eh_pis_cofins_reconhecido({"valorPIS": "10.00", "valorCOFINS": "0.00"}) is True
    assert br.eh_pis_cofins_reconhecido({"valorPIS": "0.00", "valorCOFINS": "5.50"}) is True
    assert br.eh_pis_cofins_reconhecido({"valorPIS": "0.00", "valorCOFINS": "0.00"}) is False


def test_resolver_cnpj_emitente_corrigido():
    de_para = {"CCP CERRADO EMPREENDIMENTOS IMOBILIARIOS S.A": "01543032000104"}
    assert br.resolver_cnpj_emitente_corrigido(
        "CCP Cerrado Empreendimentos Imobiliarios S.A", "340577401231", de_para
    ) == "01543032000104"
    assert br.resolver_cnpj_emitente_corrigido("Outro Fornecedor", "12345678000199", de_para) == "12345678000199"


def test_pis_cofins_reconhecido_no_item():
    payload = {"valorPIS": "0.00", "valorCOFINS": "0.00",
               "itensReceb": [{"valorPIS": "0.00", "valorCofins": "3.20"}]}
    assert br.eh_pis_cofins_reconhecido(payload) is True

    payload_sem = {"valorPIS": "0.00", "valorCOFINS": "0.00",
                   "itensReceb": [{"valorPIS": "0.00", "valorCofins": "0.00"}]}
    assert br.eh_pis_cofins_reconhecido(payload_sem) is False
