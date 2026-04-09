import pytest
import logging
from unittest.mock import patch, Mock
from src.utils.json_logger import (
    JsonLogFormatter,
    ensure_json_logging,
    setup_logger,
    get_logger,
    OperatorLoggerAdapter,
)


class TestJsonLogger:
    def test_json_formatter_initialization(self):
        formatter = JsonLogFormatter()
        assert formatter is not None
        assert hasattr(formatter, "add_fields")

    def test_json_formatter_add_fields(self):
        formatter = JsonLogFormatter()

        # Create a mock log record
        record = Mock()
        record.levelname = "INFO"
        record.funcName = "test_function"
        record.exc_info = None

        log_record = {}
        message_dict = {"extra_field": "value"}

        formatter.add_fields(log_record, record, message_dict)

        assert "timestamp" in log_record
        assert log_record["level"] == "INFO"
        assert log_record["function"] == "test_function"
        assert "extra_field" in log_record

    def test_json_formatter_with_exception(self):
        formatter = JsonLogFormatter()

        record = Mock()
        record.levelname = "ERROR"
        record.name = "test"
        record.module = "test_module"
        record.funcName = "test_function"
        record.exc_info = (ValueError, ValueError("test error"), Mock())

        log_record = {}

        formatter.add_fields(log_record, record, None)

        assert "stack_trace" in log_record

    @patch("src.utils.json_logger.logging.StreamHandler")
    def test_ensure_json_logging(self, mock_handler):
        import src.utils.json_logger as jl

        original_configured = jl._root_configured
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_level = root.level

        jl._root_configured = False  # force handler setup

        mock_handler_instance = Mock()
        mock_handler_instance.level = logging.NOTSET
        mock_handler.return_value = mock_handler_instance

        ensure_json_logging(logging.WARNING)

        assert root.level == logging.WARNING
        assert mock_handler_instance.setFormatter.called

        for h in list(root.handlers):
            root.removeHandler(h)
        for h in original_handlers:
            root.addHandler(h)
        root.setLevel(original_level)
        jl._root_configured = original_configured

    def test_setup_logger(self):
        with patch("src.utils.json_logger.ensure_json_logging") as mock_ensure:
            logger = setup_logger("test_logger", "DEBUG")
            assert logger is not None
            mock_ensure.assert_called_once()

    def test_get_logger_with_context(self):
        with patch("src.utils.json_logger.ensure_json_logging"):
            logger = get_logger("test", {"context": "value"})
            assert isinstance(logger, OperatorLoggerAdapter)
            assert logger.extra == {"context": "value"}

    def test_operator_logger_adapter(self):
        mock_logger = Mock()
        context = {"namespace": "test", "pod": "test-pod"}
        adapter = OperatorLoggerAdapter(mock_logger, context)

        msg = "test message"
        kwargs = {"extra": {"custom": "field"}}

        result_msg, result_kwargs = adapter.process(msg, kwargs)

        assert result_msg == msg
        assert "extra" in result_kwargs
        # Check that context and extra are merged
        assert "namespace" in result_kwargs["extra"]
        assert "custom" in result_kwargs["extra"]

    def test_operator_logger_adapter_no_extra(self):
        mock_logger = Mock()
        context = {"namespace": "test"}
        adapter = OperatorLoggerAdapter(mock_logger, context)

        msg = "test message"
        kwargs: dict = {}

        result_msg, result_kwargs = adapter.process(msg, kwargs)

        assert result_msg == msg
        assert "extra" in result_kwargs
        assert "namespace" in result_kwargs["extra"]

    def test_get_logger_without_context(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_ensure_json_logging_sets_level(self):
        import src.utils.json_logger as jl

        original = jl._root_configured
        jl._root_configured = True  # skip handler setup, only test level change

        root = logging.getLogger()
        ensure_json_logging(logging.DEBUG)
        assert root.level == logging.DEBUG

        jl._root_configured = original

    def test_json_formatter_format(self):
        import json

        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "message" in parsed or "level" in parsed


class TestLoggingBootstrap:
    def test_init_logging(self):
        from src.utils.logging_bootstrap import init_logging

        with patch("src.utils.logging_bootstrap.ensure_json_logging") as mock_ensure:
            init_logging()
            mock_ensure.assert_called_once()
            _, kwargs = mock_ensure.call_args
            assert "level" in kwargs
