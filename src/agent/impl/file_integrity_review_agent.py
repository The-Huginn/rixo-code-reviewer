from typing import Type, Optional, List, TYPE_CHECKING
from src.agent import SingleFileAgent
from src.data import FileIntegrityReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class FileIntegrityReviewAgent(SingleFileAgent[FileIntegrityReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    def _get_rule_groups(self) -> List[str]:
        return ["core", "implementation"]

    def _get_file_pattern(self) -> Optional[str]:
        return r"^(?!.*/test/)(?!.*Test\.(java|kt|py)$).*\.(java|kt|py)$"

    def _get_specialty(self) -> str:
        return "file integrity, implementation correctness, and validation logic"

    def _get_response_schema(self) -> Type[FileIntegrityReviewResult]:
        return FileIntegrityReviewResult

    def _get_agent_name(self) -> str:
        return "FileIntegrityReviewAgent"
