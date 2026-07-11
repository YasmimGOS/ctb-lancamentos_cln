# Arquitetura — LancamentoCLN (Python)

Arquitetura **em camadas (N-Tier)** com elementos de **DDD**. Services *stateless*
e injetáveis (facilita testes e `MODO_TESTE`), contratos em Pydantic.

```
main.py  (entry point / DISPARO do lote)
  └─ controllers/lancamento_controller.py       (orquestração do pipeline)
       └─ services/                              (lógica de negócio, stateless)
            ├─ etl_service.py                    (transformação → carga)
            ├─ business_rules.py                 (regras puras e testáveis)
            ├─ ia_service.py                     (IA multimodal assíncrona)
            ├─ power_flow.py                     (seleção/priorização)
            ├─ integra_bpms_service.py           (APIs BPMS/Serviços/registro)
            ├─ integra_megaintegrador_service.py (lançamento no Mega)
            └─ notification_service.py           (Teams/webhook)
       └─ models.py                              (contratos Pydantic)
       └─ utils/  (formatter · validators · logger)   (transversal)
       └─ config/settings.py                     (env vars + tabelas de domínio)
```

## Camadas
- **config/** — variáveis de ambiente (lê `config/.env`) e tabelas de domínio.
- **controllers/** — orquestra o pipeline; contém a árvore de decisão.
- **services/** — regra de negócio isolada; sem estado; injetável (DI).
- **models.py** — schemas Pydantic (validação de tipos e contrato do ERP).
- **utils/** — formatação, validação e logging estruturado.

## Características
- ✓ Separação de responsabilidades clara entre camadas.
- ✓ Services *stateless* → testáveis (`tests/` cobre as regras e o ETL).
- ✓ Pydantic valida a carga de saída (fronteira com o Mega).
- ✓ Logging estruturado (`utils/logger.py`).
- ✓ `MODO_TESTE=True` evita escrita externa; `ENVIAR_WEBHOOK_EM_TESTE` e
  `USAR_PDF_MOCK` para cenários de teste.
- ✓ Injeção de dependências no controller (troca por mocks nos testes).

## Disparo
`python -m lancamento_cln.main` (ou `lancamento-cln`) executa **um lote**,
espelhando o gatilho de recorrência. Agende externamente (cron / Task Scheduler
/ Airflow) no intervalo desejado (ex.: 30 min).

## Escalabilidade (paralelismo)
`executar_lote()` processa os pedidos **em paralelo** quando `MAX_WORKERS > 1`
(padrao 1 = sequencial). Como o gargalo e I/O (HTTP + *polling* da IA), usar
threads reduz muito o tempo total. Cada pedido roda isolado (`_processar_seguro`):
uma falha nao derruba o lote. Sugestao: `MAX_WORKERS=4..8` (respeitar limites de
taxa das APIs/IA). Sem filtro, o lote pega os primeiros `LIMITE_PEDIDOS`
(0 = todos) e distribui entre os workers.
