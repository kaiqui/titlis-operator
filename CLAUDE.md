# CLAUDE.md — titlis-operator

> **Regra obrigatória após cada alteração:**
> ```bash
> make lint && make test-unit
> ```
> Nunca entregue código sem confirmar que lint e testes passam.
>
> **Linter de estilo: flake8** — único gate obrigatório de estilo. Config em `.flake8`.
>
> **Proibido usar docstrings** (D100–D107 ignorados no flake8). O código deve ser autoexplicativo.

---

## 1. Visão Geral

O **titlis-operator** é um Kubernetes Operator escrito em Python (Kopf) que automatiza:

- **Scoring de compliance** — avalia Deployments contra 26+ regras em 6 pilares
- **SLO sync** — sincroniza SLOs declarativos com Datadog (3-path idempotency)
- **Auto-criação de SLOs** — detecta Deployments instrumentados com Datadog e cria SLOs padrão automaticamente
- **Notificações Slack** — alerts e digests por namespace (rate-limited)
- **Enriquecimento** — integra Backstage (ownership) e CAST AI (custo)

O operator também envia todos os eventos para o **titlis-api** via HTTP POST em
`/v1/operator/events` (autenticado por API key), que persiste no PostgreSQL para o dashboard.
O nome da classe `TitlisApiUdpClient` é legado — o transporte atual é HTTP.

> **Atenção — migração de responsabilidade:** A responsabilidade de abrir PRs de remediação
> no GitHub **migrou para o `titlis-ai`**. O operator passou a ser exclusivamente um motor de
> avaliação: observa Deployments, calcula scores, escreve CRDs e envia eventos UDP.
> Os seguintes arquivos foram removidos do operator:
> - `src/application/services/remediation_service.py`
> - `src/application/ports/github_port.py`
> - `src/infrastructure/github/`
> - `src/infrastructure/kubernetes/remediation_writer.py`
> - Variáveis `GITHUB_*` e `REMEDIATION_*` do `settings.py`

---

## 2. Stack

| Categoria | Tecnologia | Versão |
|---|---|---|
| Linguagem | Python | 3.12 |
| K8s Operator Framework | Kopf | >=1.39.0 |
| Config/Validação | Pydantic + pydantic-settings | >=2.12.0 |
| HTTP Client | httpx (async) | >=0.27.0 |
| Slack | slack-sdk | >=3.39.0 |
| Datadog | datadog-api-client | >=2.47.0 |
| Kubernetes | kubernetes | >=34.1.0 |
| YAML (round-trip) | ruamel.yaml | >=0.18.0 |
| Logging JSON | python-json-logger + structlog | >=4.0.0 |
| Retry | backoff | >=2.2.1 |
| Package Manager | Poetry | — |
| Testes | pytest + pytest-asyncio + pytest-mock | >=9.0.0 |
| Formatação | black | >=23.11.0 |
| Linting | flake8, mypy, pylint | — |
| Container | python:3.12-slim-bullseye | — |
| Deploy | Helm (charts/titlis-operator/) | — |

---

## 3. Arquitetura Hexagonal

```
Domain Models (src/domain/)
       ↕
Application Services (src/application/services/)
       ↕
Ports / Interfaces (src/application/ports/)
       ↕
Infrastructure Adapters (src/infrastructure/)
  ├── datadog/        DatadogRepository
  ├── slack/          SlackRepository
  ├── kubernetes/     AppScorecardWriter, RemediationWriter, K8sStatusWriter
  ├── backstage/      BackstageEnricher
  ├── castai/         CastaiCostEnricher
  └── titlis_api/     TitlisApiUdpClient (nome legado; usa HTTP internamente)

Controllers (src/controllers/) — thin Kopf handlers
Bootstrap (src/bootstrap/dependencies.py) — DI via @lru_cache
```

**Nota:** GitHub foi removido do operator. PRs de remediação são responsabilidade do `titlis-ai`.

**Regra:** Services nunca importam infrastructure diretamente — usam Ports (interfaces).

---

## 4. Estrutura de Diretórios

```
src/
├── main.py                              # Entry point Kopf + registro de handlers
├── settings.py                          # Pydantic Settings (todas as env vars)
├── bootstrap/
│   └── dependencies.py                  # DI: get_slo_service(), get_scorecard_service(), etc.
├── controllers/
│   ├── base.py                          # BaseController (Slack, status, helpers)
│   ├── scorecard_controller.py          # on_resource_event() para Deployments
│   ├── slo_controller.py                # on_slo_config_change() para SLOConfig CRDs
│   ├── castai_monitor_controller.py     # Loop periódico de saúde CAST AI
│   └── synthetic_monitor_controller.py  # Engine config-driven: 1 task por check
├── application/
│   ├── ports/
│   │   ├── datadog_port.py
│   │   ├── slack_port.py
│   │   └── titlis_api_port.py
│   └── services/
│       ├── scorecard_service.py         # evaluate_resource() — 26+ regras
│       ├── slo_service.py               # reconcile_slo() — 3-path idempotency
│       ├── slo_metrics_service.py       # Emissão de métricas de SLO
│       ├── slack_service.py             # Rate-limited Slack dispatch
│       ├── scorecard_enricher.py        # Backstage + CAST AI enrichment
│       └── namespace_notification_buffer.py  # Digest de notificações por namespace
├── domain/
│   ├── models.py                        # SLOConfigSpec, ResourceScorecard, Enums
│   └── slack_models.py                  # NotificationSeverity, SlackNotification
├── infrastructure/
│   ├── datadog/
│   │   ├── repository.py                # DatadogPort impl
│   │   ├── client.py                    # Low-level Datadog API wrapper
│   │   ├── factory.py                   # Factory de managers
│   │   └── managers/                    # SLO, metrics, synthetic_metrics, gauge_metric
│   ├── slack/
│   │   ├── repository.py                # SlackPort impl
│   │   └── message_builder.py           # Formatação de mensagens
│   ├── kubernetes/
│   │   ├── appscorecard_writer.py       # Upsert AppScorecard CRD
│   │   ├── remediation_writer.py        # Cria AppRemediation CRD
│   │   ├── k8s_status_writer.py         # Atualiza .status subresource
│   │   ├── castai_health.py             # Health check CAST AI agent
│   │   └── state_store.py               # Set in-memory de remediações pendentes
│   ├── backstage/
│   │   └── enricher.py
│   ├── castai/
│   │   └── cost_enricher.py
│   ├── synthetic/
│   │   ├── check_config.py              # Modelos Pydantic: SiteHealthCheckConfig, JsonValueCheckConfig
│   │   ├── json_value_checker.py        # GET + dot-path JSON extraction → JsonValueCheckResult
│   │   └── site_health.py
│   └── titlis_api/
│       └── udp_client.py                # Envia eventos UDP/HTTP para titlis-api
└── utils/
    ├── json_logger.py
    └── logging_bootstrap.py
```

---

## 5. CRDs Gerenciados

### AppScorecard (titlis.io/v1) — short: `asc`
Estado de compliance de um Deployment.

**targetRef** (spec): referência ao Deployment avaliado.

**status** (calculado pelo operator):
```yaml
overallScore: 87
complianceStatus: compliant  # compliant | non_compliant | unknown | pending
criticalIssues: 0
errorIssues: 2
pillars:
  - name: resilience
    score: 90
    passedChecks: 8
    totalChecks: 9
findings:
  - ruleId: RES-003
    pillar: resilience
    severity: error
    passed: false
    message: "CPU request não definido"
    actual: null
    expected: "100m"
remediation:
  prNumber: 42
  prUrl: "https://github.com/org/repo/pull/42"
  status: PRCreated
```

### AppRemediation (titlis.io/v1) — short: `ar`
Estado de PR de auto-remediação.

**spec**: `targetRef`, `issuesFixed[]`, `baseBranch`

**status**:
```yaml
phase: PRCreated  # PRCreated | PRMerged | PRClosed | Failed
prNumber: 42
prUrl: "https://github.com/..."
prBranch: "fix/auto-remediation-default-my-app-20240101120000"
issueCount: 3
```

### SLOConfig (titlis.io/v1) — short: `sloc`
SLO declarativo sincronizado com Datadog.

**spec**:
```yaml
service: my-api
type: metric         # metric | monitor
target: 99.9
warning: 99.0
timeframe: 30d       # 7d | 30d | 90d
# Escolha UMA das opções:
app_framework: wsgi  # OU:
# numerator: "sum:trace.flask.request.hits..."
# denominator: "sum:trace.flask.request.hits..."
# auto_detect_framework: true
tags:
  - team:backend
```

**status**:
```yaml
slo_id: "abc123"          # ID no Datadog após criação
state: ok                 # ok | error
last_sync: "2024-01-01T00:00:00Z"
detected_framework: wsgi  # se auto_detect_framework
```

---

## 6. Fluxo do ScorecardController

```
Deployment criado/atualizado/resumido
         │
         ▼
on_resource_event(body, event_type)
         │
         ├── Namespace excluído? (kube-system, datadog, etc.) → skip
         │
         ├── ScorecardService.evaluate_resource()
         │       └── 26+ regras, 6 pilares, score ponderado
         │       └── OPS-001 extrai dd_service + dd_env dos pod labels
         │             (tags.datadoghq.com/service, tags.datadoghq.com/env)
         │
         ├── [REMOVIDO] Findings remediáveis → RemediationService (migrado para titlis-ai)
         │
         ├── _maybe_auto_create_slo(body, namespace, dd_service, dd_env)
         │       ├── SLOConfig CRD com label titlis.io/source-uid já existe? → skip
         │       ├── OPS-001 falhou? → skip (sem instrumentação Datadog)
         │       ├── ENABLE_AUTO_SLO_CREATION=false? → skip
         │       └── Cria SLOConfig CRD com labels titlis.io/auto-created, source-uid, dd-env
         │
         ├── [TODO: remediação via titlis-ai — não pertence mais ao operator]
         │
         ├── AppScorecardWriter.upsert()
         │       ├── Cria branch + commit + PR no GitHub
         │       └── Verifica PR existente (idempotência)
         │
         ├── RemediationWriter.record() → AppRemediation CRD
         ├── AppScorecardWriter.upsert() → AppScorecard CRD
         ├── NamespaceNotificationBuffer.add_and_maybe_flush()
         │       └── Flush a cada 15min ou 10+ apps no namespace
         └── TitlisApiUdpClient.send_scorecard_evaluated() → titlis-api:8125
```

**Namespaces excluídos por padrão:**
`kube-system`, `kube-public`, `kube-node-lease`, `datadog`, `titlis-operator`, `titlis-system`

---

## 7. Fluxo do SLOController — 3-Path Idempotency

```
SLOConfig criado/atualizado
         │
         ▼
on_slo_config_change(body, event_type)
         │
         ├── Valida spec (service obrigatório, warning > target, targets 0-100)
         │
         ├── Detecta framework (3 fontes, por precedência):
         │       1. spec.app_framework (explícito)
         │       2. metadata.annotations["titlis.io/app-framework"]
         │       3. Datadog ServiceDefinition.tags "framework:*"
         │       4. Fallback: "wsgi"
         │
         ├── _extract_env_from_spec(spec) → str
         │       # Lê tag "env:<valor>" do spec.tags ou label titlis.io/dd-env
         │       # Padrão: "production" (não mais "dev" hardcoded)
         │
         ├── SLOService.reconcile_slo() — 3 paths:
         │       Path A (restart fast): status.slo_id presente → usa diretamente
         │       Path B (orphan safety): busca por tag titlis_resource_uid:<uid>
         │       Path C (normal): lista SLOs do serviço → busca match → cria se não existe
         │       (todas as queries usam env dinâmico de _extract_env_from_spec)
         │
         ├── Valida serviço no Datadog antes de criar SLO:
         │       get_service_definition(service) → None → action="skipped_no_datadog_service"
         │
         ├── Atualiza status com slo_id, detected_framework, state
         ├── Notifica Slack (ALERTS se erro, OPERATIONAL se sucesso)
         ├── Emite métricas: record_reconciliation(success, action, slo_type)
         └── TitlisApiUdpClient.send_slo_reconciled()
```

---

## 8. Auto-criação de SLOs

Controlado por `ENABLE_AUTO_SLO_CREATION` (padrão `false` — opt-in).

### `_maybe_auto_create_slo(body, namespace, dd_service, dd_env)`

Chamado pelo `ScorecardController` após avaliação quando OPS-001 passou.

**Guards em ordem:**
1. `ENABLE_AUTO_SLO_CREATION` desabilitado → skip
2. SLOConfig CRD com `label titlis.io/source-uid = deployment.uid` já existe → skip (idempotente)
3. Serviço não existe no catálogo Datadog → skip com log warning
4. Tipo `monitor` ou `time_slice` → skip (auto-criação só para `type=metric`)

**CRD criado:**
```yaml
metadata:
  name: "auto-{dd_service}"
  labels:
    titlis.io/auto-created: "true"
    titlis.io/source-uid: "{deployment.uid}"
    titlis.io/source-name: "{deployment.name}"
    titlis.io/source-namespace: "{namespace}"
    titlis.io/dd-env: "{dd_env}"
spec:
  service: "{dd_service}"
  auto_detect_framework: true
  target: 99.0      # AUTO_SLO_DEFAULT_TARGET
  warning: 99.5     # AUTO_SLO_DEFAULT_WARNING (deve ser > target)
  timeframe: "30d"  # AUTO_SLO_DEFAULT_TIMEFRAME
  tags: ["env:{dd_env}", "managed_by:titlis_operator"]
```

### `_extract_env_from_spec(spec: SLOConfigSpec) -> str`

Extrai `env:` de `spec.tags`. Padrão: `"production"` se ausente. Corrige o bug anterior
de `env:dev` hardcoded nas queries do Datadog (wsgi, FastAPI, aiohttp, etc.).

### Polling de mudanças pendentes de SLO

Loop background (similar ao `castai_monitor_controller`) que:
1. Chama `GET /v1/operator/pending-slo-changes` no titlis-api a cada ~30s
2. Para cada mudança `status=pending`: patcha o SLOConfig CRD via kubernetes client
3. Kopf detecta o `on.update` → `reconcile_slo()` → Path A (fast path, slo_id preservado)
4. Confirma via `POST /v1/operator/pending-slo-changes/{id}/applied`
5. Em falha: `POST /v1/operator/pending-slo-changes/{id}/failed` com mensagem de erro

Auth: usa a API key existente do operator (`TITLIS_API_API_KEY`).

---

## 9. Padrões Críticos de Implementação

### Never-Reduce (recursos de Deployment)
```python
def _keep_max(current: str, suggested: str, parser: Callable) -> str:
    return suggested if parser(suggested) >= parser(current) else current
```
**Regra:** CPU requests, CPU limits, memory requests, memory limits nunca são reduzidos.
Aplique este padrão a qualquer lógica que modifique recursos de containers.
**Esta validação também é aplicada no titlis-ai antes de criar PRs.**

### HPA utilization — usar MIN
```python
cpu_util = min(current_cpu_util, default) if current_cpu_util else default
```
**Razão:** Menor target de utilização = escala mais agressivamente = maior resiliência.
É o oposto da lógica de recursos.

### Idempotência de PR
```python
# [NOTA: criação de PR agora é responsabilidade do titlis-ai]
# No operator: check_existing_pr verifica PR aberto antes de acionar titlis-ai
```

### YAML Round-Trip
```python
# Sempre usar ruamel.yaml (não PyYAML) para ler/modificar deploy.yaml
# Preserva comentários, formatação e ordem de chaves
from ruamel.yaml import YAML
yaml = YAML()
yaml.preserve_quotes = True
```

### Pesos dos pilares
```python
PILLAR_WEIGHTS = {
    "resilience": 0.40,
    "performance": 0.20,
    "security": 0.15,
    "cost": 0.10,
    "operational": 0.10,
    "compliance": 0.05,
}
# Score geral = média ponderada dos pilares
```

### Dependency Injection
```python
# bootstrap/dependencies.py — sempre @lru_cache() para singletons
@lru_cache()
def get_slo_service() -> Optional[SLOService]:
    if not settings.enable_slo_controller:
        return None
    return SLOService(get_datadog_repository())
```

---

## 10. Integrações Externas

### Datadog
| Operação | Finalidade |
|---|---|
| `get_service_definition(service)` | Framework, team, tier do catálogo Datadog |
| `get_service_slos(service)` | Lista SLOs existentes para o serviço |
| `create_slo(slo)` | Cria novo SLO no Datadog |
| `update_slo_apps(slo_id, slo)` | Atualiza queries/thresholds de SLO existente |
| `find_slo_by_tags(tags)` | Busca por tag `titlis_resource_uid:<uid>` (orphan detection) |
| `get_container_metrics(name, namespace)` | CPU/mem histórico para defaults de remediação |
| `get_request_count(service, days)` | RPM para detectar criticidade de workload |

Auth: `DD_API_KEY` + `DD_APP_KEY`

### GitHub (REMOVIDO — responsabilidade do titlis-ai)
> Toda integração com GitHub migrou para o `titlis-ai`. O operator nunca abre PRs.
> GitHub token e base branch são configurados por tenant em `titlis_oltp.tenant_ai_config`.

### Slack
- Rate limiting: 60/min e 360/hora por padrão
- Severity → channel: CRITICAL/ERROR → alerts, WARNING/INFO → operational
- Digests de namespace: flush a cada 15min ou 10+ apps
- Auth: `SLACK_WEBHOOK_URL` (webhook) ou `SLACK_BOT_TOKEN` (bot API)

### Titlis API (HTTP — nome da classe é legado "UDP")
```python
# Eventos enviados via HTTP POST para /v1/operator/events (fire-and-forget)
await titlis_client.send_scorecard_evaluated(payload)
await titlis_client.send_slo_reconciled(payload)
await titlis_client.send_notification_log(payload)
await titlis_client.send_resource_metrics(payload)
```
Auth: header `X-Api-Key: <operator_api_key>`.
Habilitado por `TITLIS_API_ENABLED=true`. Host padrão: `http://titlis-api.titlis-system.svc.cluster.local:8080`.

O operator também faz polling de mudanças de SLO via:
```python
await titlis_client.get_pending_slo_changes()           # GET /v1/operator/pending-slo-changes
await titlis_client.confirm_slo_change_applied(id)      # POST .../applied
await titlis_client.confirm_slo_change_failed(id, err)  # POST .../failed
```

---

## 10. Variáveis de Ambiente

### Operador e Feature Flags
```bash
KUBERNETES_NAMESPACE=titlis-system
KUBERNETES_CLUSTER_NAME=unknown
RECONCILE_INTERVAL_SECONDS=300
DEBOUNCE_SECONDS=30
ENABLE_LEADER_ELECTION=true
LOG_LEVEL=DEBUG
LOG_FORMAT=json

ENABLE_SCORECARD_CONTROLLER=true
ENABLE_SLO_CONTROLLER=true
ENABLE_AUTO_REMEDIATION=true  # DEPRECATED — remediação migrou para titlis-ai
ENABLE_AUTO_SLO_CREATION=false  # opt-in: cria SLOConfig CRD automaticamente
AUTO_SLO_DEFAULT_TARGET=99.9
AUTO_SLO_DEFAULT_WARNING=99.0
AUTO_SLO_DEFAULT_TIMEFRAME=30d
AUTO_SLO_REQUIRE_DATADOG_SERVICE=true  # skip se serviço não existe no catálogo Datadog
ENABLE_CASTAI_MONITOR=false
ENABLE_SYNTHETIC_MONITOR=false
SYNTHETIC_CHECKS_CONFIG_PATH=/etc/titlis/synthetic-checks.yaml  # se omitida usa vars legadas abaixo
SYNTHETIC_MONITOR_NAME=jeitto-homepage    # legado: nome do único check
SYNTHETIC_MONITOR_URL=https://jeitto.com.br  # legado: URL do único check
SYNTHETIC_MONITOR_INTERVAL_SECONDS=60    # legado
SYNTHETIC_MONITOR_TIMEOUT_SECONDS=10.0   # legado
ENABLE_BACKSTAGE_ENRICHMENT=false
ENABLE_CASTAI_COST_ENRICHMENT=false
```

### Datadog
```bash
DD_API_KEY=...
DD_APP_KEY=...
DD_SITE=datadoghq.com       # EU: datadoghq.eu
DD_ENV=production
DD_SERVICE=titlis-operator
# Obrigatório NO DEPLOYMENT avaliado para auto-remediação:
DD_GIT_REPOSITORY_URL=https://github.com/org/repo
```

### GitHub
> Variáveis `GITHUB_*` e `REMEDIATION_*` foram removidas do operator.
> GitHub token e base branch são configurados por tenant em `titlis_oltp.tenant_ai_config`.

### Slack
```bash
SLACK_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_BOT_TOKEN=xoxb-...
SLACK_DEFAULT_CHANNEL=#titlis-notifications
SLACK_RATE_LIMIT_PER_MINUTE=60
SLACK_RATE_LIMIT_PER_HOUR=360
SLACK_TIMEOUT_SECONDS=10.0
SLACK_MAX_RETRIES=3
SLACK_ENABLED_SEVERITIES=info,warning,error,critical
SLACK_ENABLED_CHANNELS=operational,alerts
SLACK_MAX_MESSAGE_LENGTH=3000
SLACK_INCLUDE_TIMESTAMP=true
SLACK_INCLUDE_CLUSTER_INFO=true
```

### Titlis API
```bash
TITLIS_API_ENABLED=false
TITLIS_API_HTTP_BASE_URL=http://titlis-api.titlis-system.svc.cluster.local:8080
TITLIS_API_API_KEY=tk_...             # API key gerada em /v1/settings/api-keys
TITLIS_API_DEFAULT_TENANT_ID=1
```

### Integrações opcionais
```bash
BACKSTAGE_URL=https://backstage.company.com
BACKSTAGE_TOKEN=...
BACKSTAGE_CACHE_TTL_SECONDS=300

CASTAI_API_KEY=...
CASTAI_CLUSTER_ID=...
CASTAI_CLUSTER_NAME=develop
CASTAI_MONITOR_NAMESPACE=castai-agent
CASTAI_MONITOR_INTERVAL_SECONDS=60
CASTAI_COST_CACHE_TTL_SECONDS=300
```

---

## 11. Comandos

```bash
make dev-install          # Instala deps com dev (poetry install)
make test                 # pytest tests/ -v (todos)
make test-unit            # pytest tests/unit/ -v
make test-integration     # pytest tests/integration/ -v
make test-coverage        # Com relatório de cobertura (meta: >=70%)
make lint                 # black check + flake8 + mypy + pylint
make format               # black src/ tests/ (auto-format)
make run                  # Roda localmente (precisa kubeconfig + env vars)
make dev                  # clean + dev-install + test + lint (gate completo)
make clean                # Remove .coverage, __pycache__, etc.

# Testes por padrão
make test-pattern PATTERN=remediation   # Filtra por nome
make test-datadog                       # Apenas testes Datadog
make test-slack                         # Apenas testes Slack
make test-services                      # Apenas application services
make test-controllers                   # Apenas controllers
```

**Docker:**
```bash
docker build -t kailima/titlis-operator:latest .
docker push kailima/titlis-operator:latest
```

**Helm:**
```bash
helm install titlis-operator ./charts/titlis-operator \
  --namespace titlis-system \
  --values values-custom.yaml

helm upgrade titlis-operator ./charts/titlis-operator \
  --namespace titlis-system \
  --values values-custom.yaml
```

---

## 12. Adicionando uma Nova Regra de Scorecard

1. **Defina a regra** em `config/scorecard-config.yaml`:
```yaml
rules:
  - id: RES-010
    pillar: resilience
    severity: error      # critical | error | warning | info
    weight: 1.0
    is_remediable: true
    remediation_category: resources
    description: "..."
```

2. **Implemente o validador** em `src/application/services/scorecard_service.py`:
```python
def _validate_res_010(self, deployment: dict) -> Finding:
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    # ... lógica de validação ...
    return Finding(
        rule_id="RES-010",
        pillar="resilience",
        severity="error",
        passed=passed,
        message="...",
        actual=actual_value,
        expected="...",
    )
```

3. **Adicione ao dispatch** do `evaluate_resource()`.

4. **Escreva testes** em `tests/unit/test_scorecard_service.py`.

---

## 13. Adicionando uma Nova Integração (Port + Adapter)

1. Crie a interface em `src/application/ports/nova_port.py`:
```python
from abc import ABC, abstractmethod

class NovaPort(ABC):
    @abstractmethod
    async def operacao(self, param: str) -> Result:
        ...
```

2. Crie o adapter em `src/infrastructure/nova/repository.py` implementando `NovaPort`.

3. Registre no DI em `src/bootstrap/dependencies.py`:
```python
@lru_cache()
def get_nova_repository() -> Optional[NovaPort]:
    if not settings.nova_enabled:
        return None
    return NovaRepository(client=NovaClient(...))
```

4. Injete no service via `__init__`.

---

## 14. RBAC (ClusterRole)

O operator precisa das seguintes permissões no cluster:

| Recursos | Verbos |
|---|---|
| deployments, deployments/status (apps) | get, list, watch, create, update, patch, delete |
| pods, services, configmaps, events (core) | get, list, watch, create, update, patch, delete |
| namespaces | get, list, watch |
| horizontalpodautoscalers (autoscaling) | get, list, watch, create, update, patch, delete |
| appscorecards, appremediations, sloconfigs (titlis.io) | get, list, watch, create, update, patch, delete |
| leases (coordination.k8s.io) | get, list, watch, create, update, patch, delete (leader election) |
| secrets | get, list, watch (read-only) |

Definido em `charts/titlis-operator/templates/rbac.yaml`.

---

## 15. Monitor Sintético — Engine Config-Driven

O monitor sintético é um engine de checks declarativos que cria **uma task asyncio por check**,
cada uma com seu próprio intervalo.

### Tipos de check

| type | O que faz | Métricas enviadas |
|---|---|---|
| `site_health` | GET → verifica status HTTP | `synthetic.site.health` (0/1) + `synthetic.site.response_time_ms` |
| `json_value` | GET → extrai valor por dot-path no JSON → gauge | métrica definida em `metric_name` |

### Configuração via YAML (recomendada)

```yaml
# config/synthetic-checks.yaml ou caminho via SYNTHETIC_CHECKS_CONFIG_PATH
checks:
  - name: minha-api
    type: site_health
    url: https://api.empresa.com/health
    interval_seconds: 60
    tags:
      env: prod
      service: minha-api

  - name: saldo-carteira
    type: json_value
    url: https://api.carteira.internal/v1/balance
    json_path: balance          # {"balance": 1200.00}
    metric_name: carteira.saldo
    interval_seconds: 120
    tags:
      env: prod
      service: carteira
```

### Fallback legado

Se `SYNTHETIC_CHECKS_CONFIG_PATH` não estiver definida, o controller constrói um único check
`site_health` a partir de `SYNTHETIC_MONITOR_URL` / `SYNTHETIC_MONITOR_NAME` / etc. (backward compat).

### Adicionando um novo tipo de check

1. Crie `XxxCheckConfig(BaseModel)` com `type: Literal["xxx"]` em `check_config.py`
2. Adicione ao discriminated union `CheckConfig` em `check_config.py`
3. Crie `XxxChecker` em `src/infrastructure/synthetic/`
4. Adicione `_run_xxx_check()` e o branch `isinstance(check, XxxCheckConfig)` no controller
5. Escreva testes em `tests/unit/test_json_value_checker.py` (ou novo arquivo)

### Dot-path JSON extraction (`json_value`)

`json_path: "data.account.balance"` resolve `{"data": {"account": {"balance": 42.5}}}` → `42.5`.
Qualquer path ausente, não-dict intermediário ou valor não numérico retorna `success=False` e
**não envia a métrica** (log `WARNING`).

### Segurança

- Nunca coloque tokens em `headers` no YAML — injete via `envFrom` + Secret K8s
- Sanitização: apenas o valor numérico extraído é enviado ao Datadog; o corpo completo da resposta
  nunca é logado para evitar vazar dados sensíveis

---

## 16. O Que Não Fazer

- **Nunca** adicione docstrings — código deve ser autoexplicativo
- **Nunca** reduza `resources.requests/limits` — use `_keep_max()` (a mesma lógica está no titlis-ai)
- **Nunca** omita o `tenant_id` no envelope UDP para o titlis-api
- **Nunca** deixe o operator bloquear em falhas externas (Slack/Datadog) — são fire-and-forget
- **Nunca** faça `yaml.load()` com PyYAML em manifests — use `ruamel.yaml` para preservar formatação
- **Nunca** instancie repositórios fora de `bootstrap/dependencies.py` — quebraria o DI
- **Nunca** processe namespaces do sistema (kube-system, datadog, etc.) — estão na exclusion list
- **Nunca** abra PRs no GitHub diretamente do operator — essa responsabilidade é do titlis-ai
- **Nunca** acesse o Kubernetes em loop síncrono no polling de pending-slo-changes — use `run_in_executor` ou thread separada (ver `feedback_operator_threading.md`)
- **Nunca** crie SLOConfig com `type=monitor` via auto-criação — apenas `type=metric` tem suporte
- **Nunca** hardcode `env:dev` em queries Datadog — use `_extract_env_from_spec()` para obter o env real
