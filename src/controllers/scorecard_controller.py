import asyncio
import os
import kopf
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from src.controllers.base import BaseController
from src.bootstrap.dependencies import (
    get_scorecard_service,
    get_appscorecard_writer,
    get_titlis_api_client,
)
from src.domain.slack_models import NotificationChannel, NotificationSeverity
from src.domain.models import ResourceScorecard
from src.application.services.namespace_notification_buffer import (
    NamespaceNotificationBuffer,
)
from src.settings import settings
from src.infrastructure.kubernetes.client import get_k8s_apis


class ScorecardController(BaseController):
    def __init__(self) -> None:
        super().__init__("scorecard")
        self.scorecard_service = get_scorecard_service()
        self.appscorecard_writer = get_appscorecard_writer()
        self._notification_buffer = NamespaceNotificationBuffer(
            digest_interval_minutes=15
        )
        self.logger.info(
            "ScorecardController inicializado",
            extra={
                "scorecard_service_available": self.scorecard_service is not None,
                "slack_service_available": self.slack_service is not None,
                "appscorecard_writer_available": self.appscorecard_writer is not None,
            },
        )

    async def on_resource_event(
        self, body: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, Any]:
        ctx = self._get_resource_context(body)
        event_type = kwargs.get("event_type", "unknown")
        namespace = ctx["resource_namespace"]

        if self._is_namespace_excluded(namespace):
            self.logger.debug(
                f"Ignorando Deployment no namespace excluído: {namespace}",
                extra=ctx,
            )
            return {
                "ignored": True,
                "reason": f"Namespace {namespace} está na lista de exclusão",
            }

        self.logger.info(f"Deployment {event_type}", extra=ctx)

        try:
            if not self.scorecard_service:
                return {"evaluated": False, "error": "ScorecardService não disponível"}
            scorecard = self.scorecard_service.evaluate_resource(
                ctx["resource_namespace"],
                ctx["resource_name"],
                ctx["resource_kind"],
            )

            self.logger.info(
                "Scorecard avaliado",
                extra={
                    **ctx,
                    "overall_score": scorecard.overall_score,
                    "critical_issues": scorecard.critical_issues,
                    "error_issues": scorecard.error_issues,
                    "warning_issues": scorecard.warning_issues,
                    "passed_checks": scorecard.passed_checks,
                    "total_checks": scorecard.total_checks,
                },
            )

            if self.appscorecard_writer:
                try:
                    writer = self.appscorecard_writer
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: writer.upsert(
                            scorecard=scorecard,
                            deployment_body=body,
                            remediation_pr=None,
                        ),
                    )
                except Exception:
                    self.logger.exception(
                        "Falha ao escrever AppScorecard CRD",
                        extra=ctx,
                    )

            if settings.enable_auto_slo_creation:
                dd_labels = self._extract_dd_labels(body)
                if dd_labels and self._ops001_passed(scorecard):
                    dd_service, dd_env = dd_labels
                    await self._maybe_auto_create_slo(
                        body, namespace, dd_service, dd_env
                    )

            should_notify = self.scorecard_service.should_notify(scorecard)
            if should_notify:
                to_send = self._notification_buffer.add_and_maybe_flush(scorecard)
                if to_send is not None:
                    await self._send_namespace_digest(namespace, to_send)
            titlis_client = get_titlis_api_client()
            if titlis_client is not None:
                metadata = body.get("metadata", {})
                workload_uid = metadata.get("uid", "")
                compliance_status = (
                    "COMPLIANT" if scorecard.overall_score >= 90 else "NON_COMPLIANT"
                )
                validation_rules = {
                    rule.id: rule for rule in self.scorecard_service.config.rules
                }
                _HEAVY_ANNOTATIONS = {
                    "kubectl.kubernetes.io/last-applied-configuration",
                }
                annotations = {
                    k: v
                    for k, v in metadata.get("annotations", {}).items()
                    if k not in _HEAVY_ANNOTATIONS
                }
                try:
                    await titlis_client.send_scorecard_evaluated(
                        {
                            "workload_id": workload_uid,
                            "namespace": namespace,
                            "workload": ctx["resource_name"],
                            "cluster": settings.kubernetes_cluster_name,
                            "environment": self._runtime_environment(),
                            "k8s_event_type": event_type,
                            "overall_score": scorecard.overall_score,
                            "compliance_status": compliance_status,
                            "total_rules": scorecard.total_checks,
                            "passed_rules": scorecard.passed_checks,
                            "failed_rules": scorecard.total_checks
                            - scorecard.passed_checks,
                            "critical_failures": scorecard.critical_issues,
                            "error_count": scorecard.error_issues,
                            "warning_count": scorecard.warning_issues,
                            "scorecard_version": 1,
                            "workload_kind": ctx["resource_kind"],
                            "resource_version": metadata.get("resourceVersion"),
                            "labels": metadata.get("labels", {}),
                            "annotations": annotations,
                            "dd_git_repository_url": self._extract_git_repository_url(
                                body
                            ),
                            "pillar_scores": [
                                {
                                    "pillar": ps.pillar.value.upper(),
                                    "score": ps.score,
                                    "passed_checks": ps.passed_checks,
                                    "failed_checks": ps.total_checks - ps.passed_checks,
                                    "weighted_score": ps.weighted_score,
                                }
                                for ps in scorecard.pillar_scores.values()
                            ],
                            "validation_results": [
                                {
                                    "rule_id": validation.rule_id,
                                    "rule_name": validation.rule_name,
                                    "pillar": validation.pillar.value.upper(),
                                    "passed": validation.passed,
                                    "severity": validation.severity.value.upper(),
                                    "rule_type": validation_rules[
                                        validation.rule_id
                                    ].rule_type.value.upper(),
                                    "weight": validation.weight,
                                    "message": validation.message,
                                    "actual_value": (
                                        None
                                        if validation.actual_value is None
                                        else str(validation.actual_value)
                                    ),
                                    "is_remediable": bool(validation.remediation),
                                    "remediation_category": self._remediation_category(
                                        validation.rule_id
                                    ),
                                }
                                for pillar_score in scorecard.pillar_scores.values()
                                for validation in pillar_score.validation_results
                                if validation.rule_id in validation_rules
                            ],
                            "evaluated_at": scorecard.timestamp.isoformat(),
                        }
                    )
                except Exception:
                    self.logger.exception(
                        "Falha ao enviar scorecard para a Titlis API",
                        extra=ctx,
                    )

            return {
                "evaluated": True,
                "resource_name": ctx["resource_name"],
                "resource_namespace": ctx["resource_namespace"],
                "overall_score": scorecard.overall_score,
                "critical_issues": scorecard.critical_issues,
                "error_issues": scorecard.error_issues,
                "warning_issues": scorecard.warning_issues,
                "should_notify": should_notify,
            }

        except Exception:
            self.logger.exception("Erro ao processar Deployment", extra=ctx)
            return {"evaluated": False, "error": "Erro ao processar Deployment"}

    @staticmethod
    def _runtime_environment() -> str:
        return os.environ.get("APP_ENV") or os.environ.get("DD_ENV") or "unknown"

    @staticmethod
    def _extract_git_repository_url(resource_body: Dict[str, Any]) -> Optional[str]:
        containers = (
            resource_body.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        for container in containers:
            for env_var in container.get("env", []):
                if env_var.get("name") == "DD_GIT_REPOSITORY_URL":
                    value = env_var.get("value")
                    return str(value) if value is not None else None
        return None

    @staticmethod
    def _remediation_category(rule_id: str) -> Optional[str]:
        if rule_id in {"RES-007", "RES-008", "PERF-002"}:
            return "hpa"
        if rule_id in {"RES-003", "RES-004", "RES-005", "RES-006", "PERF-001"}:
            return "resources"
        return None

    @staticmethod
    def _extract_dd_labels(body: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        pod_labels = (
            body.get("spec", {})
            .get("template", {})
            .get("metadata", {})
            .get("labels", {})
        )
        dd_service = pod_labels.get("tags.datadoghq.com/service")
        dd_env = pod_labels.get("tags.datadoghq.com/env")
        if dd_service and dd_env:
            return dd_service, dd_env
        return None

    @staticmethod
    def _ops001_passed(scorecard: ResourceScorecard) -> bool:
        from src.domain.models import ValidationPillar

        pillar_score = scorecard.pillar_scores.get(ValidationPillar.OPERATIONAL)
        if pillar_score is None:
            return False
        for result in pillar_score.validation_results:
            if result.rule_id == "OPS-001":
                return result.passed
        return False

    def _find_sloconfig_by_source_uid(
        self, deployment_uid: str, namespace: str
    ) -> Optional[Dict[str, Any]]:
        try:
            _, _, custom = get_k8s_apis()
            result = custom.list_namespaced_custom_object(
                group="titlis.io",
                version="v1",
                namespace=namespace,
                plural="sloconfigs",
                label_selector=f"titlis.io/source-uid={deployment_uid}",
            )
            items = result.get("items", [])
            return items[0] if items else None
        except Exception:
            self.logger.exception(
                "Erro ao buscar SLOConfig por source-uid",
                extra={"deployment_uid": deployment_uid, "namespace": namespace},
            )
            return None

    def _apply_sloconfig(self, body: Dict[str, Any], namespace: str) -> bool:
        try:
            _, _, custom = get_k8s_apis()
            custom.create_namespaced_custom_object(
                group="titlis.io",
                version="v1",
                namespace=namespace,
                plural="sloconfigs",
                body=body,
            )
            return True
        except Exception:
            self.logger.exception(
                "Erro ao criar SLOConfig CRD",
                extra={
                    "crd_name": body.get("metadata", {}).get("name"),
                    "namespace": namespace,
                },
            )
            return False

    def _touch_sloconfig(
        self, existing: Dict[str, Any], namespace: str, deployment_rv: str
    ) -> None:
        name = existing.get("metadata", {}).get("name", "")
        current_rv = (
            existing.get("metadata", {})
            .get("annotations", {})
            .get("titlis.io/last-deployment-rv", "")
        )
        if current_rv == deployment_rv:
            return
        try:
            _, _, custom = get_k8s_apis()
            custom.patch_namespaced_custom_object(
                group="titlis.io",
                version="v1",
                namespace=namespace,
                plural="sloconfigs",
                name=name,
                body={
                    "metadata": {
                        "annotations": {"titlis.io/last-deployment-rv": deployment_rv}
                    }
                },
            )
            self.logger.debug(
                "SLOConfig tocado para forçar reconciliação",
                extra={
                    "name": name,
                    "namespace": namespace,
                    "deployment_rv": deployment_rv,
                },
            )
        except Exception:
            self.logger.exception(
                "Erro ao tocar SLOConfig",
                extra={"name": name, "namespace": namespace},
            )

    async def _maybe_auto_create_slo(
        self,
        body: Dict[str, Any],
        namespace: str,
        dd_service: str,
        dd_env: str,
    ) -> None:
        deployment_uid = body.get("metadata", {}).get("uid")
        if not deployment_uid:
            return

        existing = self._find_sloconfig_by_source_uid(deployment_uid, namespace)
        if existing:
            deployment_rv = body.get("metadata", {}).get("resourceVersion", "")
            self._touch_sloconfig(existing, namespace, deployment_rv)
            return

        slo_config_body: Dict[str, Any] = {
            "apiVersion": "titlis.io/v1",
            "kind": "SLOConfig",
            "metadata": {
                "name": f"auto-{dd_service}",
                "namespace": namespace,
                "labels": {
                    "titlis.io/auto-created": "true",
                    "titlis.io/source-uid": deployment_uid,
                    "titlis.io/source-name": body.get("metadata", {}).get("name", ""),
                    "titlis.io/source-namespace": namespace,
                    "titlis.io/dd-env": dd_env,
                },
            },
            "spec": {
                "service": dd_service,
                "auto_detect_framework": True,
                "target": settings.auto_slo_default_target,
                "warning": settings.auto_slo_default_warning,
                "timeframe": settings.auto_slo_default_timeframe,
                "tags": [f"env:{dd_env}", "managed_by:titlis_operator"],
            },
        }

        success = self._apply_sloconfig(slo_config_body, namespace)
        if success:
            self.logger.info(
                "SLOConfig auto-criado",
                extra={
                    "service": dd_service,
                    "namespace": namespace,
                    "dd_env": dd_env,
                    "deployment_uid": deployment_uid,
                },
            )

    async def _send_namespace_digest(
        self,
        namespace: str,
        scorecards: List[ResourceScorecard],
    ) -> None:
        if not self.slack_service or not scorecards:
            return

        title, message, severity = self._format_namespace_digest(namespace, scorecards)

        success = await self._send_slack_notification_safe(
            title=title,
            message=message,
            severity=severity,
            channel=NotificationChannel.ALERTS,
            namespace=namespace,
            pod_name=None,
        )

        if success and self.appscorecard_writer:
            for sc in scorecards:
                try:
                    self.appscorecard_writer.update_notification(
                        namespace=sc.resource_namespace,
                        name=sc.resource_name,
                        severity=severity.value,
                    )
                except Exception:
                    pass

        if success:
            self.logger.info(
                "Namespace digest enviado",
                extra={"namespace": namespace, "apps_count": len(scorecards)},
            )
        else:
            self.logger.warning(
                "Falha ao enviar namespace digest",
                extra={"namespace": namespace},
            )

    def _format_namespace_digest(
        self,
        namespace: str,
        scorecards: List[ResourceScorecard],
    ) -> tuple[str, str, Any]:
        sorted_sc = sorted(
            scorecards,
            key=lambda s: (
                -s.critical_issues,
                -s.error_issues,
                s.overall_score,
            ),
        )

        total = len(sorted_sc)
        total_critical = sum(s.critical_issues for s in sorted_sc)
        total_errors = sum(s.error_issues for s in sorted_sc)
        total_warnings = sum(s.warning_issues for s in sorted_sc)

        if total_critical > 0 or any(s.overall_score < 70 for s in sorted_sc):
            severity = NotificationSeverity.CRITICAL
            header_emoji = "🔴"
        elif total_errors > 0 or any(s.overall_score < 80 for s in sorted_sc):
            severity = NotificationSeverity.ERROR
            header_emoji = "🟠"
        elif total_warnings > 0 or any(s.overall_score < 90 for s in sorted_sc):
            severity = NotificationSeverity.WARNING
            header_emoji = "🟡"
        else:
            severity = NotificationSeverity.INFO
            header_emoji = "🟢"

        title = f"{header_emoji} Scorecard Digest — namespace: {namespace}"

        summary_parts = [
            f"*{total}* app{'s' if total != 1 else ''} avaliado{'s' if total != 1 else ''}"
        ]
        if total_critical:
            summary_parts.append(
                f"🔴 {total_critical} crítico{'s' if total_critical != 1 else ''}"
            )
        if total_errors:
            summary_parts.append(
                f"❌ {total_errors} erro{'s' if total_errors != 1 else ''}"
            )
        if total_warnings:
            summary_parts.append(
                f"⚠️ {total_warnings} warning{'s' if total_warnings != 1 else ''}"
            )
        summary_line = " | ".join(summary_parts)

        lines = [summary_line, ""]

        for sc in sorted_sc:
            emoji = self._score_emoji(sc.overall_score)
            name_padded = sc.resource_name[:35].ljust(35)
            score_str = f"{sc.overall_score:5.1f}/100"
            issue_parts = []
            if sc.critical_issues:
                issue_parts.append(f"🔴 {sc.critical_issues} crít.")
            if sc.error_issues:
                issue_parts.append(f"❌ {sc.error_issues} erros")
            if sc.warning_issues:
                issue_parts.append(f"⚠️ {sc.warning_issues} warn.")
            if not issue_parts:
                issue_parts.append("✅ ok")
            issues_str = "  ".join(issue_parts)
            lines.append(f"{emoji} `{name_padded}` {score_str}  {issues_str}")

        top_issues: List[str] = []
        for sc in sorted_sc:
            for ps in sc.pillar_scores.values():
                for v in ps.validation_results:
                    if not v.passed and v.severity.value in ("critical", "error"):
                        top_issues.append(
                            f"• *{sc.resource_name}*: [{v.rule_id}] {v.rule_name}"
                        )
            if len(top_issues) >= 5:
                break

        if top_issues:
            lines += ["", "*Issues críticos/errors:*"] + top_issues[:5]

        lines += [
            "",
            f"`kubectl get appscorecard -n {namespace}`",
        ]

        message = "\n".join(lines)
        if len(message) > 3000:
            message = message[:2997] + "..."

        return title, message, severity

    def _score_emoji(self, score: float) -> str:
        if score >= 90:
            return "🟢"
        if score >= 80:
            return "🟡"
        if score >= 70:
            return "🟠"
        return "🔴"

    def _get_score_status(self, score: float) -> str:
        if score >= 90:
            return "Excelente"
        if score >= 80:
            return "Bom"
        if score >= 70:
            return "Regular"
        if score >= 50:
            return "Insatisfatório"
        return "Crítico"


scorecard_controller = ScorecardController()


@kopf.on.resume("apps", "v1", "deployments")  # type: ignore[arg-type]
async def on_deployment_resume(body: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return await scorecard_controller.on_resource_event(
        body, event_type="resume", **kwargs
    )


@kopf.on.create("apps", "v1", "deployments")  # type: ignore[arg-type]
async def on_deployment_create(body: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return await scorecard_controller.on_resource_event(
        body, event_type="create", **kwargs
    )


@kopf.on.update("apps", "v1", "deployments")  # type: ignore[arg-type]
async def on_deployment_update(body: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    return await scorecard_controller.on_resource_event(
        body, event_type="update", **kwargs
    )


@kopf.on.delete("apps", "v1", "deployments")  # type: ignore[arg-type]
async def on_deployment_delete(body: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    ctx = scorecard_controller._get_resource_context(body)

    await scorecard_controller._send_slack_notification_safe(
        title=f"🗑️ Deployment Deletado: {ctx['resource_name']}",
        message=(
            f"*Deployment deletado do cluster*\n\n"
            f"*Aplicação:* {ctx['resource_name']}\n"
            f"*Namespace:* {ctx['resource_namespace']}\n"
            f"*Timestamp:* {datetime.now(timezone.utc).isoformat()}\n\n"
            f"*Observação:* Este deployment não está mais sendo monitorado pelo Titlis Operator."
        ),
        severity=NotificationSeverity.WARNING,
        channel=NotificationChannel.ALERTS,
        namespace=ctx["resource_namespace"],
    )

    scorecard_controller.logger.warning("Deployment deleted", extra=ctx)
    return {"deleted": True}
