import logging
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Type, List

from pydantic import BaseModel

from src.client.ai import AIClient
from src.config import (
    CRITICAL_REVIEW_INSTRUCTIONS,
    PERSONA,
    get_comment_format_instruction
)
from src.service import RuleLoaderService

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class BaseReviewAgent(ABC, Generic[T]):

    def __init__(self, ai_client: AIClient, rule_loader: RuleLoaderService):
        self._client = ai_client
        self._rule_loader = rule_loader
        self._rules = None

    async def fetch_rules(self, framework: str = "spring"):
        self._rules = await self._rule_loader.load_rules(self._get_rule_groups(), framework)

    def _log_session_start(self, session_id: str, context: str = ""):
        """Log session creation with optional context."""
        agent_name = self._get_agent_name()
        if context:
            logger.info(f"[SESSION] {agent_name}: Creating session {session_id} {context}")
        else:
            logger.info(f"[SESSION] {agent_name}: Creating session {session_id}")

    @abstractmethod
    def _get_rule_groups(self) -> List[str]:
        pass

    def _build_base_system_prompt(self, agent_name: str, session_id: str) -> str:
        comment_format = get_comment_format_instruction(agent_name, session_id)

        return f"""You are a RixoAgent code reviewer specializing in {self._get_specialty()}.

{PERSONA}

STRICTLY Enforce ALL rules mentioned in this section and report ONLY violations of these explicit rules:
=== RULES TO ENFORCE ===

{self._rules}

=== END OF ENFORCEMENT RULES ===

{CRITICAL_REVIEW_INSTRUCTIONS}

{comment_format}"""

    @abstractmethod
    def _get_specialty(self) -> str:
        pass

    @abstractmethod
    def _get_response_schema(self) -> Type[T]:
        pass

    @abstractmethod
    def _get_agent_name(self) -> str:
        pass
