"""
Serviço de remediação automática de HPA e Resources.

Ao detectar issues de HPA ou resources no scorecard, este serviço:
  1. Gera arquivos YAML de remediação (patches de HPA e/ou resources)
  2. Cria uma branch a partir da 'develop'
  3. Commita os arquivos na nova branch
  4. Cria um Pull Request para 'develop' no GitHub
  5. Notifica o canal Slack configurado
"""
import yaml
from datetime import datetime, timezone
from typing import List, Optional

from src.application.ports.github_port import GitHubPort
from src.application.services.slack_service import SlackNotificationService
from src.domain.github_models import (
    PullRequestResult,
    RemediationFile,
    RemediationIssue,
    RemediationRequest,
    RemediationResult,
    RemediationRuleCategory,
)
from src.domain.slack_models import (
    NotificationChannel,
    NotificationSeverity,
    SlackNotification,
)
from src.utils.json_logger import get_logger

logger = get_logger(__name__)

# IDs de regras que podem ser remediadas automaticamente
_HPA_RULE_IDS = frozenset({"RES-007", "RES-008", "PERF-002"})
_RESOURCE_RULE_IDS = frozenset({"RES-003", "RES-004", "RES-005", "RES-006", "PERF-001"})
REMEDIABLE_RULE_IDS = _HPA_RULE_IDS | _RESOURCE_RULE_IDS


class RemediationService:
    """
    Orquestra a remediação automática de HPA e resources.

    Recebe um RemediationRequest com as issues detectadas e executa o fluxo
    completo: branch → commit → PR → notificação Slack.
    """

    def __init__(
        self,
        github_port: GitHubPort,
        slack_service: Optional[SlackNotificationService] = None,
    ) -> None:
        self._github = github_port
        self._slack = slack_service
        self.logger = get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Ponto de entrada principal
    # ------------------------------------------------------------------

    async def create_remediation_pr(
        self, request: RemediationRequest
    ) -> RemediationResult:
        """
        Executa o fluxo completo de remediação para o recurso informado.

        Retorna RemediationResult com success=True e dados do PR criado,
        ou success=False com mensagem de erro.
        """
        self.logger.info(
            "Iniciando remediação automática",
            extra={
                "resource": f"{request.namespace}/{request.resource_name}",
                "kind": request.resource_kind,
                "issues_count": len(request.issues),
                "issue_ids": [i.rule_id for i in request.issues],
            },
        )

        files = self._generate_remediation_files(request)
        if not files:
            return RemediationResult(
                success=False,
                error="Nenhum arquivo de remediação gerado para as issues informadas",
            )

        branch_name = self._build_branch_name(request)

        # 1. Cria branch a partir da develop
        created = await self._github.create_branch(
            repo_owner=request.repo_owner,
            repo_name=request.repo_name,
            branch_name=branch_name,
            base_branch=request.base_branch,
        )
        if not created:
            return RemediationResult(
                success=False,
                branch_name=branch_name,
                error=f"Falha ao criar branch '{branch_name}' a partir de '{request.base_branch}'",
            )

        # 2. Commita os arquivos gerados
        committed = await self._github.commit_files(
            repo_owner=request.repo_owner,
            repo_name=request.repo_name,
            branch_name=branch_name,
            files=files,
        )
        if not committed:
            return RemediationResult(
                success=False,
                branch_name=branch_name,
                error="Falha ao commitar os arquivos de remediação na branch",
            )

        # 3. Cria o PR para develop
        try:
            pr = await self._github.create_pull_request(
                repo_owner=request.repo_owner,
                repo_name=request.repo_name,
                branch_name=branch_name,
                base_branch=request.base_branch,
                title=self._build_pr_title(request),
                body=self._build_pr_body(request, files),
            )
        except Exception as exc:
            self.logger.exception("Erro ao criar Pull Request")
            return RemediationResult(
                success=False,
                branch_name=branch_name,
                error=f"Falha ao criar Pull Request: {exc}",
            )

        pr.issues_fixed = [i.rule_id for i in request.issues]

        result = RemediationResult(
            success=True,
            pull_request=pr,
            branch_name=branch_name,
        )

        # 4. Notifica no Slack
        await self._notify_slack(request, pr)

        self.logger.info(
            "Remediação concluída com sucesso",
            extra={
                "pr_number": pr.number,
                "pr_url": pr.url,
                "branch": branch_name,
            },
        )
        return result

    # ------------------------------------------------------------------
    # Geração de arquivos de remediação
    # ------------------------------------------------------------------

    def _generate_remediation_files(
        self, request: RemediationRequest
    ) -> List[RemediationFile]:
        """Gera os arquivos YAML de remediação baseado nas issues detectadas."""
        files: List[RemediationFile] = []

        hpa_issues = [i for i in request.issues if i.rule_id in _HPA_RULE_IDS]
        resource_issues = [
            i for i in request.issues if i.rule_id in _RESOURCE_RULE_IDS
        ]

        if hpa_issues:
            files.append(self._generate_hpa_manifest(request))

        if resource_issues:
            files.append(self._generate_resources_patch(request))

        return files

    def _generate_hpa_manifest(self, request: RemediationRequest) -> RemediationFile:
        """Gera um manifesto HPA com configuração padrão recomendada."""
        manifest = {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": request.resource_name,
                "namespace": request.namespace,
                "annotations": {
                    "titlis.io/auto-generated": "true",
                    "titlis.io/generated-by": "titlis-operator-remediation",
                },
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": request.resource_kind,
                    "name": request.resource_name,
                },
                "minReplicas": 2,
                "maxReplicas": 10,
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": 70,
                            },
                        },
                    },
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "memory",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": 80,
                            },
                        },
                    },
                ],
            },
        }

        path = (
            f"k8s/{request.namespace}/{request.resource_name}-hpa.yaml"
        )
        content = yaml.dump(manifest, default_flow_style=False, allow_unicode=True)

        return RemediationFile(
            path=path,
            content=content,
            commit_message=(
                f"fix(hpa): adiciona HPA para "
                f"{request.namespace}/{request.resource_name}"
            ),
        )

    def _generate_resources_patch(
        self, request: RemediationRequest
    ) -> RemediationFile:
        """Gera um patch estratégico para adicionar requests/limits ao container."""
        patch = {
            "apiVersion": "apps/v1",
            "kind": request.resource_kind,
            "metadata": {
                "name": request.resource_name,
                "namespace": request.namespace,
            },
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": request.resource_name,
                                "resources": {
                                    "requests": {
                                        "cpu": "100m",
                                        "memory": "128Mi",
                                    },
                                    "limits": {
                                        "cpu": "500m",
                                        "memory": "512Mi",
                                    },
                                },
                            }
                        ]
                    }
                }
            },
        }

        path = (
            f"k8s/{request.namespace}/{request.resource_name}-resources-patch.yaml"
        )
        content = yaml.dump(patch, default_flow_style=False, allow_unicode=True)

        return RemediationFile(
            path=path,
            content=content,
            commit_message=(
                f"fix(resources): define requests/limits para "
                f"{request.namespace}/{request.resource_name}"
            ),
        )

    # ------------------------------------------------------------------
    # Helpers de PR
    # ------------------------------------------------------------------

    def _build_branch_name(self, request: RemediationRequest) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        safe_name = request.resource_name.replace("/", "-")
        return (
            f"fix/auto-remediation-{request.namespace}-{safe_name}-{timestamp}"
        )

    def _build_pr_title(self, request: RemediationRequest) -> str:
        count = len(request.issues)
        return (
            f"fix({request.namespace}/{request.resource_name}): "
            f"auto-remediação HPA e resources [{count} issue(s)]"
        )

    def _build_pr_body(
        self, request: RemediationRequest, files: List[RemediationFile]
    ) -> str:
        issues_md = "\n".join(
            f"- **{i.rule_id}** — {i.rule_name}: {i.description}"
            for i in request.issues
        )
        remediations_md = "\n".join(
            f"- `{i.rule_id}`: {i.remediation}" for i in request.issues
        )
        files_md = "\n".join(f"- `{f.path}`" for f in files)

        hpa_count = sum(
            1 for i in request.issues if i.category == RemediationRuleCategory.HPA
        )
        res_count = sum(
            1
            for i in request.issues
            if i.category == RemediationRuleCategory.RESOURCES
        )

        categories: List[str] = []
        if hpa_count:
            categories.append(f"HPA ({hpa_count})")
        if res_count:
            categories.append(f"Resources ({res_count})")
        categories_str = ", ".join(categories) if categories else "geral"

        return (
            f"## Auto-Remediação: {request.resource_kind} "
            f"`{request.namespace}/{request.resource_name}`\n\n"
            f"Este PR foi gerado automaticamente pelo **titlis-operator** para corrigir "
            f"problemas detectados no scorecard.\n\n"
            f"**Categorias:** {categories_str}\n\n"
            f"### Issues Detectadas\n\n"
            f"{issues_md}\n\n"
            f"### Remediações Aplicadas\n\n"
            f"{remediations_md}\n\n"
            f"### Arquivos Gerados\n\n"
            f"{files_md}\n\n"
            f"---\n"
            f"> Gerado automaticamente pelo titlis-operator em "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    # ------------------------------------------------------------------
    # Notificação Slack
    # ------------------------------------------------------------------

    async def _notify_slack(
        self,
        request: RemediationRequest,
        pr: PullRequestResult,
    ) -> None:
        """Envia notificação no Slack após a criação do PR."""
        if not self._slack or not self._slack.is_enabled():
            return

        issues_text = "\n".join(
            f"• *{i.rule_id}*: {i.rule_name}" for i in request.issues
        )

        notification = SlackNotification(
            title="Auto-Remediacao: PR Criado",
            message=(
                f"*Recurso:* `{request.namespace}/{request.resource_name}`"
                f" ({request.resource_kind})\n"
                f"*Branch:* `{pr.branch}` -> `{pr.base_branch}`\n"
                f"*Issues corrigidas ({len(request.issues)}):*\n"
                f"{issues_text}\n"
                f"*PR:* <{pr.url}|#{pr.number} - {pr.title}>"
            ),
            severity=NotificationSeverity.WARNING,
            channel=NotificationChannel.OPERATIONAL,
            namespace=request.namespace,
            additional_fields={
                "pr_url": pr.url,
                "pr_number": str(pr.number),
                "branch": pr.branch,
                "resource": f"{request.namespace}/{request.resource_name}",
            },
        )

        try:
            await self._slack.send_notification(notification)
            self.logger.info(
                "Notificacao Slack de remediacao enviada",
                extra={"pr_number": pr.number},
            )
        except Exception:
            self.logger.exception(
                "Falha ao enviar notificacao Slack de remediacao"
            )
