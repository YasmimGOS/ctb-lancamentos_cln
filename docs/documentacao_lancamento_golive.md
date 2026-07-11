# Documentação de Lançamento CLN (ETL)

## 0) Nota de contexto (importante para futuras interações da IA)
- Este projeto usa **português do Brasil** como idioma principal de documentação.
- **Acentuação deve ser utilizada normalmente** (não simplificar para texto sem acentos).
- Essa diretriz vale para novas versões deste documento e para materiais correlatos do fluxo CLN.

## 1) Objetivo
Este documento explica como construir o JSON **Resultado** a partir das entradas:
- JSON **Obter pedido**
- JSON **Dados do pedido**
- PDF do documento fiscal (quando necessário)

Foco:
- Regras de negócio
- Regras técnicas no **Power Automate Cloud**
- Base de contexto para evoluções futuras

## 2) Escopo e premissas
- Campos `tipoDocFiscal` e `acao`: calculados por lógica já conhecida (fora do escopo de detalhamento).
- Quando um campo do `Resultado` não existir nos JSONs de entrada, usar o marcador `<dado externo>` até haver fonte.
- A leitura do PDF fiscal é feita **sempre via LLM multimodal**.
- Não faz parte desta solução extrair texto do PDF com bibliotecas locais (ex.: parser textual de PDF).

## 3) Entradas conhecidas
- `Obter pedido`: cabeçalho do pedido e item principal consultado.
- `Dados do pedido`: coleção `data[]` com itens, centro de custo/projeto e metadados de compra.
- `309675.pdf`: fonte potencial para dados fiscais (número da nota, série, tributos, valores etc.).

## 4) Mapeamento ETL (Resultado raiz)
Legenda:
- `OP` = Obter pedido
- `DP` = Dados do pedido (`data[0]` para cabeçalho, quando aplicável)
- `PDF` = extraído do documento fiscal

| Campo Resultado | Origem | Regra |
|---|---|---|
| `filial` | OP.`FIL_IN_CODIGO` ou DP.`FILIAL` | Converter para string. |
| `acao` | Regra conhecida | Fora de escopo (preencher pela regra atual). |
| `contasPagarTipoDoc` | Regra formalizada via `tabela_depara_tipodoc` | Obtido por `tipoDocFiscal` no De x Para e aplicado em `Compor - Calcular acao (a vista e prazo)`. |
| `agente` | OP.`AGN_IN_CODIGO` ou DP.`AGENTE` | String. |
| `numNota` | PDF | Se não extraído: `<dado externo>`. |
| `serie` | PDF | Se não extraído: `<dado externo>`. |
| `tipoDocFiscal` | Regra conhecida | Fora de escopo (preencher pela regra atual). |
| `dataDocumento` | PDF (preferencial) / OP.`DATA_ENTREGA` fallback | Formato `dd/MM/yyyy`. |
| `dataMovimento` | Data atual | Definir ao final do fluxo como data atual no formato `dd/MM/yyyy` (fuso São Paulo). |
| `tipoPreco` | DP.`TIPO_PRECO` | String. |
| `condPagto` | OP.`COND_ST_CODIGO` ou DP.`COND_PAGTO` | String. |
| `centroCustoReduzido` | DP.`CC_PADRAO` | String. |
| `projetoReduzido` | DP.`PROJ_PADRAO` | String. |
| `valorMercadoria` | Soma dos itens `itensReceb[].valorMercadoria` | Monetário com 2 casas. |
| `totalMaoObra` | PDF/regra fiscal | Se ausente: `"0.00"` (ou `<dado externo>` se obrigatório). |
| `valorMercadoriaEmpenhada` | Processo de empenho | Se não houver fonte: `""` ou `<dado externo>`. |
| `totalFrete` | PDF | Padrão `"0.00"` se não informado. |
| `totalSeguro` | PDF | Padrão `"0.00"` se não informado. |
| `totalDespesa` | PDF | Padrão `"0.00"` se não informado. |
| `totalNota` | Soma lógica dos componentes da nota | No caso simples: igual a `valorMercadoria`. |
| `chaveAcesso` | PDF/NF-e | Se não houver: `""`. |
| `totalImportacao` | PDF/regra | Padrão `"0.00"`. |
| `despesaNaoTributada` | PDF/regra | Padrão `"0.00"`. |
| `valorAcrescimoGeral` | PDF/regra | Padrão `"0.00"`. |
| `valorDescontoGeral` | PDF/regra | Padrão `"0.00"`. |
| `baseICMS`, `valorICMS`, `valorIPI`, `totalISS`, `totalIRRF`, `totalINSS`, `valorSestSenat`, `baseSubstTributaria`, `valorICMSRetido`, `valorPIS`, `valorCOFINS`, `totalCSLL`, `baseFunRural`, `valorFunRural`, `valorICMSDesonera`, `valorPisRecupera`, `valorCofinsRecupera` | PDF / cálculo tributário externo | Se não disponível: `<dado externo>` (ou `"0.00"` quando regra aceitar default). |
| `tragnCodigo`, `tipoTrans`, `icmsStreRecupera`, `calculaValores` | Regra/parametrização ERP | Se não houver regra documentada: `<dado externo>` ou `""`. |
| `operacao` | Regra técnica | No exemplo: `"I"` para inclusão. |

## 5) Mapeamento ETL de `itensReceb`
Para cada linha de `DP.data[]`, criar 1 item em `itensReceb`.

| Campo item | Origem | Regra |
|---|---|---|
| `documento` | `numNota` (raiz) | Copiar. |
| `itemSequencia` | DP.`ITEM_SEQUENCIA` | String. |
| `produto` | DP.`PRODUTO` | String. |
| `produtoCodAlternativo` | DP.`PRODUTO` | Mesmo valor de `produto` (enquanto não houver cadastro alternativo). |
| `unidade` | DP.`UNIDADE` | String. |
| `unidadeRecebimento`, `codConversor`, `valorConverter` | Conversão de unidade | Se não houver regra: `""`. |
| `qtdeRecebimento` | DP.`QUANTIDADE_PEDIDO` | String (fallback para DP.`QUANTIDADE` quando necessário). |
| `valorMercadoria` | DP.`VALOR_TOTAL_ITEM_PEDIDO` | String (fallback para DP.`VALOR_CONFERIDO` quando necessário). |
| Campos de desconto/IPI/ICMS/ISS/IRRF/INSS/PIS/COFINS/CSLL do item | PDF/cálculo fiscal | Se não houver fonte: `<dado externo>` ou `"0.00"` quando permitido. |
| `aplicacao` | DP.`APLICACAO` | String. |
| `tipoClasse` | DP.`TIPO_CLASSE` | String. |
| `operacao` implícita em subobjetos | Regra técnica | No exemplo: `"I"`. |

### 5.1) `itensReceb[].centrosCusto`
Para cada item, criar 1 registro inicial com DP:
- `centroCustoReduzido` <- DP.`CC_RATEIO` (fallback DP.`CC_PADRAO`)
- `tipoClasse` <- DP.`TIPO_CLASSE`
- `prctRateio` <- DP.`PRCT_CC` formatado com 2 casas (`100.00`)
- `valorRateio` <- `valorMercadoriaItem * (prctRateio/100)`
- `operacao` <- `"I"`

### 5.2) `itensReceb[].centrosCusto[].projetos`
Para cada centro de custo do item:
- `projetoReduzido` <- DP.`PROJETO` (fallback DP.`PROJ_PADRAO`)
- `tipoClasse` <- DP.`TIPO_CLASSE`
- `prctRateio` <- mesmo percentual do CC
- `valorRateio` <- mesmo valor rateado do CC (na regra 1:1 atual)
- `operacao` <- `"I"`

### 5.3) `itensReceb[].pedidos`
Para cada item:
- `numNota` <- raiz.`numNota`
- `dataDocumento` <- raiz.`dataDocumento`
- `itemSequencia` <- DP.`ITEM_SEQUENCIA`
- `serieSequencia` <- DP.`SERIE_SEQUENCIA` (ou OP.`SERIE_SEQUENCIA`)
- `codPedido` <- DP.`PEDIDO` (ou OP.`PDC_IN_CODIGO`)
- `sequenciaItemPedido` <- DP.`ITEM_SEQUENCIA` (ou OP.`ITEM_SEQUENCIA`)
- `quantidade` <- DP.`QUANTIDADE_PEDIDO` (fallback DP.`QUANTIDADE`)
- `dataEntrega` <- DP.`DATA_ENTREGA` (ou OP.`DATA_ENTREGA`)
- `qtdeConvertida` <- regra de conversão; sem conversor usar mesma quantidade
- `operacao` <- `"I"`

## 6) Mapeamento ETL de `parcelas`
Regra base (1 parcela) no exemplo:
- `numNota` e `numDocumento` = `numNota`
- `numParcela` = `"1"`
- `dataVencimento` = `dataDocumento + dias(condPagto)`
- `valorParcela` = `totalNota`

Observação de negócio:
- Com `condPagto = "09D"` e `dataDocumento = 04/02/2026`, vencimento esperado = **13/02/2026** (confere com o JSON de resultado).
- Se houver condições com múltiplas parcelas, usar tabela de condição de pagamento do ERP (`<dado externo>` se não disponível na automação).

## 7) Campos com dependência externa (neste cenário)
Como não estão nos JSONs de entrada apresentados:
- `numNota`, `serie`, `chaveAcesso`
- Valores de item (`qtdeRecebimento`, `valorMercadoria` item)
- Tributos e bases (raiz e itens)
- Regras de transporte/recuperação (`tragnCodigo`, `tipoTrans`, etc.)

Quando não houver captura no momento da execução:
- Preencher com `"<dado externo>"` em ambiente de diagnóstico/documentação.
- Em produção, substituir por defaults aceitos pelo ERP (`""` ou `"0.00"`) conforme contrato do endpoint.

## 8) Estratégia obrigatória de extração via IA multimodal (PDF fiscal)
Regra mandatória:
- Todo PDF fiscal deve ser lido por IA multimodal.
- Não há caminho alternativo com leitura textual por biblioteca de PDF.
- O retorno deve ser estruturado em JSON para consumo do fluxo.

### 8.1) Campos alvo para extração
- Cabeçalho: número da nota, série, data de emissão, chave de acesso, CNPJ emissor/tomador
- Totais: valor total da nota, frete, seguro, descontos, acréscimos
- Tributos: bases e valores de ICMS/IPI/ISS/PIS/COFINS/IRRF/INSS/CSLL
- Itens: código/descrição, unidade, quantidade, valor unitário, valor total do item

### 8.2) Prompt usado no LLM de processamento de PDF
<prompt>
Objetivo:
Extrair e estruturar informações de DOCUMENTOS FISCAIS BRASILEIROS, como NF-e, NFC-e, NFS-e, CT-e, boletos, DANFE, RPS, faturas e documentos equivalentes, a partir de imagem, PDF ou texto, retornando exclusivamente um JSON válido que siga exatamente o template abaixo.

Template obrigatório:
{
  "tipoDocFiscal": "string",
  "numNota": "string",
  "serie": "string",
  "dataDocumento": "dd/MM/yyyy",
  "chaveAcesso": "string",
  "municipioPrestacao": "string",
  "ufPrestacao": "string",
  "nomeEmitente": "string",
  "cnpjEmitente": "string",
  "nomeTomador": "string",
  "cnpjCpfTomador": "string",
  "valorTotalDocumento": "string",
  "valorMercadoria": "string",
  "totalMaoObra": "string",
  "totalFrete": "string",
  "totalSeguro": "string",
  "totalDespesa": "string",
  "totalImportacao": "string",
  "despesaNaoTributada": "string",
  "valorAcrescimoGeral": "string",
  "valorDescontoGeral": "string",
  "baseICMS": "string",
  "valorICMS": "string",
  "totalISS": "string",
  "totalIRRF": "string",
  "totalINSS": "string",
  "valorSestSenat": "string",
  "baseSubstTributaria": "string",
  "valorICMSRetido": "string",
  "valorPIS": "string",
  "valorCOFINS": "string",
  "totalCSLL": "string",
  "baseFunRural": "string",
  "valorFunRural": "string",
  "valorICMSDesonera": "string",
  "valorPisRecupera": "string",
  "valorCofinsRecupera": "string",
  "percDesconto": "string",
  "valorDesconto": "string",
  "valorMaoObra": "string",
  "valorMercadoriaEmpr": "string",
  "valorBaseIPI": "string",
  "percIPI": "string",
  "valorIPI": "string",
  "valorIsentoIPI": "string",
  "valorOutrosIPI": "string",
  "valorRecuperadoIPI": "string",
  "percentualIcms": "string",
  "valorIsentoIcms": "string",
  "valorOutrosIcms": "string",
  "valorIcmsRecupera": "string",
  "valorIcmsRetido": "string",
  "baseSubTrib": "string",
  "baseISS": "string",
  "percentualISS": "string",
  "valorISS": "string",
  "baseIRFF": "string",
  "percentualIRFF": "string",
  "valorIRFF": "string",
  "baseINSS": "string",
  "percentualINSS": "string",
  "valorINSS": "string",
  "basePIS": "string",
  "percentualPIS": "string",
  "baseCofins": "string",
  "percentualCofins": "string",
  "valorCofins": "string",
  "baseCSLL": "string",
  "percentualCSLL": "string",
  "valorCSLL": "string"
}

Regras obrigatórias de saída:
1. Retornar somente um objeto JSON válido UTF-8.
2. Não retornar comentários, Markdown, explicações, blocos de código ou qualquer texto fora do JSON.
3. Retornar todos os atributos exatamente como no template.
4. Não criar campos extras.
5. Todos os valores devem ser strings.
6. Nunca usar null.
7. Nunca retornar números fora de strings.
8. Se não conseguir determinar um valor textual, usar "".
9. Para campos monetários, percentuais e tributários compatíveis com o documento, usar "0.00" quando o valor estiver ausente, zerado, indicado por traço ou não aplicável ao tipo documental.

Formatação:
1. Valores monetários, bases, percentuais e quantidades:
   - Usar ponto como separador decimal.
   - Não usar separador de milhar.
   - Usar duas casas decimais.
   - Remover R$, %, BRL, espaços e quebras.
   - Converter vírgula decimal para ponto.
   - Exemplos: "650.00", "2.00", "13.00".
2. Datas:
   - Usar dd/MM/yyyy.
   - Se houver data e hora, ignorar a hora.
   - Se a data for ambígua, interpretar no padrão brasileiro dd/MM/yyyy.
3. CNPJ e CPF:
   - Usar apenas números.
   - Remover pontos, barras, hífens e espaços.
4. Chave de acesso NF-e/NFC-e/CT-e/NFS-e:
   - Deve conter exatamente 44 dígitos .
   - Remover qualquer caractere não numérico.
   - Se não houver chave de 44 dígitos, usar "".

Processo interno antes do JSON final:
1. Identificar o documento fiscal principal.
2. Ignorar boletos, recibos, fichas de compensação e cobranças bancárias quando houver nota fiscal principal no mesmo arquivo.
3. Localizar título, cabeçalho, número, série, data, emitente, tomador, valores totais e tributos.
4. Classificar `tipoDocFiscal`.
5. Aplicar as regras tributárias conforme o tipo documental.
6. Validar internamente os campos críticos antes de responder.
7. Não exibir o raciocínio; retornar apenas o JSON final.

Classificação de `tipoDocFiscal`:
1. DANFE ou Nota Fiscal Eletrônica de mercadoria: "NF-E".
2. NFC-e: "NFC-E".
3. CT-e ou DACTE: "CT-E".
4. CT-e Outros Serviços: "CT-EOS".
5. Nota Fiscal de Serviços da Prefeitura de Goiânia: "NFS-EG".
6. Nota Fiscal de Serviços de outro município: "NFS-E".
7. Nota Fiscal de Serviço de Telecomunicação: "NFSTE".
8. Nota Fiscal de Energia Elétrica Eletrônica: "NF3E".
9. Nota Fiscal Fatura de Serviços de Comunicação: "NFSC".
10. DANFCom: "DANFCom".
11. Boleto, cobrança bancária, multa ou documento sem nota fiscal principal que não seja documento DETRAN: "BOLP".
12. Documentos DETRAN genéricos, licenciamento, seguro DPVAT ou documento DETRAN sem menção a IPVA ou ANTT: "BOLP-DETRAN".
13. Boleto ou documento DETRAN que mencione explicitamente IPVA ou ANTT: "BOLP-DETRAN-IPVA-ANTT".
14. Recibo isolado: "RECIBO".
15. Se for NFS-e de Goiânia (cuidado para não confundir com nomes parecidos como "Goianira") e houver indicação explícita de MEI, classificar como "NFS-E", não "NFS-EG".
16. Se houver NFS-e e boleto no mesmo arquivo, classificar pela NFS-e, não pelo boleto.

Extração de `numNota` e `serie`:
1. Usar o cabeçalho do documento fiscal principal.
2. `numNota` deve vir de rótulos como:
   - "Número da Nota Fiscal"
   - "Número da Nota"
   - "Nº da Nota"
   - "NFS-e nº"
   - "NF-e nº"
   - "Número da NFS-e"
   - "Número do Documento"
3. `serie` deve vir de rótulos como:
   - "Série"
   - "Serie"
   - "Série do Documento"
   - "Série da Nota"
   - "Série NF-e"
   - "Série NFS-e"
4. Se houver texto linearizado como "NOTA FISCAL Nº X SÉRIE Y DATA ...":
   - `numNota` = X
   - `serie` = Y
5. Se houver cabeçalho quebrado com rótulos em uma linha e valores na linha seguinte, por exemplo:
   - "NOTA FISCAL Nº    SÉRIE"
   - "000002331        001"
   então:
   - `numNota` = "000002331"
   - `serie` = "001"
6. Nunca usar chave de acesso, pedido, contrato, protocolo, NSU, lote, parcela, RPS, boleto, nosso número, linha digitável ou código de barras como `numNota`.
7. Nunca concatenar `numNota` com `serie`.
8. Nunca preencher `serie` com o número da nota.
9. `serie` normalmente possui de 1 a 4 caracteres alfanuméricos; se tiver muitos dígitos, revisar.

Regras gerais de tributos:
1. Só preencher tributos compatíveis com o tipo documental e explicitamente informados.
2. Nunca copiar valor de um tributo para outro.
3. Nunca copiar ISS para ICMS, ICMS para ISS, IPI para ICMS, PIS para COFINS ou qualquer tributo para outro campo.
4. Em NFS-e e NFS-EG, não preencher ICMS, ICMS ST ou IPI sem indicação explícita e inequívoca; nesses casos usar "0.00".
5. Em documentos de serviço, priorizar ISS/ISSQN, IRRF, INSS, PIS, COFINS e CSLL.
6. Em documentos de mercadoria, preencher ICMS, ICMS ST, IPI, PIS e COFINS somente quando explícitos.

Sinônimos de tributos:
1. ISS e ISSQN são equivalentes.
2. Para ISS/ISSQN, reconhecer:
   - "ISS"
   - "ISSQN"
   - "ISQN"
   - "Imposto Sobre Serviços"
   - "Imposto Sobre Serviços de Qualquer Natureza"
   - "Valor ISS"
   - "Valor ISSQN"
   - "Vl. ISSQN"
   - "Vl ISSQN"
   - "Total ISS"
   - "Total ISSQN"
   - "ISS Retido"
   - "ISSQN Retido"
   - "Valor ISS Retido"
   - "Valor ISSQN Retido"
3. Para base do ISS, reconhecer:
   - "Base ISS"
   - "Base ISSQN"
   - "Base de Cálculo"
   - "Base de Cálculo ISS"
   - "Base de Cálculo ISSQN"
   - "BC ISS"
   - "BC ISSQN"
4. Para alíquota do ISS, reconhecer:
   - "Alíquota"
   - "Aliquota"
   - "Alíquota ISS"
   - "Alíquota ISSQN"
   - "Alíq. ISS"
   - "Alíq. ISSQN"
   - "% ISS"
   - "% ISSQN"
5. Para retenção do ISS, reconhecer:
   - "Tipo de Retenção"
   - "Retido pelo Tomador"
   - "ISS Retido: Sim"
   - "ISSQN Retido: Sim"
   - "Retenção do ISS: Sim"
   - "Retenção do ISSQN: Sim"
   - "Valor ISS Retido"
   - "Valor ISSQN Retido"
   - "Total de Retenção"

Regra prioritária para ISS/ISSQN em NFS-e e NFS-EG:
1. Para `NFS-E` e `NFS-EG`, distinguir:
   - ISS/ISSQN apurado/calculado;
   - ISS/ISSQN retido pelo tomador;
   - ISS/ISSQN não retido;
   - ISS/ISSQN não devido, isento, imune, dispensado, não incidente ou não exigível.
2. Se houver indicação explícita de ISS/ISSQN retido pelo tomador, com valor de ISS maior que zero, preencher:
   - `baseISS` com a base de cálculo explícita do ISS/ISSQN, se houver;
   - `percentualISS` com a alíquota explícita do ISS/ISSQN, se houver;
   - `valorISS` com o valor explícito do ISS/ISSQN;
   - `totalISS` com o valor explícito do ISS/ISSQN.
3. A expressão "Tipo de Retenção: Retido pelo Tomador" indica retenção explícita do ISS/ISSQN.
4. Quando houver "Tipo de Retenção: Retido pelo Tomador", "Base de Cálculo", "Alíquota" e "Vl. ISSQN":
   - `baseISS` deve receber a base de cálculo;
   - `percentualISS` deve receber a alíquota;
   - `valorISS` deve receber o valor do ISSQN;
   - `totalISS` deve receber o valor do ISSQN.
5. Exemplo obrigatório:
   - Tipo de Retenção: Retido pelo Tomador
   - Base de Cálculo: R$650,00
   - Alíquota: 2%
   - Vl. ISSQN: R$13,00
   Resultado obrigatório:
   - `baseISS`: "650.00"
   - `percentualISS`: "2.00"
   - `valorISS`: "13.00"
   - `totalISS`: "13.00"
6. Se houver ISS/ISSQN retido maior que zero, nunca zerar `percentualISS` quando houver alíquota explícita.
7. Se houver ISS/ISSQN retido maior que zero e a alíquota explícita aparecer apenas como "Alíquota" dentro da seção de ISSQN, usar essa alíquota em `percentualISS`.
8. Nunca calcular `percentualISS` por divisão entre valor e base quando a alíquota não estiver explícita.
9. Se houver retenção explícita com valor maior que zero, mas não houver alíquota explícita, usar `percentualISS`: "0.00".

Regra para ISS/ISSQN não retido, não devido ou não incidente:
1. Se houver indicação explícita de que o ISS/ISSQN não foi retido, não é devido, não incide, é isento, imune, dispensado, não tributável ou não exigível, preencher:
   - `baseISS`: "0.00"
   - `percentualISS`: "0.00"
   - `valorISS`: "0.00"
   - `totalISS`: "0.00"
2. São indicações explícitas de não retenção ou não exigibilidade:
   - "ISSQN Retido: Não"
   - "ISS Retido: Não"
   - "Retenção do ISSQN: Não"
   - "Retenção do ISS: Não"
   - "ISSQN Não Retido"
   - "ISS Não Retido"
   - "ISS Não Devido"
   - "ISSQN Não Devido"
   - "ISS Não Incide"
   - "ISSQN Não Incide"
   - "ISS Isento"
   - "ISSQN Isento"
   - "ISS Imune"
   - "ISSQN Imune"
   - "ISS Dispensado"
   - "ISSQN Dispensado"
   - "ISS Não Tributável"
   - "ISSQN Não Tributável"
   - "ISS Não Exigível"
   - "ISSQN Não Exigível"
   - campo de ISS retido com valor "0,00", "0.00", "-", vazio, "Não", "Nao", "N" ou equivalente.
3. Quando houver não retenção explícita, não usar base, alíquota, valor ou total de ISS apurado para preencher `baseISS`, `percentualISS`, `valorISS` ou `totalISS`.
4. Quando houver conflito entre ISS apurado maior que zero e ISS retido igual a zero ou "Não", prevalece a não retenção:
   - `baseISS`: "0.00"
   - `percentualISS`: "0.00"
   - `valorISS`: "0.00"
   - `totalISS`: "0.00"

Ordem de precedência para ISS/ISSQN em NFS-e e NFS-EG:
1. Primeiro, verificar se há retenção explícita positiva:
   - "Retido pelo Tomador";
   - "ISS Retido: Sim";
   - "ISSQN Retido: Sim";
   - valor de ISS/ISSQN retido maior que zero;
   - total de retenção contendo ISS/ISSQN maior que zero.
   Se sim, preencher base, percentual, valor e total conforme os campos explícitos.
2. Segundo, verificar se há não retenção, não incidência, isenção, imunidade, dispensa ou não exigibilidade.
   Se sim, zerar `baseISS`, `percentualISS`, `valorISS` e `totalISS`.
3. Terceiro, se não houver nenhuma informação sobre retenção ou não retenção, usar ISS/ISSQN apurado explícito:
   - `baseISS` com base explícita;
   - `percentualISS` com alíquota explícita;
   - `valorISS` com valor explícito;
   - `totalISS` com valor explícito.
4. Nunca tratar "Retido pelo Tomador" como ausência de retenção.
5. Nunca zerar `percentualISS` quando houver retenção explícita positiva e alíquota explícita.

Outros tributos retidos:
1. Em seções de retenção, mapear:
   - PIS para `valorPIS`;
   - COFINS para `valorCOFINS` e `valorCofins`;
   - INSS para `totalINSS` e `valorINSS`;
   - IRRF ou IRFF para `totalIRRF` e `valorIRFF`;
   - CSLL para `totalCSLL` e `valorCSLL`.
2. Se houver base e percentual explícitos, preencher também:
   - `basePIS`, `percentualPIS`;
   - `baseCofins`, `percentualCofins`;
   - `baseINSS`, `percentualINSS`;
   - `baseIRFF`, `percentualIRFF`;
   - `baseCSLL`, `percentualCSLL`.
3. Não inferir retenção a partir de tributo apenas apurado se houver indicação de não retenção.

Valor total do documento:
1. Para `valorTotalDocumento`, usar o valor total bruto do documento fiscal principal.
2. Para NFS-e, preferir:
   - "Valor Total dos Serviços";
   - "Valor do Serviço";
   - "Valor Total da Nota";
   - "Vl. do Serviço".
3. Não usar valor líquido se houver valor bruto explícito.
4. Atribuir o mesmo valor de `valorTotalDocumento` a `valorMercadoria`.
5. Não usar valor de boleto se a nota fiscal principal tiver valor total explícito.

Campos monetários e tributários com zero padrão:
Quando compatíveis com o tipo documental e sem valor explícito, preencher com "0.00":
- totalMaoObra
- totalFrete
- totalSeguro
- totalDespesa
- totalImportacao
- despesaNaoTributada
- valorAcrescimoGeral
- valorDescontoGeral
- baseICMS
- valorICMS
- valorIPI
- totalISS
- totalIRRF
- totalINSS
- valorSestSenat
- baseSubstTributaria
- valorICMSRetido
- valorPIS
- valorCOFINS
- totalCSLL
- baseFunRural
- valorFunRural
- valorICMSDesonera
- valorPisRecupera
- valorCofinsRecupera
- percDesconto
- valorDesconto
- valorMaoObra
- valorMercadoriaEmpr
- valorBaseIPI
- percIPI
- valorIsentoIPI
- valorOutrosIPI
- valorRecuperadoIPI
- percentualIcms
- valorIsentoIcms
- valorOutrosIcms
- valorIcmsRecupera
- valorIcmsRetido
- baseSubTrib
- baseISS
- percentualISS
- valorISS
- baseIRFF
- percentualIRFF
- valorIRFF
- baseINSS
- percentualINSS
- valorINSS
- basePIS
- percentualPIS
- valorPIS
- baseCofins
- percentualCofins
- valorCofins
- baseCSLL
- percentualCSLL
- valorCSLL

Validações finais:
1. `valorTotalDocumento` e `valorMercadoria` devem ser iguais conforme regra de negócio.
2. Para NFS-e e NFS-EG com ISS retido positivo:
   - `percentualISS` deve refletir a alíquota explícita;
   - `valorISS` e `totalISS` devem refletir o ISS/ISSQN explícito;
   - `baseISS` deve refletir a base explícita, se houver.
3. Para NFS-e e NFS-EG com "Tipo de Retenção: Retido pelo Tomador":
   - não preencher `percentualISS` com "0.00" se houver alíquota explícita.
4. Para NFS-e e NFS-EG com "ISSQN Retido: Não" ou retenção de ISS igual a zero:
   - `baseISS`, `percentualISS`, `valorISS` e `totalISS` devem ser "0.00".
5. Nunca inventar valores.
6. Nunca calcular percentuais ausentes.
7. Em caso de conflito entre regra geral e regra específica de ISS/ISSQN, aplicar a regra específica de ISS/ISSQN.
8. Retornar somente o JSON final, sem explicações.
</prompt>

Observação sobre chave de acesso:
- O prompt principal acima considera somente chave de acesso com 44 dígitos.
- Notas de serviço podem possuir chave/código de acesso com 50 caracteres, mas esse padrão não é capturado pelo prompt principal nem pelo segundo prompt de redundância.
- Se for necessário capturar chave/código de acesso de NFS-e com 50 caracteres, será preciso criar uma regra específica futura para esse padrão.

### 8.3) Validação pós-extração
- Conciliar soma dos itens com total da nota (tolerância configurável).
- Verificar se `numNota`/`serie` não estão vazios.
- Se divergência, registrar erro técnico e encaminhar para validação humana.
- Se a IA multimodal não conseguir extrair campos críticos, o fluxo deve sinalizar pendência e bloquear envio automático ao ERP.

## 9) Implementação no Power Automate Cloud (passo a passo)
Usar os templates já criados em ações **Compor**.

1. `Inicializar variável` `varResultado` (Objeto) com saída de **Compor - template raiz**.
2. `Inicializar variável` `varItensReceb` (Array) = `[]`.
3. `Inicializar variável` `varParcelas` (Array) = `[]`.
4. Declarar variáveis auxiliares (mesmo vazias inicialmente):
- `Inicializar variável` `varAcao` (String) = `''`
- `Inicializar variável` `varTipoDocFiscal` (String) = `''`
- `Inicializar variável` `cnpjEmitente` (String) = `null`
- `Inicializar variável` `cnpjCpfTomador` (String) = `null`
- `Inicializar variável` `resposta_ia_extra` (Objeto) = `{}`
- `Inicializar variável` `dados_extra_ia` (Objeto) = `{}`
- `Inicializar variável` `DeveLancar` (Boolean) = `true`
5. Popular campos de cabeçalho (`filial`, `agente`, `tipoPreco`, `condPagto`, etc.) com `setProperty(...)` em cadeia (sem auto-referência de variável).
6. Definir `numNota`, `serie`, valores fiscais e tributos:
- de IA multimodal (PDF fiscal) e/ou API externa já estruturada;
- se não houver, aplicar defaults de negócio.
7. `Aplicar a cada` em `Dados do pedido.data`:
- Criar objeto item a partir de **Compor - template itensReceb**.
- Preencher campos do item com `setProperty`.
- Criar `centrosCusto` a partir de **Compor - template itensReceb.centrosCusto**.
- Criar `projetos` a partir de **Compor - template itensReceb.centrosCusto.projetos**.
- Criar `pedidos` a partir de **Compor - itensReceb.pedidos**.
- Atribuir arrays aninhados no item.
- `Append to array variable` em `varItensReceb`.
8. Após loop, calcular agregados:
- `valorMercadoria` = soma de `varItensReceb[*].valorMercadoria`
- `totalNota` conforme fórmula de negócio.
9. Montar parcela(s) com **Compor - template parcelas**:
- `dataVencimento` calculada por condição de pagamento.
- `valorParcela` conforme rateio das parcelas.
10. Atribuir `itensReceb` e `parcelas` no `varResultado`.
11. Serializar e enviar para integração CLN/ERP.

### 9.1) Implementação detalhada do passo 5 (até concluir `Compor - Resultado passo 5`)

#### 9.1.1) Por que usar `Compor` antes de `Definir variável`
No Power Automate Cloud, não é permitido atualizar variável com auto-referência (`A = A + B` / `varResultado = setProperty(varResultado, ...)`) na mesma expressão.
Por isso:
- montar o objeto em uma ação **Compor**
- depois atribuir o resultado à variável `varResultado`

#### 9.1.2) Ações e expressões
1. Ação: `Compor - DP item 0`  
Expressão:

```powerautomate
first(outputs('Obter_dados_do_pedido')?['body']?['data'])
```

2. Ação: `Compor - Resultado passo 5`  
Expressão:

```powerautomate
setProperty(
  setProperty(
    setProperty(
      setProperty(
        setProperty(
          setProperty(
            setProperty(
              setProperty(
                setProperty(
                  setProperty(
                    setProperty(
                      setProperty(
                        setProperty(
                          setProperty(
                            setProperty(
                              outputs('Compor_-_template_raiz'),
                              'filial',
                              string(coalesce(outputs('Compor_-_Obter_pedido')?['FIL_IN_CODIGO'], outputs('Compor_-_DP_item_0')?['FILIAL']))
                            ),
                            'agente',
                            string(coalesce(outputs('Compor_-_Obter_pedido')?['AGN_IN_CODIGO'], outputs('Compor_-_DP_item_0')?['AGENTE']))
                          ),
                          'tipoPreco',
                          string(coalesce(outputs('Compor_-_DP_item_0')?['TIPO_PRECO'], ''))
                        ),
                        'condPagto',
                        string(coalesce(outputs('Compor_-_Obter_pedido')?['COND_ST_CODIGO'], outputs('Compor_-_DP_item_0')?['COND_PAGTO'], ''))
                      ),
                      'centroCustoReduzido',
                      string(coalesce(outputs('Compor_-_DP_item_0')?['CC_PADRAO'], ''))
                    ),
                    'projetoReduzido',
                    string(coalesce(outputs('Compor_-_DP_item_0')?['PROJ_PADRAO'], ''))
                  ),
                  'dataDocumento',
                  string(coalesce(outputs('Compor_-_Obter_pedido')?['DATA_ENTREGA'], outputs('Compor_-_DP_item_0')?['DATA_ENTREGA'], '<dado externo>'))
                ),
                'dataMovimento',
                string(coalesce(outputs('Compor_-_Obter_pedido')?['DATA_ENTREGA'], outputs('Compor_-_DP_item_0')?['DATA_ENTREGA'], '<dado externo>'))
              ),
              'operacao',
              'I'
            ),
            'acao',
            variables('varAcao')
          ),
          'tipoDocFiscal',
          variables('varTipoDocFiscal')
        ),
        'contasPagarTipoDoc',
        '<dado externo>'
      ),
      'numNota',
      '<dado externo>'
    ),
    'serie',
    '<dado externo>'
  ),
  'chaveAcesso',
  ''
)
```

3. Ação: `Definir variável` (`varResultado`)  
Valor:

```powerautomate
outputs('Compor_-_Resultado_passo_5')
```

#### 9.1.3) Nomes das ações (atenção)
- O nome visível da ação pode virar nome interno com `_` nas expressões.
- Se houver erro de referência, abrir `Peek code` da ação e copiar o nome interno exato.
- Neste projeto, as fontes de entrada são:
- OP: `Compor - Obter pedido`
- DP: `Obter dados do pedido` (dados em `outputs('Obter_dados_do_pedido')?['body']?['data']`)

### 9.2) Implementação detalhada do passo 6 (atualização com IA + ação)

#### 9.2.1) Pré-condições
- A variável `resposta_ia` já contém o JSON de cabeçalho extraído pelo LLM.
- A variável `tabela_depara_tipodoc` está inicializada com o conteúdo abaixo:

```json
{
  "NF-E": [
    {
      "contasPagarTipoDoc": "NFC",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "NFSTE": [
    {
      "contasPagarTipoDoc": "NFSTE",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "NF3E": [
    {
      "contasPagarTipoDoc": "NFFEE",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "CT-E": [
    {
      "contasPagarTipoDoc": "CF",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "CT-EOS": [
    {
      "contasPagarTipoDoc": "CF",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "NFS-EG": [
    {
      "contasPagarTipoDoc": "NFS",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "NFS-E": [
    {
      "contasPagarTipoDoc": "NFS",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "NFF": [
    {
      "contasPagarTipoDoc": "NFF",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "BOLP": [
    {
      "contasPagarTipoDoc": "BOLP",
      "acao_vista": 771,
      "acao_prazo": 768
    }
  ],
  "BOLP-DETRAN": [
    {
      "contasPagarTipoDoc": "BOLP",
      "acao_vista": 770,
      "acao_prazo": 770
    }
  ],
  "BOLP-DETRAN-IPVA-ANTT": [
    {
      "contasPagarTipoDoc": "BOLP",
      "acao_vista": 768,
      "acao_prazo": 771
    }
  ],
  "RECIBO": [
    {
      "contasPagarTipoDoc": "REC",
      "acao_vista": 771,
      "acao_prazo": 768
    }
  ],
  "NFSC": [
    {
      "contasPagarTipoDoc": "NFF",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ],
  "DANFCom": [
    {
      "contasPagarTipoDoc": "NFF",
      "acao_vista": 295,
      "acao_prazo": 82
    }
  ]
}
```

- A correção de `totalISS` por `valorISS` em `resposta_ia` é executada imediatamente após `Definir variável - resposta ia`.
- A correção de `numNota` em `resposta_ia` é executada depois da correção de `totalISS` e antes do De x Para.
- A ação `Compor - Executar De x Para tabela depara tipoDocFiscal` é executada na sequência, após a normalização inicial de `resposta_ia`.
- A ação `Compor - Calcular acao (a vista e prazo)` é executada na sequência e retorna `acao` e `contasPagarTipoDoc`.
- `varResultado` já foi preenchida no passo 5.
- No escopo de `Aplicar a cada - pedidos`, logo após `Definir variável - reset de varJSONFinal`, executar:
  - `Definir variável - reset de cnpjEmitente` com valor `null`
  - `Definir variável - reset de cnpjCpfTomador` com valor `null`

#### 9.2.2) Ações e expressões
0.1. Ação: `Compor - resposta_ia com totalISS corrigido por valorISS`  
Posicionamento:
- Inserir imediatamente após `Definir variável - resposta ia`.
- Executar antes de `Compor - resposta_ia com regra numNota por pedido`.

Objetivo:
- Corrigir casos em que o LLM identifica ISS retido em `valorISS`, mas deixa `totalISS` como `"0.00"`.
- Essa correção garante que o objeto raiz receba `totalISS` correto e que `totalISSDevido`, calculado depois a partir de `totalISS`, também fique correto.

Expressão:

```powerautomate
if(
  and(
    greater(
      float(
        concat(
          '0',
          replace(
            trim(string(coalesce(variables('resposta_ia')?['valorISS'], '0'))),
            ',',
            '.'
          )
        )
      ),
      0
    ),
    lessOrEquals(
      float(
        concat(
          '0',
          replace(
            trim(string(coalesce(variables('resposta_ia')?['totalISS'], '0'))),
            ',',
            '.'
          )
        )
      ),
      0
    )
  ),
  setProperty(
    variables('resposta_ia'),
    'totalISS',
    string(coalesce(variables('resposta_ia')?['valorISS'], '0.00'))
  ),
  variables('resposta_ia')
)
```

0.2. Ação: `Definir variável - resposta_ia com totalISS corrigido por valorISS`  
Variável: `resposta_ia`  
Valor:

```powerautomate
outputs('Compor_-_resposta_ia_com_totalISS_corrigido_por_valorISS')
```

Observação:
- Exemplo corrigido: se `resposta_ia.valorISS = "11.70"` e `resposta_ia.totalISS = "0.00"`, a ação redefine `resposta_ia.totalISS` para `"11.70"`.
- Se `valorISS` estiver zerado, vazio ou ausente, nada é alterado.
- Se `totalISS` já estiver maior que zero, nada é alterado.

1. Ação: `Compor - resposta_ia com regra numNota por pedido`  
Expressão:

```powerautomate
setProperty(
  variables('resposta_ia'),
  'numNota',
  if(
    equals(trim(string(coalesce(variables('resposta_ia')?['numNota'], ''))), ''),
    string(coalesce(outputs('Compor_-_Obter_pedido')?['PDC_IN_CODIGO'], '')),
    string(coalesce(variables('resposta_ia')?['numNota'], ''))
  )
)
```

2. Ação: `Definir variável - resposta_ia (regra numNota por pedido)`  
Variável: `resposta_ia`  
Valor:

```powerautomate
outputs('Compor_-_resposta_ia_com_regra_numNota_por_pedido')
```

3. Ação: `Compor - resposta_ia com regras de percentuais por valor e base`  
Expressão:

```powerautomate
setProperty(
  setProperty(
    setProperty(
      setProperty(
        setProperty(
          setProperty(
            setProperty(
              setProperty(
                variables('resposta_ia'),
                'percentualISS',
                if(
                  equals(trim(string(coalesce(variables('resposta_ia')?['percentualISS'], ''))), ''),
                  if(
                    greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseISS'], '0')), ',', '.'))), 0),
                    formatNumber(
                      div(
                        mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorISS'], '0')), ',', '.'))), 100),
                        float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseISS'], '0')), ',', '.')))
                      ),
                      '0.00',
                      'en-US'
                    ),
                    '0.00'
                  ),
                  string(variables('resposta_ia')?['percentualISS'])
                )
              ),
              'percentualIRFF',
              if(
                equals(trim(string(coalesce(variables('resposta_ia')?['percentualIRFF'], ''))), ''),
                if(
                  greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseIRFF'], '0')), ',', '.'))), 0),
                  formatNumber(
                    div(
                      mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorIRFF'], '0')), ',', '.'))), 100),
                      float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseIRFF'], '0')), ',', '.')))
                    ),
                    '0.00',
                    'en-US'
                  ),
                  '0.00'
                ),
                string(variables('resposta_ia')?['percentualIRFF'])
              )
            ),
            'percentualINSS',
            if(
              equals(trim(string(coalesce(variables('resposta_ia')?['percentualINSS'], ''))), ''),
              if(
                greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseINSS'], '0')), ',', '.'))), 0),
                formatNumber(
                  div(
                    mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorINSS'], '0')), ',', '.'))), 100),
                    float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseINSS'], '0')), ',', '.')))
                  ),
                  '0.00',
                  'en-US'
                ),
                '0.00'
              ),
              string(variables('resposta_ia')?['percentualINSS'])
            )
          ),
          'percentualPIS',
          if(
            equals(trim(string(coalesce(variables('resposta_ia')?['percentualPIS'], ''))), ''),
            if(
              greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['basePIS'], '0')), ',', '.'))), 0),
              formatNumber(
                div(
                  mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorPIS'], '0')), ',', '.'))), 100),
                  float(concat('0', replace(string(coalesce(variables('resposta_ia')?['basePIS'], '0')), ',', '.')))
                ),
                '0.00',
                'en-US'
              ),
              '0.00'
            ),
            string(variables('resposta_ia')?['percentualPIS'])
          )
        ),
        'percentualCofins',
        if(
          equals(trim(string(coalesce(variables('resposta_ia')?['percentualCofins'], ''))), ''),
          if(
            greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseCofins'], '0')), ',', '.'))), 0),
            formatNumber(
              div(
                mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorCofins'], '0')), ',', '.'))), 100),
                float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseCofins'], '0')), ',', '.')))
              ),
              '0.00',
              'en-US'
            ),
            '0.00'
          ),
          string(variables('resposta_ia')?['percentualCofins'])
        )
      ),
      'percentualCSLL',
      if(
        equals(trim(string(coalesce(variables('resposta_ia')?['percentualCSLL'], ''))), ''),
        if(
          greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseCSLL'], '0')), ',', '.'))), 0),
          formatNumber(
            div(
              mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorCSLL'], '0')), ',', '.'))), 100),
              float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseCSLL'], '0')), ',', '.')))
            ),
            '0.00',
            'en-US'
          ),
          '0.00'
        ),
        string(variables('resposta_ia')?['percentualCSLL'])
      )
    ),
    'percentualIcms',
    if(
      equals(trim(string(coalesce(variables('resposta_ia')?['percentualIcms'], ''))), ''),
      if(
        greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseICMS'], '0')), ',', '.'))), 0),
        formatNumber(
          div(
            mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorICMS'], '0')), ',', '.'))), 100),
            float(concat('0', replace(string(coalesce(variables('resposta_ia')?['baseICMS'], '0')), ',', '.')))
          ),
          '0.00',
          'en-US'
        ),
        '0.00'
      ),
      string(variables('resposta_ia')?['percentualIcms'])
    )
  ),
  'percIPI',
  if(
    equals(trim(string(coalesce(variables('resposta_ia')?['percIPI'], ''))), ''),
    if(
      greater(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorBaseIPI'], '0')), ',', '.'))), 0),
      formatNumber(
        div(
          mul(float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorIPI'], '0')), ',', '.'))), 100),
          float(concat('0', replace(string(coalesce(variables('resposta_ia')?['valorBaseIPI'], '0')), ',', '.')))
        ),
        '0.00',
        'en-US'
      ),
      '0.00'
    ),
    string(variables('resposta_ia')?['percIPI'])
  )
)
```

4. Ação: `Definir variável - resposta_ia (regras de percentuais por valor e base)`  
Variável: `resposta_ia`  
Valor:

```powerautomate
outputs('Compor_-_resposta_ia_com_regras_de_percentuais_por_valor_e_base')
```

#### 9.2.3) Segunda rodada de extração IA para dados extras do PDF
Após a ação `Definir variável - resposta_ia`, executar uma segunda rodada de envio do mesmo PDF para um LLM especializado na captura de dados extras.

1. Ação: `Compor - prompt dados extras`
```text
Objetivo:
Extrair informações específicas de DOCUMENTOS FISCAIS BRASILEIROS a partir de imagem, PDF ou texto, retornando exclusivamente um JSON válido. Esta chamada é uma camada de redundância e validação crítica para:
1. Extrair a chave de acesso, quando existir.
2. Identificar de forma inequívoca se o ISS/ISSQN foi retido pelo tomador.

Atenção:
Esta chamada NÃO deve extrair todos os campos fiscais do documento. Ela deve focar apenas nos campos do template abaixo.

Template obrigatório:
{
  "chaveAcesso": "string",
  "issRetido": false,
  "numNota": "string"
}

Regras obrigatórias de saída:
1. Retornar somente um objeto JSON válido UTF-8.
2. Não retornar comentários, Markdown, explicações, blocos de código ou qualquer texto fora do JSON.
3. Retornar todos os atributos exatamente como no template.
4. Não criar campos extras.
5. O campo `chaveAcesso` deve ser string.
6. O campo `issRetido` deve ser booleano real JSON: true ou false.
7. Nunca usar null.
8. Se não conseguir determinar a chave de acesso, usar "".
9. Se não conseguir determinar se o ISS/ISSQN é retido, usar false.
10. Nunca inferir retenção de ISS apenas porque existe Base de Cálculo, Alíquota, Valor do ISSQN, Total do ISSQN ou ISSQN apurado.

Extração de `chaveAcesso`:
1. Procurar chave de acesso de NF-e, NFC-e, CT-e, CT-e OS, NFS-e, DANFE, DANFCom ou documento equivalente.
2. A chave deve conter exatamente 44 dígitos.
3. Remover qualquer caractere não numérico.
4. Se houver número com 44 dígitos claramente identificado como chave de acesso, preencher `chaveAcesso`.
5. Se não houver chave de 44 dígitos, usar "".
6. Nunca usar número da nota, número do documento, número do boleto, nosso número, linha digitável, código de barras bancário, número do RPS, protocolo, lote, pedido ou parcela como chave de acesso.

Extração de `numNota`:
1. Procure o número da nota tentando se adaptar ao layout do documento, sabendo que o dado pode aparecer à direita ou abaixo do rótulo que indique número da nota.

Definição crítica de `issRetido`:
O campo `issRetido` deve indicar exclusivamente se o ISS/ISSQN foi RETIDO pelo tomador ou por terceiro responsável.

Retornar `"issRetido": true` somente quando houver indicação explícita e inequívoca de retenção positiva do ISS/ISSQN, como:
1. "ISS Retido: Sim"
2. "ISSQN Retido: Sim"
3. "Retenção do ISS: Sim"
4. "Retenção do ISSQN: Sim"
5. "Tipo de Retenção: Retido pelo Tomador"
6. "Retido pelo Tomador"
7. "ISS Retido pelo Tomador"
8. "ISSQN Retido pelo Tomador"
9. "Valor ISS Retido" maior que zero
10. "Valor ISSQN Retido" maior que zero
11. "ISS Retido" com valor monetário maior que zero
12. "ISSQN Retido" com valor monetário maior que zero
13. Seção de retenções indicando ISS/ISSQN com valor maior que zero

Retornar `"issRetido": false` quando houver qualquer indicação explícita de não retenção, como:
1. "ISS Retido: Não"
2. "ISSQN Retido: Não"
3. "ISS Retido: Nao"
4. "ISSQN Retido: Nao"
5. "ISS Retido: N"
6. "ISSQN Retido: N"
7. "Retenção do ISS: Não"
8. "Retenção do ISSQN: Não"
9. "ISS Não Retido"
10. "ISSQN Não Retido"
11. "Valor ISS Retido: R$ 0,00"
12. "Valor ISSQN Retido: R$ 0,00"
13. "ISS Retido" com valor "0,00", "0.00", "-", vazio, "Não", "Nao" ou "N"
14. "ISSQN Retido" com valor "0,00", "0.00", "-", vazio, "Não", "Nao" ou "N"
15. Seção de retenções com ISS/ISSQN igual a zero
16. Documento com ISS/ISSQN apurado, mas com campo explícito "ISSQN Retido: Não"

Regra de precedência absoluta para `issRetido`:
1. Primeiro, procure expressões explícitas de retenção positiva.
2. Depois, procure expressões explícitas de não retenção.
3. Se existir conflito entre ISS/ISSQN apurado maior que zero e campo "ISSQN Retido: Não", prevalece "ISSQN Retido: Não".
4. Se existir Base de Cálculo, Alíquota e Valor do ISSQN, mas também existir "ISSQN Retido: Não", retornar `"issRetido": false`.
5. A existência de Base de Cálculo, Alíquota, Valor do ISSQN, Total do ISSQN ou imposto apurado NÃO significa retenção.
6. ISS/ISSQN apurado é diferente de ISS/ISSQN retido.
7. Só retornar true quando o documento disser que o ISS/ISSQN foi retido, ou quando houver campo de ISS/ISSQN retido com valor maior que zero.
8. Se o documento disser explicitamente "ISSQN Retido: Não", retornar false mesmo que existam valores de Base de Cálculo, Alíquota e Valor do ISSQN.

Caso típico que deve retornar false:
Se o documento apresentar algo como:
- Base de Cálculo: R$ 3.832,40
- Alíquota: 2%
- Total do ISSQN: R$ 76,65
- ISSQN Retido: Não

Então o JSON obrigatório é:
{
  "chaveAcesso": "",
  "issRetido": false,
  "numNota": ""
}

Motivo operacional desta regra:
Em NFS-e, é comum existir ISS/ISSQN calculado ou apurado na nota, com base, alíquota e valor. Isso não significa que o imposto foi retido. A retenção só existe quando o documento informa explicitamente retenção pelo tomador/responsável ou quando há valor positivo em campo de ISS/ISSQN retido.

Processo interno antes do JSON final:
1. Identificar se há documento fiscal principal.
2. Ignorar boleto, recibo, ficha de compensação, cobrança bancária e linha digitável quando houver nota fiscal principal no mesmo arquivo.
3. Procurar chave de acesso somente no documento fiscal principal.
4. Procurar especificamente campos e expressões de ISS/ISSQN retido ou não retido.
5. Diferenciar ISS/ISSQN apurado de ISS/ISSQN retido.
6. Aplicar a precedência:
   - retenção positiva explícita => `issRetido`: true
   - não retenção explícita => `issRetido`: false
   - apenas ISS apurado, sem retenção explícita => `issRetido`: false
   - ausência de informação sobre ISS => `issRetido`: false
7. Validar que `issRetido` é booleano JSON real, não string.
8. Não exibir raciocínio.
9. Retornar somente o JSON final.

Validações finais:
1. `chaveAcesso` deve ser string.
2. `issRetido` deve ser booleano real JSON.
3. Nunca retornar `"issRetido": "true"` ou `"issRetido": "false"`.
4. Nunca retornar null.
5. Nunca criar campos extras.
6. Se houver "ISSQN Retido: Não", o resultado final obrigatório é `"issRetido": false`.
7. Se houver "ISS Retido: Não", o resultado final obrigatório é `"issRetido": false`.
8. Se houver apenas base, alíquota e valor de ISSQN, sem indicação de retenção positiva, o resultado final obrigatório é `"issRetido": false`.
9. Retornar somente o JSON final, sem explicações.
```

2. Ação: chamar o LLM multimodal especializado com o mesmo PDF e o prompt acima.

3. Ação: `Definir variável - resposta_ia_extra` com o retorno JSON da segunda chamada.

4. Retificar `resposta_ia` com base em `resposta_ia_extra.issRetido`.

Objetivo:
- Usar a segunda chamada como fonte redundante e mais confiável para determinar se o ISS/ISSQN foi retido.
- Se `resposta_ia_extra.issRetido = true`, não alterar `resposta_ia`.
- Se `resposta_ia_extra.issRetido = false` e `resposta_ia.valorISS` ou `resposta_ia.totalISS` estiverem maiores que zero, retificar `resposta_ia.valorISS` e `resposta_ia.totalISS` para `"0.00"`.
- Manter `baseISS` e `percentualISS`, pois podem representar ISS/ISSQN apurado, mesmo quando não há retenção.
- Ao final deste bloco, `resposta_ia` deve estar consistente com `resposta_ia_extra.issRetido`.

4.1. Ação: `Compor - resposta_ia com numNota da redundancia`  
Código:
```powerautomate
setProperty(
  variables('resposta_ia'),
  'numNota',
  if(
    empty(trim(string(coalesce(variables('resposta_ia')?['numNota'], '')))),
    string(coalesce(variables('resposta_ia_extra')?['numNota'], '')),
    string(variables('resposta_ia')?['numNota'])
  )
)
```

4.2. Ação: `Definir variável - resposta_ia com numNota da redundancia`  
Variável: `resposta_ia`  
Valor:
```powerautomate
outputs('Compor_-_resposta_ia_com_numNota_da_redundancia')
```

Observação:
- Esta ação faz o equivalente a um `coalesce` entre `resposta_ia.numNota` e `resposta_ia_extra.numNota`, considerando string vazia, string com espaços e `null` como ausência de valor.
- Se `resposta_ia.numNota` já estiver preenchido, ele é mantido.
- Se `resposta_ia.numNota` estiver vazio, usa `resposta_ia_extra.numNota`.

4.3. Ação: `Compor - resposta_ia_extra issRetido booleano`  
Código:
```powerautomate
equals(
  variables('resposta_ia_extra')?['issRetido'],
  true
)
```

4.4. Ação: `Compor - resposta_ia valorISS decimal`  
Código:
```powerautomate
float(
  concat(
    '0',
    replace(
      trim(string(coalesce(variables('resposta_ia')?['valorISS'], '0'))),
      ',',
      '.'
    )
  )
)
```

4.5. Ação: `Compor - resposta_ia totalISS decimal`  
Código:
```powerautomate
float(
  concat(
    '0',
    replace(
      trim(string(coalesce(variables('resposta_ia')?['totalISS'], '0'))),
      ',',
      '.'
    )
  )
)
```

4.6. Ação: `Compor - resposta_ia precisa retificar ISS por redundancia`  
Código:
```powerautomate
and(
  equals(outputs('Compor_-_resposta_ia_extra_issRetido_booleano'), false),
  or(
    greater(outputs('Compor_-_resposta_ia_valorISS_decimal'), 0),
    greater(outputs('Compor_-_resposta_ia_totalISS_decimal'), 0)
  )
)
```

4.7. Ação: `Condição - retificar resposta_ia ISS nao retido`  
Condição:
```powerautomate
outputs('Compor_-_resposta_ia_precisa_retificar_ISS_por_redundancia')
```

Comparação:
```text
é igual a true
```

No ramo **Verdadeiro**, executar as ações 4.7.1 e 4.7.2.

4.7.1. Ação: `Compor - resposta_ia com ISS nao retido retificado`  
Código:
```powerautomate
setProperty(
  setProperty(
    variables('resposta_ia'),
    'valorISS',
    '0.00'
  ),
  'totalISS',
  '0.00'
)
```

4.7.2. Ação: `Definir variável - resposta_ia com ISS nao retido retificado`  
Variável: `resposta_ia`  
Valor:
```powerautomate
outputs('Compor_-_resposta_ia_com_ISS_nao_retido_retificado')
```

No ramo **Falso**, não executar nenhuma ação.

Observações:
- Se `resposta_ia` já estiver com `valorISS = "0.00"` e `totalISS = "0.00"`, o bloco não altera nada.
- Se `resposta_ia_extra.issRetido = true`, o bloco não altera nada, mesmo que `valorISS` ou `totalISS` estejam preenchidos.
- Esta retificação deve ocorrer antes de `Compor - cnpjEmitente`, antes de `Compor - Resultado passo 6` e antes da montagem dos itens, para que os campos corrigidos sejam propagados.

5. Capturar os dados da variável `resposta_ia_extra`.

6. Ação: `Compor - atualizar dados_extra_ia`  
Código:
```powerautomate
setProperty(
  setProperty(
    variables('dados_extra_ia'),
    'chaveAcesso',
    coalesce(
      if(
        equals(trim(string(coalesce(variables('resposta_ia_extra')?['chaveAcesso'], ''))), ''),
        null,
        string(variables('resposta_ia_extra')?['chaveAcesso'])
      ),
      string(coalesce(variables('dados_extra_ia')?['chaveAcesso'], ''))
    )
  ),
  'issRetido',
  if(
    equals(variables('resposta_ia_extra')?['issRetido'], true),
    true,
    bool(coalesce(variables('dados_extra_ia')?['issRetido'], false))
  )
)
```

7. Ação: `Definir variável - atualizar dados_extra_ia`  
Variável: `dados_extra_ia`  
Valor:
```powerautomate
outputs('Compor_-_atualizar_dados_extra_ia')
```

Regra da atualização em loop:
- `dados_extra_ia` inicia como `{}`.
- Se `resposta_ia_extra.chaveAcesso` vier preenchido, atualizar com o valor mais recente.
- Se `resposta_ia_extra.chaveAcesso` vier vazio, manter o valor atual já armazenado em `dados_extra_ia.chaveAcesso`.
- Se qualquer chamada retornar `resposta_ia_extra.issRetido = true`, manter `dados_extra_ia.issRetido = true`.
- Se `resposta_ia_extra.issRetido` vier ausente, inválido ou false, manter o valor atual de `dados_extra_ia.issRetido`; o default operacional é false.
- `issRetido` deve permanecer booleano real no objeto, não string.

#### 9.2.4) Consolidação de `cnpjEmitente` e `cnpjCpfTomador`
Após concluir a segunda rodada de extração, a retificação de ISS em `resposta_ia` e a ação `Definir variável - atualizar dados_extra_ia`, executar:

1. Ação: `Compor - cnpjEmitente`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjEmitente')))),
  string(coalesce(variables('resposta_ia')?['cnpjEmitente'], '')),
  variables('cnpjEmitente')
)
```

2. Ação: `Compor - cnpjCpfTomador`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjCpfTomador')))),
  string(coalesce(variables('resposta_ia')?['cnpjCpfTomador'], '')),
  variables('cnpjCpfTomador')
)
```

3. Ação: `Definir variável - cnpjEmitente`  
Código:
```powerautomate
outputs('Compor_-_cnpjEmitente')
```

4. Ação: `Definir variável - cnpjCpfTomador`  
Código:
```powerautomate
outputs('Compor_-_cnpjCpfTomador')
```

5. Ação: `Compor - Executar De x Para tabela depara tipoDocFiscal`  
Expressão:

```powerautomate
first(variables('tabela_depara_tipodoc')?[ variables('resposta_ia')?['tipoDocFiscal'] ])
```

6. Ação: `Compor - Calcular acao (a vista e prazo)`  
Código:

```json
{
  "contasPagarTipoDoc": "{outputs('Compor_-_Executar_De_x_Para_tabela_depara_tipoDocFiscal')['contasPagarTipoDoc']}",
  "acao": "{if(or(equals(variables('dados_pedido')['condPagto'], 'ADIANT'), equals(variables('dados_pedido')['condPagto'], 'TESOURARIA'), equals(variables('dados_pedido')['condPagto'], 'À VISTA'), equals(variables('dados_pedido')['condPagto'], 'CREDITO')), outputs('Compor_-_Executar_De_x_Para_tabela_depara_tipoDocFiscal')['acao_vista'], outputs('Compor_-_Executar_De_x_Para_tabela_depara_tipoDocFiscal')['acao_prazo'])}"
}
```

7. Ação: `Compor - Resultado passo 6`  
Expressão:

```powerautomate
setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(variables('varResultado'),'tipoDocFiscal',string(variables('resposta_ia')?['tipoDocFiscal'])),'numNota',string(variables('resposta_ia')?['numNota'])),'serie',string(variables('resposta_ia')?['serie'])),'dataDocumento',string(variables('resposta_ia')?['dataDocumento'])),'dataMovimento',string(variables('resposta_ia')?['dataDocumento'])),'chaveAcesso',string(variables('resposta_ia')?['chaveAcesso'])),'totalNota',string(variables('resposta_ia')?['valorTotalDocumento'])),'valorMercadoria',string(variables('resposta_ia')?['valorMercadoria'])),'totalMaoObra',string(variables('resposta_ia')?['totalMaoObra'])),'totalFrete',string(variables('resposta_ia')?['totalFrete'])),'totalSeguro',string(variables('resposta_ia')?['totalSeguro'])),'totalDespesa',string(variables('resposta_ia')?['totalDespesa'])),'totalImportacao',string(variables('resposta_ia')?['totalImportacao'])),'despesaNaoTributada',string(variables('resposta_ia')?['despesaNaoTributada'])),'valorAcrescimoGeral',string(variables('resposta_ia')?['valorAcrescimoGeral'])),'valorDescontoGeral',string(variables('resposta_ia')?['valorDescontoGeral'])),'baseICMS',string(variables('resposta_ia')?['baseICMS'])),'valorICMS',string(variables('resposta_ia')?['valorICMS'])),'valorIPI',string(variables('resposta_ia')?['valorIPI'])),'totalISS',string(variables('resposta_ia')?['totalISS'])),'totalIRRF',string(variables('resposta_ia')?['totalIRRF'])),'totalINSS',string(variables('resposta_ia')?['totalINSS'])),'valorSestSenat',string(variables('resposta_ia')?['valorSestSenat'])),'baseSubstTributaria',string(variables('resposta_ia')?['baseSubstTributaria'])),'valorICMSRetido',string(variables('resposta_ia')?['valorICMSRetido'])),'valorPIS',string(variables('resposta_ia')?['valorPIS'])),'valorCOFINS',string(variables('resposta_ia')?['valorCOFINS'])),'totalCSLL',string(variables('resposta_ia')?['totalCSLL'])),'baseFunRural',string(variables('resposta_ia')?['baseFunRural'])),'valorFunRural',string(variables('resposta_ia')?['valorFunRural'])),'valorICMSDesonera',string(variables('resposta_ia')?['valorICMSDesonera'])),'valorPisRecupera',string(variables('resposta_ia')?['valorPisRecupera'])),'valorCofinsRecupera',string(variables('resposta_ia')?['valorCofinsRecupera'])),'acao',string(outputs('Compor_-_Calcular_acao_(a_vista_e_prazo)')?['acao'])),'contasPagarTipoDoc',string(outputs('Compor_-_Calcular_acao_(a_vista_e_prazo)')?['contasPagarTipoDoc']))
```

8. Ação: `Compor - Resultado com ISS devido`  
Expressão:

```powerautomate
setProperty(
  outputs('Compor_-_Resultado_passo_6'),
  'totalISSDevido',
  string(coalesce(outputs('Compor_-_Resultado_passo_6')?['totalISS'], '0.00'))
)
```

9. Ação: `Definir variável` (`varResultado`)  
Valor:

```powerautomate
outputs('Compor_-_Resultado_com_ISS_devido')
```

8. Regra de negócio adicional (normalização de tipo documental):
- Se `varResultado.tipoDocFiscal = "BOLP-DETRAN"` ou `varResultado.tipoDocFiscal = "BOLP-DETRAN-IPVA-ANTT"`, então redefinir para `"BOLP"`.

Implementação sugerida:

8.1. Ação: `Condição - Normalizar tipoDocFiscal DETRAN para BOLP`
- Condição:

```powerautomate
or(
  equals(variables('varResultado')?['tipoDocFiscal'], 'BOLP-DETRAN'),
  equals(variables('varResultado')?['tipoDocFiscal'], 'BOLP-DETRAN-IPVA-ANTT')
)
```

8.2. Se verdadeiro, executar:
- Ação `Compor - Normalizar tipoDocFiscal DETRAN para BOLP`:

```powerautomate
setProperty(variables('varResultado'), 'tipoDocFiscal', 'BOLP')
```

- Ação `Definir variável` (`varResultado`) com:

```powerautomate
outputs('Compor_-_Normalizar_tipoDocFiscal_DETRAN_para_BOLP')
```

#### 9.2.5) Observações
- Se `resposta_ia` estiver em texto (string JSON), usar `json(variables('resposta_ia'))` no lugar de `variables('resposta_ia')`.
- A correção de `resposta_ia.numNota` e a normalização de percentuais em `resposta_ia` devem ocorrer antes de `Compor - Executar De x Para tabela depara tipoDocFiscal`, para que os valores se propaguem corretamente para `varResultado` e para os objetos internos.
- A decisão entre `acao_vista` e `acao_prazo` usa `variables('dados_pedido')['condPagto']` conforme regra atual do fluxo.
- Após o passo 7, seguir para composição de `itensReceb`, agregação de `valorMercadoria` e montagem de `parcelas`.
- Para NFS, a `chaveAcesso` não precisa seguir o padrão de 44 dígitos da NF-e.

### 9.3) Exemplo de `varResultado` após o passo 5
```json
{
  "filial": "3",
  "agente": "233213",
  "tipoPreco": "CIF",
  "condPagto": "09D",
  "centroCustoReduzido": "58",
  "projetoReduzido": "72",
  "operacao": "I",
  "acao": "",
  "tipoDocFiscal": "",
  "contasPagarTipoDoc": "<dado externo>",
  "numNota": "<dado externo>",
  "serie": "<dado externo>",
  "dataDocumento": "04/02/2026",
  "dataMovimento": "04/02/2026",
  "chaveAcesso": "",
  "totalNota": "",
  "itensReceb": [],
  "parcelas": []
}
```

### 9.4) Exemplo de `varResultado` após o passo 6 (estado atual validado)
```json
{
  "valorMercadoriaEmpenhada": "",
  "tragnCodigo": "",
  "tipoTrans": "",
  "icmsStreRecupera": "",
  "calculaValores": "",
  "itensReceb": [],
  "parcelas": [],
  "filial": "3",
  "agente": "233213",
  "tipoPreco": "CIF",
  "condPagto": "09D",
  "centroCustoReduzido": "58",
  "projetoReduzido": "72",
  "operacao": "I",
  "tipoDocFiscal": "NFS-EG",
  "numNota": "55",
  "serie": "UN",
  "dataDocumento": "04/02/2026",
  "dataMovimento": "04/02/2026",
  "chaveAcesso": "7EE4A7A3F",
  "totalNota": "1050.00",
  "valorMercadoria": "",
  "totalMaoObra": "",
  "totalFrete": "",
  "totalSeguro": "",
  "totalDespesa": "",
  "totalImportacao": "",
  "despesaNaoTributada": "",
  "valorAcrescimoGeral": "",
  "valorDescontoGeral": "0.00",
  "baseICMS": "",
  "valorICMS": "",
  "valorIPI": "0.00",
  "totalISS": "26.78",
  "totalISSDevido": "26.78",
  "totalIRRF": "0.00",
  "totalINSS": "0.00",
  "valorSestSenat": "",
  "baseSubstTributaria": "",
  "valorICMSRetido": "",
  "valorPIS": "0.00",
  "valorCOFINS": "0.00",
  "totalCSLL": "0.00",
  "baseFunRural": "",
  "valorFunRural": "",
  "valorICMSDesonera": "",
  "valorPisRecupera": "",
  "valorCofinsRecupera": "",
  "acao": "82",
  "contasPagarTipoDoc": "NFS"
}
```

### 9.5) Progresso atual na base de `itensReceb`
Estado final implementado até aqui (ações concluídas):

Template da ação `Compor - template itensReceb`:
```json
{
  "documento": "",
  "itemSequencia": "",
  "produto": "",
  "produtoCodAlternativo": "",
  "unidade": "",
  "unidadeRecebimento": "",
  "codConversor": "",
  "qtdeRecebimento": "",
  "valorConverter": "0",
  "valorMercadoria": "0",
  "percDesconto": "0",
  "valorDesconto": "0",
  "valorMaoObra": "0",
  "valorMercadoriaEmpr": "0",
  "valorBaseIPI": "0",
  "percIPI": "0",
  "valorIPI": "0",
  "valorIsentoIPI": "0",
  "valorOutrosIPI": "0",
  "valorRecuperadoIPI": "0",
  "baseIcms": "0",
  "percentualIcms": "0",
  "valorIcms": "0",
  "valorIsentoIcms": "0",
  "valorOutrosIcms": "0",
  "valorIcmsRecupera": "0",
  "valorIcmsRetido": "0",
  "baseSubTrib": "0",
  "aplicacao": "",
  "tipoClasse": "",
  "sitTribICMSA": "0",
  "sitTribICMSB": "90",
  "sitTribPIS": "70",
  "sitTribCofins": "70",
  "calculaValores": "N",
  "baseISS": "0",
  "percentualISS": "0",
  "valorISS": "0",
  "baseIRFF": "0",
  "percentualIRFF": "0",
  "valorIRFF": "0",
  "baseINSS": "0",
  "percentualINSS": "0",
  "valorINSS": "0",
  "basePIS": "0",
  "percentualPIS": "0",
  "valorPIS": "0",
  "baseCofins": "0",
  "percentualCofins": "0",
  "valorCofins": "0",
  "baseCSLL": "0",
  "percentualCSLL": "0",
  "valorCSLL": "0",
  "sitTribIPI": "999",
  "centrosCusto": [],
  "pedidos": []
}
```

Observação importante:
- Os atributos `sitTribICMSA`, `sitTribICMSB`, `sitTribPIS` e `sitTribCofins`, com os valores `"0"`, `"90"`, `"70"` e `"70"`, respectivamente, foram informados pelo time técnico da Odilon (empresa cliente) e devem ser mantidos nesse template.

1. Ação `Aplicar a cada` sobre:
```powerautomate
outputs('Obter_dados_do_pedido')?['body']?['data']
```

2. Ação `Compor - dado pedido`:
```powerautomate
item()
```

3. Ação `Compor - itemReceb preenchido base`:
```powerautomate
setProperty(
  setProperty(
    setProperty(
      setProperty(
        setProperty(
          setProperty(
            setProperty(
              setProperty(
                setProperty(
                  outputs('Compor_-_template_itensReceb'),
                  'documento',
                  string(variables('varResultado')?['numNota'])
                ),
                'itemSequencia',
                string(outputs('Compor_-_dado_pedido')?['ITEM_SEQUENCIA'])
              ),
              'produto',
              string(outputs('Compor_-_dado_pedido')?['PRODUTO'])
            ),
            'produtoCodAlternativo',
            string(outputs('Compor_-_dado_pedido')?['PRODUTO'])
          ),
          'unidade',
          string(outputs('Compor_-_dado_pedido')?['UNIDADE'])
        ),
      'qtdeRecebimento',
      string(coalesce(outputs('Compor_-_dado_pedido')?['QUANTIDADE_PEDIDO'], outputs('Compor_-_dado_pedido')?['QUANTIDADE'], ''))
    ),
    'valorMercadoria',
      string(coalesce(outputs('Compor_-_dado_pedido')?['VALOR_TOTAL_ITEM_PEDIDO'], outputs('Compor_-_dado_pedido')?['VALOR_CONFERIDO'], ''))
    ),
    'aplicacao',
    string(outputs('Compor_-_dado_pedido')?['APLICACAO'])
  ),
  'tipoClasse',
  string(outputs('Compor_-_dado_pedido')?['TIPO_CLASSE'])
)
```

4. Ação `Compor - itemReceb preenchido`:
- aplica os campos fiscais (IPI/ICMS/ISS/IRRF/INSS/PIS/COFINS/CSLL e correlatos) usando `resposta_ia` sobre o objeto de `Compor - itemReceb preenchido base`.

5. Ação `Compor - valorMercadoria item decimal`:
```powerautomate
float(concat('0',string(coalesce(outputs('Compor_-_dado_pedido')?['VALOR_TOTAL_ITEM_PEDIDO'], outputs('Compor_-_dado_pedido')?['VALOR_CONFERIDO'], '0'))))
```

6. Ação `Compor - itemReceb impostos proporcionalizados`:
- sobrescreve no item os percentuais, bases (com base no valor do item) e valores proporcionais de tributos.
- cálculo proporcional aplicado por imposto: `valorItem * percentual / 100`, com formatação `0.00`.
```powerautomate
setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(setProperty(outputs('Compor_-_itemReceb_preenchido'),'percIPI',string(coalesce(variables('resposta_ia')?['percIPI'], '0.00'))),'percentualIcms',string(coalesce(variables('resposta_ia')?['percentualIcms'], '0.00'))),'percentualISS',string(coalesce(variables('resposta_ia')?['percentualISS'], '0.00'))),'percentualIRFF',string(coalesce(variables('resposta_ia')?['percentualIRFF'], '0.00'))),'percentualINSS',string(coalesce(variables('resposta_ia')?['percentualINSS'], '0.00'))),'percentualPIS',string(coalesce(variables('resposta_ia')?['percentualPIS'], '0.00'))),'percentualCofins',string(coalesce(variables('resposta_ia')?['percentualCofins'], '0.00'))),'percentualCSLL',string(coalesce(variables('resposta_ia')?['percentualCSLL'], '0.00'))),'valorBaseIPI',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseIcms',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseISS',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseIRFF',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseINSS',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'basePIS',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseCofins',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'baseCSLL',formatNumber(outputs('Compor_-_valorMercadoria_item_decimal'), '0.00', 'en-US')),'valorIPI',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percIPI'], '0')))), 100), '0.00', 'en-US')),'valorIcms',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualIcms'], '0')))), 100), '0.00', 'en-US')),'valorISS',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualISS'], '0')))), 100), '0.00', 'en-US')),'valorIRFF',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualIRFF'], '0')))), 100), '0.00', 'en-US')),'valorINSS',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualINSS'], '0')))), 100), '0.00', 'en-US')),'valorPIS',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualPIS'], '0')))), 100), '0.00', 'en-US')),'valorCofins',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualCofins'], '0')))), 100), '0.00', 'en-US')),'valorCSLL',formatNumber(div(mul(outputs('Compor_-_valorMercadoria_item_decimal'), float(concat('0', coalesce(variables('resposta_ia')?['percentualCSLL'], '0')))), 100), '0.00', 'en-US')),'valorIcmsRetido',string(coalesce(variables('resposta_ia')?['valorIcmsRetido'], '0.00')))
```

7. Ação `Compor - itemReceb com ISS devido`:
- preenche `baseISSDevido`, `percentualISSDevido` e `valorISSDevido` com os mesmos valores já atribuídos em `baseISS`, `percentualISS` e `valorISS`.
```powerautomate
setProperty(
  setProperty(
    setProperty(
      outputs('Compor_-_itemReceb_impostos_proporcionalizados'),
      'baseISSDevido',
      string(coalesce(outputs('Compor_-_itemReceb_impostos_proporcionalizados')?['baseISS'], '0.00'))
    ),
    'percentualISSDevido',
    string(coalesce(outputs('Compor_-_itemReceb_impostos_proporcionalizados')?['percentualISS'], '0.00'))
  ),
  'valorISSDevido',
  string(coalesce(outputs('Compor_-_itemReceb_impostos_proporcionalizados')?['valorISS'], '0.00'))
)
```

8. Ação `Compor - projeto preenchido`:
- preenche `Compor - template itensReceb.centrosCusto.projetos` com `numNota`, `itemSequencia`, `projetoReduzido`, `tipoClasse`, `prctRateio`, `valorRateio`.

9. Ação `Compor - projeto preenchido final`:
```powerautomate
setProperty(outputs('Compor_-_projeto_preenchido'),'operacao','I')
```

10. Ação `Compor - array projetos do centroCusto`:
```powerautomate
createArray(outputs('Compor_-_projeto_preenchido_final'))
```

11. Ação `Compor - centroCusto preenchido`:
- preenche `Compor - template itensReceb.centrosCusto` com `numNota`, `itemSequencia`, `centroCustoReduzido`, `tipoClasse`, `prctRateio`, `valorRateio`.

12. Ação `Compor - centroCusto preenchido final`:
```powerautomate
setProperty(
  setProperty(
    outputs('Compor_-_centroCusto_preenchido'),
    'projetos',
    outputs('Compor_-_array_projetos_do_centroCusto')
  ),
  'operacao',
  'I'
)
```

13. Ação `Compor - array centrosCusto do item`:
```powerautomate
createArray(outputs('Compor_-_centroCusto_preenchido_final'))
```

14. Ação `Compor - itemReceb preenchido com centrosCusto`:
```powerautomate
setProperty(
  outputs('Compor_-_itemReceb_com_ISS_devido'),
  'centrosCusto',
  outputs('Compor_-_array_centrosCusto_do_item')
)
```

15. Ação `Compor - pedido preenchido`:
- preenche `Compor - itensReceb.pedidos` com `numNota`, `dataDocumento`, `itemSequencia`, `serieSequencia`, `codPedido`, `sequenciaItemPedido`, `quantidade`, `dataEntrega`, `qtdeConvertida`.
```powerautomate
setProperty(
  setProperty(
    setProperty(
      setProperty(
        setProperty(
          setProperty(
            setProperty(
              setProperty(
                setProperty(
                  outputs('Compor_-_itensReceb.pedidos'),
                  'numNota',
                  string(variables('varResultado')?['numNota'])
                ),
                'dataDocumento',
                string(variables('varResultado')?['dataDocumento'])
              ),
              'itemSequencia',
              string(outputs('Compor_-_dado_pedido')?['ITEM_SEQUENCIA'])
            ),
            'serieSequencia',
            string(coalesce(outputs('Compor_-_dado_pedido')?['SERIE_SEQUENCIA'], outputs('Compor_-_Obter_pedido')?['SERIE_SEQUENCIA'], ''))
          ),
          'codPedido',
          string(coalesce(outputs('Compor_-_dado_pedido')?['PEDIDO'], outputs('Compor_-_Obter_pedido')?['PDC_IN_CODIGO'], ''))
        ),
        'sequenciaItemPedido',
        string(outputs('Compor_-_dado_pedido')?['ITEM_SEQUENCIA'])
      ),
      'quantidade',
      string(coalesce(outputs('Compor_-_dado_pedido')?['QUANTIDADE_PEDIDO'], ''))
    ),
    'dataEntrega',
    string(coalesce(outputs('Compor_-_dado_pedido')?['DATA_ENTREGA'], outputs('Compor_-_Obter_pedido')?['DATA_ENTREGA'], ''))
  ),
  'qtdeConvertida',
  string(coalesce(outputs('Compor_-_dado_pedido')?['QUANTIDADE_PEDIDO'], ''))
)
```

16. Ação `Compor - pedido preenchido final`:
```powerautomate
setProperty(
  outputs('Compor_-_pedido_preenchido'),
  'operacao',
  'I'
)
```

17. Ação `Compor - array pedidos do item`:
```powerautomate
createArray(outputs('Compor_-_pedido_preenchido_final'))
```

18. Ação `Compor - itemReceb completo`:
```powerautomate
setProperty(
  outputs('Compor_-_itemReceb_preenchido_com_centrosCusto'),
  'pedidos',
  outputs('Compor_-_array_pedidos_do_item')
)
```

Exemplo atual de saída em `Compor - itemReceb completo` (1a iteração):
```json
{
  "unidadeRecebimento": "",
  "codConversor": "",
  "valorConverter": "",
  "documento": "555",
  "itemSequencia": "1",
  "produto": "156700",
  "produtoCodAlternativo": "156700",
  "unidade": "PC",
  "qtdeRecebimento": "3",
  "valorMercadoria": "300",
  "aplicacao": "209",
  "tipoClasse": "DESP",
  "percDesconto": "0.00",
  "valorDesconto": "0.00",
  "valorMaoObra": "0.00",
  "valorMercadoriaEmpr": "0.00",
  "valorBaseIPI": "300.00",
  "percIPI": "0.00",
  "valorIPI": "0.00",
  "valorIsentoIPI": "0.00",
  "valorOutrosIPI": "0.00",
  "valorRecuperadoIPI": "0.00",
  "baseIcms": "300.00",
  "percentualIcms": "0.00",
  "valorIcms": "0.00",
  "valorIsentoIcms": "0.00",
  "valorOutrosIcms": "0.00",
  "valorIcmsRecupera": "0.00",
  "valorIcmsRetido": "0.00",
  "baseSubTrib": "0.00",
  "sitTribICMSA": "0",
  "sitTribICMSB": "90",
  "sitTribPIS": "70",
  "sitTribCofins": "70",
  "calculaValores": "N",
  "baseISS": "300.00",
  "percentualISS": "2.55",
  "valorISS": "7.65",
  "baseISSDevido": "300.00",
  "percentualISSDevido": "2.55",
  "valorISSDevido": "7.65",
  "baseIRFF": "300.00",
  "percentualIRFF": "0.00",
  "valorIRFF": "0.00",
  "baseINSS": "300.00",
  "percentualINSS": "0.00",
  "valorINSS": "0.00",
  "basePIS": "300.00",
  "percentualPIS": "0.00",
  "valorPIS": "0.00",
  "baseCofins": "300.00",
  "percentualCofins": "0.00",
  "valorCofins": "0.00",
  "baseCSLL": "300.00",
  "percentualCSLL": "0.00",
  "valorCSLL": "0.00",
  "centrosCusto": [
    {
      "numNota": "555",
      "itemSequencia": "1",
      "sequenciaCC": "",
      "centroCustoReduzido": "58",
      "tipoClasse": "DESP",
      "prctRateio": "100.00",
      "valorRateio": "300.00",
      "projetos": [
        {
          "numNota": "555",
          "itemSequencia": "1",
          "sequenciaCC": "",
          "sequenciaProjeto": "",
          "projetoReduzido": "72",
          "tipoClasse": "DESP",
          "prctRateio": "100.00",
          "valorRateio": "300.00",
          "operacao": "I"
        }
      ],
      "operacao": "I"
    }
  ],
  "pedidos": [
    {
      "numNota": "555",
      "dataDocumento": "04/02/2026",
      "itemSequencia": "1",
      "serieSequencia": "1",
      "codPedido": "309675",
      "sequenciaItemPedido": "1",
      "quantidade": "",
      "dataEntrega": "04/02/2026",
      "qtdeConvertida": "",
      "operacao": "I"
    }
  ]
}
```

Status atual:
- `Append to array variable` em `varItensReceb` com `outputs('Compor_-_itemReceb_completo')` já implementado.
- `varItensReceb` já validado após o término do loop (2 itens).
- `varResultado.itensReceb` já atribuído via `setProperty(...)`.
- `parcelas` já montado e atribuído em `varResultado.parcelas`.
- Regra de vencimento já contempla sufixo `D` (dias) e `M` (meses) em `condPagto`.

### 9.6) Regra adicional pós-montagem final (campo `serie`)
Objetivo:
- Após a ação `Definir variável - varResultado com parcelas` (última ação de montagem do JSON), aplicar uma regra final para `varResultado.serie`.

Regra:
- Se `varTipoDocFiscal` **não** for um dos valores `["NF-E", "NFSC", "NFSTE", "NF3E"]`, então definir `serie` como `"UN"`.
- Caso contrário, manter o valor atual de `varResultado.serie`.

Implementação:
1. Ação: `Compor - Resultado com regra serie por tipoDocFiscal`  
Expressão:

```powerautomate
setProperty(
  variables('varResultado'),
  'serie',
  if(
    not(
      or(
        equals(variables('varTipoDocFiscal'), 'NF-E'),
        equals(variables('varTipoDocFiscal'), 'NFSC'),
        equals(variables('varTipoDocFiscal'), 'NFSTE'),
        equals(variables('varTipoDocFiscal'), 'NF3E')
      )
    ),
    'UN',
    string(coalesce(variables('varResultado')?['serie'], ''))
  )
)
```

2. Ação: `Definir variável - varResultado (regra serie por tipoDocFiscal)`  
Variável: `varResultado`  
Valor:

```powerautomate
outputs('Compor_-_Resultado_com_regra_serie_por_tipoDocFiscal')
```

Observação:
- Se o nome interno da ação `Compor` ficar diferente do nome visível, usar o identificador exato no `outputs('...')` via `Peek code`.

### 9.8) Regra adicional pós-montagem final (campo `dataMovimento`)
Objetivo:
- Manter `dataDocumento` com a regra atual (PDF preferencial e fallback OP/DP), mas definir `dataMovimento` com a data atual.

Regra:
- `dataDocumento`: permanece sem alteração.
- `dataMovimento`: sempre data atual no formato `dd/MM/yyyy`.

Implementação:
1. Ação: `Compor - Resultado com dataMovimento atual`  
Expressão:

```powerautomate
setProperty(
  variables('varResultado'),
  'dataMovimento',
  formatDateTime(
    convertTimeZone(utcNow(), 'UTC', 'E. South America Standard Time'),
    'dd/MM/yyyy'
  )
)
```

2. Ação: `Definir variável - varResultado (regra dataMovimento atual)`  
Variável: `varResultado`  
Valor:

```powerautomate
outputs('Compor_-_Resultado_com_dataMovimento_atual')
```

Observação:
- O valor atribuído em `dataMovimento` no `Compor - Resultado passo 6` passa a ser intermediário, pois esta regra final sobrescreve o campo antes da saída.

### 9.9) Regra adicional pós-montagem final (campo `chaveAcesso`)
Objetivo:
- Após a ação `Definir variável - varResultado (regra dataMovimento atual)` e antes da ação `Acrescentar à variável de matriz - anexar varResultado a varPayloads`, aplicar uma regra final para `varResultado.chaveAcesso`.

Regra:
- Se `varTipoDocFiscal` for um dos valores `["NFS-EG", "NFS-E", "BOLP", "BOLP-DETRAN", "BOLP-DETRAN-IPVA-ANTT"]`, então definir `chaveAcesso` como `""` (string vazia).
- Caso contrário, manter o valor atual de `varResultado.chaveAcesso`.

Implementação:
1. Ação: `Compor - Resultado com regra chaveAcesso por tipoDocFiscal`  
Expressão:

```powerautomate
setProperty(
  variables('varResultado'),
  'chaveAcesso',
  if(
    or(
      equals(variables('varTipoDocFiscal'), 'NFS-EG'),
      equals(variables('varTipoDocFiscal'), 'NFS-E'),
      equals(variables('varTipoDocFiscal'), 'BOLP'),
      equals(variables('varTipoDocFiscal'), 'BOLP-DETRAN'),
      equals(variables('varTipoDocFiscal'), 'BOLP-DETRAN-IPVA-ANTT')
    ),
    '',
    string(coalesce(variables('varResultado')?['chaveAcesso'], ''))
  )
)
```

2. Ação: `Definir variável - varResultado (regra chaveAcesso por tipoDocFiscal)`  
Variável: `varResultado`  
Valor:

```powerautomate
outputs('Compor_-_Resultado_com_regra_chaveAcesso_por_tipoDocFiscal')
```

Observação:
- Se o nome interno da ação `Compor` ficar diferente do nome visível, usar o identificador exato no `outputs('...')` via `Peek code`.

### 9.10) Regra adicional pós-montagem final (campo `numNota` sem zeros à esquerda)
Objetivo:
- Após a ação `Definir variável - varResultado (regra chaveAcesso por tipoDocFiscal)` e antes da ação `Acrescentar à variável de matriz - anexar varResultado a varPayloads`, remover zeros à esquerda de `varResultado.numNota`.

Premissa:
- A variável `varNumNotaSemZero` (String) já foi inicializada no início do fluxo junto das demais variáveis.

Regra:
- Resetar `varNumNotaSemZero` com o valor atual de `varResultado.numNota` normalizado para texto.
- Remover zeros à esquerda de forma textual (sem uso de `int()`), preservando suporte a números muito grandes.
- Se o valor for vazio, deve permanecer vazio.
- Se o valor for composto apenas por zeros, deve resultar em `"0"`.

Implementação:
1. Ação: `Definir variável - reset de varNumNotaSemZero`  
Variável: `varNumNotaSemZero`  
Valor:

```powerautomate
trim(string(coalesce(variables('varResultado')?['numNota'], '')))
```

2. Ação: `Condição - varNumNotaSemZero começa com zero`  
Configuração da condição:

```powerautomate
if(
  and(
    startsWith(variables('varNumNotaSemZero'), '0'),
    greater(length(variables('varNumNotaSemZero')), 1)
  ),
  1,
  0
)
```

Comparação:

```text
é igual a 1
```

2.1. No ramo **Verdadeiro**, adicionar a ação: `Do until - Remover zeros à esquerda de numNota`  
Condição de parada:

```powerautomate
not(
  and(
    startsWith(variables('varNumNotaSemZero'), '0'),
    greater(length(variables('varNumNotaSemZero')), 1)
  )
)
```

2.1.1. Dentro do loop, ação: `Compor - proximo varNumNotaSemZero`  
Expressão:

```powerautomate
substring(
  variables('varNumNotaSemZero'),
  1,
  sub(length(variables('varNumNotaSemZero')), 1)
)
```

2.1.2. Dentro do loop, ação: `Definir variável - varNumNotaSemZero`  
Variável: `varNumNotaSemZero`  
Valor:

```powerautomate
outputs('Compor_-_proximo_varNumNotaSemZero')
```

3. Ação: `Compor - Resultado com regra numNota sem zeros a esquerda (texto)`  
Expressão:

```powerautomate
setProperty(
  variables('varResultado'),
  'numNota',
  variables('varNumNotaSemZero')
)
```

4. Ação: `Definir variável - varResultado (regra numNota sem zeros a esquerda)`  
Variável: `varResultado`  
Valor:

```powerautomate
outputs('Compor_-_Resultado_com_regra_numNota_sem_zeros_a_esquerda_(texto)')
```

Observação:
- O uso de `Compor` intermediário dentro do loop evita auto-referência direta no `Definir variável`, limitação do Power Automate Cloud.
- O `Do until - Remover zeros à esquerda de numNota` só deve ser executado no ramo **Verdadeiro** da ação `Condição - varNumNotaSemZero começa com zero`. No ramo **Falso**, não executar nenhuma ação de remoção.

### 9.11) Consolidação final por anexo em `varPayloads` e definição de `varJSONFinal`
Objetivo:
- Quando o pedido possuir múltiplos anexos, cada anexo deve executar toda a lógica de montagem normalmente até gerar um objeto final em `varResultado`.
- Ao término do processamento de cada anexo, adicionar o `varResultado` na variável de lista `varPayloads`.
- Após o fim do processamento de todos os anexos, selecionar apenas 1 objeto final para ser enviado na chamada da API de lançamento de recebimento.

Regra:
- Analisar os elementos de `varPayloads` considerando o campo `contasPagarTipoDoc`.
- A prioridade de seleção deve ser:
- Prefixo `"NF"` em primeiro lugar.
- Prefixo `"CF"` em segundo lugar.
- Prefixo `"REC"` em terceiro lugar.
- Prefixo `"BOLP"` em quarto lugar.
- Se nenhum item atender aos prefixos acima, usar o primeiro elemento de `varPayloads` como fallback.

Observações:
- A comparação é por prefixo, portanto valores como `NFC`, `NFS`, `NFF`, `NFSTE` e outros iniciados por `NF` entram na maior prioridade.
- O valor selecionado deve ser armazenado na variável objeto `varJSONFinal`.
- A chamada da API de lançamento de recebimento deve consumir `varJSONFinal`, e não diretamente `varResultado`.

Implementação sugerida:
1. Ação: `Filtrar array - Payloads NF`
De:

```powerautomate
variables('varPayloads')
```

Condição avançada:

```powerautomate
startsWith(item()?['contasPagarTipoDoc'], 'NF')
```

2. Ação: `Filtrar array - Payloads CF`
De:

```powerautomate
variables('varPayloads')
```

Condição avançada:

```powerautomate
startsWith(item()?['contasPagarTipoDoc'], 'CF')
```

3. Ação: `Filtrar array - Payloads REC`
De:

```powerautomate
variables('varPayloads')
```

Condição avançada:

```powerautomate
startsWith(item()?['contasPagarTipoDoc'], 'REC')
```

4. Ação: `Filtrar array - Payloads BOLP`
De:

```powerautomate
variables('varPayloads')
```

Condição avançada:

```powerautomate
startsWith(item()?['contasPagarTipoDoc'], 'BOLP')
```

5. Ação: `Compor - JSON final priorizado`
Expressão:

```powerautomate
if(greater(length(body('Filtrar_array_-_Payloads_NF')),0),first(body('Filtrar_array_-_Payloads_NF')),if(greater(length(body('Filtrar_array_-_Payloads_CF')),0),first(body('Filtrar_array_-_Payloads_CF')),if(greater(length(body('Filtrar_array_-_Payloads_REC')),0),first(body('Filtrar_array_-_Payloads_REC')),if(greater(length(body('Filtrar_array_-_Payloads_BOLP')),0),first(body('Filtrar_array_-_Payloads_BOLP')),first(variables('varPayloads'))))))
```

6. Ação: `Definir variável - varJSONFinal`
Variável: `varJSONFinal`
Valor:

```powerautomate
outputs('Compor_-_JSON_final_priorizado')
```

Observação técnica:
- Se o nome interno das ações `Filtrar array` ou `Compor` ficar diferente do nome visível, usar o identificador exato retornado pelo `Peek code`.

#### 9.11.1) Regra final `DeveLancar` por vencimento em 7 dias ou menos
Objetivo:
- Após a ação `Definir variável - varJSONFinal`, definir se o documento deve ou não ser lançado.
- A regra considera a data de emissão do documento e a condição de pagamento.
- O vencimento é calculado como: `dataDocumento + dias da condição de pagamento`.
- Se faltarem 7 dias ou menos, considerando a data atual no fuso de São Paulo, então `DeveLancar = false`.
- Se faltarem mais de 7 dias, então `DeveLancar = true`.

Premissas:
- A variável `DeveLancar` deve ser inicializada no início do fluxo como Boolean com valor `true`.
- A condição de pagamento deve vir da ação `Obter dados do pedido`, propriedade `['body']['data'][0]['COND_PAGTO']`.
- A implementação abaixo usa validação de tamanho antes de acessar o primeiro item de `data[]`, para evitar erro quando a lista vier vazia.
- Esta regra deve ser executada após `Definir variável - varJSONFinal` e antes do escopo que executa o lançamento.
- Quando a data ou a condição de pagamento não puderem ser calculadas, a regra mantém `DeveLancar = true` e deixa os demais bloqueios e validações existentes decidirem o fluxo.

1. Ação: `Definir variável - reset DeveLancar`  
Variável: `DeveLancar`  
Valor:
```powerautomate
true
```

2. Ação: `Compor - dataDocumento para regra DeveLancar`  
Código:
```powerautomate
trim(
  string(
    coalesce(
      variables('varJSONFinal')?['dataDocumento'],
      ''
    )
  )
)
```

3. Ação: `Compor - dataDocumento ISO para regra DeveLancar`  
Código:
```powerautomate
if(
  equals(
    length(
      split(
        outputs('Compor_-_dataDocumento_para_regra_DeveLancar'),
        '/'
      )
    ),
    3
  ),
  concat(
    last(split(outputs('Compor_-_dataDocumento_para_regra_DeveLancar'), '/')),
    '-',
    first(skip(split(outputs('Compor_-_dataDocumento_para_regra_DeveLancar'), '/'), 1)),
    '-',
    first(split(outputs('Compor_-_dataDocumento_para_regra_DeveLancar'), '/'))
  ),
  ''
)
```

4. Ação: `Compor - condPagto para regra DeveLancar`  
Código:
```powerautomate
toUpper(
  trim(
    string(
      if(
        greater(
          length(coalesce(outputs('Obter_dados_do_pedido')?['body']?['data'], createArray())),
          0
        ),
        coalesce(first(outputs('Obter_dados_do_pedido')?['body']?['data'])?['COND_PAGTO'], ''),
        ''
      )
    )
  )
)
```

5. Ação: `Compor - condPagto sufixo para regra DeveLancar`  
Código:
```powerautomate
if(
  greater(length(outputs('Compor_-_condPagto_para_regra_DeveLancar')), 0),
  last(outputs('Compor_-_condPagto_para_regra_DeveLancar')),
  ''
)
```

6. Ação: `Compor - condPagto dias texto para regra DeveLancar`  
Código:
```powerautomate
if(
  and(
    greater(length(outputs('Compor_-_condPagto_para_regra_DeveLancar')), 1),
    equals(outputs('Compor_-_condPagto_sufixo_para_regra_DeveLancar'), 'D')
  ),
  substring(
    outputs('Compor_-_condPagto_para_regra_DeveLancar'),
    0,
    sub(length(outputs('Compor_-_condPagto_para_regra_DeveLancar')), 1)
  ),
  ''
)
```

7. Ação: `Compor - dataVencimento ISO para regra DeveLancar`  
Código:
```powerautomate
if(
  and(
    not(empty(outputs('Compor_-_dataDocumento_ISO_para_regra_DeveLancar'))),
    not(empty(outputs('Compor_-_condPagto_dias_texto_para_regra_DeveLancar')))
  ),
  formatDateTime(
    addDays(
      outputs('Compor_-_dataDocumento_ISO_para_regra_DeveLancar'),
      int(outputs('Compor_-_condPagto_dias_texto_para_regra_DeveLancar'))
    ),
    'yyyy-MM-dd'
  ),
  ''
)
```

8. Ação: `Compor - dataAtual ISO Sao Paulo para regra DeveLancar`  
Código:
```powerautomate
formatDateTime(
  convertTimeZone(
    utcNow(),
    'UTC',
    'E. South America Standard Time'
  ),
  'yyyy-MM-dd'
)
```

9. Ação: `Compor - dias ate vencimento para regra DeveLancar`  
Código:
```powerautomate
if(
  not(empty(outputs('Compor_-_dataVencimento_ISO_para_regra_DeveLancar'))),
  div(
    sub(
      ticks(concat(outputs('Compor_-_dataVencimento_ISO_para_regra_DeveLancar'), 'T00:00:00Z')),
      ticks(concat(outputs('Compor_-_dataAtual_ISO_Sao_Paulo_para_regra_DeveLancar'), 'T00:00:00Z'))
    ),
    864000000000
  ),
  9999
)
```

10. Ação: `Compor - calcular DeveLancar por vencimento`  
Código:
```powerautomate
if(
  and(
    not(empty(outputs('Compor_-_dataVencimento_ISO_para_regra_DeveLancar'))),
    lessOrEquals(outputs('Compor_-_dias_ate_vencimento_para_regra_DeveLancar'), 7)
  ),
  false,
  true
)
```

11. Ação: `Definir variável - DeveLancar por vencimento`  
Variável: `DeveLancar`  
Valor:
```powerautomate
outputs('Compor_-_calcular_DeveLancar_por_vencimento')
```

12. Ação: `Condição - DeveLancar permite lançamento`  
Condição:
```text
variables('DeveLancar') é igual a true
```

Comportamento:
- Ramo **True**: seguir com as validações finais existentes e executar o lançamento fiscal somente se as demais condições também permitirem.
- Ramo **False**: não executar o lançamento fiscal do anexo atual e seguir para a próxima iteração.

Observações:
- Exemplo: se `dataDocumento = 04/06/2026`, `COND_PAGTO = 09D` e a data atual em São Paulo for `12/06/2026`, o vencimento será `13/06/2026`; como falta 1 dia, `DeveLancar = false`.
- Se o vencimento já estiver vencido, o cálculo de dias será menor que zero e também resultará em `DeveLancar = false`.
- Esta regra não substitui as validações de CNPJ/CPF nem outros bloqueios já existentes; o lançamento deve ocorrer apenas quando `DeveLancar = true` e as demais validações também estiverem aprovadas.

### 9.12) Validação de documento fiscal por CNPJ/CPF após `Escopo - Definição de varJSONFinal`
Objetivo:
- Após concluir o `Escopo - Definição de varJSONFinal`, validar consistência entre os dados extraídos pela IA e os dados do pedido.
- Quando houver divergência, gerar alerta no Teams.

Posicionamento:
- Inserir um novo bloco `Escopo - cálculo de CNPJ do fornecedor e emitente` imediatamente após `Escopo - Definição de varJSONFinal`.
- Dentro desse escopo, manter as ações abaixo na ordem.

#### 9.12.1) Ações de cálculo (6 ações)
1. Ação: `Compor - CNPJ emitente normalizado`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjEmitente')))),
  '',
  replace(
    replace(
      replace(
        replace(
          trim(string(variables('cnpjEmitente'))),
          '.',
          ''
        ),
        '-',
        ''
      ),
      '/',
      ''
    ),
    ' ',
    ''
  )
)
```

2. Ação: `Compor - CNPJ fornecedor (pedido) normalizado`  
Código:
```powerautomate
replace(
  replace(
    replace(
      replace(
        trim(
          string(
            first(outputs('Obter_dados_do_pedido')?['body']?['data'])?['CNPJ_CPF_FORNECEDOR']
          )
        ),
        '.',
        ''
      ),
      '-',
      ''
    ),
    '/',
    ''
  ),
  ' ',
  ''
)
```

3. Ação: `Compor - validação cnpjEmitente x fornecedor`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjEmitente')))),
  true,
  equals(
    outputs('Compor_-_CNPJ_emitente_normalizado'),
    outputs('Compor_-_CNPJ_fornecedor_(pedido)_normalizado')
  )
)
```

4. Ação: `Compor - CNPJ_CPF tomador normalizado`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjCpfTomador')))),
  '',
  replace(
    replace(
      replace(
        replace(
          trim(string(variables('cnpjCpfTomador'))),
          '.',
          ''
        ),
        '-',
        ''
      ),
      '/',
      ''
    ),
    ' ',
    ''
  )
)
```

5. Ação: `Compor - CNPJ_CPF filial (pedido) normalizado`  
Código:
```powerautomate
replace(
  replace(
    replace(
      replace(
        trim(
          string(
            first(outputs('Obter_dados_do_pedido')?['body']?['data'])?['CNPJ_CPF_FILIAL']
          )
        ),
        '.',
        ''
      ),
      '-',
      ''
    ),
    '/',
    ''
  ),
  ' ',
  ''
)
```

6. Ação: `Compor - validação cnpjCpfTomador x filial`  
Código:
```powerautomate
if(
  empty(trim(string(variables('cnpjCpfTomador')))),
  true,
  equals(
    outputs('Compor_-_CNPJ_CPF_tomador_normalizado'),
    outputs('Compor_-_CNPJ_CPF_filial_(pedido)_normalizado')
  )
)
```

#### 9.12.2) Condições de validação e alerta
Após as 6 ações do escopo, aplicar duas ações de Condição:

1. Ação: `Condição - validação cnpjEmitente x fornecedor`  
Condição:
```text
outputs('Compor_-_validação_cnpjEmitente_x_fornecedor') é igual a true
```
Comportamento:
- Ramo **False**:
  - gerar alerta no Teams informando que os dados não batem;
  - abortar o processamento do anexo atual (não lançar recebimento);
  - seguir para o próximo anexo no `Aplicar a cada - pedidos` (equivalente a `continue` no loop).

2. Ação: `Condição - validação cnpjCpfTomador x filial`  
Condição:
```text
outputs('Compor_-_validação_cnpjCpfTomador_x_filial') é igual a true
```
Comportamento:
- Ramo **False**:
  - gerar alerta no Teams informando que os dados não batem;
  - abortar o processamento do anexo atual (não lançar recebimento);
  - seguir para o próximo anexo no `Aplicar a cada - pedidos` (equivalente a `continue` no loop).

Observação técnica:
- Como `data` é lista em `Obter dados do pedido`, a leitura é feita com `first(...?['data'])`.
- Nomes de ação não devem conter `/`. Usar padrão `CNPJ_CPF` nos nomes visíveis e internos.
- Para efetivar o abort do anexo atual, encapsular o lançamento em um escopo condicional que só execute quando ambas validações forem `true`. Se qualquer validação for `false`, o fluxo de lançamento daquele item não deve executar.

### 9.13) Regra de bloqueio de lançamento por condição de pagamento em até 7 dias
Objetivo:
- Se existir ao menos 1 pedido do mesmo documento/anexo com condição de pagamento em dias (`D`) menor ou igual a 7, bloquear o lançamento fiscal ao final daquele anexo.

Premissas:
- A regra é acumulativa por anexo/documento.
- Uma vez que a flag vire `true` em qualquer pedido, ela deve permanecer `true` até o final da iteração do anexo.

#### 9.13.1) Variável de controle
1. Ação: `Inicializar variável - varBloquearLancamentoCondPagto7Dias`  
Tipo: `Boolean`  
Valor inicial:
```powerautomate
false
```

2. Ação: `Definir variável - reset varBloquearLancamentoCondPagto7Dias`  
Valor:
```powerautomate
false
```

Posicionamento:
- Executar o reset no início de cada iteração de `Aplicar a cada - pedidos` (escopo do anexo), após os resets gerais do anexo.

#### 9.13.2) Cálculo por pedido e acumulação da flag
Inserir dentro do loop que percorre os pedidos/itens do anexo, na sequência abaixo:

1. Ação: `Compor - condPagto atual normalizada`  
Código:
```powerautomate
toUpper(
  trim(
    string(
      coalesce(
        outputs('Compor_-_dado_pedido')?['COND_PAGTO'],
        outputs('Compor_-_Obter_pedido')?['COND_ST_CODIGO'],
        ''
      )
    )
  )
)
```

2. Ação: `Compor - condPagto sufixo`  
Código:
```powerautomate
if(
  greater(length(outputs('Compor_-_condPagto_atual_normalizada')), 0),
  last(outputs('Compor_-_condPagto_atual_normalizada')),
  ''
)
```

3. Ação: `Compor - condPagto numero texto`  
Código:
```powerautomate
if(
  and(
    greater(length(outputs('Compor_-_condPagto_atual_normalizada')), 1),
    equals(outputs('Compor_-_condPagto_sufixo'), 'D')
  ),
  substring(
    outputs('Compor_-_condPagto_atual_normalizada'),
    0,
    sub(length(outputs('Compor_-_condPagto_atual_normalizada')), 1)
  ),
  ''
)
```

4. Ação: `Compor - pedido bloqueia por condPagto7Dias`  
Código:
```powerautomate
if(
  and(
    equals(outputs('Compor_-_condPagto_sufixo'), 'D'),
    not(empty(outputs('Compor_-_condPagto_numero_texto'))),
    lessOrEquals(int(outputs('Compor_-_condPagto_numero_texto')), 7)
  ),
  true,
  false
)
```

5. Ação: `Compor - definir valor de varBloquearLancamentoCondPagto7Dias acumulado`  
Código:
```powerautomate
or(
  variables('varBloquearLancamentoCondPagto7Dias'),
  outputs('Compor_-_pedido_bloqueia_por_condPagto7Dias')
)
```

6. Ação: `Definir variável - varBloquearLancamentoCondPagto7Dias`  
Valor:
```powerautomate
outputs('Compor_-_definir_valor_de_varBloquearLancamentoCondPagto7Dias_acumulado')
```

Observação técnica:
- A acumulação usa `Compor` intermediário para evitar auto-referência direta no `Definir variável`, limitação do Power Automate Cloud.

#### 9.13.3) Bloqueio no final do anexo (antes do lançamento)
Após a definição de `varJSONFinal` e validações já existentes, adicionar:

1. Ação: `Condição - bloqueio por condPagto7Dias`  
Condição:
```text
variables('varBloquearLancamentoCondPagto7Dias') é igual a false
```

Comportamento:
- Ramo **True**: seguir fluxo normal e executar o lançamento fiscal.
- Ramo **False**: não executar o lançamento fiscal do anexo atual e seguir para a próxima iteração.

Observação:
- Não foi implementada ação adicional de observabilidade específica para este bloqueio (ex.: `Compor - motivo bloqueio condPagto7Dias`).

### 9.14) Regra de zerar base de ICMS e IPI para documentos de serviço
Objetivo:
- Quando o documento fiscal for de serviço, forçar as bases de cálculo de ICMS e IPI para zero.

Tipos de serviço considerados nesta regra:
- `NFS-EG`
- `NFS-E`
- `NFF`
- `NFSTE`
- `NFSC`

Campos alvo:
- Raiz (`varResultado`): `baseICMS` e `valorBaseIPI`
- Itens (`itensReceb`): `baseIcms` e `valorBaseIPI`

Valor padrão obrigatório:
- Usar string `"0"` (zero textual) conforme regra solicitada.

#### 9.14.1) Aplicação na raiz (`varResultado`)
Posicionamento:
- Executar após `Definir variável - varResultado (regra numNota sem zeros a esquerda)`.
- Executar antes de `Acrescentar à variável de matriz - anexar varResultado a varPayloads`.

1. Ação: `Compor - Resultado com baseICMS e valorBaseIPI zerados para documento de serviço`  
Expressão:
```powerautomate
if(
  or(
    equals(variables('varTipoDocFiscal'), 'NFS-EG'),
    equals(variables('varTipoDocFiscal'), 'NFS-E'),
    equals(variables('varTipoDocFiscal'), 'NFF'),
    equals(variables('varTipoDocFiscal'), 'NFSTE'),
    equals(variables('varTipoDocFiscal'), 'NFSC')
  ),
  setProperty(
    setProperty(
      variables('varResultado'),
      'baseICMS',
      '0'
    ),
    'valorBaseIPI',
    '0'
  ),
  variables('varResultado')
)
```

2. Ação: `Definir variável - varResultado (regra baseICMS e valorBaseIPI para serviço)`  
Variável: `varResultado`  
Valor:
```powerautomate
outputs('Compor_-_Resultado_com_baseICMS_e_valorBaseIPI_zerados_para_documento_de_serviço')
```

#### 9.14.2) Aplicação nos itens (`varItensReceb`)
Posicionamento:
- Implementação ocorre dentro do loop `Aplicar a cada - Pedido`.
- Inserir após `Compor - itemReceb completo` e antes de `Acrescentar à variável de matriz - varItensReceb`.

Pré-requisito:
- No início do fluxo, nas declarações de variáveis, manter:
  - `Inicializar variável - tmpObj`
  - Tipo: `Objeto`
  - Valor: `{}`

Sequência dentro do `Aplicar a cada - Pedido`:

1. Ação: `Definir variável - reset de tmpObj`  
Valor:
```powerautomate
outputs('Compor_-_itemReceb_completo')
```

2. Ação: `Condição - tipoDocFiscal é documento de serviço (zerar bases de item)`  
Condição:
```powerautomate
or(
  equals(variables('varTipoDocFiscal'), 'NFS-EG'),
  equals(variables('varTipoDocFiscal'), 'NFS-E'),
  equals(variables('varTipoDocFiscal'), 'NFF'),
  equals(variables('varTipoDocFiscal'), 'NFSTE'),
  equals(variables('varTipoDocFiscal'), 'NFSC')
)
```
Comparação:
```text
é igual a true
```

3. No ramo **True**:

3.1. Ação: `Compor - itemReceb com bases zeradas para serviço`  
Código:
```powerautomate
setProperty(
  setProperty(
    variables('tmpObj'),
    'baseIcms',
    '0'
  ),
  'valorBaseIPI',
  '0'
)
```

3.2. Ação: `Definir variável - atualizar tmpObj`  
Valor:
```powerautomate
outputs('Compor_-_itemReceb_com_bases_zeradas_para_serviço')
```

4. Atualização da ação existente `Acrescentar à variável de matriz - varItensReceb`  
Novo valor:
```powerautomate
variables('tmpObj')
```

Observações técnicas:
- Essa abordagem evita necessidade de array auxiliar adicional para reprocessar todos os itens.
- O mesmo desenho mantém o comportamento original para documentos não classificados como serviço, porque `tmpObj` já está resetado com o item completo antes da condição.

## 10) Expressões úteis (Power Automate)
Exemplos:

```text
coalesce(items('Aplicar_a_cada')?['CC_RATEIO'], items('Aplicar_a_cada')?['CC_PADRAO'])
```

```text
formatNumber(float(variables('valorItem')), '0.00', 'en-US')
```

```text
formatDateTime(addDays(variables('dataDocumentoIso'), int(variables('diasCondPagto'))), 'dd/MM/yyyy')
```

```text
string(items('Aplicar_a_cada')?['ITEM_SEQUENCIA'])
```

## 11) Regras de robustez recomendadas
- Normalizar datas para ISO internamente e formatar para `dd/MM/yyyy` apenas na saída.
- Normalizar monetários com ponto decimal e 2 casas.
- Evitar `null` no payload final quando o ERP esperar string vazia.
- Logar payload de entrada, payload transformado e resposta do endpoint.

### 11.1) Correção de erro na ação `Compor - dataDocumento ISO`
Contexto do erro observado:
- Falha `InvalidTemplate` por `substring` fora do intervalo quando `varResultado.dataDocumento` veio vazio (`""`).
- Exemplo de execução real: `tipoDocFiscal = "BOLP"` com `dataDocumento = ""`.

Regra de correção:
- Não usar `substring` direto em `dataDocumento` sem validar estrutura.
- Converter para ISO (`yyyy-MM-dd`) somente quando a data estiver no padrão `dd/MM/yyyy`.
- Quando ausente/inválida, retornar `""` para não quebrar o fluxo.

Implementação recomendada para a ação `Compor - dataDocumento ISO`:
```powerautomate
if(
  equals(
    length(
      split(
        trim(string(coalesce(variables('varResultado')?['dataDocumento'], ''))),
        '/'
      )
    ),
    3
  ),
  concat(
    last(split(trim(string(coalesce(variables('varResultado')?['dataDocumento'], ''))), '/')),
    '-',
    first(skip(split(trim(string(coalesce(variables('varResultado')?['dataDocumento'], ''))), '/'), 1)),
    '-',
    first(split(trim(string(coalesce(variables('varResultado')?['dataDocumento'], ''))), '/'))
  ),
  ''
)
```

## 12) Aplicação ao caso do pedido 309675
No exemplo fornecido:
- Cabeçalho vem principalmente de OP/DP.
- `numNota = 555` e `serie = UN` vieram da extração da IA multimodal.
- `valorMercadoria` na raiz (`1050.00`) veio da regra do prompt (espelho de `valorTotalDocumento`).
- `valorMercadoria` e `qtdeRecebimento` nos itens passam a vir do DP (`VALOR_TOTAL_ITEM_PEDIDO` e `QUANTIDADE_PEDIDO`), garantindo preenchimento mesmo quando `VALOR_CONFERIDO`/`QUANTIDADE` vierem nulos.
- Parcela única com `condPagto 09D`: vencimento em `13/02/2026`.

