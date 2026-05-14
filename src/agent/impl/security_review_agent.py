from typing import Type, List, TYPE_CHECKING, Optional, override
from src.agent import SingleFileAgent
from src.data import SecurityReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class SecurityReviewAgent(SingleFileAgent[SecurityReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    @override
    def _get_file_pattern(self) -> Optional[str]:
        return r"(.(java|kt|py)$)"

    def _get_rule_groups(self) -> List[str]:
        return ["security"]

    def _get_specialty(self) -> str:
        return "security vulnerabilities (high-confidence only)"

    def _get_response_schema(self) -> Type[SecurityReviewResult]:
        return SecurityReviewResult

    def _get_agent_name(self) -> str:
        return "SecurityReviewAgent"
