#!/usr/bin/env python3
import asyncio
import signal

from src.bootstrap.dependencies import init_logging

init_logging()

from src.settings import settings
from src.controllers.castai_monitor_controller import _monitor_loop
from src.utils.json_logger import get_logger

logger = get_logger("CastAIMonitorMain")


async def main() -> None:
    logger.info(
        "CAST AI Monitor iniciado",
        extra={
            "cluster_name": settings.castai_cluster_name,
            "namespace": settings.castai_monitor_namespace,
            "interval_seconds": settings.castai_monitor_interval_seconds,
        },
    )

    loop = asyncio.get_running_loop()
    task = loop.create_task(_monitor_loop())

    def _stop(signum: int) -> None:
        logger.info(
            "Sinal recebido — encerrando CAST AI Monitor",
            extra={"signum": signum},
        )
        task.cancel()

    loop.add_signal_handler(signal.SIGTERM, _stop, signal.SIGTERM)
    loop.add_signal_handler(signal.SIGINT, _stop, signal.SIGINT)

    try:
        await task
    except asyncio.CancelledError:
        logger.info("CAST AI Monitor encerrado")


if __name__ == "__main__":
    asyncio.run(main())
