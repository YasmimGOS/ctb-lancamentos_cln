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
2. De-para por CNPJ do emitente (ex: MAPFRE `61074175000138` vira `BOLP`; MEI de Goiania
   `19164502000186` (RONILSON COSTA DE MOURA) vira `NFS-E`, nunca `NFS-EG`)
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

### 2.6bis CNPJ do Emitente Corrigido por Fornecedor Conhecido

Alguns fornecedores fazem a IA errar a leitura do CNPJ do emitente com frequencia (ex.: le um
CNPJ incompleto/truncado). Para esses casos conhecidos, o CNPJ correto e forcado via de-para
fixo, usando o fornecedor **cadastrado no pedido** (`AGN_ST_FANTASIA`) como chave - nao o nome
lido pela IA.

- **Config:** `config/settings.py::CNPJ_CORRETO_POR_FANTASIA`
- **Regra:** `services/business_rules.py::resolver_cnpj_emitente_corrigido`
- **Aplicado em:** `controllers/lancamento_controller.py::processar_pedido`, logo apos
  `etl.consolidar_resposta_ia`, antes de montar o payload e das validacoes de CNPJ
- **Casos cadastrados:**
  - `EQUATORIAL ENERGIA GOIAS` (fantasia do fornecedor cadastrado no pedido) -> CNPJ do emitente
    `01543032000104` (Equatorial Goias Distribuidora de Energia S.A.; adicionado em 16/07/2026 -
    a IA lia `340577401231`, incompleto)

Nao confundir com o tomador desses mesmos documentos: quando a filial compradora e o Condominio
Shopping Center Cerrado (filial 235758), o tomador correto e CCP Cerrado Empreendimentos
Imobiliarios S.A., CNPJ `13619137000251` - ja tratado via `DEPARA_FILIAIS` (ver secao 5).

### 2.6ter Emitente/Tomador Invertidos pela IA (RECIBO/Termo)

Em RECIBO ou "Termo" assinado por pessoa fisica prestadora de servico, a IA pode inverter os
papeis: le o CNPJ da FILIAL (quem pagou) como `cnpjEmitente` e o CNPJ do FORNECEDOR cadastrado no
pedido (quem prestou o servico e assinou) como `cnpjCpfTomador` - o oposto do correto (ver regra
de extracao em `prompts/prompt_1a_ia.txt`, "Definicao de emitente/tomador em RECIBO").

Deteccao e correcao automatica (sem depender de CNPJ especifico, generaliza para qualquer
fornecedor): se `cnpjEmitente` extraido bate com o CNPJ da filial esperada E `cnpjCpfTomador`
extraido bate com o CNPJ do fornecedor cadastrado no pedido, os dois campos (nome + CNPJ) sao
trocados de volta antes de montar o payload e rodar as validacoes.

- **Regra:** `services/business_rules.py::corrigir_emitente_tomador_invertidos`
- **Aplicado em:** `controllers/lancamento_controller.py::processar_pedido`, logo apos a correcao
  de CNPJ por fornecedor conhecido (2.6bis), antes de montar o payload
- **Corrige caso real:** pedido 320931, RECIBO/termo de SERGIO GLEIK DAVID (CPF `58870067149`,
  fornecedor cadastrado no pedido) lido com `nomeEmitente`/`cnpjEmitente` = RAPIDO ARAGUAIA LTDA
  (a filial, CNPJ `01657436000110`) e `nomeTomador`/`cnpjCpfTomador` = SERGIO GLEIK DAVID -
  invertido, causando bloqueio "CNPJTomador" indevido (ver 3.4).

### 2.6quater CNPJ do Tomador Corrigido por Fornecedor Conhecido (17/07/2026)

Mesmo padrão da seção 2.6bis (CNPJ do emitente), mas para o **tomador** - alguns fornecedores
emitem documentos (ex.: fatura de energia elétrica, sem seção "Tomador" explícita) em que a IA
confunde outro número de 11 dígitos presente no documento (CPF de produtor rural, código de
registro de imóvel etc.) com o CNPJ/CPF do tomador. Para esses casos conhecidos, o CNPJ correto é
forçado via de-para fixo, usando o fornecedor **cadastrado no pedido** (`AGN_ST_FANTASIA`) como
chave.

- **Config:** `config/settings.py::CNPJ_TOMADOR_CORRETO_POR_FANTASIA`
- **Regra:** `services/business_rules.py::resolver_cnpj_tomador_corrigido`
- **Aplicado em:** `controllers/lancamento_controller.py::processar_pedido`, logo após a correção
  de CNPJ do emitente (2.6bis) e antes da correção de emitente/tomador invertidos (2.6ter)
- **Casos cadastrados:**
  - `ENERGISA TOCANTINS - DISTRIBUIDORA DE ENERGIA S.A` (fantasia do fornecedor cadastrado no
    pedido) -> CNPJ do tomador `02737815000183` (Araguarina Agropastoril Ltda - Faz. Pé do Morro,
    filial 46; adicionado em 17/07/2026 - caso real: pedido 25997/nota 7853277, a IA leu
    `834.663.015-42` - um número impresso perto do endereço de entrega/dados do imóvel rural,
    aparentemente um CPF do produtor ou registro do imóvel, não o CNPJ do tomador - em vez do
    CNPJ real, impresso no campo "PAGADOR CPF/CNPJ" da ficha de compensação da fatura).
- **Cautela:** este de-para assume que o fornecedor sempre fatura a mesma filial/tomador nesta
  operação - não é uma verdade universal do fornecedor, é uma coincidência operacional atual. Se
  esse mesmo fornecedor passar a faturar outras filiais, este de-para pode aplicar o CNPJ errado
  e precisa ser revisto/generalizado (ex.: chave composta fornecedor+filial, não só fornecedor).
- **Correção complementar (mais robusta a longo prazo):** também foi adicionada uma regra
  explícita em `prompts/prompt_1a_ia.txt` e `prompts/prompt_2a_ia.txt` orientando a IA a usar o
  campo "PAGADOR CPF/CNPJ" da ficha de compensação como fonte de `cnpjCpfTomador` em faturas de
  energia elétrica (DANF3E/DANFE3e), e a não confundir esse campo com outros números de 11
  dígitos que aparecem no cabeçalho/domicílio de entrega. O de-para acima é uma rede de segurança
  adicional enquanto essa correção de prompt ainda não foi validada contra uma nova chamada real
  de IA para este fornecedor.

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

### 3.6 PIS/COFINS reconhecidos - PALIATIVO PROVISORIO (ATIVO)

> **ATENCAO:** esta e uma regra **temporaria/paliativa**, nao uma regra de negocio definitiva.
> Criada em 16/07/2026 porque ainda nao ha controle confiavel do lancamento correto de
> PIS/COFINS. Enquanto a TI nao resolve, o robo bloqueia ANTES de lancar em vez de lancar
> errado e precisar excluir o lancamento no Mega depois (excluir era o problema que motivou
> este paliativo).

- **Trigger:** payload com `valorPIS` ou `valorCOFINS` reconhecido (> 0) na raiz OU em algum
  item de `itensReceb` (`valorPIS`/`valorCofins`).
- **Acao:** NAO lancar + notificar Teams + registrar BD com status **"Provisorio"** (para nao
  reprocessar o pedido nas proximas execucoes).
- **Mensagem Teams:** pedido possui PIS/COFINS reconhecido, ha problema tecnico ainda em
  resolucao no lancamento desses tributos, pedido sera lancado manualmente. Acao PROVISORIA
  ate ajuste da TI.
- **Onde esta implementado:**
  - `services/business_rules.py::eh_pis_cofins_reconhecido` (regra pura)
  - `controllers/lancamento_controller.py::_validar_e_lancar_payload` - "Validação 9: PIS/COFINS
    reconhecidos" (bloqueio + notificacao + registro BD)
- **LIGA/DESLIGA rapido (sem mexer em codigo):** variavel `BLOQUEIO_PIS_COFINS_ATIVO` no
  `config/.env`. `True` (padrao) = paliativo ativo. `False` = desativa o bloqueio - documento com
  PIS/COFINS passa a lancar normalmente (sem zerar os valores). Usar isso pra testar rapido se a
  TI resolveu, antes de remover o codigo de vez.
- **COMO REMOVER de vez quando a TI resolver o lancamento de PIS/COFINS:**
  1. Apagar a função `eh_pis_cofins_reconhecido` em `services/business_rules.py`.
  2. Apagar o bloco "Validação 9" (e o if/else de `bloqueio_pis_cofins_ativo`) em
     `_validar_e_lancar_payload` (`controllers/lancamento_controller.py`).
  3. Apagar o campo `bloqueio_pis_cofins_ativo` em `config/settings.py` e a variavel
     `BLOQUEIO_PIS_COFINS_ATIVO` em `config/.env`.
  4. Apagar a nota "PALIATIVO PROVISÓRIO ATIVO" no docstring do topo de
     `lancamento_controller.py`.
  5. Apagar esta seção 3.6 (ou marcar como resolvida no changelog abaixo).

### 3.7 Aplicacao do item - HIPOTESE TESTADA E REFUTADA (16/07/2026)

> **HISTORICO (nao repetir este caminho):** ao investigar a nota 19 / pedido 752 (divergencia de
> Valor da Parcela/CSLL e PIS-COFINS zerados em "Totais do documento", ver incidente que motivou
> a secao 3.6), chegou-se a hipotese de que o campo `aplicacao` do item deveria ser forcado para
> "933" em documentos de servico, em vez do valor herdado do pedido de compra (109). Essa hipotese
> foi **implementada, testada e revertida no mesmo dia** apos confirmacao com a tela
> "Aplicacao do Produto" do Mega: o codigo **109** ja e a aplicacao correta, com descricao oficial
> "Servicos S/ Credito de PIS-COFINS"; "933" nao e um codigo de Aplicacao alternativo - e o
> "Sufixo do CFOP" associado a aplicacao 109 (coluna separada na tela de cadastro, compartilhada
> por outras aplicacoes como 107 e 108). Ou seja, `aplicacao` **nunca foi a causa** da divergencia.
> Nenhuma alteracao de codigo ficou pendente desta investigacao - `etl_service.py`,
> `lancamento_controller.py`, `config/settings.py` e `config/.env` foram revertidos ao estado
> anterior no mesmo dia.
- **Causa raiz da divergencia original (nota 19):** continua **nao identificada**. Proxima linha
  de investigacao sugerida: o campo `calculaValores` (enviado como `"N"` na raiz e em cada item)
  pode estar fazendo o Mega aceitar os valores informados nos campos individuais sem agrega-los
  corretamente em "Totais do documento" nem recalcular "Valor da Parcela" do mesmo jeito que
  quando um humano abre a tela "Gerar Parcelas" manualmente. Isso ainda precisa ser testado (de
  preferencia num pedido de teste, nao em producao) antes de qualquer mudanca de codigo.
- **Pendente:** nota 19 (transacao Mega 7891049) ja lancada e provavelmente precisa de
  correcao manual/estorno pela Controladoria, independente da causa raiz ainda nao confirmada.

### 3.8 Campos ausentes na raiz do payload - EM TESTE (16/07/2026)

> **Contexto:** time fiscal confirmou que a tributacao do item esta correta (PIS/COFINS/CSLL
> calculados certinho, ver print "Informacoes da Tributacao no Documento"), mas na aba
> Movimentacao do AP so aparecem "Retencao da CSLL" e "Retencao de IR" como lancamentos - PIS e
> COFINS nao viram movimento nenhum, e a CSLL vai pro agente 20 em vez do agente consolidador
> (505) que deveria somar as retencoes de PIS+COFINS+CSLL.

- **Achado:** comparando o payload atual (Python) com o template original do fluxo Power
  Automate (`docs/Json pac.txt`, acao "Compor - template_raiz", por volta da linha 3485-3537),
  4 campos da raiz existiam no fluxo original e foram perdidos na reescrita em Python:
  `valorMercadoriaEmpenhada`, `tragnCodigo`, `tipoTrans`, `icmsStreRecupera`. Nenhum dos 4 e
  preenchido com valor real em nenhum outro passo do fluxo original (ficam sempre `""`), mas
  isso nao significa que sejam inofensivos - e possivel que o Mega Integrador/middleware
  dependa da simples PRESENCA dessas chaves no JSON pra inicializar o roteamento de retencao
  combinada pro agente 505, mesmo com valor vazio.
- **Teste aplicado:** restaurados os 4 campos (vazios, `""`, igual ao original) em
  `models.py::PayloadRecebimento` e `services/etl_service.py::montar_payload`. Validado via
  script ad-hoc que o payload gerado inclui as 4 chaves e o Pydantic aceita normalmente; nenhuma
  outra logica foi alterada.
- **Como reverter (se nao resolver ou piorar):** remover as 4 linhas adicionadas em
  `services/etl_service.py` (marcadas com comentario "TESTE EM VALIDACAO") e as mesmas 4 em
  `models.py::PayloadRecebimento`. Mudanca isolada e pequena, sem flag de ambiente (nao precisa -
  e so a presenca de 4 chaves vazias, reverter = apagar as linhas).
- **Proximo passo:** rodar o robo contra um pedido real (usuario confirmou que consegue excluir/
  estornar lancamentos no Mega se o teste sair errado) e conferir na tela do Mega se PIS/COFINS
  passam a aparecer como "Retencao" na aba Movimentacao do AP, e se a CSLL vai pro agente 505 em
  vez do 20.
- **Pendente (nao relacionado a este teste):** `tests/test_pipeline.py::test_montar_payload_nfse_iss_retido`
  ja estava com uma asercao desatualizada antes desta investigacao (espera `valorMercadoria ==
  "1500.00"`, mas o codigo atual retorna "1530.00" porque reconstitui o bruto somando o ISS
  retido ao liquido para documentos de servico) - nao mexi nisso agora por estar fora do escopo
  desta investigacao, mas fica registrado para quem for revisar os testes depois.

### 3.9 valorMercadoria (bruto) de servico: preferir o pedido de compra, nao reconstruir por tributos (17/07/2026)

> **CORRIGIDO.** Pedido 320921 / nota 5473 (Electric Mobility, R$ 90,00) foi rejeitado pelo Mega:
> "Soma dos Valores das Parcelas[92,65] não confere com o Total da Fatura[90,00]".

- **Causa raiz:** para documentos de servico, `montar_payload` reconstruia o "Valor Total do
  Servico" (bruto) somando o liquido (`valorTotalDocumento`) aos tributos extraidos da NF
  (`_impostos_retidos`: ISS+PIS+COFINS+CSLL+IRRF+INSS). Isso falha quando a NF traz PIS/COFINS
  **informativos** (nao retidos - nota de rodape comum em NFS-e: "Informações preenchidas nos
  campos de PIS e COFINS são referentes aos valores totais sobre a operação") junto de tributos
  realmente retidos (IRRF/CSLL): a soma superestima o bruto. No caso real: bruto verdadeiro =
  R$90,00 (confirmado pela própria NF e pelo pedido de compra), reconstrução antiga = R$92,65
  (líquido 84,46 + IRRF 1,35 + "INSS" 6,84 - este último, na verdade, o COFINS informativo lido
  em campo trocado pela IA).
- **Correção:** em `services/etl_service.py::montar_payload`, quando `soma` (soma de
  `VALOR_TOTAL_ITEM_PEDIDO` dos itens do pedido de compra) for maior que zero, usar esse valor
  como `valorMercadoria`/`valorParcela` da raiz, em vez de reconstruir pelos tributos da IA. É a
  mesma fonte já usada no item (`montar_item`) e a mesma que o Mega valida como "Total da
  Fatura" - elimina a divergência interna entre item e raiz. Mantém o cálculo antigo (líquido +
  tributos) como fallback só quando o pedido não tiver esse valor cadastrado.
- **Por que é seguro:** testado contra os dois casos reais conhecidos - nota 5473/Electric
  Mobility (antes divergia, agora bate 90,00 = 90,00) e nota 19/SLS Empreendimentos (resultado
  idêntico ao anterior, 61.815,12, sem regressão).
- **Ainda em aberto (fora do escopo deste ajuste):** a causa de fundo mais profunda - saber com
  certeza QUAIS tributos de uma NFS-e são realmente retidos vs. apenas informativos (hoje o
  código assume que ISS precisa de confirmação explícita via IA, mas PIS/COFINS/CSLL/INSS não
  têm esse mesmo tratamento) - continua não resolvida e pode gerar valores errados no item
  (`itensReceb[].valorPIS/valorCofins/valorCSLL`) mesmo com a raiz agora correta. Ver também a
  seção 3.6 (paliativo) e considerar estender a mesma lógica de `issRetido`/`valorISSRetido`
  (prompts/prompt_2a_ia.txt) para PIS/COFINS/CSLL.

---

### 3.10 Divergência entre pedido de compra e NF (bruto) - nova validação proativa (17/07/2026)

> **CORRIGIDO - risco descoberto em produção.** A correção da seção 3.9 (preferir o valor do
> pedido de compra como `valorMercadoria`) resolveu a rejeição do Mega, mas abriu uma brecha: se
> o PRÓPRIO pedido de compra estiver cadastrado com um total diferente do bruto real da nota
> fiscal, o lançamento passa no Mega (bate com o que o Mega tem cadastrado) mas registra um valor
> **errado** em relação à NF real, sem nenhum aviso.

- **Caso real que expôs o problema:** pedido 320868 / nota 193 (Rápido Araguaia, fornecedor
  Divulg Letreiros). A NF mostra "Valor dos Serviços" (bruto) = R$ 480,00, ISS retido = R$ 11,52,
  Valor Líquido = R$ 468,48 (480,00 − 11,52 = 468,48, bate certinho). O pedido de compra, porém,
  estava cadastrado no Mega com soma de itens = R$ 456,89 (diferente do bruto real da NF). O robô
  usou 456,89 como `valorMercadoria` (regra da seção 3.9), o Mega aceitou o lançamento (código de
  transação 7907369, pk `53;1;2;G;53;1;89271;F;193;14/07/2026`) porque bateu com o próprio pedido
  - mas o valor lançado ficou incorreto em relação à nota fiscal real (diferença de R$ 23,11).
  **Este lançamento específico precisa de correção manual no Mega** (ajustar o pedido de compra
  para R$ 480,00 e relançar, ou corrigir diretamente o lançamento/transação 7907369).
- **Causa raiz:** ao remover a divergência interna (item vs. raiz), também removemos o único sinal
  que existia (a rejeição 400 do Mega "Soma dos Valores das Parcelas x Total da Fatura") de que o
  pedido de compra e a NF não batem. Sem esse sinal, o robô passou a lançar silenciosamente com o
  valor do pedido, mesmo quando ele diverge do valor real da nota.
- **Correção:** nova validação proativa em `services/etl_service.py::montar_payload` - compara o
  bruto extraído DIRETO do documento pela IA (`ia["valorMercadoria"]`, o campo "Valor Total do
  Serviço"/"Valor dos Serviços" impresso na NF) contra `soma` (pedido de compra). Se divergirem
  além de uma tolerância de arredondamento (R$ 0,05), a função retorna um terceiro valor
  (`divergencia_pedido_nf`, antes a função retornava só `(payload, bloqueia_7d)`, agora
  `(payload, bloqueia_7d, divergencia_pedido_nf)`) com os dois valores para o controller decidir.
  Em `controllers/lancamento_controller.py`, nova **Validação 9** (antes de tentar o lançamento no
  Mega): se houver divergência, bloqueia o lançamento, notifica o Teams e registra no BD com
  status "Falha"/"PedidoValorDivergente" - reproduzindo, de forma proativa, a mesma proteção que
  antes vinha implicitamente da rejeição 400 do Mega. A validação de PIS/COFINS (seção 3.6) foi
  renumerada de "Validação 9" para "Validação 10" para abrir espaço para esta nova checagem.
- **Testado:** script ad-hoc confirma que o caso Rápido Araguaia (480,00 vs. soma do pedido)
  dispara a divergência corretamente, que o caso Electric Mobility (90,00 = 90,00, seção 3.9) não
  tem falso positivo, e que uma diferença de arredondamento de R$ 0,03 fica dentro da tolerância.
- **Como reverter:** remover o bloco de cálculo de `divergencia_pedido_nf` em
  `etl_service.py::montar_payload` (voltar a retornar só `(payload, bloqueia_7d)`), remover a
  Validação 9 em `lancamento_controller.py` e renumerar a validação de PIS/COFINS de volta para 9,
  e reverter a linha `payload, bloq7, _diverge = etl.montar_payload(...)` em `tests/test_pipeline.py`.
- **Ainda em aberto:** mesmo com essa proteção, o pedido 320868/nota 193 (Rápido Araguaia) e
  qualquer outro pedido similar cadastrado ANTES desta correção pode já ter sido lançado com valor
  incorreto - vale uma checagem retroativa nos lançamentos de documentos de serviço feitos entre a
  aplicação da seção 3.9 e desta seção 3.10.
- **Caso irmão via rejeição NATIVA do Mega (não é a Validação 9 acima, é o handler pré-existente
  "Valor Unitário"/Origem/Recebimento em `lancamento_controller.py::_lancar`, não construído nesta
  sessão):** pedido 25997/nota 7853277 (Energisa Tocantins) - Mega rejeitou porque o pedido de
  compra está cadastrado com R$ 1.836,84 (só a linha "Consumo em kWh"), enquanto a fatura real soma
  R$ 1.873,10 (Consumo 1.836,84 + Adicional Bandeira Amarela 36,26, confirmado lendo o PDF). Mesma
  natureza dos outros casos desta seção (cadastro do pedido de compra incompleto/errado no Mega) -
  bloqueado corretamente, status "PedidoValorUnitarioDivergente", NÃO registrado no BD (reprocessa
  sozinho após a correção do pedido de compra no Mega). Não exigiu mudança de código.

---

### 3.11 Faturas de energia elétrica (Equatorial) - FORNECIMENTO / ITENS FINANCEIROS (17/07/2026)

> **CORRIGIDO.** Pedido 872 / nota 199225903 (Equatorial Goiás Distribuidora de Energia, filial
> 221461/MOTO FOR) foi rejeitado pelo Mega: `"Item: (1) - Campo: (Valor Unitário) - Origem:
> (284,46) - Recebimento (328,64)"`. Não foi lançado (status `PedidoValorUnitarioDivergente`, não
> registrado no BD - reprocessa normalmente na próxima execução).

- **Causa raiz:** a fatura de energia elétrica (DANFE3e/NF3e) não é um documento de
  mercadoria/serviço comum - o template genérico de extração da IA (prompt_1a_ia.txt) não tem
  campos para as seções específicas dessas faturas, e `valorMercadoria` sai `"0.00"`. O código
  então caía no fallback `total_nota` (`valorTotalDocumento`, o TOTAL da fatura = R$ 328,64) tanto
  no item quanto na raiz. Só que o Mega valida o item do recebimento contra a seção
  **FORNECIMENTO** da fatura (R$ 284,46 = R$ 5,89 "ADC BANDEIRA AMARELA" + R$ 278,57 "CONSUMO"),
  não contra o total. A diferença entre FORNECIMENTO (284,46) e o TOTAL (328,64) é a seção
  **ITENS FINANCEIROS** (R$ 44,18 = contrib. iluminação pública 37,74 + juros moratória 0,07 +
  multa 3,92 + taxa endereçamento alternativo 2,45 - todos positivos neste caso).
- **Regra de negócio (conforme instrução do usuário):** para faturas de energia elétrica,
  `valorMercadoria` (raiz e item) = soma dos valores da seção **FORNECIMENTO**. Os valores da
  seção **ITENS FINANCEIROS**: se todos positivos, a soma vai para `totalDespesa` ("despesas
  acessórias"); se houver valores negativos (créditos/descontos/estornos), a soma (em módulo,
  sem o sinal) desses negativos vai para `valorDescontoGeral` ("descontos") - os dois casos podem
  coexistir (positivos em `totalDespesa`, negativos em `valorDescontoGeral`, ao mesmo tempo).
- **Correção implementada:**
  1. Novo prompt `prompts/prompt_3a_equatorial_ia.txt` - extrai `itensFornecimento` e
     `itensFinanceiros` (listas de valores individuais de cada linha das duas seções, preservando
     sinal negativo quando houver crédito/desconto/estorno).
  2. `services/ia_service.py::IaService.extrair_equatorial` - nova 3ª chamada de IA, **condicional**
     (só executa quando `business_rules.eh_fornecedor_equatorial(fantasia)` for verdadeiro - não
     onera os demais documentos com uma chamada extra).
  3. `services/business_rules.py::aplicar_valores_equatorial(ia, itens_fornecimento,
     itens_financeiros)` - soma as duas listas e escreve `valorMercadoria`, `totalDespesa` e
     `valorDescontoGeral` no dicionário `ia` consolidado. Se `itensFornecimento` vier vazia, NÃO
     sobrescreve `valorMercadoria` (evita zerar o documento por falha pontual desta extração).
  4. `controllers/lancamento_controller.py` - chama `extrair_equatorial` logo após a extração
     extra (só quando é fornecedor Equatorial) e aplica `aplicar_valores_equatorial` dentro do
     bloco que já existia para zerar PIS/COFINS da Equatorial (mesmo ponto do fluxo).
  5. Nenhuma mudança em `services/etl_service.py` - `montar_item`/`montar_payload` já usam
     `ia.get("valorMercadoria")`/`ia.get("totalDespesa")`/`ia.get("valorDescontoGeral")`
     diretamente quando o documento não é serviço nem aluguel, então bastou popular esses campos
     corretamente no dicionário `ia` antes de montar o payload.
- **Testado com os valores reais da nota 199225903:** `itensFornecimento=["5.89","278.57"]`,
  `itensFinanceiros=["37.74","0.07","3.92","2.45"]` → `valorMercadoria`/item `valorMercadoria` =
  "284.46" (bate exatamente com o "Origem: (284,46)" da rejeição do Mega), `totalDespesa`="44.18",
  `valorDescontoGeral`="0.00", `totalNota` inalterado ="328.64" (284,46+44,18=328,64, confere).
  Testado também um caso hipotético com valor negativo misturado (desconto) e o caso de
  `itensFornecimento` vazio (fallback preserva o valor anterior) - ambos corretos.
- **Como reverter:** remover a chamada a `extrair_equatorial` e o bloco de aplicação de
  `aplicar_valores_equatorial` em `lancamento_controller.py`, remover a função
  `aplicar_valores_equatorial` de `business_rules.py`, remover `extrair_equatorial`/
  `PROMPT_EQUATORIAL` de `ia_service.py` e apagar `prompts/prompt_3a_equatorial_ia.txt`.
- **Ainda em aberto:** só testado com uma fatura real (nota 199225903, sem itens negativos em
  ITENS FINANCEIROS) - o comportamento com créditos/descontos negativos foi validado só com dados
  sintéticos, não com uma fatura real. Vale confirmar no próximo caso real que tiver desconto. A
  correção é específica para fornecedor com fantasia contendo "EQUATORIAL"
  (`eh_fornecedor_equatorial`) - se outras distribuidoras de energia (outras concessionárias) forem
  processadas pelo robô no futuro, a mesma lógica provavelmente se aplica mas o gatilho
  (`eh_fornecedor_equatorial`) precisará ser generalizado.

> **ATUALIZAÇÃO (mesmo dia, ~1h depois): a primeira versão da extração falhou em produção.**
> Rodando de novo contra a mesma nota 199225903, a extração Equatorial (3ª chamada de IA) retornou
> `itensFornecimento` com 9 valores (esperado: 2) e `itensFinanceiros` com 10 valores (esperado: 4)
> - ela misturou a tabela "Itens da Fatura" com uma caixa completamente separada da fatura, a caixa
> "Tributos" (resumo de PIS/PASEP, ICMS, COFINS do documento inteiro), e também pegou colunas
> erradas dentro da própria tabela (coluna "PIS/COFINS" e coluna de Valor ICMS, em vez de só
> "Valor (R$)"). Resultado: `valorMercadoria` calculado = R$ 623,62 (deveria ser R$ 284,46) - o
> Mega rejeitou de novo (`"Origem: (284,46) - Recebimento (623,62)"`), então **nenhum dado errado
> chegou a ser lançado**, mas o precedente mostra que a extração original (seção acima) não era
> confiável o suficiente para uso automático sem uma segunda camada de proteção.
>
> **Correção adicional:**
> 1. `prompts/prompt_3a_equatorial_ia.txt` reescrito: agora pede itens ROTULADOS
>    (`{"descricao": "...", "valorReais": "..."}` em vez de uma lista solta de números), explica
>    explicitamente que existem DUAS tabelas parecidas na fatura e que a caixa "Tributos" (PIS/PASEP,
>    ICMS, COFINS) deve ser **totalmente ignorada**, e inclui um exemplo numérico completo
>    ilustrando o formato esperado e quais colunas usar/não usar dentro da tabela "Itens da Fatura".
> 2. Nova função `services/business_rules.py::reconciliacao_equatorial(ia, tolerancia=0.05)` -
>    confere que `valorMercadoria (FORNECIMENTO) + totalDespesa (itens financeiros positivos) -
>    valorDescontoGeral (itens financeiros negativos)` bate com `valorTotalDocumento` (o TOTAL da
>    fatura, extraído de forma independente na 1ª chamada de IA). Se não bater, a extração das
>    seções está incorreta.
> 3. `controllers/lancamento_controller.py`: depois de aplicar `aplicar_valores_equatorial`, chama
>    `reconciliacao_equatorial`; se falhar, **não lança automaticamente** - notifica o Teams com o
>    motivo e os valores brutos extraídos (para conferência manual) e pula o anexo (mesmo padrão de
>    erro dos outros `except` desse loop - pedido não é registrado no BD, pode reprocessar depois).
> 4. Testado com os dados reais desta falha: a extração ruim (623,62 vs 328,64 esperado) é
>    corretamente rejeitada pela reconciliação; a extração correta (284,46 + 44,18 = 328,64) passa
>    normalmente.
> - **Lição:** para documentos com múltiplas tabelas numéricas visualmente parecidas (fatura de
>   energia é o primeiro caso conhecido), uma extração "livre" (lista de valores) é frágil demais -
>   exigir rótulo (`descricao`) por item e uma reconciliação matemática independente (contra um
>   total já confiável) é o padrão a seguir para casos futuros parecidos.
> - **Ainda em aberto:** a correção do prompt (itens rotulados + exemplo) ainda não foi testada
>   contra uma chamada real de IA (só testada com dados construídos manualmente) - o usuário
>   precisa rodar de novo o pedido 872 para confirmar que a nova versão do prompt extrai
>   corretamente `[{"descricao":"ADC BANDEIRA AMARELA","valorReais":"5.89"},
>   {"descricao":"CONSUMO","valorReais":"278.57"}]` e os 4 itens financeiros. Se a IA ainda errar
>   mesmo com o prompt novo, ao menos a reconciliação vai impedir um lançamento errado - mas o
>   pedido continuará não sendo lançado automaticamente até a extração ficar confiável.

> **ATUALIZAÇÃO 2 (mesmo dia, ~10min depois): 2ª tentativa também falhou - a reconciliação
> bloqueou de novo, sem dano.** A extração usando o prompt rotulado (atualização acima) ainda
> errou, mas de um jeito diferente e revelador: tratou o próprio título de seção "FORNECIMENTO"
> como se fosse uma linha de dado (com valor 278,57, que é na verdade o "Valor (R$)" do CONSUMO),
> o que desalinhou TODAS as linhas seguintes por uma posição - "ADC BANDEIRA AMARELA" recebeu
> 37,74 (valor da CONTRIB. ILUM. PÚBLICA), "CONSUMO" recebeu 235,00 (a coluna Quant./kWh, não
> Valor R$), e "CONTRIB. ILUM. PÚBLICA" foi parar em ITENS FINANCEIROS com 5,89 (valor do ADC
> BANDEIRA AMARELA). Os 3 últimos itens financeiros (juros, multa, taxa) saíram corretos. A
> reconciliação (`reconciliacao_equatorial`) detectou a inconsistência (soma 563,64 vs. total
> 328,64) e bloqueou corretamente - **nenhum valor errado foi lançado**, pedido 872 seguiu sem
> registro no BD.
>
> Perguntado sobre como prosseguir (tentar mais uma vez o prompt vs. marcar Equatorial para
> execução manual vs. manter só a rede de segurança), o usuário optou por **tentar mais uma vez o
> prompt**.
>
> **3ª versão do prompt** (`prompts/prompt_3a_equatorial_ia.txt`, reescrito por completo):
> - Alerta explícito, logo no início, contra o erro exato observado: nunca incluir "FORNECIMENTO"
>   ou "ITENS FINANCEIROS" como `descricao` de um item (são títulos de seção, não linhas).
> - Detalha a sequência exata de colunas de uma linha de FORNECIMENTO (Quant. → Preço unit. →
>   Valor (R$) → PIS/COFINS → Base Calc. ICMS → Alíquota ICMS → Valor ICMS → Tarifa unit.),
>   indicando explicitamente qual é a 3ª coluna numérica (a única a usar) e nomeando as armadilhas
>   (Quant. em especial, que foi usada por engano na falha desta vez).
> - Lista descrições típicas de cada seção (FORNECIMENTO: CONSUMO, ADC BANDEIRA AMARELA/VERMELHA,
>   DEMANDA etc.; ITENS FINANCEIROS: contribuições, juros, multa, taxas, descontos) para ajudar a
>   IA a confirmar a seção pela própria descrição da linha, não só pela posição.
> - Inclui, com os números REAIS desta nota (199225903), tanto o resultado CORRETO esperado quanto
>   o resultado ERRADO que já ocorreu em produção lado a lado, para servir de exemplo negativo
>   direto (não mais só um exemplo fictício).
> - Pede uma autoconferência final: a soma das duas listas deve ficar próxima do total da fatura
>   antes de responder.
> - **Ainda não testado contra uma chamada real de IA** - fica pendente rodar novamente o pedido
>   872. Se esta 3ª tentativa também falhar, a recomendação passa a ser reavaliar a abordagem
>   (extração livre por lista parece estruturalmente frágil para esse layout) e considerar mover
>   Equatorial para a lista de fornecedores com execução manual obrigatória
>   (`FANTASIAS_EXECUCAO_MANUAL`) até uma solução mais robusta.

> **ATUALIZAÇÃO 3 (mesmo dia, poucos minutos depois): 3ª tentativa falhou de forma BYTE-IDÊNTICA
> à 2ª, mesmo com o prompt totalmente reescrito.** O usuário rodou de novo o pedido 872 com o
> prompt da "ATUALIZAÇÃO 2" (alerta explícito contra o erro exato, detalhamento de colunas,
> exemplo real correto/errado lado a lado, autoconferência) e a IA retornou **exatamente os
> mesmos valores da falha anterior**: `itensFornecimento` = FORNECIMENTO/278.57,
> ADC BANDEIRA AMARELA/37.74, CONSUMO/235.00 (idêntico). Isso é evidência forte de que o
> problema não é (só) de redação do prompt - a IA multimodal está tendo uma dificuldade
> sistemática e reproduzível de ler esse layout específico de tabela (parece confundir
> visualmente qual número pertence a qual linha/coluna de forma consistente, não aleatória).
>
> **Decisão do usuário: NÃO ir para execução manual - continuar ajustando o prompt.** Cheguei a
> implementar um bloqueio prévio (fornecedor Equatorial -> lançamento manual direto, antes de
> qualquer chamada de IA) e a perguntar ao usuário se preferia isso; a resposta foi explícita:
> **"não é pra ir manual é pra ajustar o prompt"**. O bloqueio manual foi revertido por completo
> (removido de `config/settings.py` e `controllers/lancamento_controller.py`, sem deixar resíduo).
>
> **4ª versão do prompt - mudança de estratégia (transcrição posicional, não mais escolha
> semântica):** as 3 tentativas anteriores pediam para a IA identificar diretamente "qual número é
> o Valor (R$)" dentro de uma linha com 6-8 números parecidos - e ela errava de forma consistente
> (inclusive repetindo o EXACT MESMO erro duas vezes). A nova estratégia muda o que se pede: em vez
> de a IA escolher semanticamente a coluna certa, ela agora só precisa **transcrever TODOS os
> números de cada linha, na ordem em que aparecem** (`"valores": ["235.00", "0.025054", "5.89", ...]`
> por linha de FORNECIMENTO) - uma tarefa de cópia posicional, mais simples e menos sujeita a erro
> de interpretação do que identificar semanticamente qual coluna é qual. A escolha de QUAL número
> da lista é o "Valor (R$)" passa a ser feita em Python (índice 2 - a 3ª coluna, sempre na mesma
> posição: Quant. → Preço unit. → Valor (R$) → PIS/COFINS → ...), não mais pela IA.
> - `prompts/prompt_3a_equatorial_ia.txt`: reescrito para pedir `{"descricao", "valores": [...]}`
>   em vez de `{"descricao", "valorReais"}`; ITENS FINANCEIROS mantém a mesma ideia (lista de 1
>   valor normalmente), já que essas linhas nunca erraram nas 3 tentativas anteriores.
> - `services/business_rules.py`: `_valor_linha_fornecimento` extrai `valores[2]` (com fallback
>   para o último valor disponível se a linha vier com menos de 3 números); `_valor_linha_financeira`
>   extrai `valores[0]` (compatível também com o formato antigo `valorReais`/string simples, caso
>   a IA ainda devolva assim para ITENS FINANCEIROS). `_valores_reais` ganhou o parâmetro
>   `fornecimento: bool` para escolher qual extrator usar.
> - Testado com os dados reais desta nota no novo formato posicional: reconcilia corretamente
>   (284,46 + 44,18 = 328,64). Testado também um caso de fallback (linha com só 1 valor).
> - **Ainda não testado contra uma chamada real de IA** - fica pendente rodar novamente o pedido
>   872. A rede de segurança (`reconciliacao_equatorial`) continua ativa e vai barrar qualquer
>   lançamento se esta 4ª tentativa também vier inconsistente.

> **ATUALIZAÇÃO 5 (mesmo dia): novo caso real - pedido 25998/nota 198531151, com DESCONTO
> negativo - a rede de segurança bloqueou corretamente de novo, sem dano.** A 4ª versão do prompt
> (transcrição posicional) tinha funcionado para o pedido 872 (seção principal acima), mas errou
> neste novo documento, que tem uma característica ainda não testada: um item de ITENS FINANCEIROS
> com valor NEGATIVO ("COMPENSAÇÃO DE DIC MENSAL -105,44", um desconto/crédito).
> - `itensFornecimento` extraído somou R$122,57 (correto seria R$128,49 - pequeno desvio de
>   coluna/casas decimais em alguma linha, não investigado a fundo pois o erro mais grave estava em
>   `itensFinanceiros`).
> - `itensFinanceiros` extraído veio **completamente errado**: `[{"COMPENSAÇÃO DE DIC MENSAL":
>   "104.07"}, {"JUROS MORATÓRIA": "128.49"}, {"MULTA - 06/2026": "24.41"}]`. Comparando com o PDF
>   real, esses três números (104,07 / 128,49 / 24,41) NÃO pertencem a ITENS FINANCEIROS - são,
>   respectivamente, a base do PIS/PASEP, a base do ICMS e o valor do COFINS da caixa "Tributos"
>   (resumo tributário do documento, que o prompt já mandava ignorar). Os valores corretos, que
>   realmente aparecem ao lado de cada descrição em ITENS FINANCEIROS, são -105,44 / 0,56 / 3,73.
>   Ou seja: a IA não só ignorou o sinal negativo, como trocou os 3 valores inteiros pelos da caixa
>   errada - uma falha mais grave que as anteriores (que erravam a coluna dentro da tabela certa,
>   mas não trocavam de tabela inteira para ITENS FINANCEIROS).
> - `reconciliacao_equatorial` calculou 122,57 + 256,97 - 0,00 = 379,54 contra um total de fatura de
>   27,34 (diferença de 352,20) - bloqueou corretamente, notificou Teams com todos os valores brutos
>   para conferência manual, e o pedido não foi lançado nem registrado no BD (**nenhum dado errado
>   chegou ao Mega**, o mesmo padrão de segurança das falhas anteriores).
> - **Conferência manual dos valores corretos** (a partir do PDF, para referência futura): soma de
>   FORNECIMENTO = R$128,49; ITENS FINANCEIROS = -105,44 (desconto) + 0,56 (juros) + 3,73 (multa) =
>   -101,15 líquido; 128,49 + (-101,15) = 27,34 = TOTAL da fatura, confere exatamente. Ou seja, sob
>   a regra de negócio já implementada, o lançamento correto seria `valorMercadoria`="128.49",
>   `totalDespesa`="4.29" (0,56+3,73, só os positivos), `valorDescontoGeral`="105.44" (módulo do
>   negativo) - confirmado com `services/business_rules.py::aplicar_valores_equatorial` rodando
>   sobre os valores corretos digitados manualmente (reconcilia exatamente, ok=True).
> - **Correção aplicada:** `prompts/prompt_3a_equatorial_ia.txt` ganhou duas adições: (1) regra 7,
>   instruindo explicitamente a preservar o sinal de menos quando uma linha de ITENS FINANCEIROS vier
>   negativa (desconto/crédito/estorno), com exemplos de formatos ("-105,44", parênteses); (2) regra
>   8 e um segundo exemplo completo (com os números reais desta nota 198531151), alertando
>   especificamente contra o risco de um número da caixa "Tributos" coincidir ou parecer relevante e
>   ser confundido com um valor de ITENS FINANCEIROS - incluindo lado a lado o resultado ERRADO
>   observado nesta falha real e o resultado CORRETO esperado, e instruindo que, em caso de dúvida
>   sobre qual número pertence a qual linha, é preferível retornar lista vazia a "pegar emprestado"
>   um valor de outra tabela.
> - `services/business_rules.py` NÃO precisou de nenhuma alteração: a lógica de soma de
>   positivos/negativos (`aplicar_valores_equatorial`) e a reconciliação já tratam corretamente
>   valores negativos - confirmado rodando com os dados corretos desta nota (ver acima). O problema
>   estava 100% na extração (prompt), não no código de aplicação da regra.
> - **Ainda não testado contra uma chamada real de IA** com o prompt atualizado - fica pendente
>   rodar novamente o pedido 25998 para confirmar que a 5ª versão do prompt extrai corretamente
>   tanto o valor negativo quanto evita a confusão com a caixa "Tributos". A rede de segurança
>   continua ativa e vai barrar qualquer lançamento se esta tentativa também vier inconsistente.

> **ATUALIZAÇÃO 6 (mesmo dia): 5ª versão testada contra IA real - ITENS FINANCEIROS ficou
> perfeito, mas FORNECIMENTO errou de novo (de um jeito novo) - mudança de estratégia para
> resolver definitivamente.** Rodando de novo o pedido 25998 com o prompt da ATUALIZAÇÃO 5:
> - `itensFinanceiros` saiu **exatamente correto**: `[{"COMPENSAÇÃO DE DIC MENSAL": "-105.44"},
>   {"JUROS MORATÓRIA": "0.56"}, {"MULTA - 06/2026": "3.73"}]` - sinal negativo preservado, sem
>   confusão com a caixa "Tributos". 2ª vitória seguida para essa seção (nota 872 e agora esta).
> - `itensFornecimento`, porém, saiu com um erro diferente das vezes anteriores: linhas
>   deslocadas/duplicadas (o valor da 1ª linha "ADC BANDEIRA AMARELA FP" foi reutilizado para "VL
>   MÍN FAT CUSTO DISP", e daí em diante cada linha recebeu o valor da linha ANTERIOR, um
>   deslocamento em cascata), a IA transcreveu só 5-6 números por linha em vez de 8 (afetando o
>   índice fixo usado no código para achar o "Valor (R$)"), e ainda inseriu um item fantasma
>   `{"descricao": "ITENS FINANCEIROS", "valores": []}` (o próprio título de seção virou uma linha
>   vazia, o mesmo tipo de erro já visto e supostamente coberto por uma regra explícita do prompt).
>   Resultado: `valorMercadoria` calculado = R$8,91 (deveria ser R$128,49). A reconciliação
>   detectou e bloqueou corretamente (8,91+4,29-105,44=-92,24 vs. total real 27,34) - **nenhum dado
>   errado foi lançado**, mas ficou claro que esta fatura tem 9 linhas de FORNECIMENTO (bem mais
>   que as 2 linhas da nota 872), e quanto mais linhas, mais a transcrição posicional linha a linha
>   acumula erro - 5 tentativas de ajuste de prompt não resolveram esse padrão.
> - **Descoberta que motivou a mudança de estratégia:** conferindo o PDF real, a linha "TOTAL" da
>   tabela "Itens da Fatura" já traz, pronto, o total agregado de cada coluna - inclusive um número
>   que bate EXATAMENTE com a soma de FORNECIMENTO, sem precisar somar nada. Confirmado nos dois
>   casos reais conhecidos: nota 872, linha `TOTAL 328,64 16,41 284,46 54,05` → o 3º número
>   (284,46) é exatamente a soma de FORNECIMENTO; nota 198531151, linha
>   `TOTAL 27,34 7,41 128,49 24,41` → o 3º número (128,49) é exatamente a soma de FORNECIMENTO
>   (confirmado manualmente: 78,5+15,49+6,01+... = 128,49). Esse número também coincide com a base
>   de cálculo do ICMS impressa na caixa "Tributos" (faz sentido: o fornecimento de energia é a
>   própria base do ICMS nesse tipo de documento) - o que explica, inclusive, por que tentativas
>   anteriores confundiam esse valor com a caixa "Tributos".
> - **Mudança de estratégia (6ª versão do prompt):** em vez de transcrever/somar 6-9 linhas de
>   FORNECIMENTO (tarefa que falhou 5 vezes de formas diferentes), o prompt agora pede um único
>   campo `totalFornecimento` = o 3º número da linha "TOTAL" da tabela "Itens da Fatura" - uma
>   tarefa de localizar uma linha e ler uma posição, muito mais simples que transcrever/somar
>   dezenas de números espalhados por várias linhas parecidas. `itensFinanceiros` mantido igual
>   (já provado confiável 2/2).
> - `services/business_rules.py`: `aplicar_valores_equatorial(ia, total_fornecimento,
>   itens_financeiros)` - assinatura mudou de `itens_fornecimento: list` para
>   `total_fornecimento` (string/número pronto, não mais uma lista a somar); `valorMercadoria` =
>   `total_fornecimento` diretamente (antes: soma de `_valor_linha_fornecimento` por item). Função
>   `_valor_linha_fornecimento` (extração posicional por índice) removida - não é mais necessária.
> - `controllers/lancamento_controller.py`: lê `equatorial_raw.get("totalFornecimento", "")` em
>   vez de `equatorial_raw.get("itensFornecimento", [])`; logs e detalhes de Teams atualizados.
> - **Testado com os dois casos reais conhecidos** (dados corretos, simulando a extração ideal):
>   nota 872 (`totalFornecimento="284.46"`) → valorMercadoria=284.46, totalDespesa=44.18,
>   valorDescontoGeral=0.00, reconcilia=True; nota 198531151 (`totalFornecimento="128.49"`,
>   com desconto negativo) → valorMercadoria=128.49, totalDespesa=4.29, valorDescontoGeral=105.44,
>   reconcilia=True. Testado também o fallback de `totalFornecimento` vazio (preserva
>   `valorMercadoria` anterior).
> - **Como reverter:** voltar `aplicar_valores_equatorial` para aceitar `itens_fornecimento: list`
>   e somar via `_valor_linha_fornecimento` (ver histórico de versões anteriores desta seção);
>   reverter o prompt para a versão da ATUALIZAÇÃO 5 (transcrição posicional linha a linha).
> - **Ainda não testado contra uma chamada real de IA** - fica pendente rodar novamente o pedido
>   25998 para confirmar que a 6ª versão do prompt (ler `totalFornecimento` pronto) funciona na
>   prática. A rede de segurança (`reconciliacao_equatorial`) continua ativa e vai barrar qualquer
>   lançamento se esta tentativa também vier inconsistente - o padrão "3º número da linha TOTAL" é
>   uma hipótese forte (2/2 casos reais confirmam), mas ainda não foi validado com uma nova chamada
>   de IA usando o prompt reescrito.

> **ATUALIZAÇÃO 7 (mesmo dia): 6ª versão testada contra IA real - SUCESSO na extração e no
> lançamento, mas revelou um bug separado em valorParcela (ver seção 3.12).** Rodando de novo o
> pedido 25998 com o prompt `totalFornecimento`, a extração saiu perfeita:
> `totalFornecimento`="128.49" (bate exatamente com o valor real de FORNECIMENTO) e
> `itensFinanceiros` corretos (`-105.44`, `0.56`, `3.73`, sinal preservado). Reconciliação passou
> (128,49+4,29-105,44=27,34=TOTAL da fatura). O lançamento foi aceito pelo Mega com sucesso
> (transação 7909499). Confirma a hipótese da ATUALIZAÇÃO 6: pedir o número já pronto da linha
> TOTAL é muito mais confiável do que transcrever/somar linha a linha - zero erros na extração
> desta vez, mesmo com 9 linhas de FORNECIMENTO.
> - **Porém**, o usuário identificou que o payload lançado tinha `valorParcela`="128.49", quando
>   deveria ser "27.34" (o valor líquido real da fatura, após a compensação de -105,44 - e também
>   o valor exato cadastrado no pedido de compra, `VALOR_TOTAL_ITEM_PEDIDO`=27,34). Esse é um bug
>   NÃO relacionado à extração Equatorial em si, mas à regra `valorParcela = valorMercadoria
>   sempre` (seção 3.12) criada mais cedo nesta mesma sessão - ver seção 3.12 para a causa raiz e
>   correção completas.
> - **Pendência URGENTE:** transação Mega 7909499 (pedido 25998/nota 198531151) foi lançada com
>   valorParcela=128,49 em vez de 27,34 (R$101,15 a mais) - precisa de correção manual no Mega.

---

### 3.12 valorParcela deve ser o valor cadastrado no pedido de compra (soma), não valorMercadoria (17/07/2026)

> **CORRIGIDO (2ª correção no mesmo dia - a 1ª versão desta regra, "valorParcela =
> valorMercadoria sempre", ficou incompleta).** A 4ª versão do prompt Equatorial funcionou para o
> pedido 872/nota 199225903: `valorMercadoria`=284,46 (FORNECIMENTO), `totalDespesa`=44,18. Mas o
> Mega rejeitou: "Valor da Nota Fiscal (bruto): 328,64 / Valor cadastrado no pedido de compra:
> 284,46". A correção original (`valorParcela = valorMercadoria` sempre) resolveu esse caso, mas
> se mostrou incompleta ao testar um segundo caso real (pedido 25998/nota 198531151, ver seção
> 3.11 ATUALIZAÇÃO 7): o lançamento foi ACEITO pelo Mega com `valorParcela`=128,49
> (`valorMercadoria`/FORNECIMENTO bruto), mas o usuário identificou que o valor correto era 27,34
> - transação 7909499 precisa de correção manual (ver pendência acima).

- **Causa raiz da 1ª correção estar incompleta:** no caso da nota 872, o valor cadastrado no
  pedido de compra (`VALOR_TOTAL_ITEM_PEDIDO`, variável `soma` em `montar_payload`) era 284,46 -
  coincidentemente IGUAL a `valorMercadoria` (FORNECIMENTO). Por isso "usar valorMercadoria"
  parecia correto. Mas no caso da nota 198531151, o pedido de compra foi cadastrado com 27,34 (o
  valor LÍQUIDO real da fatura, após uma compensação/desconto de -105,44) - um valor DIFERENTE de
  `valorMercadoria` (128,49, o FORNECIMENTO bruto, sem descontar a compensação). Ou seja,
  `valorMercadoria` e `soma` (pedido) NÃO são sempre iguais para Equatorial - dependem de como
  cada pedido de compra foi cadastrado, e a extração Equatorial (`aplicar_valores_equatorial`)
  deliberadamente sobrescreve `valorMercadoria` = FORNECIMENTO bruto (por instrução explícita do
  usuário, ver seção 3.11), desconectando-o do valor do pedido de compra.
- **Regra correta e definitiva:** `valorParcela` deve ser igual a `soma` - o valor cadastrado no
  pedido de compra (`VALOR_TOTAL_ITEM_PEDIDO`, já usado em outros pontos do fluxo, ex.: Validação
  9/seção 3.10, como a referência do que o Mega espera receber) - não `valorMercadoria` nem
  `totalNota`. `soma` é a fonte da verdade sobre o que efetivamente será pago/cobrado, seja ela
  igual ao bruto (FORNECIMENTO), ao líquido (totalNota), ou a qualquer outro valor que quem
  cadastrou o pedido tenha definido - o código não deve assumir qual dos dois (bruto ou líquido)
  está certo, apenas refletir o pedido.
- **Correção aplicada:** em `services/etl_service.py::montar_payload`,
  `valor_parcela = fmt.format_number(soma) if soma > 0 else valor_mercadoria` (fallback para
  `valorMercadoria` só quando `soma` vier zerada/ausente, ex.: pedido sem dados confiáveis).
  `valorMercadoria` (raiz e item) e `totalNota` continuam calculados exatamente como antes - só
  `valorParcela` muda de fonte.
- **Testado (4 cenários, script ad-hoc):**
  - Equatorial nota 872: `soma`=284,46 → `valorParcela`=284,46 ✓ (mesmo resultado de antes, sem
    regressão).
  - Equatorial nota 198531151: `soma`=27,34 → `valorParcela`=27,34 ✓ (corrige o bug real).
  - Electric Mobility (serviço): `soma`=90,00 → `valorParcela`=90,00 ✓ (sem regressão).
  - Produto comum (sintético): `soma`=100,00 → `valorParcela`=100,00 ✓ (sem regressão).
- **Como reverter:** em `services/etl_service.py`, voltar `valor_parcela = valor_mercadoria`
  incondicional (versão anterior desta seção) ou `valor_mercadoria if is_servico else total_nota`
  (versão anterior a esta sessão).
- **Pendência URGENTE (herdada da seção 3.11, ATUALIZAÇÃO 7):** transação Mega 7909499
  (pedido 25998/nota 198531151, launched ANTES desta correção) tem `valorParcela`=128,49 quando
  deveria ser 27,34 - precisa de correção manual no Mega (mesma natureza da pendência já existente
  para a transação 7907369/pedido 320868, seção 3.10).
- **Ainda em aberto:** a regra `valorParcela = soma` ainda não foi validada em produção para tipos
  de documento fora de serviço/energia/produto comum (ex.: BOLP, reembolso, aluguel). Se `soma`
  vier zerada/errada nesses casos, o fallback para `valorMercadoria` mantém o comportamento
  anterior (sem piorar), mas ainda merece um teste real quando surgir um caso desses.

---

### 3.13 Item (itensReceb) x base fiscal - conflito exposto pela seção 3.12, corrigido SÓ para Equatorial, em TESTE (17/07/2026)

> **STATUS: EM TESTE, restrito a Equatorial** (`business_rules.eh_fornecedor_equatorial`). Não
> altera nenhum outro fornecedor/documento - o parâmetro novo (`is_equatorial`) tem default
> `False`, que preserva exatamente o comportamento anterior a esta seção.

- **Problema descoberto ao reprocessar o pedido 25998/nota 198531151 já com a correção da seção
  3.12 aplicada:** o Mega REJEITOU o lançamento com "Soma dos Valores das Parcelas[27,34] não
  confere com o Total da Fatura[128,49]". Ou seja, a correção da seção 3.12 (valorParcela=soma=
  27,34) e o valor do item (`itensReceb[0].valorMercadoria`=`ia["valorMercadoria"]`=128,49,
  FORNECIMENTO bruto) ficaram inconsistentes entre si - o Mega exige que a soma das parcelas bata
  com a soma de `itensReceb[].valorMercadoria` (confirmado empiricamente por essa rejeição: os
  campos `totalDespesa`/`valorDescontoGeral` do cabeçalho NÃO são considerados por essa checagem
  específica do Mega).
- **Segunda descoberta (usuário, ao revisar o payload):** os campos de base de cálculo do item -
  `baseIcms`, `baseISS`, `baseIRFF`, `baseINSS`, `basePIS`, `baseCofins`, `baseCSLL`,
  `valorBaseIPI` - vêm de `base_dec` = `vtip` (`VALOR_TOTAL_ITEM_PEDIDO`, o valor cadastrado no
  pedido de compra), não de `valorMercadoria`. Para Equatorial com desconto, isso está
  fiscalmente errado: o prompt Equatorial (seção 3.11) já registra que o `totalFornecimento`
  (FORNECIMENTO bruto, ex.: 128,49) normalmente COINCIDE com a base de cálculo do ICMS impressa na
  própria fatura - a compensação/desconto é um ajuste financeiro à parte, que não deveria reduzir
  a base de cálculo do tributo. Usar `vtip` (27,34, o valor líquido cadastrado no pedido) como base
  fiscal é incorreto quando ele diverge do bruto real da fatura.
- **Conclusão:** `base_dec`/`vtip` fazia dois papéis ao mesmo tempo - (1) fonte de `soma` (via
  retorno de `montar_item`), que vira `valorParcela`, e (2) base de cálculo dos tributos do item.
  Esses dois papéis precisam ser servidos por valores diferentes quando `valorMercadoria`
  (FORNECIMENTO) diverge do valor cadastrado no pedido (`vtip`/`soma`) - caso Equatorial com
  desconto/compensação grande.
- **Correção aplicada (SOMENTE quando `is_equatorial=True`):**
  - `services/etl_service.py::montar_item` - novo parâmetro `is_equatorial: bool = False`.
    - `valorMercadoria` do item: quando `is_equatorial and vtip > 0`, usa
      `VALOR_TOTAL_ITEM_PEDIDO` (igual ao ramo já existente para `is_servico`) em vez de
      `ia["valorMercadoria"]` - agora bate com `valorParcela` (ambos = `soma`/pedido), resolvendo a
      rejeição do Mega.
    - Base fiscal: nova variável `base_fiscal_dec` = `ia["valorMercadoria"]` quando
      `is_equatorial` e esse valor for > 0, senão = `base_dec` (idêntico a antes). `base_fmt`
      (usado em `baseIcms`, `baseISS`, `baseIRFF`, `baseINSS`, `basePIS`, `baseCofins`, `baseCSLL`,
      `valorBaseIPI`, e seus percentuais/valores calculados) passa a vir de `base_fiscal_dec`.
    - `base_dec` em si (usado no rateio de `centrosCusto`/`projetos` e devolvido para compor
      `soma` em `montar_payload`) **não muda** - continua = `vtip`.
  - `services/etl_service.py::montar_payload` - novo parâmetro `is_equatorial: bool = False`,
    repassado para `montar_item`.
  - `controllers/lancamento_controller.py` - na chamada de `montar_payload`, passa
    `is_equatorial=br.eh_fornecedor_equatorial(fantasia)`.
- **Testado (script ad-hoc, 4 cenários):**
  - Equatorial COM desconto (nota 198531151), `is_equatorial=True`: item.valorMercadoria=27,34 =
    valorParcela=27,34 (consistente, Mega deve aceitar); baseIcms/baseISS/basePIS=128,49 (base
    fiscal correta).
  - Mesmo caso com `is_equatorial=False` (comportamento antigo, para comparação): reproduz
    exatamente o bug - item=128,49 ≠ parcela=27,34.
  - Equatorial SEM desconto (nota 199225903), `is_equatorial=True`: tudo em 284,46 (sem mudança,
    já que `valorMercadoria`=`vtip` coincidem nesse caso).
  - Fornecedor comum, `is_equatorial=False` (default): tudo em 100,00, comportamento idêntico ao
    anterior a esta seção - confirma que nenhum outro fornecedor é afetado.
- **Ainda não testado em produção real** (só teste sintético/ad-hoc) - próximo pedido Equatorial
  processado vai validar se o Mega aceita o lançamento com essa mudança. Se falhar de outra forma,
  reverter é trivial: não passar `is_equatorial=True` na chamada do controller (ou remover o
  argumento), o que restaura 100% do comportamento anterior sem tocar em código de outros
  fornecedores.
- **Se validado em produção, avaliar generalizar** para outros tipos de documento onde
  `valorMercadoria` (bruto da IA) diverge de `vtip` (pedido de compra) por motivo de desconto/
  compensação legítimos (não só cadastro errado do pedido) - hoje só Equatorial tem esse padrão
  conhecido.

### 3.14 Anexo PDF protegido por senha - pula chamada de IA (ex.: faturas Tim) (18/07/2026)

- **Problema descoberto no pedido 137203** (fornecedor TIM S/A, arquivo
  "Tim -Val- 5813689404 - 11-08-2026.pdf"): o PDF é protegido por senha, então a IA nunca consegue
  ler o conteúdo - o job fica em `PROCESSING` indefinidamente e só falha por timeout depois de
  ~419s (30 tentativas de polling), sem indicar a causa real do problema.
- **Correção:** ao detectar um termo conhecido de arquivo protegido por senha no nome do anexo,
  pula a chamada de IA inteiramente e já reporta o motivo real, sem esperar o timeout.
  - `config/settings.py::ARQUIVOS_PROTEGIDOS_SENHA` - conjunto de termos conhecidos (hoje:
    `"TIM -VAL"`, padrão de nome de arquivo das faturas Tim).
  - `services/business_rules.py::eh_anexo_protegido_por_senha` - verifica se o nome do anexo
    contém algum dos termos (case-insensitive, substring).
  - `controllers/lancamento_controller.py::processar_pedido` - checagem feita logo após ler
    `nomeArquivo`, antes até da checagem de extensão de imagem já existente; se detectado, loga
    aviso, notifica Teams (`NotificationService.erro_anexo_protegido_senha`) e pula para o próximo
    anexo (`continue`), sem chamar `ia_service`.
- **Evita segundo erro duplicado no Teams:** quando TODOS os anexos do pedido são protegidos por
  senha (`anexos_protegidos` == total de anexos, mesmo padrão já usado para `anexos_imagem`), o
  fluxo NÃO cai mais no erro genérico "Falha ao determinar dados para lançamento"
  (`erro_definir_payload`) - já foi notificado o motivo real no passo anterior. Só registra no BD
  como **Sucesso** (não é falha de execução do nosso código - é um impedimento do próprio arquivo)
  com `erro="Arquivo protegido por senha - não é possível a leitura pela IA. Arquivo: <nome(s)>"` e
  `res.status="SenhaProtegidaManual"`, para não reprocessar o pedido - mesmo padrão já usado para
  anexo de imagem (`ImagemManual`).
- **Rede de segurança por fornecedor (18/07/2026):** o padrão de nome de arquivo protegido pode
  variar no futuro (a Tim já usou nomes diferentes em outras notas). Para não depender só do nome
  do arquivo, `config/settings.py::FANTASIAS_PROVAVEL_SENHA` lista fornecedores (`AGN_ST_FANTASIA`)
  cujas faturas quase sempre vêm protegidas por senha (hoje: `"TIM S/A"`). Se a chamada de IA
  (`extrair_primaria`) falhar com exceção para um fornecedor dessa lista, o controller trata a
  falha como "protegido por senha" (via `business_rules.py::eh_fornecedor_provavel_senha`) em vez
  do erro técnico genérico "Falha ao enviar Base64 para IA" - mesmo quando o nome do arquivo não
  bateu com nenhum termo de `ARQUIVOS_PROTEGIDOS_SENHA`.
- **Generaliza para qualquer fornecedor futuro** com o mesmo padrão de PDF protegido - basta
  adicionar o termo do nome de arquivo em `ARQUIVOS_PROTEGIDOS_SENHA` e/ou o fornecedor em
  `FANTASIAS_PROVAVEL_SENHA`.

---

### 3.14 PIS/COFINS/CSLL não processados no Mega - causa raiz identificada (cadastro, não código) (17-18/07/2026)

> **Contexto:** paliativo da seção 3.6 existe desde 16/07/2026 por falta de causa raiz conhecida.
> Nesta investigação, usando um caso real novo (pedido 29587/nota 117347, Starian Sistemas,
> transação Mega 7918439), a causa raiz foi finalmente identificada - é cadastro no Mega, não é
> bug do RPA nem do payload enviado.

- **Sintoma:** payload de recebimento enviado corretamente (`valorPIS`, `valorCOFINS`,
  `percentualPIS`, `percentualCofins` com os valores certos extraídos da NFS-e), Mega aceita o
  lançamento (sucesso, gera transação), mas na tela "Totais do Documento" do Mega, `Valor do PIS`
  e `Valor do COFINS` aparecem **0,00** - só CSLL e IRRF aparecem corretos.
- **Explicação do campo `calculaValores` (confirmada com o time de TI/Mega, Robert Costa, sobre um
  incidente histórico irmão - pedido 752/nota 19, transação 7886851):** `"calculaValores": "N"`
  (enviado hoje na raiz e em cada item, herdado do fluxo Power Automate original, nunca revisado)
  diz ao Mega "a responsabilidade do cálculo é nossa" - no lançamento manual, o Mega aplica regras
  automáticas próprias que não rodam quando mandamos `"N"`. Testes do time de TI (relançar a mesma
  nota, trocar a ordem de lançamento, igualar `dataMovimento`) descartaram instabilidade e
  apontaram para uma configuração de cadastro, não para o `calculaValores` isoladamente.
- **Causa raiz encontrada (artigos da base de suporte Senior/Mega):** Mega Fiscal → Tributos →
  **Aplicação do Produto** → código **109** ("Serviços S/ Crédito de PIS-COFINS", usado no item
  via `dado_pedido["APLICACAO"]`, sem lógica nossa no meio - ver `services/etl_service.py::
  montar_item` linha ~205) → aba **PIS/COFINS** → o checkbox **"Calcular"** estava **desmarcado**
  tanto para PIS quanto para COFINS (e Alíquota zerada, embora CST Entrada estivesse preenchido
  como "70"). Conforme a prioridade de busca de parâmetros do Mega (Aplicação → Regra de PIS/COFINS
  → Parâmetros Tributários), com "Calcular" desmarcado a Aplicação é desqualificada e, se os níveis
  seguintes também não tiverem PIS/COFINS configurado, o resultado fica zerado - **independente do
  que o RPA envie no payload**.
- **Hipóteses descartadas nesta investigação:**
  - Aplicação 109 vs 108 ("Serviços C/ Crédito de PIS-COFINS"): descartada - usuário confirmou que
    todos os lançamentos manuais desse tipo de documento também usam 109, nunca 108, então a
    aplicação escolhida não é o diferencial.
  - Agente (fornecedor) não enquadrado no PIS/COFINS: descartada - conferido o cadastro do agente
    Starian (Empresarial/Global/Cadastros/Agentes → aba Fiscal), 'Enquadrado no PIS' e 'Enquadrado
    no COFINS' já estavam marcados corretamente.
- **Correção aplicada (cadastro no Mega, feita pelo usuário, não é mudança de código):** marcado
  "Calcular" para PIS e COFINS na aplicação 109, com Alíquota PIS = 0,6500% e COFINS = 3,0000%
  (confirma exatamente os percentuais reais da NFS-e: 22,44/3.452,64 = 0,65% e 103,58/3.452,64 =
  3,00%) - primeira tentativa do usuário tinha os dois percentuais invertidos, corrigido antes de
  confirmar.
- **Validação parcial:** após a correção, reabrindo "Gerar Parcelas" no documento 117347, a aba
  Impostos passou a mostrar `Valor do PIS = 22,44` e `Valor do COFINS = 103,58` corretos (prova que
  o cadastro da aplicação estava mesmo zerando o cálculo). Porém "Totais do Documento" (tela
  principal) continuou mostrando PIS/COFINS = 0,00 mesmo depois da correção - hipótese em aberto é
  que a aba "Gerar Parcelas" seja só uma prévia/simulação (a própria tela avisa isso) e só grave de
  fato após clicar "Confirmar" nesse popup - **não confirmado se isso resolve o Totais do
  Documento**, fica pendente.
- **Efeito colateral notado, não resolvido:** depois da correção da aplicação, ao regenerar
  parcelas para o documento 117347, o "Valor da Parcela" mostrado (3.292,09) ficou diferente do
  valor de mercadoria (3.452,64) e do `valorParcela` originalmente enviado (3.452,64) - a diferença
  bate exatamente com o CSLL (160,55), sugerindo possível desconto duplicado de CSLL ao gerar
  parcelas com a aplicação corrigida. **Não investigado a fundo, fica como possível problema novo
  a observar em próximos testes.**
- **Pendente:**
  - Confirmar se "Totais do Documento" atualiza corretamente após confirmar a geração de parcelas
    (ou se precisa relançar/refazer a entrada, como avisa a KB da Senior).
  - Investigar o possível desconto duplicado de CSLL no "Valor da Parcela" após a correção da
    aplicação 109.
  - Reavaliar o paliativo da seção 3.6 (`BLOQUEIO_PIS_COFINS_ATIVO`) só depois de confirmar os dois
    pontos acima em mais de um pedido - a aplicação 109 é usada por vários fornecedores, então a
    correção vale para todos eles, mas precisa de mais testes antes de destravar o bloqueio geral.
  - Fonte adicional consultada, ainda sem conclusão aplicada: artigo Senior sobre "CST de PIS e
    COFINS incorreto" (causa alternativa: agente não enquadrado - descartada para Starian, mas
    pode valer conferir para outros fornecedores que apresentem o mesmo sintoma).

### 3.15 issRetido incorreto por confusão com campo de bloco diferente - CORRIGIDO e CONFIRMADO (20/07/2026)

> **CONFIRMADO EM PRODUÇÃO.** Pedido 320970/nota 988 (Brazfort Brazil Locações, fornecedor
> "RAPIDO ARAGUAIA", NFS-e Goiânia) reprocessado após a correção do prompt e o usuário confirmou:
> "Deu certo, está tudo ok".

- **Sintoma:** documento com **"ISS a reter: 1 - Sim"** e **"(-) ISS Retido: 23,04"** impressos
  explicitamente na NF. Extração primária (1ª IA) leu corretamente `totalISS`/`baseISS`/
  `percentualISS` (23.04/550.00/4.19), mas a 2ª chamada (extra, autoritativa para `issRetido`)
  devolveu `issRetido: false` - e pela regra de precedência, isso zerou todo o bloco de ISS no
  payload final, apesar da retenção ser real e explícita no documento.
- **Causa:** não era falta de regra no prompt - a regra 14 de `prompts/prompt_2a_ia.txt` já cobria
  exatamente o padrão "ISS a Reter: 1 - Sim" (código ABRASF). A IA se confundiu com um campo
  **vizinho e de bloco diferente**: "(=) Valor ISS: 0,00", dentro do bloco "Cálculo do ISSQN devido
  no Município" - esse campo representa o ISS que o PRÓPRIO PRESTADOR ainda deveria pagar
  diretamente (zero justamente porque a retenção pelo tomador já cobre a obrigação), não indica
  ausência de retenção.
- **Correção aplicada:** adicionado um terceiro exemplo real completo em `prompts/prompt_2a_ia.txt`
  (após os dois exemplos existentes de `issRetido: true`), reproduzindo exatamente esse layout de
  3 blocos e a armadilha do "Valor ISS: 0,00" vizinho ao "ISS a reter: 1 - Sim", com números reais
  desta nota (23,04 / 550,00 / 4,19).
- **Testado e confirmado em produção:** usuário reprocessou o pedido 320970/nota 988 com o prompt
  corrigido e confirmou resultado correto.
- **Pendência URGENTE (não relacionada ao prompt, é sobre o lançamento já feito):** a transação
  Mega **7944898** (pedido 320970/nota 988), lançada ANTES desta correção, saiu com ISS zerado
  (`totalISS`/`valorISS` = 0,00 em vez de 23,04) - precisa correção manual no Mega. Soma-se à lista
  de pendências de correção manual já existente (transação 7907369/pedido 320868, seção 3.10;
  transação 7909499/pedido 25998, seção 3.12).

---

### 3.16 Chave de Acesso com dígito verificador inválido - IA funde grupo de 4 dígitos parecido com o vizinho - CORRIGIDO e CONFIRMADO em produção (20/07/2026)

> **Gatilho:** falha real em produção. Pedido 320983/nota 307 (fornecedor "R P A CUNHA & CIA
> LTDA - ME - ORTOMED", CNPJ 07071977000149, filial 3/Rápido Araguaia) rejeitado pelo Mega:
> `Erro na rotina [adm_pck_nfe.F_ValidaChaveNFE] - ORA-20001: Chave de Acesso não encontrada`.

- **Sintoma:** as duas chamadas de IA (1ª e extra) leram a chave de acesso do DANFE com apenas
  **40 dígitos** cada (deveriam ser 44), e nem batiam entre si. A regra de consolidação antiga em
  `services/etl_service.py` só validava `len(chave) == 44`, então ambas foram descartadas e
  `chaveAcesso` foi enviada como `""` ao Mega - que rejeitou com um erro Oracle genérico, sem
  indicar que o problema era leitura de IA.
- **Causa raiz confirmada:** a chave impressa no documento é `5226 0707 0719 7700 0149 5500 1000
  0003 0718 9013 1292` (44 dígitos, DV módulo 11 confere). O texto está nítido - não é problema de
  resolução de imagem. As duas chamadas de IA "pularam" o grupo `0707` (ou o fundiram com o grupo
  vizinho `0719`, visualmente parecido), resultando em 40 dígitos em vez de 44. Ou seja: não é
  "baixa qualidade de PDF" no sentido de imagem ilegível, é a IA confundindo dois grupos de 4
  dígitos consecutivos e parecidos e descartando um deles.
- **Correções aplicadas (duas camadas, complementares):**
  1. **Prompt** (`prompts/prompt_1a_ia.txt` item 4 e `prompts/prompt_2a_ia.txt` item 6-7 da seção
     "Extração de chaveAcesso"): instrução explícita para ler a chave em 11 grupos de 4 dígitos,
     contar os grupos, e não pular/fundir grupos vizinhos parecidos (com o exemplo real
     "0707"/"0719" desta nota).
  2. **Código** (`utils/validators.py::chave_acesso_valida`): validação de chave de acesso passou
     a calcular o dígito verificador (módulo 11, mesmo algoritmo da SEFAZ) sobre os 43 primeiros
     dígitos, não só checar o tamanho. Isso pega tanto chave com menos/mais de 44 dígitos quanto
     chave com exatamente 44 dígitos mas conteúdo errado (dígito trocado), caso que a checagem
     antiga deixava passar silenciosamente. Usada na consolidação (`services/etl_service.py`) e em
     uma nova blocagem no controller.
  3. **Nova Validação 5B** em `controllers/lancamento_controller.py` (entre a Validação 5 - Data do
     Documento - e a Validação 6 - Condição de Pagamento): para tipos de documento que exigem chave
     (`NF-E`, `NFSC`, `NFSTE`, `NF3E`), se a chave final não passar em `chave_acesso_valida`, o
     lançamento é bloqueado (`deve_lancar = False`, status `ChaveAcessoInvalida`) **antes** de
     chegar ao Mega, com aviso no Teams mostrando as duas leituras brutas de IA (`chave_primaria_raw`
     / `chave_extra_raw`) para conferência manual - troca o erro Oracle genérico por um aviso claro
     e específico.
- **Efeito esperado:** para documentos onde a IA lê a chave certa, nada muda (segue lançando
  normal). Para documentos onde a IA erra a chave (como este), o pedido passa a ser bloqueado com
  aviso claro em vez de ir para o Mega e falhar lá com erro Oracle opaco. A melhoria do prompt deve
  reduzir a frequência desse tipo de erro de leitura, mas não elimina 100% - por isso a blocagem no
  código é a rede de segurança definitiva.
- **CONFIRMADO EM PRODUÇÃO (mesmo dia, disparo `lancamentoCLN_20260720_113108`):** a Validação 5B
  entrou em ação e bloqueou corretamente MAIS DOIS documentos com chave de acesso inválida, antes
  de chegarem ao Mega:
  - Pedido 320996/nota 4815 (COMERCIAL POLLYANNA): as duas leituras de IA trouxeram caracteres
    não numéricos (`52260737d3b9...` e `52260737d3f0...`) - reprovadas até pela checagem de
    tamanho/dígitos, nem chegou a testar o DV. Conferida a chave real direto na imagem do DANFE
    (nítida): `5226 0737 4030 7800 0248 5500 2000 0048 1513 9928 2163` -> DV módulo 11 confere.
    **Chave correta para lançamento manual: `52260737403078000248550020000048151399282163`.**
  - Pedido 320908/nota 2354 (KNOV): as duas leituras de IA (`...8134...`/`...8313...`) tinham 44
    dígitos numéricos válidos mas o DV não conferiu em nenhuma das duas. Chave real conferida na
    imagem do DANFE: `3526 0726 8813 5400 0186 5500 1000 0023 5412 3797 2872` -> DV módulo 11
    confere. **Chave correta para lançamento manual: `35260726881354000186550010000023541237972872`.**
  - Nos dois casos a imagem do DANFE está nítida (mesmo padrão do pedido 320983) - confirma que o
    problema é a IA errar dígitos específicos de grupos do meio da chave, não resolução de imagem
    baixa. A blocagem por DV funcionou exatamente como esperado: nenhuma chave errada foi enviada
    ao Mega: os dois pedidos ficaram com status `ChaveAcessoInvalida` e aviso claro no Teams com
    as duas leituras brutas, em vez do erro Oracle genérico.
  - **Ação pendente:** lançamento manual no Mega dos pedidos 320996/nota 4815 e 320908/nota 2354
    usando as chaves corretas acima.
- **Pendência em aberto:** o pedido 320983/nota 307 (caso original desta seção) ainda não foi
  reprocessado neste disparo para confirmar se o ajuste de prompt já lê a chave certa de primeira.

---

### 3.17 issRetido incorreto (falso positivo) por confundir "VALOR DO ISSQN" com "VALOR DO ISSQN RETIDO" em tabela de 5 colunas - CORRIGIDO, aguardando confirmação em produção (20/07/2026)

> **Espelho invertido da seção 3.15.** Lá a 2ª IA disse `issRetido: false` quando era retido
> (falso negativo). Aqui a 2ª IA disse `issRetido: true` quando NÃO era retido (falso positivo) -
> mesma classe de bug (confundir dois campos de ISSQN vizinhos/parecidos), erro na direção oposta.

- **Sintoma:** pedido 5841/nota 1457 (prestador Sgm Comunicacao Visual Ltda, CNPJ
  50.157.646/0001-55, NFS-e de Aparecida de Goiânia, tomador Condomínio Shopping Center Cerrado)
  lançado no Mega (transação **7948918**) com `issRetido: true` e `valorISSRetido: 99.22`,
  zerando a base tributável do prestador incorretamente.
- **Causa raiz confirmada** (PDF `1457-nfse.pdf` conferido via extração de texto): a nota tem uma
  única linha de tabela com 5 colunas lado a lado: `TOTAL LÍQUIDO DA NOTA (R$)` | `BASE DE CÁLCULO
  ISSQN (R$)` | `ALÍQUOTA ISSQN (%)` | `VALOR DO ISSQN (R$)` | `VALOR DO ISSQN RETIDO (R$)`, com os
  valores `2.250,00 | 2.250,00 | 4,41 | 99,22 | 0,00` na linha de baixo. O documento já diz
  explicitamente que a retenção é **0,00** (última coluna) - a IA pegou o valor da penúltima coluna
  (`VALOR DO ISSQN`, 99,22 - é o ISS apurado/devido pelo prestador, não retido) e tratou como se
  fosse a última (`VALOR DO ISSQN RETIDO`). É o mesmo padrão da seção 3.15 (campos de nomes muito
  parecidos, lado a lado, um deles "vence" errado), mas agora em formato de tabela de colunas em
  vez de blocos separados.
- **Correção aplicada:** adicionado um quarto exemplo real completo em `prompts/prompt_2a_ia.txt`
  (logo antes de "Motivo operacional desta regra"), reproduzindo esse layout de 5 colunas com os
  números reais desta nota, instruindo a IA a contar cabeçalhos e valores na mesma ordem da
  esquerda pra direita e usar exclusivamente o ÚLTIMO valor da linha (sob "VALOR DO ISSQN RETIDO")
  para decidir `issRetido`/`valorISSRetido`, nunca o penúltimo ("VALOR DO ISSQN").
- **Pendência URGENTE (não relacionada ao prompt, é sobre o lançamento já feito):** a transação
  Mega **7948918** (pedido 5841/nota 1457), lançada ANTES desta correção, saiu com ISS incorreto
  (`totalISS`/`valorISS` = 99,22 em vez de 0,00) - precisa correção manual no Mega. Soma-se à lista
  de pendências de correção manual já existente (transação 7907369/pedido 320868, seção 3.10;
  transação 7909499/pedido 25998, seção 3.12; transação 7944898/pedido 320970, seção 3.15).
- **Pendência de confirmação:** aguardando reprocessamento de uma nota com o mesmo layout (5
  colunas, Aparecida de Goiânia ou prestador equivalente) para confirmar que o ajuste de prompt
  corrige o resultado, seguindo o mesmo padrão de confirmação usado na 3.15.

---

### 3.18 issRetido incorreto (falso negativo) por tabela de tributos em duas linhas de 7 colunas - CORRIGIDO, aguardando confirmação em produção (20/07/2026)

> **Mesma classe de bug das seções 3.15/3.17** (campos de ISSQN vizinhos/parecidos confundindo a
> leitura), agora num layout novo: tabela de tributos partida em DUAS linhas, cada uma com 7
> colunas.

- **Sintoma:** pedido 5875/nota 1063 (prestador Digital Midia Ltda, CNPJ 35.727.978/0001-34, NFS-e
  de Goiânia, tomador Condomínio Shopping Center Cerrado) lançado no Mega (transação **7963399**)
  com `issRetido: false` e ISS zerado, apesar do documento indicar retenção.
- **Causa raiz confirmada** (PDF `nf 1063 - espaço pekids.pdf` conferido): a seção "Detalhamento dos
  Tributos" vem em duas linhas de 7 colunas cada. Linha 1: `Vl. Total dos Serviços | Desconto
  Incondicionado | Deduções Base Cálculo | Base de Cálculo | Total do ISSQN | ISSQN Retido |
  Desconto Condicionado` = `1.045,00 | 0,00 | 0,00 | 1.045,00 | 0,00 | Sim | 0,00`. Linha 2: `PIS |
  COFINS | INSS | IRRF | CSLL | Outras Retenções | Vl. ISSQN Retido | Vl. Líquido da Nota Fiscal` =
  `0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 0,00 | 20,90 | 1.024,10`. O documento diz explicitamente
  "ISSQN Retido: Sim" (linha 1, coluna 6) e "Vl. ISSQN Retido: R$ 20,90" (linha 2, coluna 7) - a IA
  ignorou os dois e usou o "Total do ISSQN: R$ 0,00" (linha 1, coluna 5) para concluir, errado, que
  não havia retenção.
- **Correção aplicada:** adicionado um quinto exemplo real completo em `prompts/prompt_2a_ia.txt`
  (logo antes de "Motivo operacional desta regra"), reproduzindo esse layout de duas linhas/7
  colunas com os números reais desta nota, instruindo a IA a tratar as duas linhas como pertencentes
  à mesma seção de tributos e a nunca deixar o "Total do ISSQN" de uma linha sobrepor o "Sim"/valor
  positivo de retenção presente na mesma seção.
- **Pendência URGENTE (não relacionada ao prompt, é sobre o lançamento já feito):** a transação
  Mega **7963399** (pedido 5875/nota 1063), lançada ANTES desta correção, saiu com ISS zerado
  (`totalISS`/`valorISS` = 0,00 em vez de 20,90) - precisa correção manual no Mega. Soma-se à lista
  de pendências de correção manual já existente (transação 7907369/pedido 320868, seção 3.10;
  transação 7909499/pedido 25998, seção 3.12; transação 7944898/pedido 320970, seção 3.15;
  transação 7948918/pedido 5841, seção 3.17).
- **Pendência de confirmação:** aguardando reprocessamento de uma nota com o mesmo layout (duas
  linhas de 7 colunas, portal issnetonline.com.br/goiania) para confirmar que o ajuste de prompt
  corrige o resultado, seguindo o mesmo padrão de confirmação usado na 3.15/3.17.

---

### 3.19 Bloqueio indevido na Validação 7 (Cond.Pagto x Boleto) por zero à esquerda - CORRIGIDO, aguardando confirmação em produção (21/07/2026)

- **Sintoma:** pedido 5873 (fornecedor Inovar Marketing Promocional Ltda, cond. pagamento
  cadastrada "8D") bloqueado pela Validação 7 com o motivo "Condição de pagamento divergente
  (cadastrada=8D, calculada=08D)", apesar de "8D" e "08D" serem exatamente a mesma condição (8
  dias). Status final registrado no BD: `CondPagtoDivergente`, sem lançamento no Mega.
- **Causa raiz confirmada:** `services/business_rules.py::valida_cond_pagto_por_vencimento`
  comparava `esperada == cond_norm` como STRING pura. `calcular_cond_pagto_por_vencimento` sempre
  formata com zero à esquerda (`f"{dias:02d}D"`, ex.: "08D"), enquanto `cond_norm` preserva o
  formato exato cadastrado no pedido (ex.: "8D", sem zero à esquerda). Para qualquer condição de
  pagamento de 1 a 9 dias sem zero à esquerda no cadastro, a comparação de string sempre falhava
  mesmo quando a quantidade de dias era idêntica, bloqueando o lançamento indevidamente.
- **Correção aplicada:** a comparação passou a usar `quantidade_cond_pagto(esperada) ==
  quantidade_cond_pagto(cond_norm)` (compara a quantidade de dias como inteiro, não a string
  formatada), eliminando a sensibilidade a zero à esquerda. Testado localmente:
  `quantidade_cond_pagto("8D") == quantidade_cond_pagto("08D")` -> `8 == 8` -> `True`.
- **Pendência de confirmação:** aguardando reprocessamento do pedido 5873 (ou outro pedido com
  cond. pagamento de 1 dígito sem zero à esquerda) para confirmar que a Validação 7 passa a aceitar
  corretamente, seguindo o mesmo padrão de confirmação usado nas seções 3.15/3.17.
- **Nota:** este pedido especificamente NÃO tem lançamento incorreto a corrigir no Mega - ele foi
  apenas bloqueado (status `CondPagtoDivergente`), não lançado com dado errado. Basta reprocessar.

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
"235758": CCP CERRADO (13619137000251) - Condominio Shopping Center Cerrado; faturas da
  Equatorial chegam endereçadas a administradora (CCP Cerrado), nao ao condominio
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

### v1.5 (18/07/2026) - Anexo PDF protegido por senha pula chamada de IA (ver 3.14)
- Corrige caso real: pedido 137203, fornecedor TIM S/A, arquivo protegido por senha causava
  timeout de ~419s na IA (job preso em `PROCESSING`) antes de reportar o erro genérico "Falha ao
  enviar Base64 para IA".
- Novo `ARQUIVOS_PROTEGIDOS_SENHA` (config/settings.py) com termos conhecidos de nome de arquivo
  protegido (primeiro caso: `"TIM -VAL"`) e `business_rules.py::eh_anexo_protegido_por_senha`.
- Controller pula a chamada de IA e reporta o motivo real (`NotificationService.
  erro_anexo_protegido_senha`) assim que detecta o termo no nome do anexo, sem esperar o timeout.
- Quando todos os anexos do pedido são protegidos por senha, não dispara mais o segundo erro
  genérico "Falha ao determinar dados para lançamento" - só registra no BD (status="Sucesso",
  já que não é falha de execução, e sim impedimento do arquivo; erro="Arquivo protegido por
  senha - não é possível a leitura pela IA. Arquivo: <nome>", `res.status="SenhaProtegidaManual"`)
  para não reprocessar.
- Nova rede de segurança por fornecedor: `FANTASIAS_PROVAVEL_SENHA` (hoje: `"TIM S/A"`) trata
  qualquer falha da IA nesse fornecedor como "protegido por senha", mesmo se o nome do arquivo
  mudar de padrão no futuro.

### v1.5 (17/07/2026) - Emitente/Tomador invertidos pela IA em RECIBO/Termo (ver 2.6ter)
- Corrige caso real: pedido 320931, RECIBO/termo de SERGIO GLEIK DAVID (CPF `58870067149`)
  bloqueado com "CNPJ do tomador não bate com o esperado" mesmo com o CNPJ do fornecedor correto
  cadastrado (confirmado via `getdadosfornecedorvdois`) - a IA leu `nomeEmitente`/`cnpjEmitente`
  como RAPIDO ARAGUAIA LTDA (a filial pagadora) e `nomeTomador`/`cnpjCpfTomador` como SERGIO
  GLEIK DAVID (o prestador que assinou o recibo), exatamente invertido da regra ja existente no
  prompt ("Definicao de emitente/tomador em RECIBO").
- Nova regra `services/business_rules.py::corrigir_emitente_tomador_invertidos`: detecta o padrao
  invertido (emitente extraido = CNPJ da filial esperada E tomador extraido = CNPJ do fornecedor
  cadastrado no pedido) e desfaz a troca antes de montar o payload - generaliza para qualquer
  fornecedor futuro com o mesmo problema, nao so este CNPJ.
- Aplicada em `controllers/lancamento_controller.py::processar_pedido`, logo apos a correcao de
  CNPJ por fornecedor conhecido (2.6bis).

### v1.5 (17/07/2026) - NFS-EG x NFS-E para prestador MEI de Goiania
- Corrige caso real: pedido 320904, prestador RONILSON COSTA DE MOURA (MEI, CNPJ
  `19164502000186`) lancado como `NFS-EG` quando deveria ser `NFS-E`. O documento tinha o campo
  "Optante - Microempreendedor Individual (MEI)" explicito - a regra de MEI ja existia no prompt
  (regra 15), mas a IA classificou pela regra 5 (cidade do prestador = Goiania) antes de chegar a
  checar a excecao de MEI. Causa raiz confirmada: ordem de avaliacao das regras, nao ausencia da
  indicacao no documento.
- `TIPO_DOC_POR_EMITENTE` (config/settings.py): adicionado `19164502000186` -> `NFS-E`, garantindo
  a classificacao correta para esse fornecedor independente do que a IA extrair.
- Prompt (`prompts/prompt_1a_ia.txt`, regra 5): referencia explicita para checar a excecao de MEI
  (regra 15) antes de fechar a classificacao como `NFS-EG`.
- Prompt (regra 15): lista o rotulo exato encontrado no documento ("Optante - Microempreendedor
  Individual (MEI)") entre os indicadores reconhecidos, e passa a considerar tambem o nome
  empresarial no formato padrao de MEI sem nome fantasia (numero de CPF/CNPJ + nome da pessoa
  fisica, sem sufixo societario), como reforco para casos sem o rotulo explicito.

### v1.5 (16/07/2026) - Prompt da IA: ano de 2 dígitos e Data de Geração x Competência
- Prompt (`prompts/prompt_1a_ia.txt`, seção "Datas" da Formatação): nova regra para datas com ano
  de 2 dígitos (dd/MM/yy) - o terceiro grupo é sempre o ano (expandir com século 2000), nunca
  inverter com o dia. Corrige caso real: pedido 320829, GRU com "Data de Geração" impressa como
  "15/07/26" que a IA leu como "26/07/2015" (inverteu dia e ano).
- Prompt ("Regra de data do documento"): para NFS-e/NFS-EG, se houver "Data de Geração" e ela
  divergir da "Data de Competência" (regra 6), usar a Data de Geração.

### v1.5 (16/07/2026) - CNPJ do tomador CCP Cerrado (filial 235758) no DEPARA_FILIAIS
- Adicionada filial `235758` (Condominio Shopping Center Cerrado) ao `DEPARA_FILIAIS`
  (config/settings.py), apontando para o CNPJ `13619137000251` (CCP Cerrado Empreendimentos
  Imobiliarios S.A.) - faturas da Equatorial para essa filial chegam endereçadas a administradora
  do shopping, nao ao condominio cadastrado. Confirmado com a usuaria em 16/07/2026.

### v1.5 (16/07/2026) - CNPJ do emitente corrigido por fornecedor conhecido (ver 2.6bis)
- Novo de-para `CNPJ_CORRETO_POR_FANTASIA` (config/settings.py) para forcar o CNPJ correto do
  emitente quando o fornecedor cadastrado no pedido e um caso conhecido de erro de leitura da IA.
- Primeiro caso: Equatorial Energia Goias (fantasia do pedido) -> CNPJ do emitente
  `01543032000104` (Equatorial Goias Distribuidora de Energia S.A.).

### v1.5 (16/07/2026) - PALIATIVO PROVISORIO (ver 3.6)
- Bloqueio provisorio de lancamento quando ha PIS/COFINS reconhecidos no documento
  (ver secao 3.6) - registra status "Provisorio" no BD e avisa Teams para lancamento manual.
- **NAO E DEFINITIVO:** criado por falta de controle confiavel do lancamento de PIS/COFINS.
  Remover assim que a TI resolver (instrucoes de remocao na secao 3.6).

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
