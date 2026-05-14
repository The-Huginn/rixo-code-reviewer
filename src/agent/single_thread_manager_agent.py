import json
import logging

from src.client.ai import AIClient
from src.config import PERSONA, PERSONA_EXAMPLES
from src.data import SingleThreadResult

logger = logging.getLogger(__name__)


class SingleThreadManagerAgent:
    """
    Manages a single PR comment thread.
    Checks if the reported issue has been fixed and resolves the thread accordingly.
    Only processes threads created by the bot itself.
    """

    def __init__(self, ai_client: AIClient):
        self._client = ai_client

    def _get_agent_name(self) -> str:
        return "SingleThreadManagerAgent"

    async def manage_thread(
            self, pr_url: str, thread: dict, current_diff: str, historical_diff: str
    ) -> SingleThreadResult:
        session_id = str(self._client.generate_session_id())
        agent_name = self._get_agent_name()

        logger.info(f"[SESSION] {agent_name}: Creating session {session_id} for thread {thread['thread_id']}")

        system_message = self._build_system_message(agent_name, session_id)
        user_message = self._build_user_message(pr_url, thread, current_diff, historical_diff)

        result = await self._client.structured_completion(
            system_message=system_message,
            user_message=user_message,
            response_schema=SingleThreadResult,
            session_id=session_id,
            allowed_tools=["mcp__rixo-dev-mcp__reply_to_pr_thread"]
        )

        result.thread_id = thread['thread_id']
        result.session_id = session_id

        logger.info(f"[SESSION] {agent_name}: Completed session {session_id} - thread {thread['thread_id']} resolved={result.resolved}")
        return result

    def _build_system_message(self, agent_name: str, session_id: str) -> str:
        return f"""You are the RIXO Single Thread Manager Agent. Your responsibility is to manage ONE specific PR comment thread by verifying if the reported issue has been fixed and resolving it accordingly.

**Scope:**
You ONLY manage threads created by the bot (yourself).

**Available Tools:**
- reply_to_pr_thread(pr_url, thread_id, comment, resolve): Reply to thread and optionally resolve it

**Understanding Diffs:**
Diffs appear between `--- DIFF ---` and `--- END DIFF ---` markers. Lines with `N+` = new code at line N. When comparing iterations, focus on CODE CONTENT, not line numbers (code shifts as files are edited).

**Thread Structure:**
The thread includes:
- `conversation`: Array of all comments (in order) with {{author, content}}. First is always the bot, subsequent are replies.

The bot's first comment footer contains a `Rationale:` line explaining which rule was violated and why. Use this rationale together with the comment to make your resolution decision.

**Decision Rules:**
When processing the thread, consider BOTH the conversation and code changes:

**Priority 1 - Check for author replies first:**
If thread has author replies disagreeing with the bot (e.g., "Ne", "To není pravda", "Nesouhlasím", author explaining why bot is wrong):
→ Reply: "Pardón, moje chyba." with resolve=True.

**Priority 2 - Check code changes:**
Compare historical diff vs current diff:
- **Issue fixed/improved** → Reply: "✅ Opraveno." with resolve=True
- **Issue NOT fixed / persists unchanged / unsure** → DO NOT REPLY AT ALL, just leave open (resolved=False)

**CRITICAL: Only reply when resolving or responding to author. Never post "still not fixed" or similar comments.**

{PERSONA}

{PERSONA_EXAMPLES}

**Output Format:**
{{
  "thread_id": <thread_id from input>,
  "resolved": true | false
}}

---
*Agent: {agent_name} | Session: `{session_id}`*"""

    def _build_user_message(
            self, pr_url: str, thread: dict, current_diff: str, historical_diff: str
    ) -> str:
        thread_json = json.dumps(thread, indent=2)

        return f"""Manage this single comment thread for PR: {pr_url}

Historical diff (when comment was made, iteration {thread.get('created_at_iteration')}):
--- DIFF ---
{historical_diff}
--- END DIFF ---

Thread to process:
{thread_json}

Current diff (latest):
--- DIFF ---
{current_diff}
--- END DIFF ---

Compare the code and apply decision rules to resolve or keep thread open.

Return result with thread_id={thread['thread_id']} and resolved status."""

    @staticmethod
    def prepare_thread_data(thread) -> dict:
        """
        Convert a PRComment object to a thread data dict for processing.

        Args:
            thread: PRComment object with thread data

        Returns:
            Dict with thread_id, file_path, line, created_at_iteration, change_tracking_id, conversation
        """
        if not thread.all_comments:
            raise ValueError(f"Thread {thread.thread_id} has no comments - this should not happen")

        conversation = [
            {
                "author": comment.get("author"),
                "content": comment.get("content")
            }
            for comment in thread.all_comments
        ]

        created_at_iteration = None
        if thread.iteration_context and isinstance(thread.iteration_context, dict):
            created_at_iteration = (
                thread.iteration_context.get("firstComparingIteration") or
                thread.iteration_context.get("secondComparingIteration")
            )

        return {
            "thread_id": thread.thread_id,
            "file_path": thread.file_path,
            "line": thread.line,
            "created_at_iteration": created_at_iteration,
            "change_tracking_id": thread.change_tracking_id,
            "conversation": conversation
        }
