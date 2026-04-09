import logging

from src.settings import settings
from src.utils.json_logger import ensure_json_logging


def init_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    ensure_json_logging(level=level)
