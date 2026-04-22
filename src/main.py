#!/usr/bin/env python3
import kopf
import logging
from typing import Any

from src.bootstrap.dependencies import init_logging

init_logging()

from src.settings import settings
from src.controllers.castai_monitor_controller import register_castai_monitor
from src.controllers.synthetic_monitor_controller import register_synthetic_monitor
from src.bootstrap.dependencies import (
    get_datadog_repository,
    get_slo_service,
    get_slack_service,
    initialize_slack_service,
    shutdown_slack_service,
    get_scorecard_service,
)

logger = logging.getLogger("titlis")


@kopf.on.startup()
def startup(settings_: "kopf.OperatorSettings | None" = None, **kwargs: Any) -> None:
    try:
        logger.info(
            "Inicializando Titlis Operator",
            extra={
                "version": "1.0.0",
                "features": {
                    "slack_notifications": settings.slack.enabled,
                    "scorecard_controller": settings.enable_scorecard_controller,
                    "slo_controller": settings.enable_slo_controller,
                    "synthetic_monitor": settings.enable_synthetic_monitor,
                },
            },
        )

        if settings.enable_slo_controller:
            get_slo_service()

        if settings.enable_scorecard_controller:
            scorecard_service = get_scorecard_service()
            if scorecard_service:
                logger.info(
                    "Scorecard service configurado",
                    extra={
                        "rules_count": len(
                            [r for r in scorecard_service.config.rules if r.enabled]
                        ),
                        "notification_batch": scorecard_service.config.batch_notifications,
                    },
                )

        slack_service = get_slack_service()
        if slack_service:
            logger.info(
                "Slack service configurado",
                extra={
                    "enabled": settings.slack.enabled,
                    "default_channel": settings.slack.default_channel,
                },
            )
        elif settings.slack.enabled:
            logger.warning(
                "Slack habilitado mas serviço não disponível",
                extra={"reason": "Verifique as credenciais"},
            )

        logger.info("Titlis Operator iniciado com sucesso")

    except Exception as exc:
        logger.exception("Falha na inicialização", extra={"error": str(exc)})
        raise kopf.TemporaryError(f"Erro na inicialização: {exc}", delay=30)


async def _wait_for_titlis_api(timeout: int = 60) -> None:
    if not settings.titlis_api.enabled:
        return
    import asyncio
    import httpx

    health_url = f"{settings.titlis_api.http_base_url}/health"
    deadline = asyncio.get_event_loop().time() + timeout
    attempt = 0
    while asyncio.get_event_loop().time() < deadline:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    logger.info(
                        "Titlis API disponível",
                        extra={"url": health_url, "attempt": attempt},
                    )
                    return
        except Exception:
            pass
        logger.info(
            "Aguardando Titlis API ficar disponível",
            extra={"url": health_url, "attempt": attempt},
        )
        await asyncio.sleep(3)
    logger.warning(
        "Titlis API não ficou disponível no timeout — prosseguindo sem garantia de entrega",
        extra={"url": health_url, "timeout_seconds": timeout},
    )


@kopf.on.startup()
async def startup_async(**kwargs: Any) -> None:
    try:
        await _wait_for_titlis_api(timeout=60)
        await initialize_slack_service()
        logger.info("Startup assíncrono concluído")
    except Exception as exc:
        logger.exception("Erro no startup assíncrono", extra={"error": str(exc)})


@kopf.on.cleanup()
async def cleanup(**kwargs: Any) -> None:
    try:
        await shutdown_slack_service()
        logger.info("Slack service finalizado")
    except Exception as exc:
        logger.exception("Erro ao finalizar Slack service", extra={"error": str(exc)})

    logger.info("Titlis Operator finalizado")


if settings.titlis_api.enabled:
    logger.info("Registrando SLO Pending Changes Controller")
    import src.controllers.slo_pending_changes_controller  # noqa: F401

if settings.enable_slo_controller:
    logger.info("Registrando SLO Controller")
    from src.controllers import slo_controller

if settings.enable_scorecard_controller:
    logger.info("Registrando Scorecard Controller")
    from src.controllers import scorecard_controller

if settings.enable_castai_monitor:
    logger.info("Registrando CAST AI Monitor Controller")
    register_castai_monitor()
    import src.controllers.castai_monitor_controller

if settings.enable_synthetic_monitor:
    logger.info("Registrando Synthetic Monitor Controller")
    register_synthetic_monitor()
    import src.controllers.synthetic_monitor_controller
