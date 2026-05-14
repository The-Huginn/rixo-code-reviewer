from typing import Type, Optional, List, TYPE_CHECKING

from src.agent import SingleFileAgent
from src.client.ai import AIClient
from src.data import TestReviewResult

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class TestReviewAgent(SingleFileAgent[TestReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    def _get_rule_groups(self) -> List[str]:
        return ["testing"]

    def _get_file_pattern(self) -> Optional[str]:
        return r"(/test/|Test\.(java|kt|py)$)"

    def _get_specialty(self) -> str:
        return "test coverage and quality"

    def _get_response_schema(self) -> Type[TestReviewResult]:
        return TestReviewResult

    def _get_agent_name(self) -> str:
        return "TestReviewAgent"
