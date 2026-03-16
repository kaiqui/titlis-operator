-- ================================================================
-- TITLIS OPERATOR — DATABASE SCHEMA
-- PostgreSQL 15+ | Estratégia: SCD Type 4 + Append-only Time-series
-- ================================================================
-- Status: criado / não integrado ao operador
-- Gerado a partir de: docs/modelagem-dados.md
--
-- Compatível com o estado atual do operador (branch feat/slo-inteligent).
-- tenant_id nullable em todas as tabelas — permite operação single-tenant
-- hoje e habilita RLS multi-tenant na Fase 1 sem migração de schema.
-- ================================================================

-- ================================================================
-- SCHEMAS
-- ================================================================
CREATE SCHEMA IF NOT EXISTS titlis_oltp;   -- Estado atual (Frontend/APIs)
CREATE SCHEMA IF NOT EXISTS titlis_audit;  -- Histórico e auditoria (SCD Type 4)
CREATE SCHEMA IF NOT EXISTS titlis_ts;     -- Métricas time-series (append-only)

-- ================================================================
-- ENUMS (domain types espelhados do Python)
-- ================================================================
CREATE TYPE titlis_oltp.compliance_status AS ENUM (
    'COMPLIANT', 'NON_COMPLIANT', 'UNKNOWN', 'PENDING'
);

CREATE TYPE titlis_oltp.service_tier AS ENUM (
    'TIER_1', 'TIER_2', 'TIER_3', 'TIER_4'
);

CREATE TYPE titlis_oltp.validation_pillar AS ENUM (
    'RESILIENCE', 'SECURITY', 'COST', 'PERFORMANCE', 'OPERATIONAL', 'COMPLIANCE'
);

CREATE TYPE titlis_oltp.validation_severity AS ENUM (
    'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'OPTIONAL'
);

CREATE TYPE titlis_oltp.validation_rule_type AS ENUM (
    'BOOLEAN', 'NUMERIC', 'ENUM', 'REGEX'
);

CREATE TYPE titlis_oltp.remediation_status AS ENUM (
    'PENDING', 'IN_PROGRESS', 'PR_OPEN', 'PR_MERGED', 'FAILED', 'SKIPPED'
);

CREATE TYPE titlis_oltp.slo_type AS ENUM (
    'METRIC', 'MONITOR', 'TIME_SLICE'
);

CREATE TYPE titlis_oltp.slo_timeframe AS ENUM (
    '7d', '30d', '90d'
);

CREATE TYPE titlis_oltp.slo_state AS ENUM (
    'ok', 'warning', 'error', 'no_data'
);

CREATE TYPE titlis_oltp.notification_severity AS ENUM (
    'INFO', 'WARNING', 'ERROR', 'CRITICAL'
);

CREATE TYPE titlis_oltp.remediation_category AS ENUM (
    'resources', 'hpa'
);

-- SLOAppFramework: espelha domain/models.py SLOAppFramework enum
-- Usado por SLOService.auto_detect_framework e SLOController
CREATE TYPE titlis_oltp.slo_app_framework AS ENUM (
    'WSGI', 'FASTAPI', 'AIOHTTP'
);

-- ================================================================
-- SCHEMA: titlis_oltp — Estado Atual (OLTP)
-- ================================================================

-- ----------------------------------------------------------------
-- tenants (Fase 1 — multi-tenant foundation)
-- Nullable nos relacionamentos enquanto operador é single-tenant.
-- Na Fase 1, adicionar NOT NULL + RLS policies via migration.
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.tenants (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL UNIQUE,
    slug        VARCHAR(100) NOT NULL UNIQUE,     -- identificador URL-safe
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    plan        VARCHAR(50) NOT NULL DEFAULT 'free',  -- free | pro | enterprise
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------
-- clusters
-- tenant_id nullable: suporta single-tenant hoje, multi-tenant na Fase 1.
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.clusters (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        REFERENCES titlis_oltp.tenants(id),
    name            VARCHAR(255) NOT NULL UNIQUE,
    environment     VARCHAR(100) NOT NULL,           -- production, staging, develop
    region          VARCHAR(100),
    provider        VARCHAR(100),                    -- aws, gcp, azure, on-prem
    k8s_version     VARCHAR(50),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clusters_tenant ON titlis_oltp.clusters (tenant_id) WHERE tenant_id IS NOT NULL;

-- ----------------------------------------------------------------
-- namespaces
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.namespaces (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id      UUID        NOT NULL REFERENCES titlis_oltp.clusters(id),
    name            VARCHAR(255) NOT NULL,
    is_excluded     BOOLEAN     NOT NULL DEFAULT FALSE,  -- excluded_namespaces config
    labels          JSONB,
    annotations     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, name)
);

-- ----------------------------------------------------------------
-- workloads  (espelha Kubernetes Deployments)
-- k8s_uid: UID do recurso K8s — usado para tag titlis_resource_uid
-- nos SLOs do Datadog (Path B de idempotência do SLOService).
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.workloads (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace_id            UUID        NOT NULL REFERENCES titlis_oltp.namespaces(id),
    name                    VARCHAR(255) NOT NULL,
    kind                    VARCHAR(100) NOT NULL DEFAULT 'Deployment',
    k8s_uid                 VARCHAR(255),            -- K8s metadata.uid (para titlis_resource_uid tag)
    service_tier            titlis_oltp.service_tier,
    dd_git_repository_url   TEXT,                    -- DD_GIT_REPOSITORY_URL (pré-condição de remediação)
    backstage_component     VARCHAR(255),
    owner_team              VARCHAR(255),
    labels                  JSONB,
    annotations             JSONB,
    resource_version        VARCHAR(100),            -- K8s resourceVersion
    is_active               BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (namespace_id, name, kind)
);

CREATE INDEX idx_workloads_k8s_uid ON titlis_oltp.workloads (k8s_uid) WHERE k8s_uid IS NOT NULL;

-- ----------------------------------------------------------------
-- validation_rules  (catálogo das 26+ regras — referência imutável)
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.validation_rules (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id              VARCHAR(50) NOT NULL UNIQUE,  -- RES-001, PERF-002...
    pillar               titlis_oltp.validation_pillar   NOT NULL,
    severity             titlis_oltp.validation_severity NOT NULL,
    rule_type            titlis_oltp.validation_rule_type NOT NULL,
    weight               NUMERIC(5,2) NOT NULL DEFAULT 1.0,
    name                 VARCHAR(255) NOT NULL,
    description          TEXT,
    is_remediable        BOOLEAN     NOT NULL DEFAULT FALSE,
    remediation_category titlis_oltp.remediation_category,  -- resources | hpa
    is_active            BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------
-- app_scorecards  (estado atual — SCD Type 4 "current table")
-- UNIQUE(workload_id) garante 1 linha por workload.
-- Antes de UPDATE, trigger copia o estado anterior para app_scorecard_history.
-- tenant_id desnormalizado para performance de RLS sem join até clusters.
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.app_scorecards (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id       UUID        NOT NULL REFERENCES titlis_oltp.workloads(id),
    tenant_id         UUID        REFERENCES titlis_oltp.tenants(id),
    version           INTEGER     NOT NULL DEFAULT 1,   -- incrementa a cada nova avaliação
    overall_score     NUMERIC(5,2) NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
    compliance_status titlis_oltp.compliance_status NOT NULL DEFAULT 'UNKNOWN',
    total_rules       INTEGER     NOT NULL DEFAULT 0,
    passed_rules      INTEGER     NOT NULL DEFAULT 0,
    failed_rules      INTEGER     NOT NULL DEFAULT 0,
    critical_failures INTEGER     NOT NULL DEFAULT 0,
    error_count       INTEGER     NOT NULL DEFAULT 0,
    warning_count     INTEGER     NOT NULL DEFAULT 0,
    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    k8s_event_type    VARCHAR(50),                      -- resume | create | update
    raw_metadata      JSONB,                            -- campos extras do K8s body
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workload_id)                                -- 1 scorecard atual por workload
);

-- ----------------------------------------------------------------
-- pillar_scores  (scores por pilar — estado atual)
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.pillar_scores (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scorecard_id   UUID        NOT NULL REFERENCES titlis_oltp.app_scorecards(id) ON DELETE CASCADE,
    pillar         titlis_oltp.validation_pillar NOT NULL,
    score          NUMERIC(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
    passed_checks  INTEGER     NOT NULL DEFAULT 0,
    failed_checks  INTEGER     NOT NULL DEFAULT 0,
    weighted_score NUMERIC(8,4),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scorecard_id, pillar)
);

-- ----------------------------------------------------------------
-- validation_results  (resultado por regra — estado atual)
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.validation_results (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scorecard_id UUID        NOT NULL REFERENCES titlis_oltp.app_scorecards(id) ON DELETE CASCADE,
    rule_id      UUID        NOT NULL REFERENCES titlis_oltp.validation_rules(id),
    passed       BOOLEAN     NOT NULL,
    message      TEXT,
    actual_value TEXT,                                  -- valor observado no Deployment
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scorecard_id, rule_id)
);

-- ----------------------------------------------------------------
-- app_remediations  (estado atual — SCD Type 4 "current table")
-- tenant_id desnormalizado para performance de RLS.
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.app_remediations (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id      UUID        NOT NULL REFERENCES titlis_oltp.workloads(id),
    tenant_id        UUID        REFERENCES titlis_oltp.tenants(id),
    version          INTEGER     NOT NULL DEFAULT 1,
    scorecard_id     UUID        REFERENCES titlis_oltp.app_scorecards(id),
    status           titlis_oltp.remediation_status NOT NULL DEFAULT 'PENDING',
    github_pr_number INTEGER,
    github_pr_url    TEXT,
    github_pr_title  TEXT,
    github_branch    TEXT,
    repository_url   TEXT,
    error_message    TEXT,
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workload_id)                                -- 1 remediação ativa por workload
);

-- ----------------------------------------------------------------
-- remediation_issues  (issues individuais vinculadas à remediação)
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.remediation_issues (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    remediation_id  UUID        NOT NULL REFERENCES titlis_oltp.app_remediations(id) ON DELETE CASCADE,
    rule_id         UUID        NOT NULL REFERENCES titlis_oltp.validation_rules(id),
    category        titlis_oltp.remediation_category NOT NULL,
    description     TEXT,
    suggested_value TEXT,       -- valor calculado pelo operador antes de _keep_max
    applied_value   TEXT,       -- valor efetivamente aplicado no PR (pode diferir por _keep_max)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------
-- slo_configs  (estado atual dos SLOs — espelha SLOConfig CRD)
--
-- Colunas de auto-detecção de framework (implementadas no operador):
--   auto_detect_framework: flag do spec — ativa detecção automática
--   app_framework: framework explícito do spec (quando não usa auto-detect)
--   detected_framework: resultado da detecção — persiste em status.detected_framework
--   detection_source: annotation | datadog_tag | fallback (H-13)
--   k8s_resource_uid: metadata.uid do SLOConfig CRD — usado para tag
--     titlis_resource_uid:<uid> no Datadog (Path B idempotência do SLOService)
-- ----------------------------------------------------------------
CREATE TABLE titlis_oltp.slo_configs (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace_id          UUID        NOT NULL REFERENCES titlis_oltp.namespaces(id),
    tenant_id             UUID        REFERENCES titlis_oltp.tenants(id),
    name                  VARCHAR(255) NOT NULL,
    slo_type              titlis_oltp.slo_type      NOT NULL,
    timeframe             titlis_oltp.slo_timeframe NOT NULL,
    target                NUMERIC(6,4) NOT NULL CHECK (target BETWEEN 0 AND 100),
    warning               NUMERIC(6,4)              CHECK (warning BETWEEN 0 AND 100),
    -- Framework detection (SLOConfigSpec + SLOConfigStatus)
    auto_detect_framework BOOLEAN     NOT NULL DEFAULT FALSE,
    app_framework         titlis_oltp.slo_app_framework,  -- spec explícito (WSGI/FASTAPI/AIOHTTP)
    detected_framework    VARCHAR(50),              -- status.detected_framework (auto-detected)
    detection_source      VARCHAR(50),              -- annotation | datadog_tag | fallback
    -- Idempotency tracking (Three-Path SLO idempotency — CLAUDE.md §P-15)
    k8s_resource_uid      VARCHAR(255),             -- metadata.uid do SLOConfig CRD
    -- Datadog sync state
    datadog_slo_id        VARCHAR(255),             -- ID gerado no Datadog após criação
    datadog_slo_state     titlis_oltp.slo_state,
    last_sync_at          TIMESTAMPTZ,
    sync_error            TEXT,
    spec_raw              JSONB,                    -- spec completo do CRD para auditoria
    version               INTEGER     NOT NULL DEFAULT 1,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (namespace_id, name),
    CONSTRAINT chk_warning_lt_target CHECK (warning IS NULL OR warning < target)
);

CREATE INDEX idx_slo_datadog_id         ON titlis_oltp.slo_configs (datadog_slo_id);
CREATE INDEX idx_slo_k8s_uid            ON titlis_oltp.slo_configs (k8s_resource_uid) WHERE k8s_resource_uid IS NOT NULL;
CREATE INDEX idx_slo_detection_source   ON titlis_oltp.slo_configs (detection_source);

-- ================================================================
-- SCHEMA: titlis_audit — Histórico e Auditoria (SCD Type 4)
-- ================================================================

-- ----------------------------------------------------------------
-- app_scorecard_history
-- Sem FK para workload_id — registros históricos devem sobreviver
-- mesmo se o workload for deletado (soft-delete em workloads).
-- Snapshot JSONB de pillar_scores e validation_results elimina
-- joins custosos em queries analíticas.
-- ----------------------------------------------------------------
CREATE TABLE titlis_audit.app_scorecard_history (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id        UUID        NOT NULL,        -- ref lógica sem FK constraint
    tenant_id          UUID,                        -- ref lógica sem FK constraint
    scorecard_version  INTEGER     NOT NULL,
    overall_score      NUMERIC(5,2) NOT NULL,
    compliance_status  VARCHAR(50) NOT NULL,
    total_rules        INTEGER     NOT NULL,
    passed_rules       INTEGER     NOT NULL,
    failed_rules       INTEGER     NOT NULL,
    critical_failures  INTEGER     NOT NULL,
    error_count        INTEGER     NOT NULL,
    warning_count      INTEGER     NOT NULL,
    pillar_scores      JSONB       NOT NULL,        -- [{pillar, score, passed, failed}]
    validation_results JSONB       NOT NULL,        -- [{rule_id, rule_ref, pillar, severity, passed, message, actual_value}]
    evaluated_at       TIMESTAMPTZ NOT NULL,
    k8s_event_type     VARCHAR(50),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_scorecard_hist_workload_time
    ON titlis_audit.app_scorecard_history (workload_id, evaluated_at DESC);

CREATE INDEX idx_scorecard_hist_compliance
    ON titlis_audit.app_scorecard_history (compliance_status, evaluated_at DESC);

CREATE INDEX idx_scorecard_hist_pillar_gin
    ON titlis_audit.app_scorecard_history USING GIN (pillar_scores);

CREATE INDEX idx_scorecard_hist_validation_gin
    ON titlis_audit.app_scorecard_history USING GIN (validation_results);

-- ----------------------------------------------------------------
-- pillar_score_history  (granularidade fina por pilar — para gráficos de evolução)
-- ----------------------------------------------------------------
CREATE TABLE titlis_audit.pillar_score_history (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id    UUID        NOT NULL,
    tenant_id      UUID,
    scorecard_version INTEGER  NOT NULL,
    pillar         VARCHAR(50) NOT NULL,
    score          NUMERIC(5,2) NOT NULL,
    passed_checks  INTEGER     NOT NULL,
    failed_checks  INTEGER     NOT NULL,
    weighted_score NUMERIC(8,4),
    evaluated_at   TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pillar_hist_workload_pillar_time
    ON titlis_audit.pillar_score_history (workload_id, pillar, evaluated_at DESC);

-- ----------------------------------------------------------------
-- remediation_history  (log de todas as transições de estado)
-- ----------------------------------------------------------------
CREATE TABLE titlis_audit.remediation_history (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id         UUID        NOT NULL,
    tenant_id           UUID,
    remediation_version INTEGER     NOT NULL,
    status              VARCHAR(50) NOT NULL,
    previous_status     VARCHAR(50),                 -- para rastrear transição de estado
    scorecard_version   INTEGER,
    github_pr_number    INTEGER,
    github_pr_url       TEXT,
    github_branch       TEXT,
    repository_url      TEXT,
    issues_snapshot     JSONB,                       -- snapshot das issues no momento
    error_message       TEXT,
    triggered_at        TIMESTAMPTZ NOT NULL,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_remediation_hist_workload_time
    ON titlis_audit.remediation_history (workload_id, triggered_at DESC);

CREATE INDEX idx_remediation_hist_status
    ON titlis_audit.remediation_history (status, created_at DESC);

-- ----------------------------------------------------------------
-- slo_compliance_history  (histórico de conformidade e sincronização)
-- detected_framework / detection_source: auditoria de H-13
-- (framework detectado incorretamente → fallback WSGI inesperado).
-- ----------------------------------------------------------------
CREATE TABLE titlis_audit.slo_compliance_history (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slo_config_id      UUID        NOT NULL,            -- ref lógica
    namespace_id       UUID        NOT NULL,
    tenant_id          UUID,
    slo_name           VARCHAR(255) NOT NULL,
    datadog_slo_id     VARCHAR(255),
    slo_type           VARCHAR(50) NOT NULL,
    timeframe          VARCHAR(10) NOT NULL,
    target             NUMERIC(6,4) NOT NULL,
    actual_value       NUMERIC(6,4),                    -- compliance % real do Datadog
    slo_state          VARCHAR(50),
    sync_action        VARCHAR(50),                     -- created | updated | noop | error
    sync_error         TEXT,
    detected_framework VARCHAR(50),                     -- framework detectado nesta sincronização
    detection_source   VARCHAR(50),                     -- annotation | datadog_tag | fallback
    recorded_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_slo_hist_config_time
    ON titlis_audit.slo_compliance_history (slo_config_id, recorded_at DESC);

CREATE INDEX idx_slo_hist_detection
    ON titlis_audit.slo_compliance_history (detected_framework, detection_source)
    WHERE detected_framework IS NOT NULL;

-- ----------------------------------------------------------------
-- notification_log  (auditoria de todas as notificações Slack)
-- ----------------------------------------------------------------
CREATE TABLE titlis_audit.notification_log (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id       UUID,                          -- NULL se digest de namespace
    namespace_id      UUID,
    tenant_id         UUID,
    notification_type VARCHAR(50) NOT NULL,          -- scorecard | remediation | digest | slo
    severity          titlis_oltp.notification_severity NOT NULL,
    channel           VARCHAR(255),
    title             TEXT,
    message_preview   VARCHAR(500),                  -- primeiros 500 chars para auditoria
    sent_at           TIMESTAMPTZ,
    success           BOOLEAN     NOT NULL DEFAULT FALSE,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notif_log_workload_time
    ON titlis_audit.notification_log (workload_id, created_at DESC);

CREATE INDEX idx_notif_log_namespace_time
    ON titlis_audit.notification_log (namespace_id, created_at DESC);

-- ================================================================
-- SCHEMA: titlis_ts — Time-series de Métricas
-- ================================================================

-- ----------------------------------------------------------------
-- resource_metrics  (CPU/memória coletados do Datadog)
-- Candidato a hypertable do TimescaleDB em produção.
-- ----------------------------------------------------------------
CREATE TABLE titlis_ts.resource_metrics (
    id                     BIGSERIAL   PRIMARY KEY,
    workload_id            UUID        NOT NULL,
    tenant_id              UUID,
    container_name         VARCHAR(255),
    metric_source          VARCHAR(50) NOT NULL DEFAULT 'datadog',
    cpu_avg_millicores     NUMERIC(10,3),
    cpu_p95_millicores     NUMERIC(10,3),
    mem_avg_mib            NUMERIC(10,3),
    mem_p95_mib            NUMERIC(10,3),
    -- Valores sugeridos conforme lógica _keep_max / suggest_*()
    suggested_cpu_request  VARCHAR(50),
    suggested_cpu_limit    VARCHAR(50),
    suggested_mem_request  VARCHAR(50),
    suggested_mem_limit    VARCHAR(50),
    sample_window          VARCHAR(20), -- '1h' | '24h' | '7d'
    collected_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_resource_metrics_workload_time
    ON titlis_ts.resource_metrics (workload_id, collected_at DESC);

-- ----------------------------------------------------------------
-- scorecard_scores  (série temporal plana para dashboards Grafana/Metabase)
-- Desnormalizado intencionalmente: elimina joins em tempo de query.
-- ----------------------------------------------------------------
CREATE TABLE titlis_ts.scorecard_scores (
    id                  BIGSERIAL   PRIMARY KEY,
    workload_id         UUID        NOT NULL,
    tenant_id           UUID,
    overall_score       NUMERIC(5,2) NOT NULL,
    resilience_score    NUMERIC(5,2),
    security_score      NUMERIC(5,2),
    cost_score          NUMERIC(5,2),
    performance_score   NUMERIC(5,2),
    operational_score   NUMERIC(5,2),
    compliance_score    NUMERIC(5,2),
    compliance_status   VARCHAR(50) NOT NULL,
    passed_rules        INTEGER,
    failed_rules        INTEGER,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_score_ts_workload_time
    ON titlis_ts.scorecard_scores (workload_id, recorded_at DESC);

-- índice por tempo sem predicado now() — predicado com now() vira constante
-- em índices parciais e fica obsoleto. Usar filtro na query.
CREATE INDEX idx_score_ts_recorded_at
    ON titlis_ts.scorecard_scores (recorded_at DESC);

-- ================================================================
-- VIEWS — abstração para Frontend e APIs
-- ================================================================

-- Dashboard principal: estado atual de todos os workloads
CREATE OR REPLACE VIEW titlis_oltp.v_workload_dashboard AS
SELECT
    w.id                    AS workload_id,
    c.name                  AS cluster_name,
    c.environment,
    c.tenant_id,
    n.name                  AS namespace,
    w.name                  AS workload_name,
    w.kind,
    w.service_tier,
    w.owner_team,
    sc.overall_score,
    sc.compliance_status,
    sc.passed_rules,
    sc.failed_rules,
    sc.critical_failures,
    sc.version              AS scorecard_version,
    sc.evaluated_at,
    ar.status               AS remediation_status,
    ar.github_pr_url,
    ar.github_pr_number,
    sc.updated_at           AS last_scored_at
FROM titlis_oltp.workloads w
JOIN titlis_oltp.namespaces n      ON n.id = w.namespace_id
JOIN titlis_oltp.clusters c        ON c.id = n.cluster_id
LEFT JOIN titlis_oltp.app_scorecards sc ON sc.workload_id = w.id
LEFT JOIN titlis_oltp.app_remediations ar ON ar.workload_id = w.id
WHERE w.is_active = TRUE
  AND n.is_excluded = FALSE;

-- Evolução de score com delta entre avaliações consecutivas
CREATE OR REPLACE VIEW titlis_audit.v_score_evolution AS
SELECT
    workload_id,
    scorecard_version,
    overall_score,
    compliance_status,
    passed_rules,
    failed_rules,
    evaluated_at,
    overall_score - LAG(overall_score) OVER (
        PARTITION BY workload_id ORDER BY evaluated_at
    ) AS score_delta
FROM titlis_audit.app_scorecard_history
ORDER BY workload_id, evaluated_at DESC;

-- Top regras que mais falham (análise de impacto)
CREATE OR REPLACE VIEW titlis_audit.v_top_failing_rules AS
SELECT
    (vr->>'rule_ref')   AS rule_id,
    (vr->>'pillar')     AS pillar,
    (vr->>'severity')   AS severity,
    COUNT(*)            AS total_failures,
    COUNT(DISTINCT h.workload_id) AS affected_workloads,
    MAX(h.evaluated_at) AS last_seen
FROM titlis_audit.app_scorecard_history h,
     jsonb_array_elements(h.validation_results) AS vr
WHERE (vr->>'passed')::BOOLEAN = FALSE
GROUP BY 1, 2, 3
ORDER BY total_failures DESC;

-- Eficácia das remediações: taxa de sucesso por workload
CREATE OR REPLACE VIEW titlis_audit.v_remediation_effectiveness AS
SELECT
    workload_id,
    COUNT(*)                                                       AS total_attempts,
    COUNT(*) FILTER (WHERE status = 'PR_MERGED')                   AS successful,
    COUNT(*) FILTER (WHERE status = 'FAILED')                      AS failed,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'PR_MERGED')
        / NULLIF(COUNT(*), 0), 2
    )                                                              AS success_rate_pct,
    MAX(triggered_at)                                              AS last_attempt_at
FROM titlis_audit.remediation_history
GROUP BY workload_id;

-- Diagnóstico de detecção de framework (checklist semanal H-13)
-- Lista SLOs com detection_source=fallback — possível framework errado.
CREATE OR REPLACE VIEW titlis_oltp.v_slo_framework_detection AS
SELECT
    n.name                  AS namespace,
    sc.name                 AS slo_name,
    sc.slo_type,
    sc.auto_detect_framework,
    sc.app_framework        AS explicit_framework,
    sc.detected_framework,
    sc.detection_source,
    sc.datadog_slo_id,
    sc.datadog_slo_state,
    sc.last_sync_at,
    sc.sync_error
FROM titlis_oltp.slo_configs sc
JOIN titlis_oltp.namespaces n ON n.id = sc.namespace_id
ORDER BY
    (sc.detection_source = 'fallback') DESC,  -- fallbacks primeiro
    sc.last_sync_at DESC NULLS LAST;

-- ================================================================
-- TRIGGERS — updated_at automático + audit trail
-- ================================================================

CREATE OR REPLACE FUNCTION titlis_oltp.fn_update_timestamp()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'tenants', 'clusters', 'namespaces', 'workloads', 'validation_rules',
        'app_scorecards', 'pillar_scores', 'app_remediations', 'slo_configs'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_update_ts
             BEFORE UPDATE ON titlis_oltp.%I
             FOR EACH ROW EXECUTE FUNCTION titlis_oltp.fn_update_timestamp()',
            tbl
        );
    END LOOP;
END;
$$;

-- Trigger: antes de sobrescrever scorecard atual, arquiva o estado anterior
CREATE OR REPLACE FUNCTION titlis_oltp.fn_scorecard_to_history()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Só arquiva se a versão mudou (nova avaliação)
    IF OLD.version IS DISTINCT FROM NEW.version THEN
        INSERT INTO titlis_audit.app_scorecard_history (
            workload_id, tenant_id, scorecard_version, overall_score, compliance_status,
            total_rules, passed_rules, failed_rules, critical_failures,
            error_count, warning_count, pillar_scores, validation_results,
            evaluated_at, k8s_event_type
        )
        SELECT
            OLD.workload_id,
            OLD.tenant_id,
            OLD.version,
            OLD.overall_score,
            OLD.compliance_status::TEXT,
            OLD.total_rules, OLD.passed_rules, OLD.failed_rules,
            OLD.critical_failures, OLD.error_count, OLD.warning_count,
            COALESCE(
                (SELECT jsonb_agg(jsonb_build_object(
                    'pillar', pillar, 'score', score,
                    'passed_checks', passed_checks, 'failed_checks', failed_checks,
                    'weighted_score', weighted_score
                )) FROM titlis_oltp.pillar_scores WHERE scorecard_id = OLD.id),
                '[]'::jsonb
            ),
            COALESCE(
                (SELECT jsonb_agg(jsonb_build_object(
                    'rule_id', vr.id,
                    'rule_ref', r.rule_id,
                    'pillar', r.pillar,
                    'severity', r.severity,
                    'passed', vr.passed,
                    'message', vr.message,
                    'actual_value', vr.actual_value
                ))
                FROM titlis_oltp.validation_results vr
                JOIN titlis_oltp.validation_rules r ON r.id = vr.rule_id
                WHERE vr.scorecard_id = OLD.id),
                '[]'::jsonb
            ),
            OLD.evaluated_at,
            OLD.k8s_event_type;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_scorecard_to_history
BEFORE UPDATE ON titlis_oltp.app_scorecards
FOR EACH ROW
EXECUTE FUNCTION titlis_oltp.fn_scorecard_to_history();

-- Trigger: toda transição de status de remediação gera um registro histórico
CREATE OR REPLACE FUNCTION titlis_oltp.fn_remediation_to_history()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status OR OLD.version IS DISTINCT FROM NEW.version THEN
        INSERT INTO titlis_audit.remediation_history (
            workload_id, tenant_id, remediation_version, status, previous_status,
            scorecard_version, github_pr_number, github_pr_url, github_branch,
            repository_url, error_message, triggered_at, resolved_at
        )
        SELECT
            NEW.workload_id,
            NEW.tenant_id,
            NEW.version,
            NEW.status::TEXT,
            OLD.status::TEXT,
            (SELECT version FROM titlis_oltp.app_scorecards
             WHERE workload_id = NEW.workload_id),
            NEW.github_pr_number,
            NEW.github_pr_url,
            NEW.github_branch,
            NEW.repository_url,
            NEW.error_message,
            NEW.triggered_at,
            NEW.resolved_at;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_remediation_to_history
AFTER UPDATE ON titlis_oltp.app_remediations
FOR EACH ROW
EXECUTE FUNCTION titlis_oltp.fn_remediation_to_history();

-- ================================================================
-- INDEXES DE PERFORMANCE
-- ================================================================

-- OLTP — leituras do frontend
CREATE INDEX idx_workloads_namespace      ON titlis_oltp.workloads (namespace_id)
    WHERE is_active = TRUE;
CREATE INDEX idx_scorecard_compliance     ON titlis_oltp.app_scorecards (compliance_status);
CREATE INDEX idx_scorecard_score          ON titlis_oltp.app_scorecards (overall_score);
CREATE INDEX idx_remediation_status       ON titlis_oltp.app_remediations (status);
CREATE INDEX idx_val_results_rule_passed  ON titlis_oltp.validation_results (rule_id, passed);

-- ================================================================
-- ROLES E PERMISSÕES
-- ================================================================
-- Criar roles antes de executar este bloco em produção:
--   CREATE ROLE operator_role;
--   CREATE ROLE analytics_role;
--   CREATE ROLE metrics_collector_role;
--
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA titlis_oltp TO operator_role;
-- GRANT SELECT ON ALL TABLES IN SCHEMA titlis_audit TO analytics_role;
-- GRANT INSERT ON ALL TABLES IN SCHEMA titlis_ts TO metrics_collector_role;
--
-- RLS (Fase 1 — multi-tenant):
--   ALTER TABLE titlis_oltp.clusters ENABLE ROW LEVEL SECURITY;
--   CREATE POLICY tenant_isolation ON titlis_oltp.clusters
--       USING (tenant_id = current_setting('app.current_tenant_id')::UUID);
--   (repetir para todas as tabelas com tenant_id)

-- ================================================================
-- PARTICIONAMENTO (produção — recomendado após 6 meses de dados)
-- ================================================================
-- Converter titlis_audit.app_scorecard_history e titlis_ts.* para
-- PARTITION BY RANGE (evaluated_at / recorded_at) por trimestre.
-- Usar pg_partman para automação da criação de partições.
--
-- SELECT create_parent(
--     'titlis_audit.app_scorecard_history',
--     'evaluated_at', 'native', 'quarterly'
-- );
