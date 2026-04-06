from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestResolvePathFunction:
    def test_simple_key(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        assert _resolve_path({"balance": 1200.0}, "balance") == 1200.0

    def test_nested_key(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        data = {"data": {"account": {"balance": 42.5}}}
        assert _resolve_path(data, "data.account.balance") == 42.5

    def test_missing_key_returns_none(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        assert _resolve_path({"other": 1}, "balance") is None

    def test_non_numeric_returns_none(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        assert _resolve_path({"balance": "not-a-number"}, "balance") is None

    def test_integer_is_coerced_to_float(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        assert _resolve_path({"count": 99}, "count") == 99.0

    def test_intermediate_non_dict_returns_none(self):
        from src.infrastructure.synthetic.json_value_checker import _resolve_path

        assert _resolve_path({"a": "string"}, "a.b") is None


class TestJsonValueChecker:
    @pytest.mark.asyncio
    async def test_returns_value_on_success(self):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"balance": 1200.0}

        with patch(
            "src.infrastructure.synthetic.json_value_checker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            from src.infrastructure.synthetic.json_value_checker import (
                JsonValueChecker,
            )

            checker = JsonValueChecker(
                name="wallet-balance",
                url="https://api.internal/balance",
                timeout_seconds=5.0,
                headers={},
            )
            result = await checker.check(json_path="balance", metric_name="wallet.balance")

        assert result.success is True
        assert result.value == 1200.0
        assert result.metric_name == "wallet.balance"
        assert result.reason == "ok"

    @pytest.mark.asyncio
    async def test_returns_failure_on_non_2xx(self):
        mock_response = MagicMock(status_code=503)

        with patch(
            "src.infrastructure.synthetic.json_value_checker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            from src.infrastructure.synthetic.json_value_checker import (
                JsonValueChecker,
            )

            checker = JsonValueChecker(
                name="wallet-balance",
                url="https://api.internal/balance",
                timeout_seconds=5.0,
                headers={},
            )
            result = await checker.check(json_path="balance", metric_name="wallet.balance")

        assert result.success is False
        assert result.value is None
        assert "503" in result.reason

    @pytest.mark.asyncio
    async def test_returns_failure_when_path_missing(self):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"other_field": 42}

        with patch(
            "src.infrastructure.synthetic.json_value_checker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            from src.infrastructure.synthetic.json_value_checker import (
                JsonValueChecker,
            )

            checker = JsonValueChecker(
                name="wallet-balance",
                url="https://api.internal/balance",
                timeout_seconds=5.0,
                headers={},
            )
            result = await checker.check(json_path="balance", metric_name="wallet.balance")

        assert result.success is False
        assert result.value is None
        assert "balance" in result.reason

    @pytest.mark.asyncio
    async def test_returns_failure_on_timeout(self):
        with patch(
            "src.infrastructure.synthetic.json_value_checker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            from src.infrastructure.synthetic.json_value_checker import (
                JsonValueChecker,
            )

            checker = JsonValueChecker(
                name="wallet-balance",
                url="https://api.internal/balance",
                timeout_seconds=1.0,
                headers={},
            )
            result = await checker.check(json_path="balance", metric_name="wallet.balance")

        assert result.success is False
        assert result.reason == "timeout"

    @pytest.mark.asyncio
    async def test_nested_path(self):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"data": {"account": {"balance": 99.9}}}

        with patch(
            "src.infrastructure.synthetic.json_value_checker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_http

            from src.infrastructure.synthetic.json_value_checker import (
                JsonValueChecker,
            )

            checker = JsonValueChecker(
                name="nested-check",
                url="https://api.internal/status",
                timeout_seconds=5.0,
                headers={"X-Custom": "header"},
            )
            result = await checker.check(
                json_path="data.account.balance",
                metric_name="account.balance",
            )

        assert result.success is True
        assert result.value == 99.9


class TestCheckConfig:
    def test_site_health_defaults(self):
        from src.infrastructure.synthetic.check_config import SiteHealthCheckConfig

        c = SiteHealthCheckConfig(name="my-site", url="https://example.com")
        assert c.type == "site_health"
        assert c.interval_seconds == 60
        assert c.tags == {}

    def test_json_value_requires_json_path_and_metric_name(self):
        from src.infrastructure.synthetic.check_config import JsonValueCheckConfig

        c = JsonValueCheckConfig(
            name="balance",
            url="https://api/balance",
            json_path="balance",
            metric_name="wallet.balance",
        )
        assert c.type == "json_value"
        assert c.json_path == "balance"
        assert c.metric_name == "wallet.balance"

    def test_synthetic_checks_config_parses_discriminated_union(self):
        from src.infrastructure.synthetic.check_config import SyntheticChecksConfig

        raw = {
            "checks": [
                {"type": "site_health", "name": "homepage", "url": "https://x.com"},
                {
                    "type": "json_value",
                    "name": "balance",
                    "url": "https://api/b",
                    "json_path": "balance",
                    "metric_name": "wallet.balance",
                },
            ]
        }
        config = SyntheticChecksConfig.model_validate(raw)
        assert len(config.checks) == 2
        assert config.checks[0].type == "site_health"
        assert config.checks[1].type == "json_value"
