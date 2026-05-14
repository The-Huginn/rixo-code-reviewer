from typing import Type, List, TYPE_CHECKING
from src.agent import AllFilesAgent
from src.data import DocumentationReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class DocumentationReviewAgent(AllFilesAgent[DocumentationReviewResult]):
    """
    Pre-PR review agent that validates endpoint documentation completeness.

    This agent reviews the entire PR to ensure:
    - All new/modified controller endpoints have corresponding tests
    - Test files have @Documented annotation
    - Documentation files (.adoc) are updated
    - HTTP methods match request body usage (POST vs GET)
    """

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    def _get_rule_groups(self) -> List[str]:
        return ["documentation"]

    def _get_specialty(self) -> str:
        return "endpoint documentation and test coverage validation"

    def _get_response_schema(self) -> Type[DocumentationReviewResult]:
        return DocumentationReviewResult

    def _get_agent_name(self) -> str:
        return "DocumentationReviewAgent"