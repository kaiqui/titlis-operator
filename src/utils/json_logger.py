# logging_config.py
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, MutableMapping, Optional

_STANDARD_LOG_RECORD_KEYS = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonLogFormatter(logging.Formatter):
    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Optional[Dict[str, Any]],
    ) -> None:
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["function"] = record.funcName

        if message_dict:
            log_record.update(message_dict)

        if record.exc_info:
            try:
                log_record["stack_trace"] = traceback.format_exception(*record.exc_info)
            except Exception:
                log_record["stack_trace"] = str(record.exc_info)

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_record: Dict[str, Any] = {}
        self.add_fields(log_record, record, None)
        log_record["message"] = record.getMessage()

        for key, value in record.__dict__.items():
            if (
                key in _STANDARD_LOG_RECORD_KEYS
                or key.startswith("_")
                or key in log_record
            ):
                continue
            try:
                json.dumps(value)
                log_record[key] = value
            except (TypeError, ValueError):
                log_record[key] = str(value)

        return json.dumps(log_record)


_root_configured = False


def ensure_json_logging(level: int = logging.INFO) -> None:
    global _root_configured
    root = logging.getLogger()

    if not _root_configured:
        try:
            for h in list(getattr(root, "handlers", [])):
                root.removeHandler(h)
        except TypeError:
            pass

        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)
        logging.captureWarnings(True)
        root.setLevel(level)
        _root_configured = True


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    ensure_json_logging()
    log = logging.getLogger(name)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    log.setLevel(numeric_level)
    return log


class OperatorLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        extra = dict(self.extra or {})
        extra.update(kwargs.get("extra", {}))
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(
    name: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> logging.Logger:
    ensure_json_logging()
    log = logging.getLogger(name)
    if context is not None:
        return OperatorLoggerAdapter(log, context)  # type: ignore[return-value]
    return log
