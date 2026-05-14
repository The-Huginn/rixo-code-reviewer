import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from claude_code_sdk.types import HookJSONOutput, HookContext

from src.client.azure import AzureDevOpsClient
from src.data.pending_comment import PendingComment

if TYPE_CHECKING:
    from src.service.pending_comments_pool import PendingCommentsPool

logger = logging.getLogger(__name__)


class CommentInterceptorHook:
    """
    PreToolUse hook that intercepts add_pr_comment MCP calls.

    Instead of letting the MCP tool post directly to Azure DevOps,
    this hook captures the comment and adds it to a pending pool.
    The actual posting happens later via batch publishing.
    """

    def __init__(
        self,
        pool: "PendingCommentsPool",
        agent_name: str,
        session_id: str,
        devops_client: AzureDevOpsClient,
        current_iteration: Optional[int] = None
    ):
        self.pool = pool
        self.agent_name = agent_name
        self.session_id = session_id
        self.devops = devops_client
        self.current_iteration = current_iteration

    async def __call__(
            self,
            input_data: Dict[str, Any],
            tool_use_id: str | None,
            context: HookContext
    ) -> HookJSONOutput:
        """
        Intercept add_pr_comment and add to pool instead of executing.

        Returns a synthetic success response to make the agent believe
        the comment was posted, while actually storing it for later.
        """
        logger.debug(f"[PENDING-POOL] Hook received input: {input_data}")

        # Tool parameters are nested inside 'tool_input' in the hook input data
        tool_input = input_data.get("tool_input", {})

        pr_url = tool_input.get("pr_url", "")
        file_path = tool_input.get("file_path", "")

        # Fetch diff eagerly
        diff = await self._fetch_diff(pr_url, file_path)

        comment = PendingComment(
            pr_url=pr_url,
            file_path=file_path,
            line_start=tool_input.get("line_start", 0),
            comment=tool_input.get("comment", ""),
            change_tracking_id=tool_input.get("change_tracking_id", 0),
            agent_name=self.agent_name,
            session_id=self.session_id,
            iteration=self.current_iteration,
            is_existing=False,
            diff=diff
        )

        comment_id = self.pool.add(comment)
        comment_text_preview = comment.comment[:100] + ("..." if len(comment.comment) > 100 else "")
        logger.info(
            f"[PENDING-POOL] Intercepted comment from {self.agent_name}: "
            f"file={comment.file_path}, line={comment.line_start}, "
            f"id={comment_id}, text={comment_text_preview}"
        )

        # PreToolUse hook format: deny the tool call and provide reason to Claude
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Comment intercepted and queued for batch publishing. "
                    f"ID: {comment_id}, File: {comment.file_path}:{comment.line_start}. "
                    f"Continue with your review - comment will be posted after duplicate check."
                )
            }
        }

    async def _fetch_diff(self, pr_url: str, file_path: str) -> str:
        """Fetch diff for a file, returning empty string on error."""
        try:
            if self.current_iteration:
                return await self.devops.get_file_diff_at_iteration(
                    pr_url, file_path, self.current_iteration
                )
            return await self.devops.get_file_diff(pr_url, file_path)
        except Exception as e:
            logger.warning(f"Failed to fetch diff for {file_path}: {e}")
            return ""
