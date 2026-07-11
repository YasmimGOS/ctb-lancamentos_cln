# LancamentoCLN_GoLive — Especificação Funcional (v1.4)

> **Objetivo:** fonte única para (re)implementar em Python o motor de ETL que hoje
> roda no Power Automate (`LancamentoCLN_GoLive`). Cobre pipeline, regras de
> negócio, contrato de dados e o mapeamento fluxo → módulos Python.

**Versão:** 1.4 · **Data:** 10/07/2026 · **Autor técnico:** RPA/OSAC

---

## 1. Visão geral
A cada 30 min o robô obtém pedidos **aguardando CLN**, processa cada pedido,
extrai dados fiscais dos PDFs anexos via **IA multimodal assíncrona**, monta a
carga JSON e submete ao **Mega ERP**. Disparo: `main.py` (agendado externamente).

Pipeline: (1) obter lista → (2) selecionar → (3) por pedido: gate reembolso →
obter dados → anexos → (4) por anexo: IA 1ª + IA 2ª → consolidar → montar payload
→ (5) priorizar (NF>CF>REC>BOLP) → (6) validar (APOLICE, CNPJ, 7 dias) →
(7) lançar + registrar (Teams/BD).

## 2. Integrações (via env, sem segredo no código)
| Serviço | Endpoint (env) | Auth (env) |
|---|---|---|
| BPMS lista | `INTEGRA_BPMS_PEDANEXORPA_URL` (GET) | `INTEGRA_BPMS_TOKEN` |
| BPMS dados | `INTEGRA_BPMS_PEDIDODADOSRECEB_URL` (POST) | `INTEGRA_BPMS_TOKEN` |
| Serviços anexos | `INTEGRA_SERVICOS_MEGA_ANEXO_URL` (POST) | `INTEGRA_SERVICOS_TOKEN` |
| BPMS consulta/registro | `INTEGRA_BPMS_BASE_URL` + `/tabpedidosrpaconsulta` / `/tabpedidosrpainsert` | `INTEGRA_BPMS_TOKEN` |
| IA | `ANTHROPIC_API_URL` (submit) + `AI_PDF_INTELLIGENCE_STATUS_URL/{job_id}` | `ANTHROPIC_API_KEY` (X-API-Key) |
| Mega | `INTEGRA_MEGAINTEGRADOR_RECEBIMENTO_URL` | `INTEGRA_MEGAINTEGRADOR_TOKEN` |
| Webhook | `POWER_AUTOMATE_WEBHOOK_URL` | — |

> `config/.env` **não** vai para o Git (ver `.gitignore`). Tokens já vêm com o
> prefixo `Bearer`. A URL do webhook deve começar com `https://`.

## 3. Regras de negócio
- **Datas:** ERP em `dd/MM/yyyy`; converter p/ ISO nos cálculos; inválida → `""`.
  `dataDocumento` é a emissão (nunca o vencimento).
- **tipoDocFiscal:** de-para `→ {contasPagarTipoDoc, acao}`; à vista vs a prazo;
  override por emitente (MAPFRE `61074175000138 → BOLP`) **exceto se APOLICE**
  (⭐ precedência — correção v1.4); `BOLP-DETRAN*` viram `BOLP` no cabeçalho;
  tipo desconhecido/APOLICE → guard `{"", 0}`.
- **APOLICE:** não lançar → Teams + registro (bloqueio **antes** do lançamento).
- **ISS (precedência):** apurado × retido; 2ª IA confirma; `valorISSRetido>0`
  sobrepõe ISS; não retenção → zera; `valorISS>0` e `totalISS<=0` → copia.
- **CNPJ por raiz:** emitente×fornecedor e tomador×filial; aceita **mesma raiz**
  (matriz×filial); tomador valida contra de-para (cnpj/nome) e filial do pedido.
- **CondPagto:** normaliza `"20D M"→"20D"`; `quantidade` blindada (0 se não
  numérico); vencimento por `D`/`M`; **≤7 dias** bloqueia (exceto aluguel).
- **Valores:** valorMercadoria do item com fallback ao pedido e a `totalNota`
  (boletos); raiz = soma; `totalNota` cai para a soma se ≤0 (correção BOLP).
- **Serviço** (`NFS-EG/NFS-E/NFF/NFSTE/NFSC`): zera baseICMS e valorBaseIPI.
- **Aluguel** (`03397056000110`): valorMercadoria=Aluguel+Encargos; IR impresso.
- **numNota:** remove zeros à esquerda. **série/chave:** por tipoDocFiscal.
- **Reembolso:** `AGN_ST_FANTASIA` contém "REEMBOLSO" → não lançar + Teams.

## 4. JSON final
Raiz + `itensReceb[]` (com `centrosCusto[]`→`projetos[]` e `pedidos[]`) +
`parcelas[]`. `totalNota == valorMercadoria` (boletos) e valor de item > 0.
Contrato completo tipado em `src/lancamento_cln/models.py` (Pydantic).

## 5. IA (2 chamadas assíncronas por anexo)
1ª (`prompt_1a_ia.txt`) extração completa; 2ª (`prompt_2a_ia.txt`) redundância
(chaveAcesso, issRetido, valorISSRetido, cnpjCpfTomador, numNota). Padrão:
`POST submit → job_id → polling status → COMPLETED → intel_answer` (limpa ```json).

> Os arquivos `prompts/*.txt` são **resumos fiéis**; a versão integral de produção
> está embutida no fluxo Power Automate e pode ser colada aqui sem mudar o código.

## 6. Mapeamento fluxo → Python
config/settings.py (tabelas/tokens) · utils/formatter+validators (helpers WDL) ·
services/business_rules (regras) · services/etl_service (montagem) ·
services/ia_service (IA) · services/integra_* (APIs) · services/power_flow
(seleção/priorização) · controllers/lancamento_controller (árvore) · main.py (disparo).

## 7. Diferenças intencionais x fluxo atual
1. APOLICE e reembolso bloqueiam **antes** do lançamento (não dependem do 400).
2. `if` do Python tem short-circuit (gu- ards preservados nas funções).
3. Parcelamento com **1 parcela** (como produção), com ponto único p/ evoluir.

## 7.1 Escalabilidade
Sem filtro, o lote seleciona os primeiros `LIMITE_PEDIDOS` (0 = todos) e os processa **em paralelo** via `MAX_WORKERS` (ThreadPoolExecutor). Ganho vem do I/O (HTTP + polling da IA). Falha de um pedido nao derruba os demais.

## 8. Changelog
- **v1.4** — Reescrita Python (camadas). Consolida precedência de APOLICE,
  validação de CNPJ por raiz, normalização condPagto, blindagem quantidade,
  fallback de valorMercadoria/totalNota (boletos), APOLICE no prompt e reembolso; execucao paralela por lote (MAX_WORKERS).
