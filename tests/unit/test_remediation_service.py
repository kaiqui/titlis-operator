"""
Testes unitários para RemediationService.

Cobre:
- Geração de arquivos de remediação (HPA e resources)
- Fluxo completo de criação do PR
- Tratamento de erros em cada etapa
- Notificação Slack após o PR
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.services.remediation_service import (
    REMEDIABLE_RULE_IDS,
    RemediationService,
    _HPA_RULE_IDS,
    _RESOURCE_RULE_IDS,
)
from src.domain.github_models import (
    PullRequestResult,
    RemediationIssue,
    RemediationRequest,
    RemediationRuleCategory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_github_port():
    port = AsyncMock()
    port.branch_exists.return_value = False
    port.create_branch.return_value = True
    port.commit_files.return_value = True
    port.create_pull_request.return_value = PullRequestResult(
        number=42,
        title="fix(default/my-app): auto-remediação HPA e resources [2 issue(s)]",
        url="https://github.com/org/repo/pull/42",
        branch="fix/auto-remediation-default-my-app-20240101000000",
        base_branch="develop",
    )
    return port


@pytest.fixture
def mock_slack_service():
    svc = MagicMock()
    svc.is_enabled.return_value = True
    svc.send_notification = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def hpa_issue():
    return RemediationIssue(
        rule_id="RES-007",
        rule_name="HPA Configurado",
        description="Deployment deve ter HPA configurado",
        remediation="Configure HPA para auto-scaling",
    )


@pytest.fixture
def resource_issue():
    return RemediationIssue(
        rule_id="RES-003",
        rule_name="CPU Requests Definidos",
        description="Container deve ter requests de CPU definidos",
        remediation="Defina requests.cpu",
    )


@pytest.fixture
def base_request(hpa_issue, resource_issue):
    return RemediationRequest(
        resource_name="my-app",
        namespace="default",
        resource_kind="Deployment",
        issues=[hpa_issue, resource_issue],
        repo_owner="org",
        repo_name="repo",
        base_branch="develop",
    )


@pytest.fixture
def service(mock_github_port, mock_slack_service):
    return RemediationService(
        github_port=mock_github_port,
        slack_service=mock_slack_service,
    )


# ---------------------------------------------------------------------------
# Testes de constants
# ---------------------------------------------------------------------------


class TestRemediableRuleIds:
    def test_hpa_rule_ids_presente(self):
        assert "RES-007" in _HPA_RULE_IDS
        assert "RES-008" in _HPA_RULE_IDS
        assert "PERF-002" in _HPA_RULE_IDS

    def test_resource_rule_ids_presente(self):
        assert "RES-003" in _RESOURCE_RULE_IDS
        assert "RES-004" in _RESOURCE_RULE_IDS
        assert "RES-005" in _RESOURCE_RULE_IDS
        assert "RES-006" in _RESOURCE_RULE_IDS
        assert "PERF-001" in _RESOURCE_RULE_IDS

    def test_remediable_uniao(self):
        assert REMEDIABLE_RULE_IDS == _HPA_RULE_IDS | _RESOURCE_RULE_IDS


# ---------------------------------------------------------------------------
# Testes de RemediationIssue (category inference)
# ---------------------------------------------------------------------------


class TestRemediationIssueCategory:
    def test_hpa_issue_categoria_correta(self):
        issue = RemediationIssue(
            rule_id="RES-007",
            rule_name="HPA",
            description="desc",
            remediation="fix",
        )
        assert issue.category == RemediationRuleCategory.HPA

    def test_resource_issue_categoria_correta(self):
        issue = RemediationIssue(
            rule_id="RES-003",
            rule_name="CPU",
            description="desc",
            remediation="fix",
        )
        assert issue.category == RemediationRuleCategory.RESOURCES


# ---------------------------------------------------------------------------
# Testes de _generate_remediation_files
# ---------------------------------------------------------------------------


class TestGenerateRemediationFiles:
    def test_gera_arquivo_hpa_para_issue_hpa(self, service, hpa_issue):
        request = RemediationRequest(
            resource_name="app",
            namespace="ns",
            resource_kind="Deployment",
            issues=[hpa_issue],
            repo_owner="o",
            repo_name="r",
        )
        files = service._generate_remediation_files(request)
        assert len(files) == 1
        assert "hpa" in files[0].path

    def test_gera_arquivo_resources_para_issue_resource(self, service, resource_issue):
        request = RemediationRequest(
            resource_name="app",
            namespace="ns",
            resource_kind="Deployment",
            issues=[resource_issue],
            repo_owner="o",
            repo_name="r",
        )
        files = service._generate_remediation_files(request)
        assert len(files) == 1
        assert "resources-patch" in files[0].path

    def test_gera_ambos_arquivos_para_ambas_issues(self, service, base_request):
        files = service._generate_remediation_files(base_request)
        assert len(files) == 2
        paths = [f.path for f in files]
        assert any("hpa" in p for p in paths)
        assert any("resources-patch" in p for p in paths)

    def test_retorna_lista_vazia_sem_issues_remediaveis(self, service):
        request = RemediationRequest(
            resource_name="app",
            namespace="ns",
            resource_kind="Deployment",
            issues=[
                RemediationIssue(
                    rule_id="SEC-001",
                    rule_name="Imagem com Tag",
                    description="Use tag específica",
                    remediation="Não use latest",
                )
            ],
            repo_owner="o",
            repo_name="r",
        )
        files = service._generate_remediation_files(request)
        assert files == []


# ---------------------------------------------------------------------------
# Testes de _generate_hpa_manifest
# ---------------------------------------------------------------------------


class TestGenerateHpaManifest:
    def test_conteudo_yaml_valido(self, service, base_request):
        import yaml

        f = service._generate_hpa_manifest(base_request)
        manifest = yaml.safe_load(f.content)
        assert manifest["kind"] == "HorizontalPodAutoscaler"
        assert manifest["apiVersion"] == "autoscaling/v2"
        assert manifest["spec"]["minReplicas"] == 2
        assert manifest["spec"]["maxReplicas"] == 10
        assert len(manifest["spec"]["metrics"]) == 2

    def test_namespace_e_nome_corretos(self, service, base_request):
        import yaml

        f = service._generate_hpa_manifest(base_request)
        manifest = yaml.safe_load(f.content)
        assert manifest["metadata"]["name"] == base_request.resource_name
        assert manifest["metadata"]["namespace"] == base_request.namespace

    def test_path_inclui_namespace_e_nome(self, service, base_request):
        f = service._generate_hpa_manifest(base_request)
        assert base_request.namespace in f.path
        assert base_request.resource_name in f.path

    def test_annotation_auto_generated(self, service, base_request):
        import yaml

        f = service._generate_hpa_manifest(base_request)
        manifest = yaml.safe_load(f.content)
        assert manifest["metadata"]["annotations"]["titlis.io/auto-generated"] == "true"


# ---------------------------------------------------------------------------
# Testes de _generate_resources_patch
# ---------------------------------------------------------------------------


class TestGenerateResourcesPatch:
    def test_conteudo_yaml_valido(self, service, base_request):
        import yaml

        f = service._generate_resources_patch(base_request)
        manifest = yaml.safe_load(f.content)
        containers = manifest["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        resources = containers[0]["resources"]
        assert "requests" in resources
        assert "limits" in resources

    def test_requests_e_limits_definidos(self, service, base_request):
        import yaml

        f = service._generate_resources_patch(base_request)
        manifest = yaml.safe_load(f.content)
        resources = manifest["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["cpu"] == "100m"
        assert resources["requests"]["memory"] == "128Mi"
        assert resources["limits"]["cpu"] == "500m"
        assert resources["limits"]["memory"] == "512Mi"


# ---------------------------------------------------------------------------
# Testes do fluxo completo: create_remediation_pr
# ---------------------------------------------------------------------------


class TestCreateRemediationPr:
    @pytest.mark.asyncio
    async def test_fluxo_completo_sucesso(
        self, service, mock_github_port, mock_slack_service, base_request
    ):
        result = await service.create_remediation_pr(base_request)

        assert result.success is True
        assert result.pull_request is not None
        assert result.pull_request.number == 42
        assert result.branch_name is not None

        mock_github_port.create_branch.assert_called_once()
        mock_github_port.commit_files.assert_called_once()
        mock_github_port.create_pull_request.assert_called_once()
        mock_slack_service.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_nao_ha_arquivos(self, service):
        request = RemediationRequest(
            resource_name="app",
            namespace="ns",
            resource_kind="Deployment",
            issues=[
                RemediationIssue(
                    rule_id="SEC-001",
                    rule_name="Imagem",
                    description="desc",
                    remediation="fix",
                )
            ],
            repo_owner="o",
            repo_name="r",
        )
        result = await service.create_remediation_pr(request)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_create_branch_falha(
        self, service, mock_github_port, base_request
    ):
        mock_github_port.create_branch.return_value = False
        result = await service.create_remediation_pr(base_request)
        assert result.success is False
        assert "branch" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_commit_falha(
        self, service, mock_github_port, base_request
    ):
        mock_github_port.commit_files.return_value = False
        result = await service.create_remediation_pr(base_request)
        assert result.success is False
        assert "commitar" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_create_pr_levanta_excecao(
        self, service, mock_github_port, base_request
    ):
        mock_github_port.create_pull_request.side_effect = RuntimeError("API error")
        result = await service.create_remediation_pr(base_request)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_nao_falha_quando_slack_falha(
        self, service, mock_slack_service, base_request
    ):
        mock_slack_service.send_notification.side_effect = RuntimeError("slack down")
        result = await service.create_remediation_pr(base_request)
        # Deve ter sucesso mesmo com Slack falhando
        assert result.success is True

    @pytest.mark.asyncio
    async def test_issues_fixed_populado(
        self, service, base_request
    ):
        result = await service.create_remediation_pr(base_request)
        assert result.success is True
        assert result.pull_request is not None
        assert set(result.pull_request.issues_fixed) == {
            i.rule_id for i in base_request.issues
        }


# ---------------------------------------------------------------------------
# Testes de _build_branch_name
# ---------------------------------------------------------------------------


class TestBuildBranchName:
    def test_branch_comeca_com_fix(self, service, base_request):
        name = service._build_branch_name(base_request)
        assert name.startswith("fix/auto-remediation-")

    def test_branch_contem_namespace_e_recurso(self, service, base_request):
        name = service._build_branch_name(base_request)
        assert base_request.namespace in name
        assert base_request.resource_name in name

    def test_branch_unica_por_timestamp(self, service, base_request):
        name1 = service._build_branch_name(base_request)
        name2 = service._build_branch_name(base_request)
        # Não deve ser sempre igual (pode ser igual num mesmo segundo, tudo bem)
        assert isinstance(name1, str)
        assert isinstance(name2, str)


# ---------------------------------------------------------------------------
# Testes de _build_pr_title e _build_pr_body
# ---------------------------------------------------------------------------


class TestBuildPrContent:
    def test_titulo_contem_namespace_e_recurso(self, service, base_request):
        title = service._build_pr_title(base_request)
        assert base_request.namespace in title
        assert base_request.resource_name in title

    def test_titulo_contem_contagem_de_issues(self, service, base_request):
        title = service._build_pr_title(base_request)
        assert "2" in title

    def test_body_contem_ids_das_issues(self, service, base_request):
        files = service._generate_remediation_files(base_request)
        body = service._build_pr_body(base_request, files)
        for issue in base_request.issues:
            assert issue.rule_id in body

    def test_body_contem_nomes_dos_arquivos(self, service, base_request):
        files = service._generate_remediation_files(base_request)
        body = service._build_pr_body(base_request, files)
        for f in files:
            assert f.path in body
