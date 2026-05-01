import json
import time
import logging

import httpx

from src.application.ports.titlis_api_port import (
    TitlisApiPort,
    RemediationState,
    SLOPendingChange,
)
from typing import List, Optional

logger = logging.getLogger(__name__)


class TitlisApiUdpClient(TitlisApiPort):
    def __init__(
        self,
        host: str,
        udp_port: int,
        http_base_url: str,
        api_key: str,
        request_timeout_seconds: float = 10.0,
        connect_timeout_seconds: float = 3.0,
    ):
        self._http_base_url = http_base_url
        self._api_key = api_key
        self._request_timeout_seconds = request_timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._timeout = httpx.Timeout(
            timeout=request_timeout_seconds,
            connect=connect_timeout_seconds,
        )

    async def _send_http(self, event_type: str, data: dict) -> None:
        envelope = {
            "v": 1,
            "t": event_type,
            "ts": int(time.time() * 1000),
            "api_key": self._api_key,
            "data": data,
        }
        url = f"{self._http_base_url}/v1/operator/events"
        payload_bytes = len(json.dumps(envelope, default=str))
        started_at = time.perf_counter()
        logger.info(
            "titlis_api_http_send_started",
            extra={
                "event": event_type,
                "url": url,
                "bytes": payload_bytes,
                "request_timeout_seconds": self._request_timeout_seconds,
                "connect_timeout_seconds": self._connect_timeout_seconds,
            },
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url,
                    json=envelope,
                    headers={"X-Api-Key": self._api_key},
                )
                resp.raise_for_status()
            logger.info(
                "http_evento_enviado",
                extra={
                    "event": event_type,
                    "url": url,
                    "bytes": payload_bytes,
                    "status_code": resp.status_code,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "titlis_api_http_send_timeout",
                extra={
                    "event": event_type,
                    "url": url,
                    "bytes": payload_bytes,
                    "request_timeout_seconds": self._request_timeout_seconds,
                    "connect_timeout_seconds": self._connect_timeout_seconds,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "titlis_api_http_send_bad_status",
                extra={
                    "event": event_type,
                    "url": url,
                    "bytes": payload_bytes,
                    "status_code": exc.response.status_code,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )
        except httpx.RequestError as exc:
            logger.warning(
                "titlis_api_http_send_request_error",
                extra={
                    "event": event_type,
                    "url": url,
                    "bytes": payload_bytes,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )
        except Exception as exc:
            logger.warning(
                "titlis_api_http_send_failed",
                extra={
                    "event": event_type,
                    "url": url,
                    "bytes": payload_bytes,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )

    async def send_scorecard_evaluated(self, payload: dict) -> None:
        await self._send_http("scorecard_evaluated", payload)

    async def send_remediation_event(self, payload: dict) -> None:
        await self._send_http("remediation_updated", payload)

    async def send_slo_reconciled(self, payload: dict) -> None:
        await self._send_http("slo_reconciled", payload)

    async def send_notification_log(self, payload: dict) -> None:
        await self._send_http("notification_sent", payload)

    async def send_resource_metrics(self, payload: dict) -> None:
        await self._send_http("resource_metrics", payload)

    async def get_remediation(self, workload_id: str) -> Optional[RemediationState]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._http_base_url}/v1/workloads/{workload_id}/remediation"
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                return RemediationState(
                    status=data["status"],
                    version=data["version"],
                    github_pr_url=data.get("github_pr_url"),
                    github_pr_number=data.get("github_pr_number"),
                )
        except Exception as exc:
            logger.warning(
                "titlis_api_http_get_failed",
                extra={"workload_id": workload_id, "error": repr(exc)},
            )
            return None

    async def get_pending_slo_changes(self) -> List[SLOPendingChange]:
        url = f"{self._http_base_url}/v1/operator/pending-slo-changes"
        started_at = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    url,
                    headers={"X-Api-Key": self._api_key},
                )
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                items = resp.json()
                return [
                    SLOPendingChange(
                        id=item["id"],
                        slo_config_name=item["slo_config_name"],
                        namespace=item["namespace"],
                        field=item["field"],
                        old_value=item["old_value"],
                        new_value=item["new_value"],
                        requested_by=item.get("requested_by", "unknown"),
                        extra=item,
                    )
                    for item in items
                ]
        except httpx.TimeoutException as exc:
            logger.warning(
                "titlis_api_get_pending_slo_changes_timeout",
                extra={
                    "url": url,
                    "request_timeout_seconds": self._request_timeout_seconds,
                    "connect_timeout_seconds": self._connect_timeout_seconds,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )
        except Exception as exc:
            logger.warning(
                "titlis_api_get_pending_slo_changes_failed",
                extra={
                    "url": url,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "error": repr(exc),
                },
            )
            return []

    async def confirm_slo_change_applied(self, change_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._http_base_url}/v1/operator/pending-slo-changes/{change_id}/applied",
                    headers={"X-Api-Key": self._api_key},
                )
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.warning(
                "titlis_api_confirm_slo_change_applied_failed",
                extra={"change_id": change_id, "error": repr(exc)},
            )
            return False

    async def confirm_slo_change_failed(self, change_id: str, error: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._http_base_url}/v1/operator/pending-slo-changes/{change_id}/failed",
                    headers={"X-Api-Key": self._api_key},
                    json={"error": error},
                )
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.warning(
                "titlis_api_confirm_slo_change_failed_failed",
                extra={"change_id": change_id, "error": repr(exc)},
            )
            return False

    async def close(self) -> None:
        pass
