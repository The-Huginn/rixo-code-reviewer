from typing import Type, List, TYPE_CHECKING
from src.agent import AllFilesAgent
from src.data import ArchitectureReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class ArchitectureReviewAgent(AllFilesAgent):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    def _get_rule_groups(self) -> List[str]:
        return ["architecture", "core", "reviewer"]

    def _get_specialty(self) -> str:
        return "architecture and layer separation"

    def _get_response_schema(self) -> Type[ArchitectureReviewResult]:
        return ArchitectureReviewResult

    def _get_agent_name(self) -> str:
        return "ArchitectureReviewAgent"
