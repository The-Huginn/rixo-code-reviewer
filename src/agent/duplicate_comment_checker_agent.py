import logging
from typing import Optional, List

from pydantic import BaseModel

from src.client.ai import AIClient
from src.data.pending_comment import PendingComment

logger = logging.getLogger(__name__)


class DuplicateCheckResult(BaseModel):
    """Result of duplicate check - which existing comment (if any) is a duplicate."""
    is_duplicate: bool
    duplicate_of_index: Optional[int] = None  # Index in the candidates list (0-based)
    reasoning: str
    confidence: float  # 0.0 - 1.0


class DuplicateCommentCheckerAgent:
    """
    AI agent that compares a new code review comment against ALL existing comments.

    Provides full context of all existing comments so the AI can find the best match
    rather than comparing one-by-one without context.
    """

    def __init__(self, ai_client: AIClient):
        self._ai = ai_client

    def _get_agent_name(self) -> str:
        return "DuplicateCommentCheckerAgent"

    async def check_against_all(
        self,
        new_comment: PendingComment,
        existing_comments: List[PendingComment],
        pr_url: str
    ) -> DuplicateCheckResult:
        """
        Check if new_comment duplicates ANY of the existing comments.

        Args:
            new_comment: The newly created comment to check
            existing_comments: ALL existing comments to compare against
            pr_url: The PR URL (used for logging context only)

        Returns:
            DuplicateCheckResult with is_duplicate, duplicate_of_index, reasoning, confidence
        """
        session_id = self._ai.generate_session_id()
        agent_name = self._get_agent_name()

        logger.info(
            f"[{agent_name}] Checking comment on {new_comment.file_path}:{new_comment.line_start} "
            f"against {len(existing_comments)} existing comments"
        )

        # Use diff embedded in comment
        new_diff = new_comment.diff or ""

        # Build comparison prompt with ALL existing comments
        system_message = self._build_system_message()
        user_message = self._build_batch_comparison_prompt(
            new_comment, existing_comments, new_diff
        )

        try:
            result = await self._ai.structured_completion(
                system_message=system_message,
                user_message=user_message,
                response_schema=DuplicateCheckResult,
                session_id=session_id,
                allowed_tools=[],  # No tools needed for comparison
                model="haiku"  # Use fast model for duplicate checking
            )

            if result.is_duplicate and result.duplicate_of_index is not None:
                dup_comment = existing_comments[result.duplicate_of_index]
                logger.info(
                    f"[{agent_name}] DUPLICATE FOUND: comment on line {new_comment.line_start} "
                    f"duplicates existing comment #{result.duplicate_of_index} on line {dup_comment.line_start} "
                    f"(confidence: {result.confidence:.2f})"
                )
                logger.info(f"[{agent_name}] Reason: {result.reasoning[:200]}...")
            else:
                logger.info(
                    f"[{agent_name}] UNIQUE: comment on line {new_comment.line_start} "
                    f"(confidence: {result.confidence:.2f})"
                )

            return result

        except Exception as e:
            logger.error(f"[{agent_name}] Failed to check duplicate: {e}")
            # On error, assume not duplicate to avoid losing comments
            return DuplicateCheckResult(
                is_duplicate=False,
                duplicate_of_index=None,
                reasoning=f"Error during comparison: {e}",
                confidence=0.0
            )

    def _build_system_message(self) -> str:
        return """You are a SEMANTIC code review comment duplicate detector.

Your task: Given a NEW comment and a list of EXISTING comments, determine if the NEW comment
is a semantic duplicate of ANY existing comment.

## CRITICAL: Focus on SEMANTIC meaning, NOT word matching!

A comment is a DUPLICATE if it conveys the SAME CORE MESSAGE:
- Tells the developer to do the SAME THING (even with completely different words)
- Flags the SAME CODE ISSUE or smell (even if explained differently)
- The ACTION the developer should take is the same
- Example: "Use isNull() instead of == null" and "Don't compare with null directly, use isNull()" are DUPLICATES

A comment is NOT a duplicate only if:
- It addresses a genuinely DIFFERENT problem
- It requests a DIFFERENT action from the developer
- It concerns a different aspect (e.g., one about logic, another about naming)

## Key principle:
If a developer fixes one comment, would the other comment ALSO be resolved? If YES → DUPLICATE.

DO NOT consider as different just because:
- Wording is different
- One is longer/shorter
- One has more detail
- Line numbers differ slightly (code may have shifted)
- One uses code examples, other doesn't

## Response format:
{
  "is_duplicate": true/false,
  "duplicate_of_index": <0-based index of matching existing comment, or null if not duplicate>,
  "reasoning": "<brief explanation>",
  "confidence": <0.0-1.0>
}"""

    def _build_batch_comparison_prompt(
        self,
        new_comment: PendingComment,
        existing_comments: List[PendingComment],
        diff: str
    ) -> str:
        max_diff_length = 1500  # Reduced since we now show multiple diffs

        def truncate_diff(d: str) -> str:
            if not d:
                return "(no diff available)"
            return d[:max_diff_length] + "..." if len(d) > max_diff_length else d

        def truncate_comment(c: str, max_len: int = 1500) -> str:
            return c[:max_len] + "..." if len(c) > max_len else c

        # Build existing comments section with their diffs
        existing_section = ""
        for i, ec in enumerate(existing_comments):
            ec_diff = truncate_diff(ec.diff or "")
            ec_text = truncate_comment(ec.comment)
            existing_section += f"""
### EXISTING COMMENT #{i}
**Line:** {ec.line_start}
**Message:** {ec_text}
**Code context at time of comment:**
```
{ec_diff}
```
"""

        # New comment with its diff
        new_diff = truncate_diff(diff)
        new_comment_text = truncate_comment(new_comment.comment)

        prompt = f"""## FILE: {new_comment.file_path}

## NEW COMMENT TO CHECK
**Line:** {new_comment.line_start}
**Message:** {new_comment_text}
**Code context:**
```
{new_diff}
```

## EXISTING COMMENTS ON THIS FILE ({len(existing_comments)} total):
{existing_section}

## TASK:
Does the NEW COMMENT duplicate ANY of the existing comments semantically?
If yes, which one (by index)?

Note: Code context may differ between comments if the file was modified between iterations.
Focus on whether the comments address the SAME underlying issue, not whether the code looks identical.

Remember: Same MESSAGE = duplicate, even if different WORDS."""

        return prompt
