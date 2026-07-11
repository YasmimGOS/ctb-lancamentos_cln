"""Verifica que o lote processa N pedidos (sequencial e em paralelo)."""
import time
from lancamento_cln.config import get_settings
from lancamento_cln.controllers import LancamentoController


class _Bpms:
    def __init__(self, n): self.n = n
    def obter_lista_pedidos(self):
        return [{"PDC_IN_CODIGO": 1000 + i, "FIL_IN_CODIGO": 15537, "AGN_IN_CODIGO": 1,
                 "AGN_ST_FANTASIA": "FORN", "COND_ST_CODIGO": "30D"} for i in range(self.n)]
    def obter_dados_pedido(self, f, p):
        return [{"ITEM_SEQUENCIA": 1, "PRODUTO": 1, "UNIDADE": "UN", "QUANTIDADE_PEDIDO": 1,
                 "VALOR_TOTAL_ITEM_PEDIDO": "100.00", "PRCT_CC": "100",
                 "CNPJ_CPF_FORNECEDOR": "12345678000199", "CNPJ_CPF_FILIAL": "07258201000132"}]
    def consultar_anexos(self, f, a, p, d):
        return [{"filial": 15537, "pedido": p, "nomeArquivo": "n.pdf", "anexoBase64": "x"}]
    def consultar_bd(self, c): return []
    def registrar(self, *a, **k): pass


class _IA:
    def _demora(self):
        time.sleep(0.2)  # simula I/O (polling)
    def extrair_primaria(self, b):
        self._demora()
        return {"tipoDocFiscal": "BOLP", "numNota": "10", "dataDocumento": "29/06/2026",
                "valorTotalDocumento": "100.00", "cnpjEmitente": "12345678000199",
                "nomeTomador": "PONTAL", "cnpjCpfTomador": "07258201000132"}
    def extrair_extra(self, b):
        self._demora()
        return {"issRetido": False, "valorISSRetido": "0.00", "numNota": "", "cnpjCpfTomador": "07258201000132"}


class _Mega:
    def lancar_recebimento(self, payload):
        return 200, {"data": {"codTransacao": "T", "pkMega": "0;0;0;0;0;0;PK"}}


class _Teams:
    def sucesso(self, m): pass
    def aviso(self, m): pass
    def erro(self, m, tecnico=False): pass


def _rodar(n, workers):
    s = get_settings()
    s.modo_teste = True
    s.max_workers = workers
    s.limite_pedidos = 0   # 0 = todos (sem filtro, pega os N primeiros)
    s.filtro_pedidos = ""
    s.codigo_teste = ""
    ctrl = LancamentoController(s, bpms=_Bpms(n), mega=_Mega(), ia=_IA(), teams=_Teams())
    return ctrl.executar_lote()


def test_processa_os_10_primeiros_paralelo():
    res = _rodar(10, workers=5)
    assert len(res) == 10
    assert all(r.lancado for r in res)


def test_paralelo_mais_rapido_que_sequencial():
    t0 = time.time(); _rodar(6, workers=1); seq = time.time() - t0
    t0 = time.time(); _rodar(6, workers=6); par = time.time() - t0
    assert par < seq  # paralelo deve reduzir o tempo
