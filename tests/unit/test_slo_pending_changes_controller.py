import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

from tests.mock_kopf import MockKopf

sys.modules["kopf"] = MockKopf()


def _make_pending_change(
    change_id="change-uuid-001",
    slo_config_name="auto-my-api",
    namespace="default",
    field="target",
    old_value="99.9",
    new_value="99.5",
    requested_by="titlis-ai",
):
    from src.application.ports.titlis_api_port import SLOPendingChange

    return SLOPendingChange(
        id=change_id,
        slo_config_name=slo_config_name,
        namespace=namespace,
        field=field,
        old_value=old_value,
        new_value=new_value,
        requested_by=requested_by,
    )


class TestCoerceFieldValue:
    def test_target_coerced_to_float(self):
        from src.controllers.slo_pending_changes_controller import _coerce_field_value

        assert _coerce_field_value("target", "99.5") == 99.5
        assert isinstance(_coerce_field_value("target", "99.5"), float)

    def test_warning_coerced_to_float(self):
        from src.controllers.slo_pending_changes_controller import _coerce_field_value

        assert _coerce_field_value("warning", "99.0") == 99.0
        assert isinstance(_coerce_field_value("warning", "99.0"), float)

    def test_timeframe_kept_as_string(self):
        from src.controllers.slo_pending_changes_controller import _coerce_field_value

        assert _coerce_field_value("timeframe", "7d") == "7d"
        assert isinstance(_coerce_field_value("timeframe", "7d"), str)


class TestApplyPendingChanges:
    @pytest.mark.asyncio
    async def test_does_nothing_when_no_pending_changes(self):
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=[])

        with patch(
            "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
            return_value=mock_client,
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        mock_client.get_pending_slo_changes.assert_called_once()
        mock_client.confirm_slo_change_applied.assert_not_called()
        mock_client.confirm_slo_change_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_nothing_when_titlis_client_is_none(self):
        with patch(
            "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
            return_value=None,
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

    @pytest.mark.asyncio
    async def test_applies_single_change_successfully(self):
        change = _make_pending_change(field="target", new_value="99.5")
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=[change])
        mock_client.confirm_slo_change_applied = AsyncMock(return_value=True)

        mock_custom = Mock()
        mock_custom.patch_namespaced_custom_object.return_value = {}

        with (
            patch(
                "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
                return_value=mock_client,
            ),
            patch(
                "src.controllers.slo_pending_changes_controller.get_k8s_apis",
                return_value=(Mock(), Mock(), mock_custom),
            ),
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        mock_custom.patch_namespaced_custom_object.assert_called_once_with(
            group="titlis.io",
            version="v1",
            namespace="default",
            plural="sloconfigs",
            name="auto-my-api",
            body={"spec": {"target": 99.5}},
        )
        mock_client.confirm_slo_change_applied.assert_called_once_with(
            "change-uuid-001"
        )
        mock_client.confirm_slo_change_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_applies_timeframe_change_as_string(self):
        change = _make_pending_change(
            change_id="c-002",
            slo_config_name="auto-checkout",
            namespace="payments",
            field="timeframe",
            old_value="30d",
            new_value="7d",
        )
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=[change])
        mock_client.confirm_slo_change_applied = AsyncMock(return_value=True)

        mock_custom = Mock()
        mock_custom.patch_namespaced_custom_object.return_value = {}

        with (
            patch(
                "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
                return_value=mock_client,
            ),
            patch(
                "src.controllers.slo_pending_changes_controller.get_k8s_apis",
                return_value=(Mock(), Mock(), mock_custom),
            ),
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        call_body = mock_custom.patch_namespaced_custom_object.call_args[1]["body"]
        assert call_body == {"spec": {"timeframe": "7d"}}

    @pytest.mark.asyncio
    async def test_reports_failure_when_k8s_patch_raises(self):
        change = _make_pending_change()
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=[change])
        mock_client.confirm_slo_change_failed = AsyncMock(return_value=True)

        with (
            patch(
                "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
                return_value=mock_client,
            ),
            patch(
                "src.controllers.slo_pending_changes_controller.get_k8s_apis",
                side_effect=Exception("CRD not found"),
            ),
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        mock_client.confirm_slo_change_applied.assert_not_called()
        mock_client.confirm_slo_change_failed.assert_called_once_with(
            "change-uuid-001", "CRD not found"
        )

    @pytest.mark.asyncio
    async def test_applies_multiple_changes_independently(self):
        changes = [
            _make_pending_change(
                change_id="c-1",
                slo_config_name="svc-a",
                field="target",
                new_value="99.0",
            ),
            _make_pending_change(
                change_id="c-2",
                slo_config_name="svc-b",
                field="warning",
                new_value="98.5",
            ),
        ]
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=changes)
        mock_client.confirm_slo_change_applied = AsyncMock(return_value=True)

        mock_custom = Mock()
        mock_custom.patch_namespaced_custom_object.return_value = {}

        with (
            patch(
                "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
                return_value=mock_client,
            ),
            patch(
                "src.controllers.slo_pending_changes_controller.get_k8s_apis",
                return_value=(Mock(), Mock(), mock_custom),
            ),
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        assert mock_custom.patch_namespaced_custom_object.call_count == 2
        assert mock_client.confirm_slo_change_applied.call_count == 2
        applied_ids = {
            c[0][0] for c in mock_client.confirm_slo_change_applied.call_args_list
        }
        assert applied_ids == {"c-1", "c-2"}

    @pytest.mark.asyncio
    async def test_first_change_failure_does_not_block_second(self):
        changes = [
            _make_pending_change(change_id="c-fail", slo_config_name="svc-bad"),
            _make_pending_change(change_id="c-ok", slo_config_name="svc-good"),
        ]
        mock_client = AsyncMock()
        mock_client.get_pending_slo_changes = AsyncMock(return_value=changes)
        mock_client.confirm_slo_change_applied = AsyncMock(return_value=True)
        mock_client.confirm_slo_change_failed = AsyncMock(return_value=True)

        mock_custom = Mock()

        def patch_side_effect(**kwargs):
            if kwargs["name"] == "svc-bad":
                raise Exception("not found")
            return {}

        mock_custom.patch_namespaced_custom_object.side_effect = patch_side_effect

        with (
            patch(
                "src.controllers.slo_pending_changes_controller.get_titlis_api_client",
                return_value=mock_client,
            ),
            patch(
                "src.controllers.slo_pending_changes_controller.get_k8s_apis",
                return_value=(Mock(), Mock(), mock_custom),
            ),
        ):
            from src.controllers.slo_pending_changes_controller import (
                apply_pending_slo_changes,
            )

            await apply_pending_slo_changes()

        mock_client.confirm_slo_change_failed.assert_called_once_with(
            "c-fail", "not found"
        )
        mock_client.confirm_slo_change_applied.assert_called_once_with("c-ok")


class TestPendingChangesStartup:
    @pytest.mark.asyncio
    async def test_skips_when_titlis_api_is_disabled(self):
        from src.controllers import slo_pending_changes_controller as controller

        with (
            patch.object(controller.settings.titlis_api, "enabled", False),
            patch.object(controller.settings, "enable_slo_controller", True),
            patch(
                "src.controllers.slo_pending_changes_controller.asyncio.create_task"
            ) as create_task,
        ):
            await controller.slo_pending_changes_startup()

        create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_slo_controller_is_disabled(self):
        from src.controllers import slo_pending_changes_controller as controller

        with (
            patch.object(controller.settings.titlis_api, "enabled", True),
            patch.object(controller.settings, "enable_slo_controller", False),
            patch(
                "src.controllers.slo_pending_changes_controller.asyncio.create_task"
            ) as create_task,
        ):
            await controller.slo_pending_changes_startup()

        create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_starts_loop_when_both_flags_are_enabled(self):
        from src.controllers import slo_pending_changes_controller as controller

        def _close_task(coro, name=None):
            coro.close()
            return Mock()

        with (
            patch.object(controller.settings.titlis_api, "enabled", True),
            patch.object(controller.settings, "enable_slo_controller", True),
            patch(
                "src.controllers.slo_pending_changes_controller.asyncio.create_task",
                side_effect=_close_task,
            ) as create_task,
        ):
            await controller.slo_pending_changes_startup()

        create_task.assert_called_once()


class TestPendingChangesApi:
    @pytest.mark.asyncio
    async def test_get_pending_slo_changes_parses_response(self):
        from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient
        import httpx

        client = TitlisApiUdpClient(
            host="localhost",
            udp_port=8125,
            http_base_url="http://localhost:8080",
            api_key="tls_k_test",
        )
        payload = [
            {
                "id": "uuid-1",
                "slo_config_name": "auto-svc",
                "namespace": "prod",
                "field": "target",
                "old_value": "99.9",
                "new_value": "99.5",
                "requested_by": "titlis-ai",
            }
        ]
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload
        mock_response.raise_for_status = Mock()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.get_pending_slo_changes()

        assert len(result) == 1
        assert result[0].id == "uuid-1"
        assert result[0].slo_config_name == "auto-svc"
        assert result[0].field == "target"
        assert result[0].new_value == "99.5"

    @pytest.mark.asyncio
    async def test_get_pending_slo_changes_returns_empty_on_404(self):
        from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient

        client = TitlisApiUdpClient(
            host="localhost",
            udp_port=8125,
            http_base_url="http://localhost:8080",
            api_key="tls_k_test",
        )
        mock_response = Mock()
        mock_response.status_code = 404

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.get_pending_slo_changes()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_slo_changes_returns_empty_on_exception(self):
        from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient

        client = TitlisApiUdpClient(
            host="localhost",
            udp_port=8125,
            http_base_url="http://localhost:8080",
            api_key="tls_k_test",
        )

        with patch("httpx.AsyncClient", side_effect=Exception("network error")):
            result = await client.get_pending_slo_changes()

        assert result == []

    @pytest.mark.asyncio
    async def test_confirm_slo_change_applied_success(self):
        from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient

        client = TitlisApiUdpClient(
            host="localhost",
            udp_port=8125,
            http_base_url="http://localhost:8080",
            api_key="tls_k_test",
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.confirm_slo_change_applied("uuid-1")

        assert result is True
        mock_http_client.post.assert_called_once()
        url = mock_http_client.post.call_args[0][0]
        assert "uuid-1/applied" in url

    @pytest.mark.asyncio
    async def test_confirm_slo_change_failed_sends_error_body(self):
        from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient

        client = TitlisApiUdpClient(
            host="localhost",
            udp_port=8125,
            http_base_url="http://localhost:8080",
            api_key="tls_k_test",
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result = await client.confirm_slo_change_failed("uuid-2", "CRD not found")

        assert result is True
        call_kwargs = mock_http_client.post.call_args[1]
        assert call_kwargs["json"] == {"error": "CRD not found"}
        url = mock_http_client.post.call_args[0][0]
        assert "uuid-2/failed" in url
