from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class RemediationRuleCategory(str, Enum):
    HPA = "hpa"
    RESOURCES = "resources"


@dataclass
class RemediationIssue:
    """Issue detectada pelo scorecard que pode ser remediada automaticamente."""

    rule_id: str
    rule_name: str
    description: str
    remediation: str
    category: RemediationRuleCategory = RemediationRuleCategory.RESOURCES

    # Mapeamento de regras para categoria
    _HPA_RULE_IDS: frozenset = field(
        default_factory=lambda: frozenset({"RES-007", "RES-008", "PERF-002"}),
        init=False,
        repr=False,
        compare=False,
    )
    _RESOURCE_RULE_IDS: frozenset = field(
        default_factory=lambda: frozenset(
            {"RES-003", "RES-004", "RES-005", "RES-006", "PERF-001"}
        ),
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.rule_id in {"RES-007", "RES-008", "PERF-002"}:
            self.category = RemediationRuleCategory.HPA
        elif self.rule_id in {"RES-003", "RES-004", "RES-005", "RES-006", "PERF-001"}:
            self.category = RemediationRuleCategory.RESOURCES


@dataclass
class RemediationFile:
    """Arquivo gerado para remediação, que será commitado no PR."""

    path: str
    content: str
    commit_message: str


@dataclass
class PullRequestResult:
    """Resultado da criação de um Pull Request no GitHub."""

    number: int
    title: str
    url: str
    branch: str
    base_branch: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    issues_fixed: List[str] = field(default_factory=list)


@dataclass
class RemediationRequest:
    """Solicitação de remediação automática para um recurso Kubernetes."""

    resource_name: str
    namespace: str
    resource_kind: str
    issues: List[RemediationIssue]
    repo_owner: str
    repo_name: str
    base_branch: str = "develop"


@dataclass
class RemediationResult:
    """Resultado da execução de uma remediação automática."""

    success: bool
    pull_request: Optional[PullRequestResult] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
