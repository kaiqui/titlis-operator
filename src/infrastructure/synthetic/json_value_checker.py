import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from src.utils.json_logger import get_logger


@dataclass
class JsonValueCheckResult:
    check_name: str
    url: str
    metric_name: str
    value: Optional[float]
    success: bool
    checked_at: int = field(default_factory=lambda: int(time.time()))
    reason: str = ""


def _resolve_path(data: Any, path: str) -> Optional[float]:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


class JsonValueChecker:
    def __init__(
        self,
        name: str,
        url: str,
        timeout_seconds: float,
        headers: dict[str, str],
    ) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.name = name
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "User-Agent": "titlis-operator-synthetic-monitor/1.0",
            **headers,
        }

    async def check(self, json_path: str, metric_name: str) -> JsonValueCheckResult:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as http:
                response = await http.get(self.url, headers=self.headers)

            if not (200 <= response.status_code < 300):
                return JsonValueCheckResult(
                    check_name=self.name,
                    url=self.url,
                    metric_name=metric_name,
                    value=None,
                    success=False,
                    reason=f"HTTP {response.status_code}",
                )

            data = response.json()
            value = _resolve_path(data, json_path)

            if value is None:
                return JsonValueCheckResult(
                    check_name=self.name,
                    url=self.url,
                    metric_name=metric_name,
                    value=None,
                    success=False,
                    reason=f"path '{json_path}' not found or not numeric",
                )

            self.logger.info(
                "JSON value check concluído",
                extra={
                    "check_name": self.name,
                    "metric_name": metric_name,
                    "json_path": json_path,
                    "value": value,
                },
            )

            return JsonValueCheckResult(
                check_name=self.name,
                url=self.url,
                metric_name=metric_name,
                value=value,
                success=True,
                reason="ok",
            )

        except httpx.TimeoutException:
            self.logger.exception(
                "Timeout no JSON value check",
                extra={"check_name": self.name, "url": self.url},
            )
            return JsonValueCheckResult(
                check_name=self.name,
                url=self.url,
                metric_name=metric_name,
                value=None,
                success=False,
                reason="timeout",
            )
        except (httpx.RequestError, ValueError) as exc:
            self.logger.exception(
                "Erro de rede/parse no JSON value check",
                extra={"check_name": self.name, "url": self.url, "error": str(exc)},
            )
            return JsonValueCheckResult(
                check_name=self.name,
                url=self.url,
                metric_name=metric_name,
                value=None,
                success=False,
                reason=str(exc),
            )
