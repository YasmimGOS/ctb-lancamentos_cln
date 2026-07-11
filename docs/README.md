# LancamentoCLN (Python)

Reescrita em Python do fluxo Power Automate **LancamentoCLN_GoLive**: motor de ETL
que obtem pedidos aguardando CLN, extrai dados fiscais de PDFs via IA multimodal,
monta a carga JSON do recebimento e submete ao Mega ERP.

Arquitetura em camadas (N-Tier + DDD). **Versao:** 1.4

---

## Documentacao

### Documentos Essenciais

1. **[REGRAS_PROJETO.md](src/docs/REGRAS_PROJETO.md)** - Todas as regras de negocio consolidadas (fonte da verdade)
2. **[CLAUDE.md](src/docs/CLAUDE.md)** - Instrucoes para o assistente Claude ao trabalhar no projeto
3. **[ARQUITETURA.md](ARQUITETURA.md)** - Arquitetura em camadas do projeto
4. **[documentacao_lancamento_cln.md](documentacao_lancamento_cln.md)** - Especificacao funcional completa v1.4

### Estrutura de Pastas

```
ctb-lancamentos_cln/
├── config/                      # Configuracoes + .env
├── controllers/                 # Orquestracao do pipeline
├── services/                    # Logica de negocio (stateless)
├── utils/                       # Formatacao, validacao, logs
├── prompts/                     # Prompts da IA
├── docs/                        # Documentacao
│   ├── REGRAS_PROJETO.md        # Regras de negocio
│   ├── CLAUDE.md                # Instrucoes para Claude
│   ├── ARQUITETURA.md           # Arquitetura em camadas
│   └── documentacao_lancamento_cln.md  # Especificacao funcional
├── tests/                       # Testes unitarios
├── main.py                      # Entry point
├── models.py                    # Contratos Pydantic
├── .env.example                 # Modelo de configuracao
└── README.md                    # Este arquivo
```

---

## Instalacao

### Instalacao Rapida (Desenvolvimento Local)

```bash
# Instalar dependencias direto
pip install pydantic requests python-dateutil python-dotenv

# Criar .env com credenciais
cp .env.example config/.env

# Editar .env e preencher tokens/API keys
# ANTHROPIC_API_KEY, INTEGRA_BPMS_TOKEN, etc.

# Rodar projeto
python main.py
```

### Instalacao Completa (Com Testes)

```bash
# Criar ambiente virtual
python -m venv .venv

# Ativar (Windows Git Bash)
source .venv/Scripts/activate

# Ativar (Linux/Mac)
source .venv/bin/activate

# Instalar com ferramentas de dev
pip install -e ".[dev]"

# Rodar testes
pytest
```

### Configuracao do .env

Coloque o arquivo de credenciais em **`config/.env`**
(ou defina `LANCAMENTO_ENV_FILE`). Modelo em `.env.example`.

**NUNCA** versionar o `.env` (ja esta no `.gitignore`).

---

## Execucao

### Rodar o Projeto

```bash
# Forma 1: diretamente
python main.py

# Forma 2: comando instalado (se instalou com pip install -e .)
lancamento-cln
```

### Modo Teste

Configure no `.env`:

```bash
MODO_TESTE=True
CODIGO_TESTE=7794              # Processa SOMENTE esse pedido
LIMITE_PEDIDOS=1               # Limite de pedidos
ENVIAR_WEBHOOK_EM_TESTE=False  # Nao envia Teams em teste
```

---

## Testes

```bash
# Rodar todos os testes
pytest

# Rodar com cobertura
pytest --cov=lancamento_cln
```

> Regras em `services/business_rules.py` sao funcoes puras e testaveis.
> `MODO_TESTE=True` evita chamadas de escrita externas.

---

## Logs

### Sistema de Logging Detalhado

O projeto possui logging completo para facilitar debug:

**Localizacao:** `logs/ctb-lancamentos_cln_YYYYMMDD_HHMMSS.log`

**Caracteristicas:**
- Console: nivel configuravel via `LOG_LEVEL` (padrao: INFO)
- Arquivo: sempre DEBUG (detalhes completos)
- Rotacao automatica: 10MB por arquivo, 5 backups
- Logs HTTP automaticos: URL, request body, response body, tempo de resposta
- Tokens/senhas: automaticamente redacted nos logs
- Um arquivo por execucao com timestamp completo (data + hora)

**Configuracao:**
```bash
# No .env
LOG_LEVEL=DEBUG  # ou INFO, WARNING, ERROR
```

**Exemplo de log HTTP:**
```
2026-07-10 21:11:34 | INFO  | lancamento_cln.http | HTTP REQUEST | POST https://api.exemplo.com/endpoint
2026-07-10 21:11:34 | DEBUG | lancamento_cln.http | Request Body: {"campo": "valor"}
2026-07-10 21:11:35 | INFO  | lancamento_cln.http | HTTP RESPONSE | Status: 200 | Tempo: 0.45s
2026-07-10 21:11:35 | DEBUG | lancamento_cln.http | Response Body: {"success": true}
```

---

## Prompts da IA

`prompts/*.txt` sao resumos fieis das instrucoes. Para
paridade total com producao, cole o prompt integral que esta no fluxo Power
Automate (o codigo nao muda).

---

## Execucao Paralela

Configure no `.env`:

```bash
MAX_WORKERS=4  # Processa 4 pedidos em paralelo (padrao: 1 = sequencial)
```

Recomendacao: 4-8 workers para I/O intensivo (HTTP + polling IA).

---

## Contribuindo

### Fluxo de Trabalho

1. Ler **`src/docs/REGRAS_PROJETO.md`** antes de alterar regras de negocio
2. Ler **`src/docs/CLAUDE.md`** para entender padroes do projeto
3. Implementar seguindo arquitetura em camadas
4. Adicionar testes unitarios
5. **Atualizar documentacao apos sucesso** (REGRAS_PROJETO.md, CLAUDE.md, README.md)

### Mensagens ao Teams

- **SEM emojis**
- **SEM detalhes tecnicos desnecessarios**
- Objetivas e diretas

---

## Changelog

### v1.4 (10/07/2026)
- Reescrita Python (arquitetura em camadas)
- Precedencia absoluta de APOLICE
- Validacao CNPJ por raiz (matriz vs filial)
- Execucao paralela (MAX_WORKERS)
- Mensagens Teams sem emojis
- Documentacao consolidada (REGRAS_PROJETO.md, CLAUDE.md)

---

**Grupo Odilon Santos** | RPA/OSAC
