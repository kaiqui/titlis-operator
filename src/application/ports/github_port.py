from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.github_models import PullRequestResult, RemediationFile


class GitHubPort(ABC):
    """Porta abstrata para operações no GitHub."""

    @abstractmethod
    async def branch_exists(
        self, repo_owner: str, repo_name: str, branch_name: str
    ) -> bool:
        """Verifica se uma branch existe no repositório."""
        pass

    @abstractmethod
    async def create_branch(
        self,
        repo_owner: str,
        repo_name: str,
        branch_name: str,
        base_branch: str,
    ) -> bool:
        """Cria uma nova branch a partir de uma branch base."""
        pass

    @abstractmethod
    async def get_file_content(
        self,
        repo_owner: str,
        repo_name: str,
        file_path: str,
        ref: str,
    ) -> Optional[str]:
        """Retorna o conteúdo de um arquivo como string, ou None se não encontrado."""
        pass

    @abstractmethod
    async def commit_files(
        self,
        repo_owner: str,
        repo_name: str,
        branch_name: str,
        files: List[RemediationFile],
    ) -> bool:
        """Commita uma lista de arquivos em uma branch."""
        pass

    @abstractmethod
    async def create_pull_request(
        self,
        repo_owner: str,
        repo_name: str,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> PullRequestResult:
        """Cria um Pull Request de branch_name para base_branch."""
        pass

    @abstractmethod
    async def find_open_remediation_pr(
        self,
        repo_owner: str,
        repo_name: str,
        namespace: str,
        resource_name: str,
        base_branch: str,
    ) -> Optional[PullRequestResult]:
        """
        Procura um PR aberto de remediação para o recurso informado.

        Filtra PRs cujo head branch começa com
        'fix/auto-remediation-{namespace}-{resource_name}-'.
        Retorna o primeiro encontrado, ou None.
        """
        pass
