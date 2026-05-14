from typing import Type, List, TYPE_CHECKING, override, Optional
from src.agent import SingleFileAgent
from src.data import StyleReviewResult
from src.client.ai import AIClient

if TYPE_CHECKING:
    from src.service import RuleLoaderService


class StyleReviewAgent(SingleFileAgent[StyleReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    @override
    def _get_file_pattern(self) -> Optional[str]:
        return r"(.(java|kt|py)$)"

    def _get_rule_groups(self) -> List[str]:
        return ["style"]

    def _get_specialty(self) -> str:
        return "code style and formatting"

    def _get_response_schema(self) -> Type[StyleReviewResult]:
        return StyleReviewResult

    def _get_agent_name(self) -> str:
        return "StyleReviewAgent"
