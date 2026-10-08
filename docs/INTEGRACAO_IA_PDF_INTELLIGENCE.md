# Integração com o serviço de IA (AI PDF Intelligence)

> Documento de referência técnica sobre como este projeto (CLN) chama o serviço de IA que lê
> documentos fiscais (PDF/imagem) e devolve os dados extraídos em JSON. Objetivo: servir de modelo
> para a TI replicar a mesma integração em outros projetos/RPAs.

Serviço: **AI PDF Intelligence** (Cloud Run, `us-central1`)
Documentação interativa (Swagger): https://ai-pdf-intelligence-tasks-39936366597.us-central1.run.app/docs

---

## 1. Visão geral do fluxo

O serviço é **assíncrono**: você não recebe o resultado da leitura na mesma requisição que envia o
documento. O padrão é **submit → poll**:

```
1. POST /pdf/async   (envia o documento em base64 + prompt)  -> devolve { "job_id": "..." }
2. GET  /status/{job_id}   (repetido em polling)              -> devolve { "status": "...", "intel_answer": "..." }
```

Nenhuma chamada de IA é feita sem antes verificar se o serviço está de pé (`/health`) — ver seção 6.

Neste projeto, toda a integração está isolada em **`services/ia_service.py`** (classe `IaService`).
Nenhum outro módulo monta a requisição HTTP para a IA diretamente — todos os pontos do sistema que
precisam ler um documento passam por essa classe. Essa camada de isolamento é o que torna a
integração fácil de replicar em outro projeto: basta copiar `ia_service.py` + os prompts e adaptar.

---

## 2. Chamada 1 — Submissão do documento (`POST /pdf/async`)

### Endpoint
```
POST {AI_PDF_INTELLIGENCE_BASE_URL}/pdf/async
```

### Headers
```
X-API-Key: <chave do projeto>
Content-Type: application/json
```
A chave é **por projeto** (cada projeto/cliente da IA tem a sua própria `X-API-Key`; não são
intercambiáveis — ver seção 8).

### Corpo da requisição (JSON)

| Campo         | Tipo   | Obrigatório | Descrição |
|---------------|--------|:---:|-----------|
| `base64_pdf`  | string | um dos dois | Conteúdo do **PDF** em base64 (sem prefixo `data:...;base64,`). |
| `base64_image`| string | um dos dois | Conteúdo de uma **imagem** (PNG/JPG/etc.) em base64. Usar no lugar de `base64_pdf` quando o anexo é imagem — ver seção 4. |
| `prompt`      | string | sim | Texto de instrução que diz à IA o que extrair e em que formato devolver (ver seção 3). |
| `model_tier`  | string | não (padrão `medio`) | Nível de "esforço"/custo do modelo — ver seção 5. |
| `model`       | string | não | Override do modelo Anthropic específico (ex.: `claude-sonnet-4-5-20250929`). Só enviado se configurado; normalmente omitido e o serviço usa seu próprio default por tier. |
| `max_tokens`  | int | não | Teto de tokens de saída (neste projeto, `4096`). Só enviado se configurado. |

Exemplo real (`services/ia_service.py::_extrair`):
```python
headers = {"X-API-Key": self.s.ia_api_key}
campo_conteudo = "base64_image" if eh_imagem else "base64_pdf"
corpo = {campo_conteudo: conteudo_base64, "prompt": prompt, "model_tier": model_tier}
if self.s.ia_model:
    corpo["model"] = self.s.ia_model
if self.s.ia_max_tokens:
    corpo["max_tokens"] = self.s.ia_max_tokens

resp = requests.post(url, headers=headers, json=corpo, timeout=120)
job_id = resp.json()["job_id"]
```

### Exemplo completo do body enviado (PDF)

O `prompt` é enviado por extenso (o conteúdo inteiro do arquivo `.txt`, não um resumo) — abaixo,
truncado só para caber no exemplo:

```json
{
  "base64_pdf": "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoK...",
  "prompt": "Objetivo:\nExtrair e estruturar informações de DOCUMENTOS FISCAIS BRASILEIROS, como NF-e, NFC-e, NFS-e,\nCT-e, boletos, DANFE, RPS, faturas e documentos equivalentes, a partir de imagem, PDF ou texto,\nretornando exclusivamente um JSON válido que siga exatamente o template abaixo.\n\nTemplate obrigatório:\n{\n  \"tipoDocFiscal\": \"string\",\n  \"numNota\": \"string\",\n  ... (texto completo do arquivo prompts/prompt_1a_ia.txt, ~830 linhas) ...",
  "model_tier": "medio",
  "model": "claude-sonnet-4-5-20250929",
  "max_tokens": 4096
}
```

### Exemplo completo do body enviado (imagem)

Idêntico ao de cima, trocando só o campo do conteúdo:
```json
{
  "base64_image": "iVBORw0KGgoAAAANSUhEUgAAB4AAAAeACAYAAAB1...",
  "prompt": "Objetivo:\nExtrair e estruturar informações de DOCUMENTOS FISCAIS BRASILEIROS...",
  "model_tier": "medio"
}
```

### Resposta da submissão (`POST /pdf/async`)
```json
{
  "job_id": "3f9a1c2e-7b4d-4a1f-9e2c-8d5a6f0b1c9d"
}
```

### Resposta esperada
```json
{ "job_id": "3f9a1c2e-....." }
```
Se `job_id` não vier na resposta, é tratado como erro fatal (`RuntimeError("IA nao retornou job_id")`)
— não adianta prosseguir para o polling sem ele.

### Resiliência nesta chamada
- Timeout de 120s.
- Até 3 tentativas, com 30s de espera entre elas, em caso de erro 5xx **ou 401** (o 401 é tratado
  como falha transitória conhecida do serviço, não como chave inválida — foi observado acontecer e
  se resolver sozinho em retry).

---

## 3. O `prompt`: como a extração é orientada

O `prompt` é um texto grande (não um few-shot com exemplos de imagem, só instrução textual) que:
1. Define o **template JSON obrigatório de saída** (lista fixa de campos, todos como string) — a IA
   deve devolver exclusivamente esse JSON, nada de texto ao redor.
2. Lista **regras de negócio/domínio** para preencher cada campo corretamente (ex.: como
   diferenciar NF-e de NFS-e, como tratar retenções, como calcular ISS, exceções por tipo de
   documento etc.).

Neste projeto há **3 prompts**, carregados de arquivos texto em `prompts/` (função
`_carregar_prompt`, que só faz `Path.read_text`) e usados em **3 chamadas distintas** por documento
(ver seção 7):

| Arquivo | Uso | Tamanho |
|---|---|---|
| `prompts/prompt_1a_ia.txt` | Extração primária — todos os campos gerais do documento fiscal (cabeçalho, valores, tributos). | ~830 linhas |
| `prompts/prompt_2a_ia.txt` | Extração "extra" — campos complementares (2ª chamada, sempre executada após a primária). | ~377 linhas |
| `prompts/prompt_3a_equatorial_ia.txt` | Extração condicional — só para faturas de energia elétrica do fornecedor Equatorial, que tem estrutura de itens (seções FORNECIMENTO/ITENS FINANCEIROS) que os outros dois prompts não cobrem. | ~122 linhas |

Padrão recomendado para replicar: **um prompt por "visão" do documento**, cada um pedindo um JSON
com um conjunto de campos fixo. Isso mantém cada prompt menor/mais preciso do que um único prompt
gigante tentando extrair tudo de uma vez, e permite chamadas condicionais (ex.: só dispara o prompt
3 se o documento for de um fornecedor específico).

---

## 4. Documento em imagem vs. PDF

A API aceita os dois formatos, um campo por vez:

- PDF → campo `base64_pdf`
- Imagem (PNG, JPG, etc.) → campo `base64_image`

O resto do fluxo é **idêntico**: mesmo endpoint de submissão, mesmo `job_id`, mesmo polling em
`/status/{job_id}`. A única mudança é qual dos dois campos vai no corpo do `POST`.

Neste projeto, a decisão de qual campo usar é feita pela extensão do arquivo do anexo
(`controllers/lancamento_controller.py`):
```python
eh_imagem = nome.lower().endswith(IMAGENS)  # ex.: (".png", ".jpg", ".jpeg", ...)
...
ia_raw = self.ia.extrair_primaria(base64_conteudo, model_tier=model_tier_pedido, eh_imagem=eh_imagem)
```
e propagada até `_extrair`, que escolhe o campo:
```python
campo_conteudo = "base64_image" if eh_imagem else "base64_pdf"
```

Importante: quando o anexo é imagem, o **pré-processamento de PDF** (rasterização, correção de
rotação — ver seção 9) é pulado; ele só se aplica a PDFs.

---

## 5. `model_tier`: modelo por complexidade

Campo opcional no corpo do `POST /pdf/async`. Controla o "esforço"/custo do modelo usado pela IA
para ler o documento. Quatro valores:

| Valor | Quando usar |
|---|---|
| `leve` | Documento simples, mais rápido e mais barato. |
| `medio` | **Padrão.** Usado por default em praticamente todas as chamadas deste projeto. |
| `alto` | Tabela complicada (ex.: faturas Energisa/Saneago) ou letra pequena. |
| `altissimo` | Casos extremos — raciocínio pesado. O mais caro; reservado para retry pontual. |

### Como este projeto usa os tiers (padrão de custo-consciência a replicar)

O projeto **nunca** escolhe `alto`/`altissimo` de saída — sempre começa em `medio`
(`services/business_rules.py::MODEL_TIER_PADRAO = "medio"`) e só escala para `altissimo` como
**retry único, automático, quando a extração primária vem "vazia criticamente"** (campos essenciais
como `tipoDocFiscal`, `numNota` e `valorTotalDocumento` todos em branco):

```python
# controllers/lancamento_controller.py::_escalar_para_altissimo_se_vazio
def _escalar_para_altissimo_se_vazio(self, ia_raw, base64_pdf, eh_imagem, nome):
    if not br.eh_extracao_vazia_criticamente(ia_raw):
        return ia_raw          # extração ok, não precisa escalar
    ia_raw_altissimo = self.ia.extrair_primaria(base64_pdf, model_tier=br.MODEL_TIER_ALTISSIMO,
                                                 eh_imagem=eh_imagem)
    if br.eh_extracao_vazia_criticamente(ia_raw_altissimo):
        return ia_raw          # nem o tier caro resolveu; segue com o resultado original
    return ia_raw_altissimo    # tier caro resolveu; usa esse resultado
```

Motivo do padrão: **1 tentativa em `medio` + 1 retry condicional em `altissimo`** custa muito menos,
na média, do que sempre chamar em `alto`/`altissimo`, e cobre os casos difíceis sem penalizar o
volume normal de documentos simples.

---

## 6. Health check antes de processar (evita gastar tempo com o serviço fora do ar)

Antes de processar qualquer lote de documentos, o projeto chama `GET /health` para distinguir dois
cenários de falha bem diferentes (`IaService.verificar_servico_ia`):

- **Deploy quebrado**: Cloud Run responde com HTML (não JSON) — falha imediata, não adianta
  insistir; aciona a TI.
- **Cold start (scale-to-zero)**: o container está "dormindo" e precisa de um ping para acordar —
  nesse caso um simples GET já resolve (`aquecer_servico_ia`, chamado antes do lote).

```python
r = requests.get(f"{base_url}/health", timeout=15)
if r.status_code == 200:
    return True, ""
if "text/html" in r.headers.get("Content-Type", ""):
    return False, "Deploy quebrado ou fora do ar"
return True, ""   # respondeu JSON (mesmo que não 200) = container ativo
```

Se o `/health` falhar, o lote inteiro é abortado com **uma única notificação**, em vez de deixar
cada documento falhar sozinho no polling (o que levaria ~7 min de timeout por documento, sem motivo).

---

## 7. Chamada 2 — Polling do resultado (`GET /status/{job_id}`)

### Endpoint
```
GET {AI_PDF_INTELLIGENCE_STATUS_URL}/{job_id}
Headers: X-API-Key: <chave do projeto>
```

### Estratégia de polling (backoff exponencial)

```python
intervalo_atual = 2          # IA_POLL_INTERVALO_INICIAL_S
intervalo_maximo = 15        # IA_POLL_INTERVALO_MAXIMO_S
max_tentativas = 30          # IA_POLL_MAX_TENTATIVAS

for tentativa in range(1, max_tentativas + 1):
    time.sleep(intervalo_atual)
    st = requests.get(f"{status_url}/{job_id}", headers=headers, timeout=60)
    ...
    # dobra o intervalo a cada rodada até bater no teto de 15s
    intervalo_atual = min(intervalo_atual * 2, intervalo_maximo)
```
Com esses parâmetros, o tempo total máximo de espera fica em torno de **~7 minutos** antes de
desistir com `TimeoutError`.

### Tratamento de cada `status` possível

| `status` retornado | Ação |
|---|---|
| `COMPLETED` | Extrai `intel_answer` (string JSON), faz parse e retorna o dict. Fim do polling. |
| `FAILED` / `EXPIRED` | **Curto-circuito**: aborta imediatamente com erro, sem esperar o timeout completo — esses são status terminais, um novo polling do mesmo job nunca vai mudar o resultado. |
| `404` (job não encontrado) | Tratado como "ainda não propagou entre instâncias do serviço" (não como erro), **mas só até 5 vezes consecutivas** (`MAX_404_CONSECUTIVOS`) — depois disso, aborta assumindo que o job nunca foi criado/persistido. |
| qualquer outro (`PROCESSING`, etc.) | Continua o polling, aplicando o backoff. |

### Resposta bruta do `GET /status/{job_id}` (status `COMPLETED`)

`intel_answer` vem como **string** (JSON serializado dentro de um campo JSON, às vezes com cerca de
markdown) — não como objeto JSON nativo. Exemplo real de resposta:
```json
{
  "job_id": "3f9a1c2e-7b4d-4a1f-9e2c-8d5a6f0b1c9d",
  "status": "COMPLETED",
  "intel_answer": "```json\n{\n  \"tipoDocFiscal\": \"NF-E\",\n  \"numNota\": \"123456\",\n  \"serie\": \"1\",\n  \"dataDocumento\": \"15/07/2026\",\n  \"dataVencimento\": \"30/07/2026\",\n  \"almoxarifado\": \"\",\n  \"chaveAcesso\": \"52260712345678000199550010001234561123456789\",\n  \"municipioPrestacao\": \"GOIANIA\",\n  \"ufPrestacao\": \"GO\",\n  \"nomeEmitente\": \"FORNECEDOR EXEMPLO LTDA\",\n  \"cnpjEmitente\": \"12345678000199\",\n  \"nomeTomador\": \"RAPIDO ARAGUAIA\",\n  \"cnpjCpfTomador\": \"01657436000110\",\n  \"valorTotalDocumento\": \"1500.00\",\n  \"valorMercadoria\": \"1500.00\",\n  \"totalISS\": \"0.00\",\n  \"totalIRRF\": \"0.00\",\n  \"valorPIS\": \"0.00\",\n  \"valorCOFINS\": \"0.00\"\n}\n```"
}
```

### JSON final após `_limpar_json` (1ª chamada — `prompt_1a_ia.txt`, extração primária)

Depois de remover as cercas de markdown e fazer `json.loads`, o dict devolvido por
`IaService.extrair_primaria` segue **todos** os campos do template obrigatório (`services/ia_service.py`
sempre entrega os 79 campos abaixo, todos como string, `"0.00"`/`""` quando não aplicável/ausente):

```json
{
  "tipoDocFiscal": "NF-E",
  "numNota": "123456",
  "serie": "1",
  "dataDocumento": "15/07/2026",
  "dataVencimento": "30/07/2026",
  "almoxarifado": "",
  "chaveAcesso": "52260712345678000199550010001234561123456789",
  "municipioPrestacao": "GOIANIA",
  "ufPrestacao": "GO",
  "nomeEmitente": "FORNECEDOR EXEMPLO LTDA",
  "cnpjEmitente": "12345678000199",
  "nomeTomador": "RAPIDO ARAGUAIA",
  "cnpjCpfTomador": "01657436000110",
  "valorTotalDocumento": "1500.00",
  "valorMercadoria": "1500.00",
  "totalMaoObra": "0.00",
  "totalFrete": "0.00",
  "totalSeguro": "0.00",
  "totalDespesa": "0.00",
  "totalImportacao": "0.00",
  "despesaNaoTributada": "0.00",
  "valorAcrescimoGeral": "0.00",
  "valorDescontoGeral": "0.00",
  "baseICMS": "1500.00",
  "valorICMS": "270.00",
  "totalISS": "0.00",
  "totalIRRF": "0.00",
  "totalINSS": "0.00",
  "valorSestSenat": "0.00",
  "baseSubstTributaria": "0.00",
  "valorICMSRetido": "0.00",
  "valorPIS": "0.00",
  "valorCOFINS": "0.00",
  "totalCSLL": "0.00",
  "baseFunRural": "0.00",
  "valorFunRural": "0.00",
  "valorICMSDesonera": "0.00",
  "valorPisRecupera": "0.00",
  "valorCofinsRecupera": "0.00",
  "percDesconto": "0.00",
  "valorDesconto": "0.00",
  "valorMaoObra": "0.00",
  "valorMercadoriaEmpr": "0.00",
  "valorBaseIPI": "0.00",
  "percIPI": "0.00",
  "valorIPI": "0.00",
  "valorIsentoIPI": "0.00",
  "valorOutrosIPI": "0.00",
  "valorRecuperadoIPI": "0.00",
  "percentualIcms": "18.00",
  "valorIsentoIcms": "0.00",
  "valorOutrosIcms": "0.00",
  "valorIcmsRecupera": "0.00",
  "valorIcmsRetido": "0.00",
  "baseSubTrib": "0.00",
  "baseISS": "0.00",
  "percentualISS": "0.00",
  "valorISS": "0.00",
  "baseIRFF": "0.00",
  "percentualIRFF": "0.00",
  "valorIRFF": "0.00",
  "baseINSS": "0.00",
  "percentualINSS": "0.00",
  "valorINSS": "0.00",
  "basePIS": "0.00",
  "percentualPIS": "0.00",
  "baseCofins": "0.00",
  "percentualCofins": "0.00",
  "valorCofins": "0.00",
  "baseCSLL": "0.00",
  "percentualCSLL": "0.00",
  "valorCSLL": "0.00"
}
```
(Lista completa do template — inclusive campos com grafia parecida mas distinta, ex. `valorPIS` vs.
`percentualPIS`/`basePIS` — está em `prompts/prompt_1a_ia.txt`, linhas 7-80.)

### JSON de saída da 2ª chamada (`prompt_2a_ia.txt` — extração "extra", sempre executada)

Template bem menor, focado em validação cruzada (chave de acesso, retenção de ISS, tomador):
```json
{
  "chaveAcesso": "52260712345678000199550010001234561123456789",
  "issRetido": false,
  "valorISSRetido": "0.00",
  "cnpjCpfTomador": "01657436000110",
  "numNota": "123456"
}
```
Note que `issRetido` é o único campo booleano nativo em todo o contrato — todos os outros campos,
em todos os 3 prompts, são string mesmo quando representam número/data/flag.

### JSON de saída da 3ª chamada (`prompt_3a_equatorial_ia.txt` — condicional, só fornecedor Equatorial)

```json
{
  "totalFornecimento": "842.17",
  "itensFinanceiros": [
    {"descricao": "JUROS DE MORA", "valores": ["12.30"]},
    {"descricao": "MULTA POR ATRASO", "valores": ["8.42", "0.00"]}
  ]
}
```
Este é o único dos 3 templates cujo formato de saída não é "chave: string" simples — tem um array de
objetos (`itensFinanceiros`), porque a fatura de energia lista um número variável de itens
financeiros linha a linha.

### `intel_answer`: parsing defensivo
O campo `intel_answer` vem como **string** contendo JSON (às vezes cercado por ```` ```json ... ``` ````
markdown fence). O parsing remove esses marcadores antes de decodificar, e se ainda assim não for
JSON válido, loga o erro e devolve `{}` em vez de derrubar o processo:
```python
def _limpar_json(texto: str) -> dict:
    s = (texto or "{}").strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(s or "{}")
    except json.JSONDecodeError:
        log.error("intel_answer nao e JSON valido: %.200s", s)
        return {}
```

---

## 8. Autenticação e chaves — uma chave por projeto

- Header: `X-API-Key`.
- Cada projeto/cliente que consome a API AI PDF Intelligence tem sua **própria chave**, configurada
  via variável de ambiente (neste projeto, `ANTHROPIC_API_KEY` no `.env`, mapeada para
  `Settings.ia_api_key`). **As chaves não são compartilháveis entre projetos** — a chave usada por
  este projeto (CLN) é diferente da chave que será usada pelo projeto **Aquisição de Novos
  Talentos** (chave a ser enviada separadamente pela usuária).
- Ao replicar em outro projeto: solicitar/gerar a chave específica do novo projeto e configurá-la
  como variável de ambiente própria — nunca reaproveitar a chave de outro projeto.

### Variáveis de ambiente usadas nesta integração (`config/settings.py`)

| Variável | Papel |
|---|---|
| `ANTHROPIC_API_KEY` | Chave do projeto (`X-API-Key`). |
| `ANTHROPIC_API_URL` (ou `AI_PDF_INTELLIGENCE_BASE_URL` + `/pdf/async`) | URL de submissão. |
| `AI_PDF_INTELLIGENCE_STATUS_URL` | URL base do polling (`/status`). |
| `ANTHROPIC_MODEL` | Override opcional do modelo (campo `model` no corpo). |
| `MAX_TOKENS` | Teto de tokens de saída (campo `max_tokens`, default `4096`). |
| `IA_POLL_INTERVALO_INICIAL_S` | Intervalo inicial do polling em segundos (default `2`). |
| `IA_POLL_INTERVALO_MAXIMO_S` | Teto do backoff em segundos (default `15`). |
| `IA_POLL_MAX_TENTATIVAS` | Nº máximo de checagens de status (default `30`). |
| `IA_POLL_USAR_BACKOFF` | Liga/desliga o backoff exponencial (default `true`). |

---

## 9. Pré-processamento antes de enviar (só para PDF)

Antes de qualquer PDF ser enviado à IA, ele passa por `utils/pdf_preflight.py::normalizar_documento`:

1. Valida que o base64 realmente decodifica para um PDF.
2. Mede se o PDF tem camada de texto nativa. Se tiver, segue sem alteração (mais barato/rápido).
3. Se **não** tiver texto (PDF vetorizado/escaneado — ex.: layout DANFSe v2.0), re-renderiza a
   página em 300 DPI e detecta/corrige rotação (texto na vertical vs. horizontal) usando perfil de
   projeção de tinta (`numpy`/`Pillow`/`PyMuPDF`).
4. Se a extração da IA vier "vazia criticamente" e o laudo do pré-voo indicar rotação alternativa
   possível (heurística não distingue 90° de 270°), o controller reenvia **uma vez** com a rotação
   oposta antes de escalar para o tier `altissimo` (mais barato do que trocar de modelo).
5. Qualquer falha não fatal no pré-processamento (dependência ausente, etc.) devolve o documento
   original sem quebrar o fluxo.

Esse pré-processamento é específico deste projeto (não faz parte do contrato da API de IA) — pode
ou não valer a pena replicar, dependendo de quão "sujos" costumam ser os PDFs do novo projeto.

---

## 10. Sequência completa por documento (visão de ponta a ponta)

```
┌─ Início do lote ────────────────────────────────────────────────────────┐
│ 1. GET /health  → serviço operacional? (aborta lote inteiro se não)     │
└───────────────────────────────────────────────────────────────────────┘
Para cada anexo do pedido:
  2. Detecta se é imagem (extensão) ou PDF.
  3. Se PDF: pré-voo (pdf_preflight) → pode rasterizar/corrigir rotação.
  4. Chamada de IA #1 (prompt_1a_ia.txt) — extração primária:
       POST /pdf/async  { base64_pdf|base64_image, prompt, model_tier: "medio" }
       → job_id
       GET /status/{job_id}  (polling com backoff) → intel_answer (JSON)
     4a. Se extração veio vazia E havia rotação alternativa → reenvia 1x com rotação oposta.
     4b. Se extração ainda veio vazia criticamente → reenvia 1x com model_tier "altissimo".
  5. Chamada de IA #2 (prompt_2a_ia.txt) — extração "extra" (sempre executada).
  6. [Condicional] Chamada de IA #3 (prompt_3a_equatorial_ia.txt) — só se o
     fornecedor for identificado como Equatorial (fatura de energia elétrica).
       6a. Se não reconciliar e o tier usado não era "altissimo" → 1 retry em "altissimo".
  7. Resultados das 3 chamadas são combinados/reconciliados para montar o
     payload final do lançamento.
```

---

## 11. Resumo para replicar em outro projeto

Checklist mínimo:
1. Obter a `X-API-Key` específica do novo projeto (não reaproveitar chave de outro projeto).
2. Configurar as URLs (`/pdf/async` para submissão, `/status` para polling) como variáveis de
   ambiente.
3. Escrever um ou mais `prompt_*.txt` com o template JSON de saída + regras de negócio do domínio
   do novo projeto (o padrão "1 prompt = 1 visão do documento, campos fixos" facilita manutenção).
4. Implementar uma classe fina (equivalente a `IaService`) com:
   - `verificar_servico_ia()` / warm-up via `/health` antes de processar lotes;
   - um método de extração genérico que decide `base64_pdf` vs `base64_image` conforme o tipo de
     arquivo, aceita `model_tier` como parâmetro (default `medio`), faz o `POST` e depois o
     polling com backoff exponencial e tratamento de `COMPLETED`/`FAILED`/`EXPIRED`/`404`;
   - parsing defensivo do `intel_answer` (remover fences de markdown, `try/except JSONDecodeError`).
5. (Opcional, mas recomendado pelo padrão de custo deste projeto) só escalar para `alto`/`altissimo`
   como retry condicional quando a extração em `medio` vier vazia/insuficiente — nunca como default.
6. (Opcional) Pré-processar PDFs sem camada de texto antes de enviar, se o volume de documentos
   escaneados/vetorizados for relevante no novo projeto.

## 12. Referências no código (este projeto)

| Arquivo | Papel |
|---|---|
| `services/ia_service.py` | Toda a integração HTTP com a IA (submit, poll, health, warm-up). |
| `prompts/prompt_1a_ia.txt`, `prompt_2a_ia.txt`, `prompt_3a_equatorial_ia.txt` | Os 3 prompts usados. |
| `services/http_client.py` | Wrapper HTTP genérico (retry, timeout, logging com redação de segredos/base64). |
| `config/settings.py` | Todas as variáveis de ambiente da integração. |
| `controllers/lancamento_controller.py` | Orquestração: ordem das 3 chamadas por documento, escalonamento de tier, retries, tratamento de imagem vs. PDF. |
| `utils/pdf_preflight.py` | Pré-processamento de PDF (rasterização/rotação) antes do envio. |
| `services/business_rules.py` | `MODEL_TIER_PADRAO`, `MODEL_TIER_ALTISSIMO`, `eh_extracao_vazia_criticamente`. |
