# Apresentação: Engenharia e Arquitetura do Titlis Operator

## Slide 1: Capa

**Título:** Titlis Operator - Onboarding Técnico
**Subtítulo:** Arquitetura, Patterns e Guia de Extensão
**Público-Alvo:** Time de Engenharia / SRE
**Objetivo:** Capacitar o time a manter, depurar e estender o operador de Observabilidade.

---

## Seção 1: Fundamentos e Stack

### Slide 2: O que é o Titlis?

* **Definição:** Um Kubernetes Operator desenvolvido em Python.
* **Propósito:** Automatizar a configuração de observabilidade no Datadog ("Observability as Code").
* **Funcionalidades Core:**
1. **Gerenciamento de SLOs:** Transforma CRDs (`SLOConfig`) em SLOs reais no Datadog.
2. **Compliance & Discovery:** Monitora Deployments para garantir que as tags e variáveis de ambiente do Datadog (ex: `DD_ENV`, `DD_SERVICE`) estejam corretas.
3. **Service Catalog:** Sincroniza definições de serviço.



### Slide 3: Tech Stack & Requisitos

* **Linguagem:** Python 3.10+ (Uso extensivo de Type Hinting).
* **Framework de Operador:** **Kopf** (Kubernetes Operator Pythonic Framework).
* *Por que Kopf?* Simplicidade, decorators intuitivos e loop de reconciliação robusto.


* **Bibliotecas Chave:**
* `kubernetes`: Cliente oficial K8s.
* `datadog-api-client`: Cliente oficial Datadog.
* `pydantic`: Validação de configurações (`src/settings.py`) e modelos.


* **Infraestrutura:** Roda como um Deployment no cluster, utiliza *Leader Election* para HA.

---

## Seção 2: Arquitetura e Patterns

### Slide 4: Arquitetura de Alto Nível

* O projeto não segue o padrão "script solto". Ele adota uma **Arquitetura em Camadas** (inspirada em Hexagonal/Clean Arch) para facilitar testes unitários.
* **Fluxo de Dados:**
1. **Controller (Kopf):** Escuta o evento do K8s.
2. **Service (Application):** Aplica a regra de negócio (ex: "Calcular query do FastAPI").
3. **Port (Interface):** Define o contrato.
4. **Adapter/Repository (Infrastructure):** Fala com o mundo externo (API Datadog ou K8s API).



### Slide 5: Design Patterns Implementados

* **Singleton/Factory:** Usado em `src/bootstrap/dependencies.py` para injetar dependências (Repositories, Services) e garantir conexões únicas.
* **Adapter:** O `DatadogRepository` isola a complexidade da API do Datadog (que muda entre v1 e v2) do resto da aplicação.
* **Strategy (Implícito):** No `SLOService`, a construção da query muda dependendo da estratégia de framework (`FastAPI`, `WSGI`, `AIOHTTP`).
* **Leader Election:** Implementado manualmente (`src/utils/leader_election.py`) e via configuração do Kopf para garantir que apenas um pod altere o Datadog por vez.

---

## Seção 3: Mergulho no Código (Deep Dive)

### Slide 6: Estrutura de Pastas (O Mapa da Mina)

* `src/controllers/`: **Ponto de entrada.** Onde estão os decorators `@kopf.on`. Não deve ter lógica de negócio pesada.
* `src/application/services/`: **Cérebro.** Onde a mágica acontece (ex: `slo_service.py`, `compliance_service.py`).
* `src/domain/`: **Modelos.** Dataclasses e Pydantic models que representam o negócio (agnósticos de infra).
* `src/infrastructure/`: **IO.** Implementações concretas de Datadog e Kubernetes.
* `src/bootstrap/`: **Config.** Injeção de dependência e carregamento de env vars.

### Slide 7: O Ciclo de Vida do SLO (`SLOController`)

1. **Watch:** O controller detecta um `SLOConfig` (CRD).
2. **Validate:** Verifica se `spec.service` existe e se `warning > target`.
3. **Build:** O `SLOService` constrói o objeto SLO. Se o usuário definiu `app_framework: fastapi`, o serviço gera as queries de *numerator* e *denominator* automaticamente.
4. **Reconcile:**
* Busca SLOs existentes no Datadog via tag `slo_uid`.
* Se existir e for diferente -> **Update**.
* Se não existir -> **Create**.


5. **Status:** Atualiza o `.status` do CRD no Kubernetes com o `slo_id` gerado ou erro.

### Slide 8: O Ciclo de Compliance (`DeploymentsController`)

1. **Watch:** Escuta todo `Deployment` criado/alterado.
2. **Check:** O `ComplianceService` verifica:
* Anotação `admission.datadoghq.com/enabled`.
* `EnvValidationService` valida variáveis (regras definidas em `config.yaml` ou ENV vars).


3. **Report:** Loga violações (INFO/WARN/ERROR).
* *Extensão futura:* Emitir K8s Events ou bloquear via Webhook.



---

## Seção 4: Guia de Manutenção e Extensão

### Slide 9: Cenário A - Adicionar suporte a um novo Framework (ex: Django)

* **Onde tocar:** `src/application/services/slo_service.py`.
* **Passo 1:** Adicionar `DJANGO` ao Enum `SLOAppFramework` em `src/domain/models.py`.
* **Passo 2:** No método `_build_slo_from_spec`, adicionar a lógica de geração de query:
```python
elif spec.app_framework == SLOAppFramework.DJANGO:
    query = { "numerator": "trace.django.request...", ... }

```


* **Passo 3:** Atualizar testes em `tests/application/services/test_slo_service_framework.py`.

### Slide 10: Cenário B - Validar nova variável de ambiente

* **Onde tocar:** Não precisa mudar código!
* **Como fazer:** O `EnvValidationService` carrega regras dinamicamente.
* Edite o ConfigMap montado em `/etc/env-validation/config.yaml`.
* Ou ajuste a variável de ambiente `ENV_VALIDATION_RULES`.



### Slide 11: Debug e Testes Locais

* **Rodando Testes:** O projeto usa `pytest`.
* Unitários: Testam services com Mocks.
* Integração: `tests/integration` simula cenários completos.


* **Ambiente Local:** Utilize o script `tests/setup_test_environment.py` para "mockar" as variáveis do K8s e rodar o operador localmente sem precisar de um cluster real o tempo todo.
* **Logs:** Logs estruturados em JSON (`src/utils/json_logger.py`). Procure por `extra={"slo_id": ...}` no Datadog Logs ou stdout.

### Slide 12: Boas Práticas e "Gotchas"

* **Idempotência:** O operador pode receber o mesmo evento 10 vezes. A lógica `check_and_update_existing_slo` garante que só chamamos a API do Datadog se houver *diff* real.
* **API Rate Limits:** O `DatadogClientBase` (`src/infraestructure/datadog/client.py`) já possui retries exponenciais (`execute_with_retry`). Não remova isso.
* **Kopf Errors:**
* Erro Temporário (Network) -> Levante `kopf.TemporaryError` (o operador tenta de novo).
* Erro Permanente (Config inválida) -> Levante `kopf.PermanentError` (o operador para de tentar e marca erro no status).