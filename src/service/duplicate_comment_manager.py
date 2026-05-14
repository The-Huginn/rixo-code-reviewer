import asyncio
import logging
from typing import Optional, List, Tuple

from src.agent.duplicate_comment_checker_agent import DuplicateCommentCheckerAgent
from src.client.embedding import EmbeddingClient
from src.data.pending_comment import PendingComment
from src.service.pending_comments_pool import PendingCommentsPool

logger = logging.getLogger(__name__)


class DuplicateCommentManager:
    """
    Background worker that processes pending comments for duplicate detection.

    Uses a tiered approach for efficient and accurate duplicate detection:
    1. Embedding similarity for fast pre-filtering (most cases resolved here)
    2. AI semantic verification for uncertain cases only

    This reduces API costs and latency while maintaining accuracy.
    """

    # Embedding similarity thresholds
    EMBED_DUPLICATE_THRESHOLD = 0.88  # Above this → definitely duplicate (skip AI)
    EMBED_UNIQUE_THRESHOLD = 0.60     # Below this → definitely unique (skip AI)

    # AI confidence threshold (for uncertain cases)
    AI_CONFIDENCE_THRESHOLD = 0.6

    def __init__(
        self,
        pool: PendingCommentsPool,
        checker: DuplicateCommentCheckerAgent,
        pr_url: str,
        embedding_client: Optional[EmbeddingClient] = None
    ):
        """
        Initialize the duplicate comment manager.

        Args:
            pool: Pool of pending and processed comments
            checker: AI-based duplicate checker agent (fallback)
            pr_url: PR URL for context
            embedding_client: Optional embedding client for similarity detection.
                              If not provided, falls back to AI-only mode.
        """
        self._pool = pool
        self._checker = checker
        self._pr_url = pr_url
        self._embeddings = embedding_client
        self._running = False
        self._task: Optional[asyncio.Task] = None

        if self._embeddings:
            logger.info("[DUPLICATE-MANAGER] Initialized with embedding-based similarity detection")
        else:
            logger.info("[DUPLICATE-MANAGER] Initialized in AI-only mode (no embedding client)")

    async def start(self) -> None:
        """Start background processing."""
        logger.info("[DUPLICATE-MANAGER] Starting background duplicate detection")
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Stop background processing."""
        logger.info("[DUPLICATE-MANAGER] Stopping background duplicate detection")
        self._running = False
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Clean up embedding client
        if self._embeddings:
            await self._embeddings.close()

    async def wait_for_completion(self, timeout: float = 300.0) -> None:
        """
        Wait until all pending comments are processed.

        Args:
            timeout: Maximum time to wait in seconds (default 5 minutes)
        """
        logger.info("[DUPLICATE-MANAGER] Waiting for all pending comments to be processed...")
        start_time = asyncio.get_event_loop().time()

        while self._pool.has_pending():
            if asyncio.get_event_loop().time() - start_time > timeout:
                pending_count = len(self._pool.get_pending_check())
                logger.warning(
                    f"[DUPLICATE-MANAGER] Timeout waiting for completion. "
                    f"{pending_count} comments still pending."
                )
                break
            await asyncio.sleep(0.1)

        logger.info("[DUPLICATE-MANAGER] All pending comments processed")

    async def _process_loop(self) -> None:
        """Main processing loop - runs until stopped and queue is empty."""
        while self._running or self._pool.has_pending():
            pending = self._pool.get_pending_check()

            if not pending:
                await asyncio.sleep(0.1)
                continue

            # Process each pending comment
            for comment in pending:
                await self._process_comment(comment)

        logger.info("[DUPLICATE-MANAGER] Processing loop finished")

    async def _process_comment(self, comment: PendingComment) -> None:
        """
        Process a single comment using tiered duplicate detection.

        Stage 1: Embedding similarity (fast, cheap)
        Stage 2: AI verification (only for uncertain cases)

        Args:
            comment: The comment to check for duplicates
        """
        logger.info(
            f"[DUPLICATE-MANAGER] Processing comment {comment.id} "
            f"({comment.file_path}:{comment.line_start})"
        )

        processed = self._pool.get_processed()

        # Filter to same file only (different files can't be duplicates)
        candidates = [
            c for c in processed
            if c.file_path == comment.file_path
        ]

        if not candidates:
            logger.info(
                f"[DUPLICATE-MANAGER] No existing comments on {comment.file_path}, marking as unique"
            )
            self._pool.move_to_processed(comment.id, is_duplicate=False)
            return

        logger.info(
            f"[DUPLICATE-MANAGER] Checking against {len(candidates)} existing comments on {comment.file_path}"
        )

        try:
            # Try embedding-based detection first (if available)
            if self._embeddings:
                decision, uncertain_candidates = await self._check_with_embeddings(comment, candidates)
                if decision is not None:
                    is_duplicate, duplicate_of = decision
                    self._pool.move_to_processed(comment.id, is_duplicate, duplicate_of)
                    return
                # Embedding was uncertain — forward only the uncertain candidates to AI
                await self._check_with_ai(comment, uncertain_candidates)
                return

            # No embeddings available — fall back to AI with all same-file candidates
            await self._check_with_ai(comment, candidates)

        except Exception as e:
            logger.error(
                f"[DUPLICATE-MANAGER] Error checking duplicates for {comment.id}: {e}"
            )
            # On error, mark as unique to avoid losing comments
            self._pool.move_to_processed(comment.id, is_duplicate=False)

    async def _check_with_embeddings(
        self,
        comment: PendingComment,
        candidates: List[PendingComment]
    ) -> Tuple[Optional[Tuple[bool, Optional[str]]], List[PendingComment]]:
        """
        Check for duplicates using embedding similarity.

        Returns:
            Tuple of (decision, uncertain_candidates) where:
              - decision is (is_duplicate, duplicate_of_id) if Tier 1 reached a verdict, else None.
              - uncertain_candidates is the subset of candidates whose similarity fell in
                the uncertain band [EMBED_UNIQUE_THRESHOLD, EMBED_DUPLICATE_THRESHOLD).
                Empty when a decision was reached. Forwarded to AI when decision is None.
        """
        try:
            # Find most similar candidates
            similar = await self._embeddings.find_most_similar(
                comment.comment,
                [c.comment for c in candidates],
                top_k=3
            )

            if not similar:
                logger.info(f"[DUPLICATE-MANAGER] [EMBEDDING] No similarity results, marking as unique")
                return (False, None), []

            best_idx, best_sim = similar[0]

            logger.info(
                f"[DUPLICATE-MANAGER] [EMBEDDING] Best similarity: {best_sim:.3f} "
                f"(thresholds: dup>{self.EMBED_DUPLICATE_THRESHOLD}, unique<{self.EMBED_UNIQUE_THRESHOLD})"
            )

            # High similarity → definitely duplicate
            if best_sim >= self.EMBED_DUPLICATE_THRESHOLD:
                duplicate_comment = candidates[best_idx]
                logger.info(
                    f"[DUPLICATE-MANAGER] [EMBEDDING] HIGH SIMILARITY ({best_sim:.3f}) → DUPLICATE "
                    f"of comment on line {duplicate_comment.line_start}"
                )
                return (True, duplicate_comment.id), []

            # Low similarity → definitely unique
            if best_sim < self.EMBED_UNIQUE_THRESHOLD:
                logger.info(
                    f"[DUPLICATE-MANAGER] [EMBEDDING] LOW SIMILARITY ({best_sim:.3f}) → UNIQUE"
                )
                return (False, None), []

            # Uncertain range → forward only the candidates in the uncertain band to AI
            uncertain = [
                candidates[idx] for idx, sim in similar
                if self.EMBED_UNIQUE_THRESHOLD <= sim < self.EMBED_DUPLICATE_THRESHOLD
            ]
            logger.info(
                f"[DUPLICATE-MANAGER] [EMBEDDING] UNCERTAIN ({best_sim:.3f}) → "
                f"forwarding {len(uncertain)} uncertain candidate(s) to AI"
            )
            return None, uncertain

        except Exception as e:
            logger.warning(
                f"[DUPLICATE-MANAGER] [EMBEDDING] Error during embedding check: {e}, "
                f"falling back to AI"
            )
            return None, candidates

    async def _check_with_ai(
        self,
        comment: PendingComment,
        candidates: List[PendingComment]
    ) -> None:
        """
        Check for duplicates using AI semantic analysis.

        Args:
            comment: The comment to check
            candidates: Candidate comments to compare against
        """
        logger.info(f"[DUPLICATE-MANAGER] [AI] Checking against {len(candidates)} candidates")

        result = await self._checker.check_against_all(comment, candidates, self._pr_url)

        is_duplicate = result.is_duplicate and result.confidence >= self.AI_CONFIDENCE_THRESHOLD
        duplicate_of = None

        if is_duplicate and result.duplicate_of_index is not None:
            if 0 <= result.duplicate_of_index < len(candidates):
                duplicate_comment = candidates[result.duplicate_of_index]
                duplicate_of = duplicate_comment.id
                logger.info(
                    f"[DUPLICATE-MANAGER] [AI] DUPLICATE of comment on line {duplicate_comment.line_start} "
                    f"(confidence: {result.confidence:.2f})"
                )
            else:
                logger.warning(
                    f"[DUPLICATE-MANAGER] [AI] Invalid duplicate_of_index {result.duplicate_of_index} "
                    f"(only {len(candidates)} candidates), treating as unique"
                )
                is_duplicate = False

        if not is_duplicate:
            logger.info(
                f"[DUPLICATE-MANAGER] [AI] UNIQUE (confidence: {result.confidence:.2f})"
            )

        self._pool.move_to_processed(comment.id, is_duplicate, duplicate_of)
