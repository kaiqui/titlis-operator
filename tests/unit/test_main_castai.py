import asyncio
import signal
from unittest.mock import AsyncMock, patch

import pytest


class TestMainCastAIMain:
    @pytest.mark.asyncio
    async def test_runs_monitor_loop(self):
        loop_started = []

        async def mock_loop():
            loop_started.append(True)

        with (
            patch("src.main_castai.settings") as mock_settings,
            patch("src.main_castai._monitor_loop", side_effect=mock_loop),
        ):
            mock_settings.castai_cluster_name = "my-cluster"
            mock_settings.castai_monitor_namespace = "castai-agent"
            mock_settings.castai_monitor_interval_seconds = 60

            from src.main_castai import main

            await main()

        assert loop_started, "_monitor_loop deve ser iniciado como task"

    @pytest.mark.asyncio
    async def test_handles_cancelled_error_gracefully(self):
        async def mock_loop():
            raise asyncio.CancelledError()

        with (
            patch("src.main_castai.settings") as mock_settings,
            patch("src.main_castai._monitor_loop", side_effect=mock_loop),
        ):
            mock_settings.castai_cluster_name = "cluster"
            mock_settings.castai_monitor_namespace = "castai-agent"
            mock_settings.castai_monitor_interval_seconds = 60

            from src.main_castai import main

            await main()  # deve capturar CancelledError sem propagar


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_calls_health_check(self):
        call_count = [0]

        async def mock_health_check():
            call_count[0] += 1
            raise asyncio.CancelledError()

        with (
            patch(
                "src.controllers.castai_monitor_controller.run_castai_health_check",
                side_effect=mock_health_check,
            ),
            patch(
                "src.controllers.castai_monitor_controller.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            from src.controllers.castai_monitor_controller import _monitor_loop

            with pytest.raises(asyncio.CancelledError):
                await _monitor_loop()

        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_continues_after_generic_exception(self):
        call_count = [0]

        async def mock_health_check():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient error")
            raise asyncio.CancelledError()

        with (
            patch(
                "src.controllers.castai_monitor_controller.run_castai_health_check",
                side_effect=mock_health_check,
            ),
            patch(
                "src.controllers.castai_monitor_controller.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            from src.controllers.castai_monitor_controller import _monitor_loop

            with pytest.raises(asyncio.CancelledError):
                await _monitor_loop()

        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_reraises_cancelled_error(self):
        async def mock_health_check():
            raise asyncio.CancelledError()

        with (
            patch(
                "src.controllers.castai_monitor_controller.run_castai_health_check",
                side_effect=mock_health_check,
            ),
            patch(
                "src.controllers.castai_monitor_controller.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            from src.controllers.castai_monitor_controller import _monitor_loop

            with pytest.raises(asyncio.CancelledError):
                await _monitor_loop()

    @pytest.mark.asyncio
    async def test_initial_sleep_before_first_check(self):
        sleep_args = []

        async def mock_sleep(n):
            sleep_args.append(n)
            if len(sleep_args) >= 2:
                raise asyncio.CancelledError()

        with (
            patch(
                "src.controllers.castai_monitor_controller.run_castai_health_check",
                AsyncMock(),
            ),
            patch(
                "src.controllers.castai_monitor_controller.asyncio.sleep",
                side_effect=mock_sleep,
            ),
        ):
            from src.controllers.castai_monitor_controller import _monitor_loop

            with pytest.raises(asyncio.CancelledError):
                await _monitor_loop()

        assert sleep_args[0] == 10, "primeiro sleep deve ser o warm-up de 10s"
