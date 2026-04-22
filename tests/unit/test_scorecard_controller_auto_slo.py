import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from tests.mock_kopf import MockKopf

sys.modules["kopf"] = MockKopf()


def _make_deployment_body(
    name="my-app",
    namespace="default",
    uid="uid-abc-123",
    dd_service="my-api",
    dd_env="production",
    include_dd_labels=True,
):
    pod_labels = {}
    if include_dd_labels:
        pod_labels = {
            "tags.datadoghq.com/service": dd_service,
            "tags.datadoghq.com/env": dd_env,
            "tags.datadoghq.com/version": "1.0.0",
            "admission.datadoghq.com/enabled": "true",
        }
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "uid": uid,
            "resourceVersion": "rv-001",
        },
        "spec": {
            "template": {
                "metadata": {
                    "labels": pod_labels,
                }
            }
        },
    }


def _make_scorecard_with_ops001(passed: bool):
    from src.domain.models import (
        ResourceScorecard,
        ValidationPillar,
        PillarScore,
        ValidationResult,
        ValidationSeverity,
        ValidationRuleType,
    )

    result = ValidationResult(
        rule_id="OPS-001",
        rule_name="Datadog instrumentation",
        pillar=ValidationPillar.OPERATIONAL,
        passed=passed,
        severity=ValidationSeverity.ERROR,
        weight=1.0,
        message="ok" if passed else "missing labels",
    )
    pillar_score = PillarScore(
        pillar=ValidationPillar.OPERATIONAL,
        score=100.0 if passed else 0.0,
        max_score=100.0,
        passed_checks=1 if passed else 0,
        total_checks=1,
        weighted_score=1.0 if passed else 0.0,
        validation_results=[result],
    )
    scorecard = ResourceScorecard(
        resource_name="my-app",
        resource_namespace="default",
        resource_kind="Deployment",
        overall_score=100.0 if passed else 50.0,
    )
    scorecard.pillar_scores[ValidationPillar.OPERATIONAL] = pillar_score
    return scorecard


class TestExtractDdLabels:
    def test_extracts_service_and_env(self):
        from src.controllers.scorecard_controller import ScorecardController

        body = _make_deployment_body()
        result = ScorecardController._extract_dd_labels(body)
        assert result == ("my-api", "production")

    def test_returns_none_when_labels_missing(self):
        from src.controllers.scorecard_controller import ScorecardController

        body = _make_deployment_body(include_dd_labels=False)
        result = ScorecardController._extract_dd_labels(body)
        assert result is None

    def test_returns_none_when_only_service_present(self):
        from src.controllers.scorecard_controller import ScorecardController

        body = _make_deployment_body()
        body["spec"]["template"]["metadata"]["labels"] = {
            "tags.datadoghq.com/service": "my-api"
        }
        result = ScorecardController._extract_dd_labels(body)
        assert result is None

    def test_returns_none_when_only_env_present(self):
        from src.controllers.scorecard_controller import ScorecardController

        body = _make_deployment_body()
        body["spec"]["template"]["metadata"]["labels"] = {
            "tags.datadoghq.com/env": "production"
        }
        result = ScorecardController._extract_dd_labels(body)
        assert result is None


class TestOps001Passed:
    def test_returns_true_when_ops001_passed(self):
        from src.controllers.scorecard_controller import ScorecardController

        scorecard = _make_scorecard_with_ops001(passed=True)
        assert ScorecardController._ops001_passed(scorecard) is True

    def test_returns_false_when_ops001_failed(self):
        from src.controllers.scorecard_controller import ScorecardController

        scorecard = _make_scorecard_with_ops001(passed=False)
        assert ScorecardController._ops001_passed(scorecard) is False

    def test_returns_false_when_operational_pillar_missing(self):
        from src.controllers.scorecard_controller import ScorecardController
        from src.domain.models import ResourceScorecard

        scorecard = ResourceScorecard(
            resource_name="app",
            resource_namespace="ns",
            resource_kind="Deployment",
        )
        assert ScorecardController._ops001_passed(scorecard) is False

    def test_returns_false_when_ops001_rule_not_in_results(self):
        from src.controllers.scorecard_controller import ScorecardController
        from src.domain.models import (
            ResourceScorecard,
            ValidationPillar,
            PillarScore,
            ValidationResult,
            ValidationSeverity,
        )

        other_result = ValidationResult(
            rule_id="OPS-002",
            rule_name="Other rule",
            pillar=ValidationPillar.OPERATIONAL,
            passed=True,
            severity=ValidationSeverity.INFO,
            weight=1.0,
            message="ok",
        )
        pillar_score = PillarScore(
            pillar=ValidationPillar.OPERATIONAL,
            score=100.0,
            max_score=100.0,
            passed_checks=1,
            total_checks=1,
            weighted_score=1.0,
            validation_results=[other_result],
        )
        scorecard = ResourceScorecard(
            resource_name="app",
            resource_namespace="ns",
            resource_kind="Deployment",
        )
        scorecard.pillar_scores[ValidationPillar.OPERATIONAL] = pillar_score
        assert ScorecardController._ops001_passed(scorecard) is False


class TestFindSloConfigBySourceUid:
    def _make_controller(self):
        with (
            patch("src.controllers.base.get_status_writer") as mw,
            patch("src.controllers.base.get_slack_service") as ms,
            patch("src.controllers.scorecard_controller.get_scorecard_service") as msc,
            patch(
                "src.controllers.scorecard_controller.get_appscorecard_writer"
            ) as maw,
        ):
            mw.return_value = Mock()
            ms.return_value = None
            msc.return_value = Mock()
            maw.return_value = None
            from src.controllers.scorecard_controller import ScorecardController

            return ScorecardController()

    def test_returns_none_when_no_sloconfig_exists(self):
        ctrl = self._make_controller()
        mock_custom = Mock()
        mock_custom.list_namespaced_custom_object.return_value = {"items": []}

        with patch(
            "src.controllers.scorecard_controller.get_k8s_apis",
            return_value=(Mock(), Mock(), mock_custom),
        ):
            result = ctrl._find_sloconfig_by_source_uid("uid-123", "default")

        assert result is None
        mock_custom.list_namespaced_custom_object.assert_called_once_with(
            group="titlis.io",
            version="v1",
            namespace="default",
            plural="sloconfigs",
            label_selector="titlis.io/source-uid=uid-123",
        )

    def test_returns_first_item_when_sloconfig_exists(self):
        ctrl = self._make_controller()
        existing = {"metadata": {"name": "auto-my-api"}}
        mock_custom = Mock()
        mock_custom.list_namespaced_custom_object.return_value = {"items": [existing]}

        with patch(
            "src.controllers.scorecard_controller.get_k8s_apis",
            return_value=(Mock(), Mock(), mock_custom),
        ):
            result = ctrl._find_sloconfig_by_source_uid("uid-123", "default")

        assert result == existing

    def test_returns_none_on_k8s_exception(self):
        ctrl = self._make_controller()

        with patch(
            "src.controllers.scorecard_controller.get_k8s_apis",
            side_effect=Exception("k8s unavailable"),
        ):
            result = ctrl._find_sloconfig_by_source_uid("uid-123", "default")

        assert result is None


class TestMaybeAutoCreateSlo:
    def _make_controller(self):
        with (
            patch("src.controllers.base.get_status_writer") as mw,
            patch("src.controllers.base.get_slack_service") as ms,
            patch("src.controllers.scorecard_controller.get_scorecard_service") as msc,
            patch(
                "src.controllers.scorecard_controller.get_appscorecard_writer"
            ) as maw,
        ):
            mw.return_value = Mock()
            ms.return_value = None
            msc.return_value = Mock()
            maw.return_value = None
            from src.controllers.scorecard_controller import ScorecardController

            return ScorecardController()

    @pytest.mark.asyncio
    async def test_touches_existing_sloconfig_on_deployment_update(self):
        ctrl = self._make_controller()
        body = _make_deployment_body()
        existing = {"metadata": {"name": "auto-my-api", "annotations": {}}}

        with (
            patch.object(
                ctrl, "_find_sloconfig_by_source_uid", return_value=existing
            ) as mock_find,
            patch.object(ctrl, "_apply_sloconfig") as mock_apply,
            patch.object(ctrl, "_touch_sloconfig") as mock_touch,
        ):
            await ctrl._maybe_auto_create_slo(body, "default", "my-api", "production")

        mock_find.assert_called_once_with("uid-abc-123", "default")
        mock_apply.assert_not_called()
        mock_touch.assert_called_once_with(existing, "default", "rv-001")

    @pytest.mark.asyncio
    async def test_creates_sloconfig_when_none_exists(self):
        ctrl = self._make_controller()
        body = _make_deployment_body()

        with (
            patch.object(ctrl, "_find_sloconfig_by_source_uid", return_value=None),
            patch.object(ctrl, "_apply_sloconfig", return_value=True) as mock_apply,
        ):
            await ctrl._maybe_auto_create_slo(body, "default", "my-api", "production")

        mock_apply.assert_called_once()
        call_body = mock_apply.call_args[0][0]
        assert call_body["metadata"]["name"] == "auto-my-api"
        assert call_body["metadata"]["labels"]["titlis.io/auto-created"] == "true"
        assert call_body["metadata"]["labels"]["titlis.io/source-uid"] == "uid-abc-123"
        assert call_body["metadata"]["labels"]["titlis.io/dd-env"] == "production"
        assert call_body["spec"]["service"] == "my-api"
        assert "env:production" in call_body["spec"]["tags"]

    @pytest.mark.asyncio
    async def test_sloconfig_body_has_correct_defaults(self):
        ctrl = self._make_controller()
        body = _make_deployment_body(dd_env="staging")

        captured = {}

        def capture_apply(body_arg, ns_arg):
            captured["body"] = body_arg
            return True

        with (
            patch.object(ctrl, "_find_sloconfig_by_source_uid", return_value=None),
            patch.object(ctrl, "_apply_sloconfig", side_effect=capture_apply),
        ):
            await ctrl._maybe_auto_create_slo(body, "default", "my-api", "staging")

        spec = captured["body"]["spec"]
        assert spec["auto_detect_framework"] is True
        assert spec["target"] == 99.0
        assert spec["warning"] == 99.5
        assert spec["timeframe"] == "30d"
        assert "env:staging" in spec["tags"]
        assert "managed_by:titlis_operator" in spec["tags"]

    @pytest.mark.asyncio
    async def test_skips_when_deployment_uid_missing(self):
        ctrl = self._make_controller()
        body = {"metadata": {"name": "app", "namespace": "default"}}

        with (
            patch.object(ctrl, "_find_sloconfig_by_source_uid") as mock_find,
            patch.object(ctrl, "_apply_sloconfig") as mock_apply,
        ):
            await ctrl._maybe_auto_create_slo(body, "default", "my-api", "production")

        mock_find.assert_not_called()
        mock_apply.assert_not_called()

    def test_apply_sloconfig_calls_k8s_create(self):
        ctrl = self._make_controller()
        mock_custom = Mock()
        mock_custom.create_namespaced_custom_object.return_value = {}
        body = {"metadata": {"name": "auto-my-api", "namespace": "default"}, "spec": {}}

        with patch(
            "src.controllers.scorecard_controller.get_k8s_apis",
            return_value=(Mock(), Mock(), mock_custom),
        ):
            result = ctrl._apply_sloconfig(body, "default")

        assert result is True
        mock_custom.create_namespaced_custom_object.assert_called_once_with(
            group="titlis.io",
            version="v1",
            namespace="default",
            plural="sloconfigs",
            body=body,
        )

    def test_apply_sloconfig_returns_false_on_exception(self):
        ctrl = self._make_controller()
        body = {"metadata": {"name": "auto-my-api"}, "spec": {}}

        with patch(
            "src.controllers.scorecard_controller.get_k8s_apis",
            side_effect=Exception("k8s error"),
        ):
            result = ctrl._apply_sloconfig(body, "default")

        assert result is False
