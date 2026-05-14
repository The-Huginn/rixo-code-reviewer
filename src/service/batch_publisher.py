import logging
from typing import List

from src.client.azure import AzureDevOpsClient
from src.data.pending_comment import PendingComment
from src.data.models import PublishResult
from src.service.pending_comments_pool import PendingCommentsPool

logger = logging.getLogger(__name__)


class BatchPublisher:
    """Publishes pending comments to Azure DevOps via HTTP in batch."""

    def __init__(self, devops_client: AzureDevOpsClient):
        self._devops = devops_client

    async def publish_all(self, pool: PendingCommentsPool) -> PublishResult:
        """
        Publish all non-duplicate comments from the pool via HTTP.

        Args:
            pool: PendingCommentsPool containing comments to publish

        Returns:
            PublishResult with success and failure counts
        """
        comments = pool.get_publishable()
        return await self._publish_comments(comments)

    async def _publish_comments(self, comments: List[PendingComment]) -> PublishResult:
        """
        Shared publishing logic for comments.

        Args:
            comments: List of PendingComment objects to publish

        Returns:
            PublishResult with success and failure counts
        """
        success_count = 0
        failure_count = 0

        if not comments:
            logger.info("[PENDING-POOL] No comments to publish")
            return PublishResult(success_count=0, failure_count=0)

        logger.info(f"[PENDING-POOL] Starting batch publish of {len(comments)} comments")

        for i, comment in enumerate(comments, 1):
            try:
                comment_preview = comment.comment[:80] + ("..." if len(comment.comment) > 80 else "")
                logger.info(
                    f"[PENDING-POOL] [{i}/{len(comments)}] Publishing comment {comment.id} "
                    f"from {comment.agent_name} to {comment.file_path}:{comment.line_start}, "
                    f"session={comment.session_id}, text={comment_preview}"
                )
                await self._devops.add_comment(
                    pr_url=comment.pr_url,
                    file_path=comment.file_path,
                    line=comment.line_start,
                    comment=comment.comment,
                    change_tracking_id=comment.change_tracking_id
                )
                success_count += 1
                logger.info(
                    f"[PENDING-POOL] Successfully published comment {comment.id} "
                    f"({success_count}/{len(comments)})"
                )
            except Exception as e:
                failure_count += 1
                logger.error(
                    f"[PENDING-POOL] Failed to publish comment {comment.id} "
                    f"from {comment.agent_name} (session={comment.session_id}): {e}"
                )

        logger.info(
            f"[PENDING-POOL] Batch publish complete: {success_count} successful, "
            f"{failure_count} failed out of {len(comments)} total"
        )

        return PublishResult(success_count=success_count, failure_count=failure_count)
