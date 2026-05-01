from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.infrastructure.synthetic.check_config import (
    JsonValueCheckConfig,
    SiteHealthCheckConfig,
    SyntheticChecksConfig,
)


class TestSyntheticSiteHealthChecker:
    def test_check_returns_healthy_on_http_200(self):
        mock_response = MagicMock(status_code=200)

        with patch(
            "src.infrastructure.synthetic.site_health.httpx.Client"
        ) as mock_client_cls:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http
            mock_client_cls.return_value.__exit__.return_value = False

            from src.infrastructure.synthetic.site_health import (
                SyntheticSiteHealthChecker,
            )

            checker = SyntheticSiteHealthChecker(
                monitor_name="jeitto-homepage",
                target_url="https://jeitto.com.br",
                timeout_seconds=5.0,
            )

            result = checker.check()

            assert result.is_healthy is True
            assert result.status_code == 200
            assert result.target_host == "jeitto.com.br"
            assert result.reason == "HTTP 200"

    def test_check_returns_unhealthy_on_timeout(self):
        with patch(
            "src.infrastructure.synthetic.site_health.httpx.Client"
        ) as mock_client_cls:
            mock_http = MagicMock()
            mock_http.get.side_effect = httpx.TimeoutException("timeout")
            mock_client_cls.return_value.__enter__.return_value = mock_http
            mock_client_cls.return_value.__exit__.return_value = False

            from src.infrastructure.synthetic.site_health import (
                SyntheticSiteHealthChecker,
            )

            checker = SyntheticSiteHealthChecker(
                monitor_name="jeitto-homepage",
                target_url="https://jeitto.com.br",
                timeout_seconds=1.0,
            )

            result = checker.check()

            assert result.is_healthy is False
            assert result.status_code is None
            assert result.reason == "timeout"


class TestSyntheticSiteMetricsManager:
    @patch("src.infrastructure.datadog.managers.synthetic_metrics.ApiClient")
    @patch("src.infrastructure.datadog.managers.synthetic_metrics.MetricsApi")
    def test_send_check_result_submits_health_and_latency(
        self, mock_metrics_api_cls, mock_api_client_cls
    ):
        mock_api = MagicMock()
        mock_metrics_api_cls.return_value = mock_api
        mock_api_client_cls.return_value.__enter__ = lambda s: MagicMock()
        mock_api_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        from src.infrastructure.datadog.managers.synthetic_metrics import (
            SyntheticSiteMetricsManager,
        )

        manager = SyntheticSiteMetricsManager(
            api_key="fake-key", app_key=None, site="datadoghq.com"
        )

        result = manager.send_check_result(
            {
                "monitor_name": "jeitto-homepage",
                "target_url": "https://jeitto.com.br",
                "target_host": "jeitto.com.br",
                "is_healthy": True,
                "response_time_ms": 123.45,
                "status_code": 200,
                "reason": "HTTP 200",
                "checked_at": 1234567890,
            }
        )

        assert result is True
        mock_api.submit_metrics.assert_called_once()
        payload = mock_api.submit_metrics.call_args.kwargs["body"]
        assert len(payload.series) == 2
        assert payload.series[0].metric == manager.HEALTH_METRIC_NAME
        assert payload.series[1].metric == manager.LATENCY_METRIC_NAME


class TestRunSiteHealthCheck:
    def _make_check(self, **kwargs) -> SiteHealthCheckConfig:
        return SiteHealthCheckConfig(
            name="my-api",
            url="https://api.example.com/health",
            interval_seconds=60,
            **kwargs,
        )

    def test_sends_metrics_on_healthy_result(self):
        check = self._make_check()
        mock_result = MagicMock(
            is_healthy=True,
            status_code=200,
            response_time_ms=45.0,
        )
        mock_result.to_dict.return_value = {"is_healthy": True}

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteHealthChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteMetricsManager"
            ) as mock_manager_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = "fake-key"
            mock_settings.datadog_app_key = None
            mock_settings.datadog_site = "datadoghq.com"
            mock_checker_cls.return_value.check.return_value = mock_result
            mock_manager = MagicMock()
            mock_manager_cls.return_value = mock_manager

            from src.controllers.synthetic_monitor_controller import (
                _run_site_health_check,
            )

            _run_site_health_check(check)

            mock_manager.send_check_result.assert_called_once()

    def test_skips_metrics_when_no_api_key(self):
        check = self._make_check()
        mock_result = MagicMock(is_healthy=False, status_code=503)
        mock_result.to_dict.return_value = {}

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteHealthChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteMetricsManager"
            ) as mock_manager_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = None
            mock_checker_cls.return_value.check.return_value = mock_result

            from src.controllers.synthetic_monitor_controller import (
                _run_site_health_check,
            )

            _run_site_health_check(check)

            mock_manager_cls.assert_not_called()

    def test_logs_exception_on_datadog_send_failure(self):
        check = self._make_check()
        mock_result = MagicMock(is_healthy=True, status_code=200, response_time_ms=10.0)
        mock_result.to_dict.return_value = {}

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteHealthChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.SyntheticSiteMetricsManager"
            ) as mock_manager_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = "fake-key"
            mock_settings.datadog_app_key = None
            mock_settings.datadog_site = "datadoghq.com"
            mock_checker_cls.return_value.check.return_value = mock_result
            mock_manager_cls.return_value.send_check_result.side_effect = RuntimeError(
                "network error"
            )

            from src.controllers.synthetic_monitor_controller import (
                _run_site_health_check,
            )

            _run_site_health_check(check)  # deve logar e não propagar


class TestRunJsonValueCheck:
    def _make_check(self, **kwargs) -> JsonValueCheckConfig:
        return JsonValueCheckConfig(
            name="saldo",
            url="https://api.carteira.internal/v1/balance",
            interval_seconds=120,
            json_path="balance",
            metric_name="carteira.saldo",
            **kwargs,
        )

    def test_sends_gauge_on_successful_check(self):
        check = self._make_check()
        mock_result = MagicMock(success=True, value=1200.0, reason="ok", checked_at=0)

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.JsonValueChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.GaugeMetricSender"
            ) as mock_sender_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = "fake-key"
            mock_settings.datadog_app_key = None
            mock_settings.datadog_site = "datadoghq.com"
            mock_checker_cls.return_value.check.return_value = mock_result
            mock_sender = MagicMock()
            mock_sender_cls.return_value = mock_sender

            from src.controllers.synthetic_monitor_controller import (
                _run_json_value_check,
            )

            _run_json_value_check(check)

            mock_sender.send.assert_called_once()
            call_kwargs = mock_sender.send.call_args.kwargs
            assert call_kwargs["metric_name"] == "carteira.saldo"
            assert call_kwargs["value"] == 1200.0

    def test_skips_gauge_when_no_api_key(self):
        check = self._make_check()
        mock_result = MagicMock(success=True, value=42.0)

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.JsonValueChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.GaugeMetricSender"
            ) as mock_sender_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = None
            mock_checker_cls.return_value.check.return_value = mock_result

            from src.controllers.synthetic_monitor_controller import (
                _run_json_value_check,
            )

            _run_json_value_check(check)

            mock_sender_cls.assert_not_called()

    def test_skips_gauge_when_check_fails(self):
        check = self._make_check()
        mock_result = MagicMock(success=False, value=None, reason="HTTP 500")

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.JsonValueChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.GaugeMetricSender"
            ) as mock_sender_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = "fake-key"
            mock_settings.datadog_app_key = None
            mock_settings.datadog_site = "datadoghq.com"
            mock_checker_cls.return_value.check.return_value = mock_result

            from src.controllers.synthetic_monitor_controller import (
                _run_json_value_check,
            )

            _run_json_value_check(check)

            mock_sender_cls.assert_not_called()

    def test_skips_gauge_when_value_is_none(self):
        check = self._make_check()
        mock_result = MagicMock(success=True, value=None, reason="path not found")

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.JsonValueChecker"
            ) as mock_checker_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.GaugeMetricSender"
            ) as mock_sender_cls,
            patch(
                "src.controllers.synthetic_monitor_controller.settings"
            ) as mock_settings,
        ):
            mock_settings.datadog_api_key = "fake-key"
            mock_settings.datadog_app_key = None
            mock_settings.datadog_site = "datadoghq.com"
            mock_checker_cls.return_value.check.return_value = mock_result

            from src.controllers.synthetic_monitor_controller import (
                _run_json_value_check,
            )

            _run_json_value_check(check)

            mock_sender_cls.assert_not_called()


class TestCheckLoop:
    def test_dispatches_site_health_check(self):
        check = SiteHealthCheckConfig(
            name="test", url="http://example.com", interval_seconds=60
        )

        sleep_calls = [0]

        def mock_sleep(n):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 2:
                raise SystemExit(0)

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.time.sleep",
                side_effect=mock_sleep,
            ),
            patch(
                "src.controllers.synthetic_monitor_controller._run_site_health_check"
            ) as mock_run,
        ):
            from src.controllers.synthetic_monitor_controller import _check_loop

            with pytest.raises(SystemExit):
                _check_loop(check)

            mock_run.assert_called_once_with(check)

    def test_dispatches_json_value_check(self):
        check = JsonValueCheckConfig(
            name="gauge",
            url="http://example.com/data",
            interval_seconds=120,
            json_path="value",
            metric_name="my.metric",
        )

        sleep_calls = [0]

        def mock_sleep(n):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 2:
                raise SystemExit(0)

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.time.sleep",
                side_effect=mock_sleep,
            ),
            patch(
                "src.controllers.synthetic_monitor_controller._run_json_value_check"
            ) as mock_run,
        ):
            from src.controllers.synthetic_monitor_controller import _check_loop

            with pytest.raises(SystemExit):
                _check_loop(check)

            mock_run.assert_called_once_with(check)

    def test_continues_after_exception(self):
        check = SiteHealthCheckConfig(
            name="test", url="http://example.com", interval_seconds=60
        )

        run_calls = [0]

        def mock_run(c):
            run_calls[0] += 1
            raise ValueError("check failed")

        sleep_calls = [0]

        def mock_sleep(n):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 3:
                raise SystemExit(0)

        with (
            patch(
                "src.controllers.synthetic_monitor_controller.time.sleep",
                side_effect=mock_sleep,
            ),
            patch(
                "src.controllers.synthetic_monitor_controller._run_site_health_check",
                side_effect=mock_run,
            ),
        ):
            from src.controllers.synthetic_monitor_controller import _check_loop

            with pytest.raises(SystemExit):
                _check_loop(check)

        assert run_calls[0] == 2
