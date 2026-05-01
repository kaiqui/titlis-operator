#!/usr/bin/env python3
import signal
import threading

from src.bootstrap.dependencies import init_logging

init_logging()

from src.controllers.synthetic_monitor_controller import (
    _check_loop,
    _load_checks_config,
)
from src.utils.json_logger import get_logger

logger = get_logger("SyntheticMonitorMain")

_stop_event = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:
    logger.info(
        "Sinal recebido — encerrando Synthetic Monitor",
        extra={"signum": signum},
    )
    _stop_event.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = _load_checks_config()

    if not config.checks:
        logger.warning(
            "Nenhum check configurado — monitor sintético ocioso",
            extra={"feature": "synthetic_monitor"},
        )
        return

    logger.info(
        "Synthetic Monitor iniciado",
        extra={
            "check_count": len(config.checks),
            "check_names": [c.name for c in config.checks],
        },
    )

    for check in config.checks:
        threading.Thread(
            target=_check_loop,
            args=(check,),
            name=f"synthetic-monitor-{check.name}",
            daemon=True,
        ).start()
        logger.info(
            "Check sintético iniciado",
            extra={
                "check_name": check.name,
                "check_type": check.type,
                "url": check.url,
                "interval_seconds": check.interval_seconds,
            },
        )

    _stop_event.wait()
    logger.info("Synthetic Monitor encerrado")


if __name__ == "__main__":
    main()
