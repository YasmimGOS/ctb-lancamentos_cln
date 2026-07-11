# Regras de Negocio - LancamentoCLN

> **Versao:** 1.4 | **Data:** 10/07/2026 | **Tipo:** Documentacao de Referencia

Este documento consolida **todas as regras de negocio** do projeto LancamentoCLN.
Mantenha sempre atualizado apos mudancas validadas.

---

## 1. Pipeline Geral

O fluxo segue este pipeline obrigatorio:

1. **Obter lista de pedidos** aguardando CLN (BPMS)
2. **Selecionar pedidos** (filtro por codigo ou limite)
3. **Por pedido:**
   - Gate reembolso (bloqueia se identificado)
   - Obter dados do pedido
   - Consultar anexos (PDFs)
4. **Por anexo:**
   - Extrair dados via IA (1a e 2a chamada)
   - Consolidar resposta IA
   - Montar payload JSON
5. **Priorizar payload** (NF > CF > REC > BOLP)
6. **Validar** (APOLICE, CNPJ emitente/tomador, condicao 7 dias)
7. **Lancar no Mega ERP** + registrar (Teams/BD)

---

## 2. Regras de Dados

### 2.1 Datas

- **Formato ERP:** `dd/MM/yyyy`
- **Formato interno:** ISO `yyyy-MM-dd` para calculos
- **dataDocumento:** SEMPRE a data de emissao (NUNCA vencimento)
- **Data invalida:** retornar string vazia `""`

### 2.2 CNPJ

- **Validacao por raiz:** permite matriz vs filial (primeiros 8 digitos)
- **Normalizacao:** sempre remover pontos, barras e hifens
- **Comparacao:**
  - Emitente vs Fornecedor: aceita mesma raiz
  - Tomador vs Filial: aceita mesma raiz + de-para de filiais

### 2.3 Tipo de Documento Fiscal

**Ordem de precedencia:**
1. **APOLICE tem precedencia absoluta** (bloqueia lancamento)
2. De-para por CNPJ do emitente (ex: MAPFRE `61074175000138` vira `BOLP`)
3. Tipo retornado pela IA

**De-para para contasPagarTipoDoc e acao:**

| tipoDocFiscal | contasPagarTipoDoc | acao_vista | acao_prazo |
|---------------|-------------------|------------|------------|
| NF-E | NFC | 295 | 82 |
| NFSTE | NFSTE | 295 | 82 |
| NF3E | NFFEE | 295 | 82 |
| CT-E | CF | 295 | 82 |
| CT-EOS | CF | 295 | 82 |
| NFS-EG | NFS | 295 | 82 |
| NFS-E | NFS | 295 | 82 |
| NFF | NFF | 295 | 82 |
| BOLP | BOLP | 771 | 768 |
| BOLP-DETRAN | BOLP | 770 | 770 |
| BOLP-DETRAN-IPVA-ANTT | BOLP | 768 | 771 |
| RECIBO | REC | 771 | 768 |
| NFSC | NFF | 295 | 82 |
| DANFCom | NFF | 295 | 82 |

**Notas:**
- `BOLP-DETRAN*` viram `BOLP` no cabecalho
- Tipo desconhecido ou APOLICE retorna `{"contasPagarTipoDoc": "", "acao": 0}`

### 2.4 Condicao de Pagamento

**Normalizacao:**
- `"20D M"` → `"20D"` (remove sufixo apos numero+unidade)
- Unidade: `D` (dias) ou `M` (meses)
- Quantidade: extrair numero antes da unidade

**Classificacao a vista:**
- `ADIANT`, `TESOURARIA`, `A VISTA`, `AVISTA`, `CREDITO`

**Bloqueio <= 7 dias:**
- Condicoes com `D` (dias) <= 7 bloqueiam lancamento
- **EXCECAO:** CNPJ `03397056000110` (Aluguel IR) sempre lanca

### 2.5 Valores

**valorMercadoria do item:**
1. Tentar obter do item retornado pela IA
2. Fallback: usar `PED_NU_MERCADORIAS` do pedido
3. Fallback final (boletos): usar `totalNota`

**totalNota:**
- Se `totalNota <= 0`: usa soma dos valores dos itens
- Correcao especial para BOLP

**Documentos de servico** (`NFS-EG`, `NFS-E`, `NFF`, `NFSTE`, `NFSC`):
- Zerar `baseICMS`
- Zerar `valorBaseIPI`

**Aluguel IR** (CNPJ `03397056000110`):
- `valorMercadoria = Aluguel + Encargos`
- IR impresso (logica especifica)

### 2.6 ISS (Imposto sobre Servicos)

**Precedencia de retencao:**
1. Se `valorISSRetido > 0` (da 2a IA): sobrepoe ISS da 1a IA
2. Calcular `percentualISS = (valorISSRetido * 100) / base`
3. Atualizar: `valorISS`, `totalISS`, `baseISS`, `percentualISS`

**Retificacao quando NAO retido:**
- Se IA indicou retencao mas 2a IA diz que nao: zerar todos campos ISS

**Correcao totalISS:**
- Se `valorISS > 0` e `totalISS <= 0`: copiar `valorISS` para `totalISS`

### 2.7 Outros Campos

**numNota:**
- Remover zeros a esquerda
- Se vazio: usar `PDC_IN_CODIGO` (codigo do pedido)

**serie:**
- Tipos `NF-E`, `NFSC`, `NFSTE`, `NF3E`: usar serie da IA ou extrair da chave (posicoes 22-25)
- CNPJ especifico `34274233030605`: serie = `"0"`
- Outros tipos: `"UN"`

**chaveAcesso:**
- Tipos `NFS-EG`, `NFS-E`, `BOLP*`: sempre vazio
- Outros: usar chave retornada pela IA

---

## 3. Regras de Bloqueio

### 3.1 Reembolso
- **Trigger:** `AGN_ST_FANTASIA` contem "REEMBOLSO"
- **Acao:** NAO lancar + notificar Teams + registrar BD
- **Mensagem:** "Pedido {pdc} identificado como REEMBOLSO. Requer lancamento manual."

### 3.2 Apolice de Seguro
- **Trigger:** `tipoDocFiscal == "APOLICE"`
- **Acao:** NAO lancar + notificar Teams + registrar BD
- **Mensagem:** "Pedido {pdc} identificado como Apolice de Seguro. Requer lancamento manual."

### 3.3 CNPJ Emitente Divergente
- **Trigger:** CNPJ do emitente != CNPJ do fornecedor (validacao por raiz)
- **Acao:** NAO lancar + notificar Teams
- **Mensagem:** "Pedido {pdc}: CNPJ do emitente divergente (Fornecedor: {cnpj_forn} / Emitente: {cnpj_emit})."

### 3.4 CNPJ Tomador Divergente
- **Trigger:** CNPJ do tomador != CNPJ da filial (validacao por raiz + de-para)
- **Acao:** NAO lancar + notificar Teams
- **Mensagem:** "Pedido {pdc}: CNPJ do tomador divergente (Filial: {cnpj_fil} / Tomador: {cnpj_tom})."

### 3.5 Condicao Pagamento <= 7 dias
- **Trigger:** Vencimento da parcela 1 <= 7 dias da data atual
- **Excecao:** Aluguel IR (CNPJ `03397056000110`)
- **Acao:** NAO lancar + notificar Teams + registrar BD
- **Mensagem:** "Pedido {pdc}: condicao de pagamento <= 7 dias. Lancamento bloqueado."

---

## 4. Integracao IA (Claude)

### 4.1 Fluxo Assincrono

1. **Submit (POST):**
   - Endpoint: `ANTHROPIC_API_URL`
   - Headers: `X-API-Key: {ANTHROPIC_API_KEY}`
   - Body: `{model, prompt, base64_pdf, max_tokens}`
   - Retorno: `{job_id}`

2. **Polling (GET):**
   - Endpoint: `AI_PDF_INTELLIGENCE_STATUS_URL/{job_id}`
   - Intervalo: 30s
   - Max tentativas: 20 (10 minutos)
   - Status esperado: `COMPLETED`

3. **Extracao:**
   - Limpar markdown (```json)
   - Parse JSON

### 4.2 Duas Chamadas por Anexo

**1a IA (extracao completa):**
- Prompt: `prompts/prompt_1a_ia.txt`
- Extrai: todos os campos fiscais, itens, impostos

**2a IA (validacao redundante):**
- Prompt: `prompts/prompt_2a_ia.txt`
- Valida: `chaveAcesso`, `issRetido`, `valorISSRetido`, `cnpjCpfTomador`, `numNota`

### 4.3 Consolidacao

- 2a IA tem precedencia sobre campos especificos
- ISS: regra de precedencia de retencao (ver 2.6)
- Calcular percentuais faltantes por `valor / base * 100`

---

## 5. Filiais (De-Para)

```
"3": RAPIDO ARAGUAIA (01657436000110)
"35": RAPIDO ARAGUAIA (01657436000463)
"36": CREMMY (00693410000165)
"40": VIACAO ARAGUARINA (01552504000187)
"15519": AGROPASTORIL (02737815000426)
"15535": ODILON SANTOS (06992809000123)
"15537": PONTAL (07258201000132)
"150103": RAPIDO ARAGUAIA (01657436000625)
"221461": MOTO FOR (02862548000176)
```

---

## 6. Execucao Paralela

- **Controle:** `MAX_WORKERS` (padrao: 1 = sequencial)
- **Sugestao:** 4-8 workers para I/O intensivo
- **Isolamento:** falha em 1 pedido NAO derruba o lote
- **Selecao:** `LIMITE_PEDIDOS` (0 = todos) quando nao ha filtro

---

## 7. Modo Teste

**Variaveis de ambiente:**
- `MODO_TESTE=True`: evita escrita externa
- `ENVIAR_WEBHOOK_EM_TESTE=False`: nao envia Teams em teste
- `USAR_PDF_MOCK=True`: usa mocks de PDF
- `CODIGO_TESTE=7794`: processa SOMENTE esse pedido
- `FILTRO_PEDIDOS=7794,320085`: lista CSV de pedidos

---

## 8. Notificacoes Teams

**Webhook:** `POWER_AUTOMATE_WEBHOOK_URL`

**Formato das mensagens:**
- SEM emojis
- SEM detalhes tecnicos desnecessarios
- Objetivas e diretas

**Exemplos:**
- Sucesso: `Pedido 7794 lancado com sucesso. NF 12345 | Transacao 67890`
- Aviso: `Pedido 7794 identificado como REEMBOLSO. Requer lancamento manual.`
- Erro: `Falha ao lancar pedido 7794. Verificar logs para detalhes.`

---

## 9. Changelog

### v1.4 (10/07/2026)
- Reescrita Python (arquitetura em camadas)
- Precedencia absoluta de APOLICE
- Validacao CNPJ por raiz (matriz vs filial)
- Normalizacao condicao de pagamento
- Blindagem quantidade (0 se nao numerico)
- Fallback valorMercadoria/totalNota (boletos)
- APOLICE no prompt da IA
- Bloqueio reembolso antes do lancamento
- Execucao paralela (MAX_WORKERS)
- Mensagens Teams sem emojis e objetivas
- Estrutura simplificada: arquivos na raiz (sem src/)

---

**IMPORTANTE:** Este documento e a fonte unica da verdade para regras de negocio.
Sempre atualize apos validacao de mudancas.
