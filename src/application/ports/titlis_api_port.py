from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from typing import List, Optional


@dataclass
class RemediationState:
    status: str
    version: int
    github_pr_url: Optional[str]
    github_pr_number: Optional[int]


@dataclass
class SLOPendingChange:
    id: str
    slo_config_name: str
    namespace: str
    field: str
    old_value: str
    new_value: str
    requested_by: str
    extra: dict = dc_field(default_factory=dict)


class TitlisApiPort(ABC):
    @abstractmethod
    async def send_scorecard_evaluated(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_remediation_event(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_slo_reconciled(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_notification_log(self, payload: dict) -> None: ...

    @abstractmethod
    async def send_resource_metrics(self, payload: dict) -> None: ...

    @abstractmethod
    async def get_remediation(self, workload_id: str) -> Optional[RemediationState]: ...

    @abstractmethod
    async def get_pending_slo_changes(self) -> List[SLOPendingChange]: ...

    @abstractmethod
    async def confirm_slo_change_applied(self, change_id: str) -> bool: ...

    @abstractmethod
    async def confirm_slo_change_failed(self, change_id: str, error: str) -> bool: ...
