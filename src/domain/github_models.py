from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class RemediationRuleCategory(str, Enum):
    HPA = "hpa"
    RESOURCES = "resources"


@dataclass
class DatadogProfilingMetrics:
    cpu_avg_millicores: Optional[int] = None
    memory_avg_mib: Optional[int] = None

    def suggest_cpu_request(self, default: str = "100m") -> str:
        if self.cpu_avg_millicores:
            return f"{max(100, int(self.cpu_avg_millicores * 1.2))}m"
        return default

    def suggest_cpu_limit(self, default: str = "500m") -> str:
        if self.cpu_avg_millicores:
            return f"{max(300, int(self.cpu_avg_millicores * 3))}m"
        return default

    def suggest_memory_request(self, default: str = "128Mi") -> str:
        if self.memory_avg_mib:
            return f"{max(128, int(self.memory_avg_mib * 1.2))}Mi"
        return default

    def suggest_memory_limit(self, default: str = "512Mi") -> str:
        if self.memory_avg_mib:
            return f"{max(256, int(self.memory_avg_mib * 2))}Mi"
        return default


@dataclass
class RemediationIssue:
    rule_id: str
    rule_name: str
    description: str
    remediation: str
    category: RemediationRuleCategory = RemediationRuleCategory.RESOURCES

    def __post_init__(self) -> None:
        if self.rule_id in {"RES-007", "RES-008", "PERF-002"}:
            self.category = RemediationRuleCategory.HPA
        elif self.rule_id in {"RES-003", "RES-004", "RES-005", "RES-006", "PERF-001"}:
            self.category = RemediationRuleCategory.RESOURCES


@dataclass
class RemediationFile:
    path: str
    content: str
    commit_message: str


@dataclass
class PullRequestResult:
    number: int
    title: str
    url: str
    branch: str
    base_branch: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    issues_fixed: List[str] = field(default_factory=list)


@dataclass
class RemediationRequest:
    resource_name: str
    namespace: str
    resource_kind: str
    issues: List[RemediationIssue]
    resource_body: Dict[str, Any]
    base_branch: str = "develop"


@dataclass
class RemediationResult:
    success: bool
    pull_request: Optional[PullRequestResult] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
