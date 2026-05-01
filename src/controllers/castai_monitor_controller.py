import asyncio

from src.settings import settings
from src.infrastructure.kubernetes.castai_health import CastAIHealthChecker
from src.infrastructure.datadog.managers.castai_metrics import CastAIMetricsManager
from src.utils.json_logger import get_logger

logger = get_logger("CastAIMonitorController")


async def _monitor_loop() -> None:
    await asyncio.sleep(10)

    while True:
        try:
            await run_castai_health_check()
        except asyncio.CancelledError:
            logger.info("CastAI Monitor loop cancelado")
            raise
        except Exception:
            logger.exception(
                "Erro não tratado no loop do CastAI Monitor — continuando",
                extra={"feature": "castai_monitor"},
            )

        await asyncio.sleep(settings.castai_monitor_interval_seconds)


async def run_castai_health_check() -> None:
    cluster_name = settings.castai_cluster_name
    namespace = settings.castai_monitor_namespace

    if not cluster_name:
        logger.error(
            "CASTAI_CLUSTER_NAME não configurado — métrica não será enviada",
            extra={"feature": "castai_monitor"},
        )
        return

    logger.info(
        "Iniciando verificação de health CAST AI",
        extra={
            "cluster_name": cluster_name,
            "namespace": namespace,
        },
    )

    try:
        checker = CastAIHealthChecker(
            namespace=namespace,
            cluster_name=cluster_name,
        )
        results = await asyncio.get_event_loop().run_in_executor(
            None, checker.check_all
        )
    except Exception:
        logger.exception(
            "Falha crítica ao verificar pods CAST AI",
            extra={"cluster_name": cluster_name},
        )
        return

    if not settings.datadog_api_key:
        logger.error(
            "DD_API_KEY não configurada — métricas CAST AI não serão enviadas",
            extra={"cluster_name": cluster_name},
        )
        return

    try:
        metrics_manager = CastAIMetricsManager(
            api_key=settings.datadog_api_key,
            app_key=settings.datadog_app_key,
            site=settings.datadog_site,
        )
        metrics_manager.send_all([r.to_dict() for r in results])

    except Exception:
        logger.exception(
            "Falha ao enviar métricas CAST AI para Datadog",
            extra={"cluster_name": cluster_name},
        )
        return

    logger.info(
        "Ciclo de monitoramento CAST AI concluído",
        extra={
            "cluster_name": cluster_name,
            "checked_services": [r.service for r in results],
            "healthy": [r.service for r in results if r.is_healthy],
            "unhealthy": [r.service for r in results if not r.is_healthy],
        },
    )
