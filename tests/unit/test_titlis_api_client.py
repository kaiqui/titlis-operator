import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.infrastructure.titlis_api.udp_client import TitlisApiUdpClient


@pytest.mark.asyncio
async def test_send_always_includes_api_key_in_envelope():
    client = TitlisApiUdpClient(
        host="localhost",
        udp_port=8125,
        http_base_url="http://localhost:8080",
        api_key="tls_k_abc123def456789012345678901234567890ab",
    )

    captured = {}

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.raise_for_status = MagicMock()
        mock_session = AsyncMock()
        mock_session.post.return_value = mock_resp

        def capture_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            captured["headers"] = kwargs.get("headers", {})
            return mock_resp

        mock_session.post = AsyncMock(side_effect=capture_post)
        mock_client.return_value.__aenter__.return_value = mock_session

        await client.send_scorecard_evaluated({"namespace": "prod", "workload": "api"})

    assert captured["url"].endswith("/v1/operator/events")
    envelope = captured["json"]
    assert envelope["v"] == 1
    assert envelope["t"] == "scorecard_evaluated"
    assert envelope["api_key"] == "tls_k_abc123def456789012345678901234567890ab"
    assert "tenant_id" not in envelope
    assert "ts" in envelope
    assert (
        captured["headers"]["X-Api-Key"]
        == "tls_k_abc123def456789012345678901234567890ab"
    )


@pytest.mark.asyncio
async def test_get_remediation_returns_none_on_404():
    client = TitlisApiUdpClient(
        host="localhost",
        udp_port=8125,
        http_base_url="http://localhost:8080",
        api_key="tls_k_abc123def456789012345678901234567890ab",
    )
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session = AsyncMock()
        mock_session.get.return_value = mock_resp
        mock_client.return_value.__aenter__.return_value = mock_session
        result = await client.get_remediation("some-uuid")
        assert result is None
