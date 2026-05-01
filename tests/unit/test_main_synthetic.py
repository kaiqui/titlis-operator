import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.synthetic.check_config import (
    SiteHealthCheckConfig,
    SyntheticChecksConfig,
)


class TestMainSyntheticMain:
    def test_exits_when_no_checks_configured(self):
        with (
            patch(
                "src.main_synthetic._load_checks_config",
                return_value=SyntheticChecksConfig(checks=[]),
            ),
            patch("src.main_synthetic.threading.Thread") as mock_thread_cls,
        ):
            from src.main_synthetic import main

            main()

            mock_thread_cls.assert_not_called()

    def test_spawns_one_daemon_thread_per_check(self):
        checks = [
            SiteHealthCheckConfig(
                name="check-a", url="http://a.example.com", interval_seconds=60
            ),
            SiteHealthCheckConfig(
                name="check-b", url="http://b.example.com", interval_seconds=120
            ),
        ]
        config = SyntheticChecksConfig(checks=checks)

        mock_thread = MagicMock()

        with (
            patch("src.main_synthetic._load_checks_config", return_value=config),
            patch("src.main_synthetic._stop_event") as mock_event,
            patch(
                "src.main_synthetic.threading.Thread", return_value=mock_thread
            ) as mock_thread_cls,
        ):
            mock_event.wait.return_value = None

            from src.main_synthetic import main

            main()

        assert mock_thread_cls.call_count == 2
        assert mock_thread.start.call_count == 2

        for call in mock_thread_cls.call_args_list:
            assert call.kwargs.get("daemon") is True

    def test_thread_names_include_check_name(self):
        checks = [
            SiteHealthCheckConfig(
                name="homepage", url="http://example.com", interval_seconds=60
            ),
        ]
        config = SyntheticChecksConfig(checks=checks)

        mock_thread = MagicMock()

        with (
            patch("src.main_synthetic._load_checks_config", return_value=config),
            patch("src.main_synthetic._stop_event") as mock_event,
            patch(
                "src.main_synthetic.threading.Thread", return_value=mock_thread
            ) as mock_thread_cls,
        ):
            mock_event.wait.return_value = None

            from src.main_synthetic import main

            main()

        thread_name = mock_thread_cls.call_args.kwargs["name"]
        assert "homepage" in thread_name

    def test_blocks_on_stop_event(self):
        checks = [
            SiteHealthCheckConfig(
                name="api", url="http://api.example.com", interval_seconds=60
            )
        ]
        config = SyntheticChecksConfig(checks=checks)

        wait_called = []

        with (
            patch("src.main_synthetic._load_checks_config", return_value=config),
            patch("src.main_synthetic._stop_event") as mock_event,
            patch("src.main_synthetic.threading.Thread", return_value=MagicMock()),
        ):
            mock_event.wait.side_effect = lambda: wait_called.append(True)

            from src.main_synthetic import main

            main()

        assert wait_called, "_stop_event.wait() deve ser chamado para bloquear main"

    def test_registers_signal_handlers(self):
        with (
            patch(
                "src.main_synthetic._load_checks_config",
                return_value=SyntheticChecksConfig(checks=[]),
            ),
            patch("src.main_synthetic.signal.signal") as mock_signal,
        ):
            from src.main_synthetic import main

            main()

            registered_signals = [call.args[0] for call in mock_signal.call_args_list]
            assert signal.SIGTERM in registered_signals
            assert signal.SIGINT in registered_signals


class TestHandleSignal:
    def test_sets_stop_event(self):
        with patch("src.main_synthetic._stop_event") as mock_event:
            from src.main_synthetic import _handle_signal

            _handle_signal(signal.SIGTERM, None)

            mock_event.set.assert_called_once()

    def test_sets_stop_event_on_sigint(self):
        with patch("src.main_synthetic._stop_event") as mock_event:
            from src.main_synthetic import _handle_signal

            _handle_signal(signal.SIGINT, None)

            mock_event.set.assert_called_once()
