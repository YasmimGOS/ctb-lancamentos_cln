# Instrucoes para Claude - LancamentoCLN

> **Projeto:** LancamentoCLN (Python) | **Versao:** 1.4 | **Data:** 10/07/2026

Este documento contem instrucoes **obrigatorias** para o assistente Claude ao trabalhar neste projeto.

---

## 1. Documentos de Referencia (SEMPRE ler primeiro)

Antes de fazer qualquer alteracao, SEMPRE consulte:

1. **`docs/REGRAS_PROJETO.md`** - Todas as regras de negocio (fonte da verdade)
2. **`docs/documentacao_lancamento_cln.md`** - Especificacao funcional completa v1.4
3. **`docs/ARQUITETURA.md`** - Arquitetura em camadas do projeto
4. **`README.md`** - Como instalar e executar

---

## 2. Arquitetura do Projeto

### Estrutura de Pastas

```
ctb-lancamentos_cln/
├── config/
│   ├── .env                      ← Credenciais (NAO versionar)
│   ├── settings.py               ← Configuracoes + tabelas de dominio
│   └── __init__.py
├── controllers/
│   ├── lancamento_controller.py  ← Orquestracao do pipeline
│   └── __init__.py
├── services/
│   ├── business_rules.py         ← Regras puras (stateless)
│   ├── etl_service.py            ← Transformacao → carga JSON
│   ├── ia_service.py             ← IA multimodal assincrona
│   ├── integra_bpms_service.py   ← APIs BPMS
│   ├── integra_megaintegrador_service.py  ← Lancamento Mega
│   ├── notification_service.py   ← Teams/webhook
│   ├── power_flow.py             ← Selecao/priorizacao
│   ├── http_client.py            ← Cliente HTTP
│   └── __init__.py
├── utils/
│   ├── formatter.py              ← Formatacao de datas/numeros
│   ├── validators.py             ← Validacao de CNPJ/dados
│   ├── logger.py                 ← Logging estruturado
│   └── __init__.py
├── prompts/
│   ├── prompt_1a_ia.txt          ← Prompt 1a IA (extracao)
│   └── prompt_2a_ia.txt          ← Prompt 2a IA (validacao)
├── docs/
│   ├── REGRAS_PROJETO.md         ← Regras de negocio consolidadas
│   ├── CLAUDE.md                 ← Este arquivo
│   ├── documentacao_lancamento_cln.md  ← Especificacao funcional v1.4
│   └── ARQUITETURA.md            ← Arquitetura em camadas
├── tests/                        ← Testes unitarios
├── examples/                     ← Exemplos de uso
├── logs/                         ← Logs de execucao
├── main.py                       ← Entry point / disparador
├── models.py                     ← Contratos Pydantic
├── .env.example                  ← Modelo de .env
├── README.md                     ← Documentacao principal
├── pyproject.toml                ← Configuracao do projeto
└── .gitignore                    ← Arquivos ignorados pelo Git
```

### Camadas

1. **config/** - Variaveis de ambiente e tabelas de dominio
2. **controllers/** - Orquestracao do pipeline (arvore de decisao)
3. **services/** - Logica de negocio isolada, stateless, injetavel
4. **models.py** - Schemas Pydantic (validacao de tipos)
5. **utils/** - Formatacao, validacao, logging (transversal)

---

## 3. Principios de Desenvolvimento

### 3.1 Regras de Negocio

- **NUNCA altere regras de negocio sem validacao explicita do usuario**
- Todas as regras estao em `services/business_rules.py` (funcoes puras)
- Consulte `src/docs/REGRAS_PROJETO.md` antes de qualquer mudanca
- Regras sao **stateless** e **testaveis**

### 3.2 Separacao de Responsabilidades

- **Controllers:** APENAS orquestracao, NAO contem logica de negocio
- **Services:** logica de negocio isolada, sem I/O direto
- **Utils:** funcoes auxiliares reutilizaveis
- **Models:** contratos de dados (Pydantic)

### 3.3 Codigo Limpo

- Funcoes pequenas e focadas (Single Responsibility)
- Nomes descritivos em portugues (padrao do projeto)
- Comentarios apenas quando necessario (codigo auto-explicativo)
- Type hints SEMPRE (Python 3.10+)

### 3.4 Testes

- Regras de negocio DEVEM ter testes unitarios
- Usar mocks para I/O (APIs, IA, BD)
- `MODO_TESTE=True` para testes de integracao

---

## 4. Mensagens ao Teams

### 4.1 Formato Obrigatorio

- **SEM emojis** (removidos em v1.4)
- **SEM detalhes tecnicos desnecessarios**
- **Objetivas e diretas**
- Apenas conteudo que sera exibido no Teams

### 4.2 Exemplos Corretos

```
✓ Pedido 7794 lancado com sucesso. NF 12345 | Transacao 67890
✓ Pedido 7794 identificado como REEMBOLSO. Requer lancamento manual.
✓ Pedido 7794: CNPJ do emitente divergente (Fornecedor: 12345678000100 / Emitente: 98765432000111).
✓ Falha ao lancar pedido 7794. Verificar logs para detalhes.
```

### 4.3 Exemplos Incorretos

```
✗ ❌ Falha ao obter lista de pedidos.
✗ É necessário inspecionar os detalhes técnicos de execução do fluxo para fazer o diagnóstico deste erro.
✗ 🎉 Sucesso total!
```

---

## 5. Fluxo de Trabalho

### 5.1 Ao Receber uma Solicitacao

1. Ler `src/docs/REGRAS_PROJETO.md` para entender contexto
2. Verificar arquivos envolvidos
3. Propor solucao respeitando arquitetura em camadas
4. Implementar com testes (se aplicavel)
5. Atualizar documentacao (ver 5.3)

### 5.2 Ao Corrigir um Bug

1. Identificar a camada responsavel
2. Corrigir mantendo separacao de responsabilidades
3. Adicionar teste para prevenir regressao
4. Atualizar documentacao se necessario

### 5.3 OBRIGATORIO: Atualizar Documentacao Apos Sucesso

**Sempre que uma implementacao for bem-sucedida, atualize:**

1. **`src/docs/REGRAS_PROJETO.md`** - Se regras de negocio mudaram
2. **`src/docs/CLAUDE.md`** - Se novos padroes/instrucoes foram adicionados
3. **`README.md`** - Se instalacao/uso mudou

**Formato do changelog:**
```markdown
### vX.Y (DD/MM/YYYY)
- Descricao breve da mudanca
- Impacto em regras de negocio
- Novos arquivos/modulos criados
```

---

## 6. Variaveis de Ambiente

### 6.1 Localizacao do .env

Ordem de busca:
1. `LANCAMENTO_ENV_FILE` (variavel de ambiente)
2. `config/.env` ← **RECOMENDADO**
3. `.env` (raiz)

### 6.2 Nunca Versionar

- `.env` esta no `.gitignore`
- Tokens sempre com prefixo `Bearer` (automatico no settings.py)
- Usar `.env.example` como modelo

---

## 7. Execucao e Testes

### 7.1 Rodar Localmente

```bash
# Instalar dependencias
pip install pydantic requests python-dateutil python-dotenv

# Rodar projeto
python main.py
```

### 7.2 Modo Teste

```bash
# No .env
MODO_TESTE=True
CODIGO_TESTE=7794
LIMITE_PEDIDOS=1
ENVIAR_WEBHOOK_EM_TESTE=False
```

### 7.3 Testes Unitarios

```bash
pytest tests/
```

---

## 8. Padroes de Codigo

### 8.1 Imports

```python
from __future__ import annotations

# Standard library
import sys
from pathlib import Path

# Third-party
from pydantic import BaseModel
import requests

# Local
from ..config import get_settings
from ..utils import get_logger
```

### 8.2 Funcoes de Regra de Negocio

```python
def nome_descritivo(param1: str, param2: int) -> dict:
    """Docstring clara explicando o que a funcao faz.

    Args:
        param1: Descricao do parametro
        param2: Descricao do parametro

    Returns:
        Descricao do retorno
    """
    # Logica aqui
    return resultado
```

### 8.3 Services

```python
class MeuService:
    def __init__(self, settings=None):
        self.s = settings or get_settings()

    def metodo_publico(self, param: str) -> dict:
        """Metodo publico documentado."""
        return self._metodo_privado(param)

    def _metodo_privado(self, param: str) -> dict:
        """Metodo privado (prefixo _)."""
        # Logica interna
        return {}
```

---

## 9. Logs

### 9.1 Estrutura de Logging

**Logs sao salvos em:** `logs/ctb-lancamentos_cln_YYYYMMDD_HHMMSS.log`

- **Console:** nivel configuravel via `LOG_LEVEL` (padrao: INFO)
- **Arquivo:** sempre DEBUG (detalhado)
- **Rotacao:** 10MB por arquivo, 5 backups
- **Formato arquivo:** timestamp | nivel | modulo | funcao | mensagem
- **Exemplo nome:** `ctb-lancamentos_cln_20260710_211339.log`

### 9.2 Niveis

- `log.debug()` - Detalhes de debug (request/response bodies completos)
- `log.info()` - Informacoes gerais (progresso, URLs, status)
- `log.warning()` - Avisos (tentativas de retry)
- `log.error()` - Erros (nao criticos)
- `log.exception()` - Erros com stacktrace

### 9.3 Logging HTTP (Automatico)

O `http_client.py` loga automaticamente:
- **Request:** metodo, URL, headers (tokens redacted), body completo
- **Response:** status code, tempo de resposta, body completo
- **Erros:** tentativas de retry com intervalo

### 9.4 Formato

```python
from utils import get_logger

log = get_logger("nome_modulo")

log.info("Pedido %s processado. Status: %s", pdc, status)
log.error("Falha ao lancar pedido %s: %s", pdc, erro)
```

### 9.5 Exemplo de Log

```
2026-07-10 21:11:34 | INFO     | lancamento_cln.http      | request_json         | ====================================
2026-07-10 21:11:34 | INFO     | lancamento_cln.http      | request_json         | HTTP REQUEST | POST https://api.exemplo.com/endpoint
2026-07-10 21:11:34 | INFO     | lancamento_cln.http      | request_json         | Headers: {'Authorization': '***REDACTED***'}
2026-07-10 21:11:34 | DEBUG    | lancamento_cln.http      | request_json         | Request Body:
{
  "campo1": "valor1",
  "campo2": 123
}
2026-07-10 21:11:35 | INFO     | lancamento_cln.http      | request_json         | HTTP RESPONSE | Status: 200 | Tempo: 0.45s
2026-07-10 21:11:35 | DEBUG    | lancamento_cln.http      | request_json         | Response Body:
{
  "success": true,
  "data": {...}
}
```

---

## 10. Checklist de Validacao

Antes de concluir uma tarefa, verifique:

- [ ] Codigo segue arquitetura em camadas
- [ ] Regras de negocio estao em `business_rules.py`
- [ ] Mensagens Teams sao objetivas e sem emojis
- [ ] Type hints presentes
- [ ] Testes unitarios criados/atualizados
- [ ] Documentacao atualizada (`REGRAS_PROJETO.md`, `CLAUDE.md`, `README.md`)
- [ ] .env nao foi versionado
- [ ] Logs estruturados e claros

---

## 11. Contato e Suporte

- **Documentacao tecnica:** `docs/documentacao_lancamento_cln.md`
- **Arquitetura:** `docs/ARQUITETURA.md`
- **Regras de negocio:** `docs/REGRAS_PROJETO.md`

---

**IMPORTANTE:** Este e um projeto critico para o Grupo Odilon Santos.
Sempre priorize clareza, manutencao e documentacao completa.
