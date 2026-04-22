from typing import Optional

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TitlisApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TITLIS_API_")

    enabled: bool = Field(default=False)
    host: str = Field(default="titlis-api.titlis-system.svc.cluster.local")
    udp_port: int = Field(default=8125)
    http_port: int = Field(default=8080)
    scheme: str = Field(default="http")
    api_key: Optional[SecretStr] = Field(default=None)

    @model_validator(mode="after")
    def require_api_key_when_enabled(self) -> "TitlisApiSettings":
        if self.enabled and not self.api_key:
            raise ValueError(
                "TITLIS_API_API_KEY é obrigatória quando TITLIS_API_ENABLED=true. "
                "Gere uma key no painel em /settings/api-keys e configure o Secret K8s."
            )
        return self

    @property
    def http_base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.http_port}"


class SlackSettings(BaseSettings):
    enabled: bool = Field(default=False, validation_alias="SLACK_ENABLED")
    webhook_url: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_WEBHOOK_URL"
    )
    client_id: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_CLIENT_ID"
    )
    client_secret: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_CLIENT_SECRET"
    )
    signing_secret: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_SIGNING_SECRET"
    )
    verification_token: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_VERIFICATION_TOKEN"
    )
    bot_token: Optional[SecretStr] = Field(
        default=None, validation_alias="SLACK_BOT_TOKEN"
    )
    default_channel: str = Field(
        default="#titlis-notifications", validation_alias="SLACK_DEFAULT_CHANNEL"
    )
    secret_name: str = Field(
        default="titlis-slack-keys", validation_alias="SLACK_SECRET_NAME"
    )
    rate_limit_per_minute: int = Field(
        default=60, validation_alias="SLACK_RATE_LIMIT_PER_MINUTE"
    )
    rate_limit_per_hour: int = Field(
        default=360, validation_alias="SLACK_RATE_LIMIT_PER_HOUR"
    )
    timeout_seconds: float = Field(
        default=10.0, validation_alias="SLACK_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(default=3, validation_alias="SLACK_MAX_RETRIES")
    enabled_severities: str = Field(
        default="info,warning,error,critical",
        validation_alias="SLACK_ENABLED_SEVERITIES",
    )
    enabled_channels: str = Field(
        default="operational,alerts", validation_alias="SLACK_ENABLED_CHANNELS"
    )
    message_title: str = Field(
        default="Kopf Operator Notification", validation_alias="SLACK_MESSAGE_TITLE"
    )
    include_timestamp: bool = Field(
        default=True, validation_alias="SLACK_INCLUDE_TIMESTAMP"
    )
    include_cluster_info: bool = Field(
        default=True, validation_alias="SLACK_INCLUDE_CLUSTER_INFO"
    )
    include_namespace: bool = Field(
        default=True, validation_alias="SLACK_INCLUDE_NAMESPACE"
    )
    max_message_length: int = Field(
        default=3000, validation_alias="SLACK_MAX_MESSAGE_LENGTH"
    )
    config_path: Optional[str] = Field(
        default=None, validation_alias="SLACK_CONFIG_PATH"
    )

    model_config = SettingsConfigDict(
        env_prefix="SLACK_", case_sensitive=False, extra="ignore"
    )


class Settings(BaseSettings):
    titlis_api: TitlisApiSettings = Field(default_factory=TitlisApiSettings)
    slack: SlackSettings = Field(default_factory=SlackSettings)

    kubernetes_namespace: str = Field(
        default="titlis-system", validation_alias="KUBERNETES_NAMESPACE"
    )
    kubernetes_cluster_name: str = Field(
        default="unknown", validation_alias="KUBERNETES_CLUSTER_NAME"
    )
    service_account_name: str = Field(
        default="titlis-operator", validation_alias="SERVICE_ACCOUNT_NAME"
    )

    datadog_api_key: Optional[str] = Field(default=None, validation_alias="DD_API_KEY")
    datadog_app_key: Optional[str] = Field(default=None, validation_alias="DD_APP_KEY")
    datadog_site: str = Field(default="datadoghq.com", validation_alias="DD_SITE")
    datadog_secret_name: str = Field(
        default="titlis-datadog-keys", validation_alias="DD_SECRET_NAME"
    )

    reconcile_interval_seconds: int = Field(
        default=300, validation_alias="RECONCILE_INTERVAL_SECONDS"
    )
    debounce_seconds: int = Field(default=30, validation_alias="DEBOUNCE_SECONDS")
    enable_leader_election: bool = Field(
        default=True, validation_alias="ENABLE_LEADER_ELECTION"
    )
    leader_election_namespace: str = Field(
        default="titlis", validation_alias="LEADER_ELECTION_NAMESPACE"
    )

    log_level: str = Field(default="DEBUG", validation_alias="LOG_LEVEL")
    log_format: str = Field(default="json", validation_alias="LOG_FORMAT")

    metrics_enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    tracing_enabled: bool = Field(default=False, validation_alias="TRACING_ENABLED")

    enable_scorecard_controller: bool = Field(
        default=True, validation_alias="ENABLE_SCORECARD_CONTROLLER"
    )
    enable_slo_controller: bool = Field(
        default=True, validation_alias="ENABLE_SLO_CONTROLLER"
    )

    enable_castai_monitor: bool = Field(
        default=False, validation_alias="ENABLE_CASTAI_MONITOR"
    )
    castai_monitor_namespace: str = Field(
        default="castai-agent", validation_alias="CASTAI_MONITOR_NAMESPACE"
    )
    castai_monitor_interval_seconds: int = Field(
        default=60, validation_alias="CASTAI_MONITOR_INTERVAL_SECONDS"
    )
    castai_cluster_name: str = Field(
        default="develop", validation_alias="CASTAI_CLUSTER_NAME"
    )

    enable_synthetic_monitor: bool = Field(
        default=False, validation_alias="ENABLE_SYNTHETIC_MONITOR"
    )
    synthetic_monitor_name: str = Field(
        default="jeitto-homepage", validation_alias="SYNTHETIC_MONITOR_NAME"
    )
    synthetic_monitor_url: str = Field(
        default="https://jeitto.com.br", validation_alias="SYNTHETIC_MONITOR_URL"
    )
    synthetic_monitor_interval_seconds: int = Field(
        default=60, validation_alias="SYNTHETIC_MONITOR_INTERVAL_SECONDS"
    )
    synthetic_monitor_timeout_seconds: float = Field(
        default=10.0, validation_alias="SYNTHETIC_MONITOR_TIMEOUT_SECONDS"
    )
    synthetic_checks_config_path: Optional[str] = Field(
        default="config/synthetic-checks.yaml",
        validation_alias="SYNTHETIC_CHECKS_CONFIG_PATH",
    )

    backstage_url: Optional[str] = Field(default=None, validation_alias="BACKSTAGE_URL")
    backstage_token: Optional[str] = Field(
        default=None, validation_alias="BACKSTAGE_TOKEN"
    )
    backstage_cache_ttl_seconds: int = Field(
        default=300, validation_alias="BACKSTAGE_CACHE_TTL_SECONDS"
    )

    castai_api_key: Optional[str] = Field(
        default=None, validation_alias="CASTAI_API_KEY"
    )
    castai_cluster_id: Optional[str] = Field(
        default=None, validation_alias="CASTAI_CLUSTER_ID"
    )
    castai_cost_cache_ttl_seconds: int = Field(
        default=300, validation_alias="CASTAI_COST_CACHE_TTL_SECONDS"
    )

    enable_backstage_enrichment: bool = Field(
        default=False, validation_alias="ENABLE_BACKSTAGE_ENRICHMENT"
    )
    enable_castai_cost_enrichment: bool = Field(
        default=False, validation_alias="ENABLE_CASTAI_COST_ENRICHMENT"
    )

    enable_auto_slo_creation: bool = Field(
        default=True, validation_alias="ENABLE_AUTO_SLO_CREATION"
    )
    auto_slo_default_target: float = Field(
        default=99.0, validation_alias="AUTO_SLO_DEFAULT_TARGET"
    )
    auto_slo_default_warning: float = Field(
        default=99.5, validation_alias="AUTO_SLO_DEFAULT_WARNING"
    )
    auto_slo_default_timeframe: str = Field(
        default="30d", validation_alias="AUTO_SLO_DEFAULT_TIMEFRAME"
    )
    auto_slo_require_datadog_service: bool = Field(
        default=True, validation_alias="AUTO_SLO_REQUIRE_DATADOG_SERVICE"
    )
    auto_slo_pending_changes_poll_interval_seconds: int = Field(
        default=30, validation_alias="AUTO_SLO_PENDING_CHANGES_POLL_INTERVAL_SECONDS"
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
