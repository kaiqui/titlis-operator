import time
from typing import Optional

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.metrics_api import MetricsApi
from datadog_api_client.v2.model.metric_intake_type import MetricIntakeType
from datadog_api_client.v2.model.metric_payload import MetricPayload
from datadog_api_client.v2.model.metric_point import MetricPoint
from datadog_api_client.v2.model.metric_series import MetricSeries

from src.utils.json_logger import get_logger


class GaugeMetricSender:
    def __init__(
        self,
        api_key: str,
        app_key: Optional[str],
        site: str,
    ) -> None:
        self.logger = get_logger(self.__class__.__name__)
        if not api_key:
            raise ValueError("DD_API_KEY é obrigatória para GaugeMetricSender")
        self.configuration = self._build_configuration(api_key, app_key, site)

    def send(
        self,
        metric_name: str,
        value: float,
        tags: list[str],
        timestamp: Optional[int] = None,
    ) -> bool:
        ts = timestamp or int(time.time())
        series = [
            MetricSeries(
                metric=metric_name,
                type=MetricIntakeType.GAUGE,
                points=[MetricPoint(timestamp=ts, value=value)],
                tags=tags,
            )
        ]
        self.logger.info(
            "Enviando gauge metric para Datadog",
            extra={"metric": metric_name, "value": value, "tags": tags},
        )
        try:
            with ApiClient(self.configuration) as api_client:
                MetricsApi(api_client).submit_metrics(body=MetricPayload(series=series))
            return True
        except Exception:
            self.logger.exception(
                "Erro ao enviar gauge metric para Datadog",
                extra={"metric": metric_name},
            )
            return False

    def _build_configuration(
        self, api_key: str, app_key: Optional[str], site: str
    ) -> Configuration:
        config = Configuration()
        config.api_key["apiKeyAuth"] = api_key
        if app_key:
            config.api_key["appKeyAuth"] = app_key
        config.server_variables["site"] = site
        return config
