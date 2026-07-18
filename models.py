"""Camada de dados: contratos Pydantic (schemas de entrada e de saida).

Os nomes dos campos da carga final seguem o contrato do Mega ERP (camelCase),
de modo que ``model_dump()`` ja produz o JSON aceito.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PedidoLista(BaseModel):
    model_config = ConfigDict(extra="allow")
    ORG_IN_CODIGO: int | None = None
    ORG_ST_FANTASIA: str | None = None
    FIL_IN_CODIGO: int | None = None
    FIL_ST_FANTASIA: str | None = None
    SERIE_SEQUENCIA: int | None = None
    PDC_IN_CODIGO: int | None = None
    PDC_DT_EMISSAO: str | None = None
    AGN_IN_CODIGO: int | None = None
    AGN_ST_FANTASIA: str | None = None
    PDC_ST_SITUACAO: str | None = None
    PDC_ST_STATUS: str | None = None
    PDC_ST_ANEXO: str | None = None
    COND_ST_CODIGO: str | None = None
    PRODUTO: int | None = None
    ITEM_SEQUENCIA: int | None = None
    DATA_ENTREGA: str | None = None
    ITP_RE_QUANTIDADE: float | None = None
    ITP_RE_QTDEACONVERTER: float | None = None


class DadoPedido(BaseModel):
    model_config = ConfigDict(extra="allow")
    ITEM_SEQUENCIA: Any = None
    PRODUTO: Any = None
    UNIDADE: Any = None
    QUANTIDADE_PEDIDO: Any = None
    VALOR_TOTAL_ITEM_PEDIDO: Any = None
    VALOR_CONFERIDO: Any = None
    APLICACAO: Any = None
    TIPO_CLASSE: Any = None
    CC_RATEIO: Any = None
    CC_PADRAO: Any = None
    PROJETO: Any = None
    PROJ_PADRAO: Any = None
    PRCT_CC: Any = None
    SERIE_SEQUENCIA: Any = None
    PEDIDO: Any = None
    DATA_ENTREGA: Any = None
    COND_PAGTO: Any = None
    TIPO_PRECO: Any = None
    CNPJ_CPF_FORNECEDOR: Any = None
    CNPJ_CPF_FILIAL: Any = None


class Anexo(BaseModel):
    model_config = ConfigDict(extra="allow")
    filial: Any = None
    pedido: Any = None
    nomeArquivo: str | None = None
    anexoBase64: str | None = None
    chaveAnexo: Any = None
    dataPedido: Any = None


class RespostaIA(BaseModel):
    model_config = ConfigDict(extra="allow")
    tipoDocFiscal: str = ""
    numNota: str = ""
    serie: str = ""
    dataDocumento: str = ""
    chaveAcesso: str = ""
    municipioPrestacao: str = ""
    ufPrestacao: str = ""
    nomeEmitente: str = ""
    cnpjEmitente: str = ""
    nomeTomador: str = ""
    cnpjCpfTomador: str = ""
    valorTotalDocumento: str = ""
    valorMercadoria: str = ""
    baseICMS: str = ""
    valorICMS: str = ""
    totalISS: str = ""
    totalIRRF: str = ""
    totalINSS: str = ""
    valorPIS: str = ""
    valorCOFINS: str = ""
    totalCSLL: str = ""
    percentualIcms: str = ""
    valorBaseIPI: str = ""
    percIPI: str = ""
    valorIPI: str = ""
    valorIcmsRetido: str = ""
    baseISS: str = ""
    percentualISS: str = ""
    valorISS: str = ""
    baseIRFF: str = ""
    percentualIRFF: str = ""
    valorIRFF: str = ""
    baseINSS: str = ""
    percentualINSS: str = ""
    valorINSS: str = ""
    basePIS: str = ""
    percentualPIS: str = ""
    baseCofins: str = ""
    percentualCofins: str = ""
    valorCofins: str = ""
    baseCSLL: str = ""
    percentualCSLL: str = ""
    valorCSLL: str = ""


class RespostaIAExtra(BaseModel):
    model_config = ConfigDict(extra="allow")
    chaveAcesso: str = ""
    issRetido: bool = False
    valorISSRetido: str = "0.00"
    cnpjCpfTomador: str = ""
    numNota: str = ""


class Projeto(BaseModel):
    model_config = ConfigDict(extra="allow")
    numNota: str = ""
    itemSequencia: str = ""
    projetoReduzido: str = ""
    tipoClasse: str = ""
    prctRateio: str = ""
    valorRateio: str = ""
    operacao: str = "I"


class CentroCusto(BaseModel):
    model_config = ConfigDict(extra="allow")
    numNota: str = ""
    itemSequencia: str = ""
    centroCustoReduzido: str = ""
    tipoClasse: str = ""
    prctRateio: str = ""
    valorRateio: str = ""
    projetos: list[Projeto] = Field(default_factory=list)
    operacao: str = "I"


class PedidoRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    numNota: str = ""
    dataDocumento: str = ""
    itemSequencia: str = ""
    serieSequencia: str = ""
    codPedido: str = ""
    sequenciaItemPedido: str = ""
    quantidade: str = ""
    dataEntrega: str = ""
    qtdeConvertida: str = ""
    operacao: str = "I"


class ItemReceb(BaseModel):
    """Template completo de item de recebimento (Mega ERP).

    Segue o template do Power Automate Cloud: 'Compor - template itensReceb'.
    Todos os campos são strings, mesmo percentuais e valores monetários.
    """
    model_config = ConfigDict(extra="allow")
    documento: str = ""
    itemSequencia: str = ""
    produto: str = ""
    produtoCodAlternativo: str = ""
    unidade: str = ""
    unidadeRecebimento: str = ""
    codConversor: str = ""
    qtdeRecebimento: str = ""
    valorConverter: str = "0"
    valorMercadoria: str = "0"
    percDesconto: str = "0"
    valorDesconto: str = "0"
    valorMaoObra: str = "0"
    valorMercadoriaEmpr: str = "0"
    valorBaseIPI: str = "0"
    percIPI: str = "0"
    valorIPI: str = "0"
    valorIsentoIPI: str = "0"
    valorOutrosIPI: str = "0"
    valorRecuperadoIPI: str = "0"
    baseIcms: str = "0"
    percentualIcms: str = "0"
    valorIcms: str = "0"
    valorIsentoIcms: str = "0"
    valorOutrosIcms: str = "0"
    valorIcmsRecupera: str = "0"
    valorIcmsRetido: str = "0"
    baseSubTrib: str = "0"
    aplicacao: str = ""
    tipoClasse: str = ""
    sitTribICMSA: str = "0"
    sitTribICMSB: str = "90"
    sitTribPIS: str = "70"
    sitTribCofins: str = "70"
    calculaValores: str = "N"
    baseISS: str = "0"
    percentualISS: str = "0"
    valorISS: str = "0"
    baseIRFF: str = "0"
    percentualIRFF: str = "0"
    valorIRFF: str = "0"
    baseINSS: str = "0"
    percentualINSS: str = "0"
    valorINSS: str = "0"
    basePIS: str = "0"
    percentualPIS: str = "0"
    valorPIS: str = "0"
    baseCofins: str = "0"
    percentualCofins: str = "0"
    valorCofins: str = "0"
    baseCSLL: str = "0"
    percentualCSLL: str = "0"
    valorCSLL: str = "0"
    sitTribIPI: str = "49"
    codEnquadramentoIPI: str = "999"
    centrosCusto: list[CentroCusto] = Field(default_factory=list)
    pedidos: list[PedidoRef] = Field(default_factory=list)


class Parcela(BaseModel):
    model_config = ConfigDict(extra="allow")
    numNota: str = ""
    numDocumento: str = ""
    numParcela: str = ""
    dataVencimento: str = ""
    valorParcela: str = ""


class PayloadRecebimento(BaseModel):
    model_config = ConfigDict(extra="allow")
    filial: str = ""
    acao: str = ""
    contasPagarTipoDoc: str = ""
    agente: str = ""
    numNota: str = ""
    serie: str = ""
    tipoDocFiscal: str = ""
    dataDocumento: str = ""
    dataMovimento: str = ""
    condPagto: str = ""
    valorMercadoria: str = ""
    valorMercadoriaEmpenhada: str = ""
    totalNota: str = ""
    chaveAcesso: str = ""
    valorDescontoGeral: str = ""
    baseICMS: str = ""
    valorICMS: str = ""
    valorIPI: str = ""
    totalISS: str = ""
    totalIRRF: str = ""
    totalINSS: str = ""
    valorPIS: str = ""
    valorCOFINS: str = ""
    totalCSLL: str = ""
    # Campos restaurados do template original do fluxo Power Automate (ver
    # docs/REGRAS_PROJETO.md secao 3.7) - existiam no payload original enviado ao Mega e foram
    # perdidos na reescrita em Python. TESTE EM VALIDACAO.
    tragnCodigo: str = ""
    tipoTrans: str = ""
    icmsStreRecupera: str = ""
    valorBaseIPI: str = ""
    calculaValores: str = "N"
    operacao: str = ""
    itensReceb: list[ItemReceb] = Field(default_factory=list)
    parcelas: list[Parcela] = Field(default_factory=list)


class ResultadoPedido(BaseModel):
    model_config = ConfigDict(extra="allow")
    pedido: Any = None
    filial: Any = None
    deve_lancar: bool = True
    lancado: bool = False
    status: str = ""
    mensagem: str = ""
    num_doc: str = ""
    tipoDocFiscal: str = ""

