import asyncio
import logging
from threading import Lock
from typing import Dict, List, Optional

from src.client.azure import AzureDevOpsClient
from src.data.pending_comment import PendingComment

logger = logging.getLogger(__name__)


class PendingCommentsPool:
    """
    Thread-safe pool for collecting pending comments before batch publishing.

    Uses two separate queues:
    - pending_check: Comments awaiting duplicate check
    - processed: Comments that have been checked (either confirmed unique or marked as duplicate)

    Pre-loaded existing comments go directly to processed set to serve as comparison baseline.
    """

    def __init__(self):
        self._pending_check: Dict[str, PendingComment] = {}  # Awaiting duplicate check
        self._processed: Dict[str, PendingComment] = {}  # Confirmed (duplicate or not)
        self._lock = Lock()

    def add_for_check(self, comment: PendingComment) -> str:
        """
        Add new comment to pending_check queue for duplicate detection.

        Args:
            comment: The comment to add

        Returns:
            The comment ID
        """
        with self._lock:
            self._pending_check[comment.id] = comment
            logger.info(
                f"[PENDING-POOL] Added comment {comment.id} to pending_check queue "
                f"(queue size: {len(self._pending_check)}, processed: {len(self._processed)})"
            )
            return comment.id

    async def load_existing_comments(
        self,
        pr_comments: List,
        devops_client: AzureDevOpsClient,
        pr_url: str
    ) -> None:
        """
        Pre-load existing comments with diffs directly to processed set (skip duplicate check).
        These serve as baseline for comparing new comments against.

        Args:
            pr_comments: List of PRComment objects from Azure DevOps
            devops_client: Client for fetching diffs
            pr_url: The PR URL for fetching diffs
        """
        # Fetch all diffs in parallel
        async def fetch_diff_for_comment(comment, iteration):
            try:
                if iteration:
                    return await devops_client.get_file_diff_at_iteration(
                        pr_url, comment.file_path, iteration
                    )
                return await devops_client.get_file_diff(pr_url, comment.file_path)
            except Exception as e:
                logger.warning(
                    f"Failed to fetch diff for existing comment on {comment.file_path}: {e}"
                )
                return ""

        # Prepare diff fetch tasks
        diff_tasks = []
        comment_data = []

        for pr_comment in pr_comments:
            iteration = None
            if pr_comment.iteration_context and isinstance(pr_comment.iteration_context, dict):
                iteration = (
                    pr_comment.iteration_context.get("firstComparingIteration") or
                    pr_comment.iteration_context.get("secondComparingIteration")
                )

            comment_data.append((pr_comment, iteration))
            diff_tasks.append(fetch_diff_for_comment(pr_comment, iteration))

        # Fetch all diffs in parallel
        diffs = await asyncio.gather(*diff_tasks, return_exceptions=True)

        # Create pending comments with diffs
        with self._lock:
            for (pr_comment, iteration), diff in zip(comment_data, diffs):
                # Handle exceptions that may have been raised in gather
                diff_content = "" if isinstance(diff, Exception) else (diff or "")

                pending = PendingComment(
                    pr_url="",  # Not needed for existing comments
                    file_path=pr_comment.file_path,
                    line_start=pr_comment.line,
                    comment=pr_comment.content,
                    change_tracking_id=pr_comment.change_tracking_id or 0,
                    agent_name="existing",
                    session_id="existing",
                    iteration=iteration,
                    is_existing=True,
                    thread_id=pr_comment.thread_id,
                    is_processed=True,  # Already processed (loaded from Azure)
                    diff=diff_content
                )
                self._processed[pending.id] = pending

            logger.info(
                f"[PENDING-POOL] Pre-loaded {len(pr_comments)} existing comments to processed set"
            )

    def get_pending_check(self) -> List[PendingComment]:
        """Get all comments awaiting duplicate check."""
        with self._lock:
            return list(self._pending_check.values())

    def get_processed(self) -> List[PendingComment]:
        """Get all processed comments (for comparison baseline)."""
        with self._lock:
            return list(self._processed.values())

    def move_to_processed(
        self,
        comment_id: str,
        is_duplicate: bool,
        duplicate_of: Optional[str] = None
    ) -> None:
        """
        Move comment from pending_check to processed after duplicate decision.

        Args:
            comment_id: ID of the comment to move
            is_duplicate: Whether the comment is a duplicate
            duplicate_of: ID of the original comment if duplicate
        """
        with self._lock:
            if comment_id not in self._pending_check:
                logger.warning(f"[PENDING-POOL] Comment {comment_id} not found in pending_check")
                return

            comment = self._pending_check.pop(comment_id)
            comment.is_duplicate = is_duplicate
            comment.duplicate_of = duplicate_of
            comment.is_processed = True
            self._processed[comment_id] = comment

            status = "DUPLICATE" if is_duplicate else "UNIQUE"
            logger.info(
                f"[PENDING-POOL] Moved comment {comment_id} to processed as {status} "
                f"(pending: {len(self._pending_check)}, processed: {len(self._processed)})"
            )

    def get_publishable(self) -> List[PendingComment]:
        """
        Get NEW, non-duplicate, processed comments for publishing.

        Returns:
            List of comments that should be published to Azure DevOps
        """
        with self._lock:
            publishable = [
                c for c in self._processed.values()
                if not c.is_duplicate and not c.is_existing
            ]
            total_processed = len(self._processed)
            existing = sum(1 for c in self._processed.values() if c.is_existing)
            duplicates = sum(1 for c in self._processed.values() if c.is_duplicate)

            logger.info(
                f"[PENDING-POOL] Publishable comments: {len(publishable)} "
                f"(total processed: {total_processed}, existing: {existing}, duplicates: {duplicates})"
            )
            return publishable

    def has_pending(self) -> bool:
        """Check if there are comments awaiting processing."""
        with self._lock:
            return len(self._pending_check) > 0

    # Legacy methods for backward compatibility
    def add(self, comment: PendingComment) -> str:
        """Legacy method - redirects to add_for_check."""
        return self.add_for_check(comment)

    def get_all(self) -> List[PendingComment]:
        """Get all comments (both pending and processed)."""
        with self._lock:
            all_comments = list(self._pending_check.values()) + list(self._processed.values())
            return all_comments

    def get_by_file(self, file_path: str) -> List[PendingComment]:
        """Get comments for a specific file (both pending and processed)."""
        with self._lock:
            all_comments = list(self._pending_check.values()) + list(self._processed.values())
            return [c for c in all_comments if c.file_path == file_path]

    def mark_duplicate(self, comment_id: str, duplicate_of: str) -> None:
        """Legacy method - mark a comment as duplicate."""
        with self._lock:
            # Check in pending_check first
            if comment_id in self._pending_check:
                self._pending_check[comment_id].is_duplicate = True
                self._pending_check[comment_id].duplicate_of = duplicate_of
            # Then check in processed
            elif comment_id in self._processed:
                self._processed[comment_id].is_duplicate = True
                self._processed[comment_id].duplicate_of = duplicate_of
            logger.info(f"[PENDING-POOL] Marked comment {comment_id} as duplicate of {duplicate_of}")

    def clear(self) -> None:
        """Clear all comments from the pool."""
        with self._lock:
            pending_count = len(self._pending_check)
            processed_count = len(self._processed)
            self._pending_check.clear()
            self._processed.clear()
            logger.info(
                f"[PENDING-POOL] Cleared pool (pending: {pending_count}, processed: {processed_count})"
            )

    def __len__(self) -> int:
        """Return total number of comments in the pool."""
        with self._lock:
            return len(self._pending_check) + len(self._processed)
