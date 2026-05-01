import time
from typing import Union

from src.infrastructure.datadog.managers.gauge_metric import GaugeMetricSender
from src.infrastructure.datadog.managers.synthetic_metrics import (
    SyntheticSiteMetricsManager,
)
from src.infrastructure.synthetic.check_config import (
    JsonValueCheckConfig,
    SiteHealthCheckConfig,
    SyntheticChecksConfig,
)
from src.infrastructure.synthetic.json_value_checker import JsonValueChecker
from src.infrastructure.synthetic.site_health import SyntheticSiteHealthChecker
from src.settings import settings
from src.utils.json_logger import get_logger

logger = get_logger("SyntheticMonitorController")

_AnyCheck = Union[SiteHealthCheckConfig, JsonValueCheckConfig]


def _load_checks_config() -> SyntheticChecksConfig:
    import os

    config_path = settings.synthetic_checks_config_path
    if config_path and os.path.isfile(config_path):
        from ruamel.yaml import YAML

        ruyaml = YAML()
        with open(config_path) as fh:
            raw = ruyaml.load(fh)
        return SyntheticChecksConfig.model_validate(raw or {})

    if settings.synthetic_monitor_url:
        return SyntheticChecksConfig(
            checks=[
                SiteHealthCheckConfig(
                    name=settings.synthetic_monitor_name,
                    url=settings.synthetic_monitor_url,
                    interval_seconds=settings.synthetic_monitor_interval_seconds,
                    timeout_seconds=settings.synthetic_monitor_timeout_seconds,
                )
            ]
        )

    return SyntheticChecksConfig(checks=[])


def _tags_dict_to_list(tags: dict[str, str]) -> list[str]:
    return [f"{k}:{v}" for k, v in tags.items()]


def _run_site_health_check(check: SiteHealthCheckConfig) -> None:
    checker = SyntheticSiteHealthChecker(
        monitor_name=check.name,
        target_url=check.url,
        timeout_seconds=check.timeout_seconds,
    )
    result = checker.check()

    if not settings.datadog_api_key:
        logger.error(
            "DD_API_KEY não configurada — site_health não será enviado",
            extra={"check_name": check.name},
        )
        return

    try:
        manager = SyntheticSiteMetricsManager(
            api_key=settings.datadog_api_key,
            app_key=settings.datadog_app_key,
            site=settings.datadog_site,
        )
        manager.send_check_result(
            result.to_dict(),
            extra_tags=_tags_dict_to_list(check.tags),
        )
    except Exception:
        logger.exception(
            "Falha ao enviar site_health para Datadog",
            extra={"check_name": check.name},
        )
        return

    logger.info(
        "Ciclo site_health concluído",
        extra={
            "check_name": check.name,
            "is_healthy": result.is_healthy,
            "status_code": result.status_code,
            "response_time_ms": result.response_time_ms,
        },
    )


def _run_json_value_check(check: JsonValueCheckConfig) -> None:
    checker = JsonValueChecker(
        name=check.name,
        url=check.url,
        timeout_seconds=check.timeout_seconds,
        headers=check.headers,
    )
    result = checker.check(
        json_path=check.json_path,
        metric_name=check.metric_name,
    )

    if not settings.datadog_api_key:
        logger.error(
            "DD_API_KEY não configurada — json_value não será enviado",
            extra={"check_name": check.name},
        )
        return

    if not result.success or result.value is None:
        logger.warning(
            "JSON value check falhou — gauge não enviado",
            extra={
                "check_name": check.name,
                "url": check.url,
                "reason": result.reason,
            },
        )
        return

    tags = [f"check_name:{check.name}", *_tags_dict_to_list(check.tags)]
    try:
        sender = GaugeMetricSender(
            api_key=settings.datadog_api_key,
            app_key=settings.datadog_app_key,
            site=settings.datadog_site,
        )
        sender.send(
            metric_name=check.metric_name,
            value=result.value,
            tags=tags,
            timestamp=result.checked_at,
        )
    except Exception:
        logger.exception(
            "Falha ao enviar json_value para Datadog",
            extra={"check_name": check.name, "metric_name": check.metric_name},
        )


def _check_loop(check: _AnyCheck) -> None:
    time.sleep(10)
    while True:
        try:
            if isinstance(check, SiteHealthCheckConfig):
                _run_site_health_check(check)
            elif isinstance(check, JsonValueCheckConfig):
                _run_json_value_check(check)
        except Exception:
            logger.exception(
                "Erro não tratado no check loop — continuando",
                extra={"check_name": check.name},
            )
        time.sleep(check.interval_seconds)
