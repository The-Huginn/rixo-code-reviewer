import logging
import re
from abc import ABC, abstractmethod
from typing import TypeVar, Optional

from claude_code_sdk.types import HookMatcher
from pydantic import BaseModel
from src.agent import BaseReviewAgent
from src.client.azure import AzureDevOpsClient
from src.config import (
    SINGLE_FILE_CONTEXT_NOTICE,
    DIFF_FORMAT_EXPLANATION,
    GROUPING_SIMILAR_ISSUES,
    RAG_QUERY_GUIDANCE,
    CYPHER_QUERY_GUIDANCE
)
from src.hooks.comment_interceptor import CommentInterceptorHook
from src.service.pending_comments_pool import PendingCommentsPool

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

_KB_TOOLS = [
    "mcp__rixo-dev-mcp__query_codebase_rag",
    "mcp__rixo-dev-mcp__query_codebase_cypher",
]


class SingleFileAgent(BaseReviewAgent[T], ABC):

    @abstractmethod
    def _get_file_pattern(self) -> Optional[str]:
        return None

    def should_review_file(self, file_path: str) -> bool:
        pattern = self._get_file_pattern()
        if pattern is None:
            return True
        return bool(re.search(pattern, file_path))

    def _build_system_message(self, agent_name: str, session_id: str) -> str:
        base_prompt = self._build_base_system_prompt(agent_name, session_id)

        return f"""{base_prompt}

{SINGLE_FILE_CONTEXT_NOTICE}

**Available Tools:**
- add_pr_comment(pr_url, file_path, line, comment, changeTrackingId): Post inline comment to PR
- query_codebase_rag(query, query_context, repo_name, time_budget): Query codebase for broader context (agentic, slower)
- query_codebase_cypher(query, repo_name): Fast structured queries for relationships and patterns

{RAG_QUERY_GUIDANCE}

{CYPHER_QUERY_GUIDANCE}

For each clear violation of the ENFORCEMENT RULES, call add_pr_comment immediately with the formatted comment including metadata footer."""

    async def review(
            self,
            file_path: str,
            diff: str,
            pr_url: str,
            change_tracking_id: int,
            devops_client: AzureDevOpsClient,
            all_files: list[str] = None,
            pending_pool: Optional[PendingCommentsPool] = None,
            current_iteration: Optional[int] = None,
            kb_available: bool = True
    ) -> T:
        session_id = self._client.generate_session_id()
        agent_name = self._get_agent_name()

        system_message = self._build_system_message(agent_name, session_id)
        user_message = self._build_file_review_message(
            file_path, diff, pr_url, change_tracking_id, all_files
        )

        self._log_session_start(session_id, f"for file {file_path}")

        hooks = None
        if pending_pool is not None:
            interceptor = CommentInterceptorHook(
                pending_pool, agent_name, session_id, devops_client, current_iteration
            )
            hooks = {
                "PreToolUse": [
                    HookMatcher(
                        matcher="mcp__rixo-dev-mcp__add_pr_comment",
                        hooks=[interceptor]
                    )
                ]
            }

        allowed_tools = ["mcp__rixo-dev-mcp__add_pr_comment"]
        if kb_available:
            allowed_tools.extend(_KB_TOOLS)

        result = await self._client.structured_completion(
            system_message=system_message,
            user_message=user_message,
            response_schema=self._get_response_schema(),
            session_id=session_id,
            allowed_tools=allowed_tools,
            hooks=hooks
        )

        result.session_id = session_id

        return result

    def _build_file_review_message(
            self,
            file_path: str,
            diff: str,
            pr_url: str,
            change_tracking_id: int,
            all_files: list[str] = None
    ) -> str:
        files_section = ""
        if all_files:
            files_list = "\n".join(f"  - {f}" for f in all_files)
            files_section = f"""

All files changed in this PR:
{files_list}

Use this list to infer relationships (e.g., interface/implementation pairs, test files, related components)."""

        return f"""File: {file_path}

PR Context:
- PR URL: {pr_url}
- Change Tracking ID: {change_tracking_id}{files_section}

Changes (diff):
--- DIFF WITH LINE NUMBERS ---
{diff}
--- END DIFF ---

{DIFF_FORMAT_EXPLANATION}

{GROUPING_SIMILAR_ISSUES}

For each issue or GROUP of similar issues found, call:
add_pr_comment(
    pr_url="{pr_url}",
    file_path="{file_path}",
    line=<exact_line_number_of_issue>,
    comment=<formatted_comment_with_metadata_footer>,
    changeTrackingId={change_tracking_id}
)

After reviewing, return JSON summary with issues_posted count."""
