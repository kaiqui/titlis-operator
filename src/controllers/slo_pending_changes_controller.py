import asyncio
from typing import Any

import kopf

from src.settings import settings
from src.bootstrap.dependencies import get_titlis_api_client
from src.infrastructure.kubernetes.client import get_k8s_apis
from src.utils.json_logger import get_logger

logger = get_logger("SLOPendingChangesController")


@kopf.on.startup()
async def slo_pending_changes_startup(**kwargs: Any) -> None:
    if not settings.titlis_api.enabled:
        logger.info(
            "Titlis API desabilitada — polling de pending SLO changes ignorado",
            extra={"feature": "slo_pending_changes"},
        )
        return

    asyncio.create_task(_pending_changes_loop(), name="slo-pending-changes-loop")

    logger.info(
        "SLO pending changes loop iniciado",
        extra={
            "poll_interval_seconds": settings.auto_slo_pending_changes_poll_interval_seconds,
        },
    )


async def _pending_changes_loop() -> None:
    await asyncio.sleep(15)

    while True:
        try:
            await apply_pending_slo_changes()
        except asyncio.CancelledError:
            logger.info("SLO pending changes loop cancelado")
            raise
        except Exception:
            logger.exception(
                "Erro não tratado no loop de pending SLO changes — continuando",
                extra={"feature": "slo_pending_changes"},
            )

        await asyncio.sleep(settings.auto_slo_pending_changes_poll_interval_seconds)


async def apply_pending_slo_changes() -> None:
    titlis_client = get_titlis_api_client()
    if titlis_client is None:
        return

    pending = await titlis_client.get_pending_slo_changes()
    if not pending:
        return

    logger.info(
        "Pending SLO changes recebidos",
        extra={"count": len(pending)},
    )

    for change in pending:
        await _apply_single_change(titlis_client, change)


async def _apply_single_change(titlis_client: Any, change: Any) -> None:
    logger.info(
        "Aplicando pending SLO change",
        extra={
            "change_id": change.id,
            "slo_config_name": change.slo_config_name,
            "namespace": change.namespace,
            "field": change.field,
            "old_value": change.old_value,
            "new_value": change.new_value,
        },
    )

    try:
        _, _, custom = get_k8s_apis()

        new_value = _coerce_field_value(change.field, change.new_value)
        patch_body = {"spec": {change.field: new_value}}

        custom.patch_namespaced_custom_object(
            group="titlis.io",
            version="v1",
            namespace=change.namespace,
            plural="sloconfigs",
            name=change.slo_config_name,
            body=patch_body,
        )

        await titlis_client.confirm_slo_change_applied(change.id)
        logger.info(
            "Pending SLO change aplicado com sucesso",
            extra={"change_id": change.id, "slo_config_name": change.slo_config_name},
        )

    except Exception as exc:
        error_msg = str(exc)
        logger.exception(
            "Falha ao aplicar pending SLO change",
            extra={
                "change_id": change.id,
                "slo_config_name": change.slo_config_name,
                "error": error_msg,
            },
        )
        await titlis_client.confirm_slo_change_failed(change.id, error_msg)


def _coerce_field_value(field: str, value: str) -> Any:
    if field in ("target", "warning"):
        return float(value)
    return value
