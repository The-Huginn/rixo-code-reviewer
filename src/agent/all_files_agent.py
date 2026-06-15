from abc import ABC, abstractmethod
from typing import TypeVar, Type, List, Optional
from claude_code_sdk.types import HookMatcher
from pydantic import BaseModel
from src.agent import BaseReviewAgent
from src.client.azure import FileChange, AzureDevOpsClient
from src.config import GROUPING_SIMILAR_ISSUES, DIFF_FORMAT_EXPLANATION, RAG_QUERY_GUIDANCE, CYPHER_QUERY_GUIDANCE
from src.hooks.comment_interceptor import CommentInterceptorHook
from src.service.pending_comments_pool import PendingCommentsPool

T = TypeVar('T', bound=BaseModel)

# Model override for per-PR/architecture agents
PER_PR_MODEL = "opus"

_KB_TOOLS = [
    "mcp__rixo-dev-mcp__query_codebase_rag",
    "mcp__rixo-dev-mcp__query_codebase_cypher",
]


class AllFilesAgent(BaseReviewAgent[T], ABC):

    async def review_pr(
            self,
            pr_url: str,
            changed_files: List[FileChange],
            devops_client: AzureDevOpsClient,
            pending_pool: Optional[PendingCommentsPool] = None,
            current_iteration: Optional[int] = None,
            kb_available: bool = True
    ) -> T:
        agent_name = self._get_agent_name()
        session_id = str(self._client.generate_session_id())

        system_message = self._build_system_message(agent_name, session_id, kb_available=kb_available)
        user_message = self._build_user_message(pr_url, changed_files)

        self._log_session_start(session_id, "for PR review")

        hooks = None
        if pending_pool:
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

        allowed_tools = ["mcp__rixo-dev-mcp__add_pr_comment", "mcp__rixo-dev-mcp__get_pr_file_diff"]
        if kb_available:
            allowed_tools.extend(_KB_TOOLS)

        result = await self._client.structured_completion(
            system_message=system_message,
            user_message=user_message,
            response_schema=self._get_response_schema(),
            session_id=session_id,
            allowed_tools=allowed_tools,
            model=PER_PR_MODEL,
            hooks=hooks
        )

        # Set session_id in result for logging
        result.session_id = session_id

        return result

    def _build_system_message(self, agent_name: str, session_id: str, kb_available: bool = True) -> str:
        base_prompt = self._build_base_system_prompt(agent_name, session_id, kb_available=kb_available)

        kb_tools_section = ""
        kb_guidance_section = ""
        if kb_available:
            kb_tools_section = (
                "\n- query_codebase_rag(query, query_context, repo_name, time_budget): Query codebase for broader context (agentic, slower)"
                "\n- query_codebase_cypher(query, repo_name): Fast structured queries for relationships and patterns"
            )
            kb_guidance_section = f"\n\n{RAG_QUERY_GUIDANCE}\n\n{CYPHER_QUERY_GUIDANCE}"

        return f"""{base_prompt}

{DIFF_FORMAT_EXPLANATION}

**Available Tools:**
- get_pr_file_diff(pr_url, file_path): Retrieve diff for a specific file
- add_pr_comment(pr_url, file_path, line_start, comment, change_tracking_id): Post inline comment{kb_tools_section}{kb_guidance_section}

**Review Strategy:**
1. Use get_pr_file_diff() to fetch diffs for files you need to review
2. For each issue found, call add_pr_comment

After reviewing, return JSON summary with issues_posted count."""

    def _build_user_message(self, pr_url: str, changed_files: List[FileChange]) -> str:
        files_list = "\n".join([
            f"- {f.path} (type: {f.change_type}, tracking_id: {f.change_tracking_id})"
            for f in changed_files
        ])

        return f"""PR URL: {pr_url}

Changed files in this PR:
{files_list}

**Your Task:**
Review this PR for {self._get_specialty()} issues.

Use get_pr_file_diff(pr_url="{pr_url}", file_path="<path>") to retrieve specific file diffs.
You should explore files strategically to understand the full architectural context.

{GROUPING_SIMILAR_ISSUES}

For each violation or GROUP of similar violations found, call:
add_pr_comment(
    pr_url="{pr_url}",
    file_path="<file_path>",
    line=<exact_line_of_issue>,
    comment=<formatted_comment_with_metadata_footer>,
    changeTrackingId=<tracking_id_from_file_list>
)

After reviewing, return JSON summary with issues_posted count."""

    @abstractmethod
    def _get_specialty(self) -> str:
        pass

    @abstractmethod
    def _get_response_schema(self) -> Type[T]:
        pass

    @abstractmethod
    def _get_agent_name(self) -> str:
        pass
