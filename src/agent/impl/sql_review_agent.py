from typing import Type, Optional, List, TYPE_CHECKING
from src.agent import SingleFileAgent
from src.data import SQLReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class SQLReviewAgent(SingleFileAgent[SQLReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    def _get_rule_groups(self) -> List[str]:
        return ["sql"]

    def _get_file_pattern(self) -> Optional[str]:
        return r"\.sql$"

    def _get_specialty(self) -> str:
        return "SQL test data quality and formatting"

    def _get_response_schema(self) -> Type[SQLReviewResult]:
        return SQLReviewResult

    def _get_agent_name(self) -> str:
        return "SQLReviewAgent"