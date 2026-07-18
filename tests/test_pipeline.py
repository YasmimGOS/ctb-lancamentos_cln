"""Teste de integracao do ETL (montagem do payload, sem I/O)."""
from lancamento_cln.services import business_rules as br
from lancamento_cln.services import etl_service as etl
from lancamento_cln.models import PayloadRecebimento


def test_montar_payload_nfse_iss_retido():
    pedido = {"FIL_IN_CODIGO": 15537, "AGN_IN_CODIGO": 30178, "COND_ST_CODIGO": "30D", "PDC_IN_CODIGO": 320999}
    dados = [{"ITEM_SEQUENCIA": 1, "PRODUTO": 158991, "UNIDADE": "UN", "QUANTIDADE_PEDIDO": 1,
              "VALOR_TOTAL_ITEM_PEDIDO": "1500.00", "TIPO_CLASSE": "01", "CC_RATEIO": "10",
              "PROJETO": "5", "PRCT_CC": "100"}]
    ia = {"tipoDocFiscal": "NFS-E", "numNota": "000000321", "dataDocumento": "29/06/2026",
          "valorTotalDocumento": "1500.00", "valorMercadoria": "0", "cnpjEmitente": "12345678000199",
          "nomeTomador": "PONTAL", "cnpjCpfTomador": "07258201000132",
          "valorISS": "30.00", "baseISS": "1500.00", "totalISS": "0.00"}
    extra = {"issRetido": True, "valorISSRetido": "30.00", "numNota": ""}

    ia_final, cnpj_emit, _, tipo = etl.consolidar_resposta_ia(ia, extra, pedido["PDC_IN_CODIGO"])
    acao = br.calcular_acao_e_conta(tipo, pedido["COND_ST_CODIGO"])
    payload, bloq7, _diverge = etl.montar_payload(pedido, dados, ia_final, cnpj_emit, tipo, acao, "", "America/Sao_Paulo")
    p = PayloadRecebimento(**payload)

    assert p.numNota == "321"                 # zeros removidos
    assert p.contasPagarTipoDoc == "NFS"      # de-para
    assert p.baseICMS == "0"                  # servico zera base
    assert p.valorMercadoria == "1500.00"
    assert p.parcelas[0].dataVencimento == "29/07/2026"
    assert p.itensReceb[0].valorISS == "30.00"
    assert bloq7 is False
