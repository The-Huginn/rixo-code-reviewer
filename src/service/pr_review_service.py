import asyncio
import logging
import re
from datetime import datetime
from threading import Lock
from typing import List, Optional, Dict, TYPE_CHECKING

from src.agent.duplicate_comment_checker_agent import DuplicateCommentCheckerAgent
from src.client.azure import AzureDevOpsClient, FileChange, PRComment
from src.client.embedding import EmbeddingClient
from src.data import ReviewSummary, ReviewState, ReviewStatus, ReviewResult
from src.service.batch_publisher import BatchPublisher
from src.service.cached_file_service import CachedFileService
from src.service.duplicate_comment_manager import DuplicateCommentManager
from src.service.indexed_repo_service import IndexedRepoService
from src.service.pending_comments_pool import PendingCommentsPool

if TYPE_CHECKING:
    from src.agent import SingleFileAgent, AllFilesAgent, SingleThreadManagerAgent
from src.config import config
from src.constants import (
    VOTE_APPROVE,
    VOTE_WAIT_FOR_AUTHOR,
    VOTE_REJECT,
    VOTE_RESET,
    CHANGE_TYPE_DELETE,
    MASTER_BRANCH_WARNING_MESSAGE,
    DEVELOP_BRANCH_INFO_MESSAGE
)

logger = logging.getLogger(__name__)


class PRReviewService:
    # Authors whose PRs should be skipped. Configured in application.yml (review.ignored_authors).
    IGNORED_AUTHORS = frozenset(config.review.ignored_authors)

    # Branch patterns for skipping code review (source_pattern, target_pattern)
    # Skip if source matches pattern and target is the specified branch
    SKIP_BRANCH_PATTERNS = [
        # feature/*, release/*, hotfix/* -> develop
        (r"^refs/heads/(feature|release|hotfix)/", "develop"),
        # release/*, hotfix/* -> master
        (r"^refs/heads/(release|hotfix)/", "master"),
    ]

    # Repository whitelist — only PRs from these repositories will be reviewed.
    # Configured in application.yml (review.allowed_repositories). Empty = deny-by-default.
    ALLOWED_REPOSITORIES = frozenset(config.review.allowed_repositories)

    def __init__(
            self,
            devops_client: AzureDevOpsClient,
            per_file_agents: List["SingleFileAgent"],
            per_pr_agents: List["AllFilesAgent"] = None,
            single_thread_manager: Optional["SingleThreadManagerAgent"] = None,
            ai_client=None,
            indexed_repo_service: Optional[IndexedRepoService] = None
    ):
        self.devops = devops_client
        self.per_file_agents = per_file_agents
        self.per_pr_agents = per_pr_agents or []
        self.single_thread_manager = single_thread_manager
        self._ai_client = ai_client
        self._indexed_repo_service = indexed_repo_service
        self._session_semaphore = asyncio.Semaphore(config.app.max_parallel_sessions)
        self._file_locks = {}
        self._states: Dict[str, ReviewState] = {}
        self._state_lock = Lock()

    @staticmethod
    def _extract_pr_number(pr_url: str) -> str:
        match = re.search(r'/pullrequest/(\d+)', pr_url)
        if not match:
            raise ValueError(f"Could not extract PR number from URL: {pr_url}")
        return match.group(1)

    def _should_skip_review(self, pr_details) -> bool:
        """Check if code review should be skipped for this PR."""
        # Skip if repository is not in whitelist
        if pr_details.repository and pr_details.repository not in self.ALLOWED_REPOSITORIES:
            logger.info(f"[REVIEW] Repository '{pr_details.repository}' not in whitelist, skipping")
            return True

        if pr_details.author in self.IGNORED_AUTHORS:
            return True

        source = pr_details.source_branch
        target = pr_details.target_branch.lower()

        for source_pattern, target_branch in self.SKIP_BRANCH_PATTERNS:
            if target_branch in target and re.match(source_pattern, source):
                return True

        return False

    def get_review_state(self, pr_url: str) -> Optional[ReviewState]:
        try:
            pr_number = self._extract_pr_number(pr_url)
            with self._state_lock:
                return self._states.get(pr_number)
        except ValueError:
            return None

    def can_start_review(self, pr_url: str) -> bool:
        try:
            pr_number = self._extract_pr_number(pr_url)
            with self._state_lock:
                existing = self._states.get(pr_number)
                return not (existing and existing.status == ReviewStatus.IN_PROGRESS)
        except ValueError:
            return False

    async def review_pr(self, pr_url: str) -> ReviewResult:
        """
        Main orchestrator for PR review process.

        This method coordinates the entire review workflow:
        1. State management (start/complete/fail)
        2. Target branch checking (master/develop warnings)
        3. Thread manager execution
        4. Code review agents execution
        5. Verdict calculation
        6. Approval setting
        """
        logger.info(f"[REVIEW START] PR URL: {pr_url}")

        pr_number = self._extract_pr_number(pr_url)
        with self._state_lock:
            state = ReviewState(
                pr_url=pr_url,
                status=ReviewStatus.IN_PROGRESS,
                started_at=datetime.now()
            )
            self._states[pr_number] = state
            logger.info(f"[REVIEW STATE] Started review for PR #{pr_number}")

        try:
            pr_details = await self.devops.get_pr_details(pr_url)

            if self._should_skip_review(pr_details):
                logger.info(f"[REVIEW SKIPPED] PR #{pr_details.pr_id}: {pr_details.source_branch} -> {pr_details.target_branch}")
                with self._state_lock:
                    state = self._states.get(pr_number)
                    if state:
                        state.status = ReviewStatus.COMPLETED
                        state.result = ReviewResult(issues=0, vote=VOTE_APPROVE)
                        state.completed_at = datetime.now()
                return ReviewResult(issues=0, vote=VOTE_APPROVE)

            # Check if the PR's repository is indexed in the knowledge base
            kb_available = True
            if self._indexed_repo_service and pr_details.repository:
                kb_available = await self._indexed_repo_service.is_repo_indexed(
                    pr_details.repository
                )
                if not kb_available:
                    logger.info(
                        f"[REVIEW] Repository '{pr_details.repository}' not indexed in KB, "
                        f"skipping KB tools for this review"
                    )

            # Reset vote to signal review has started
            await self._reset_vote(pr_url, pr_details.status)

            files = await self.devops.get_pr_files(pr_url)
            existing_comments = await self.devops.get_comments(pr_url)
            file_service = CachedFileService(pr_url, self.devops)

            logger.info(f"[REVIEW] PR #{pr_details.pr_id}: {pr_details.title}")
            logger.info(f"[REVIEW] Files changed: {len(files)}")
            logger.info(f"[REVIEW] Existing comments: {len(existing_comments)}")

            master_branch_warning_posted = await self._check_target_branch(
                pr_url, pr_details, files, existing_comments
            )

            # Fetch all bot comments (including resolved) for thread management and suppression
            all_bot_comments = await self.devops.get_bot_comments(pr_url, include_resolved=True)
            active_bot_comments = [c for c in all_bot_comments if not c.is_resolved]
            resolved_bot_comments = [c for c in all_bot_comments if c.is_resolved]

            false_positive_comments = [c for c in resolved_bot_comments if self._is_false_positive(c)]
            fixed_by_author = len(resolved_bot_comments) - len(false_positive_comments)

            logger.info(
                f"[REVIEW] Bot comments: {len(active_bot_comments)} active, "
                f"{len(false_positive_comments)} false positives (suppressed), "
                f"{fixed_by_author} fixed by author"
            )

            thread_manager_verdict = await self._run_thread_manager(pr_url, active_bot_comments, file_service)

            # Pass ALL bot comments (including resolved) for comprehensive duplicate detection
            await self._run_code_review_agents(
                pr_url, files, all_bot_comments, file_service,
                kb_available=kb_available
            )

            current_unresolved = await self.devops.get_bot_comments(pr_url, include_resolved=False)
            total_unresolved_issues = len(current_unresolved)
            logger.info(f"[REVIEW] Post-publish unresolved bot comments: {total_unresolved_issues}")

            vote = self._calculate_final_verdict(
                thread_manager_verdict, total_unresolved_issues, master_branch_warning_posted
            )
            await self._set_pr_approval(pr_url, vote, pr_details.status)

            logger.info(f"[REVIEW COMPLETE] PR #{pr_details.pr_id}")

            with self._state_lock:
                state = self._states.get(pr_number)
                if state:
                    state.status = ReviewStatus.COMPLETED
                    state.result = ReviewResult(issues=total_unresolved_issues, vote=vote)
                    state.completed_at = datetime.now()
                    logger.info(
                        f"[REVIEW STATE] Completed review for PR #{pr_number}: {total_unresolved_issues} issues, vote={vote}")

            return ReviewResult(issues=total_unresolved_issues, vote=vote)

        except Exception as e:
            logger.error(f"[REVIEW FAILED] {e}")

            with self._state_lock:
                state = self._states.get(pr_number)
                if state:
                    state.status = ReviewStatus.FAILED
                    state.error = str(e)
                    state.completed_at = datetime.now()
                    logger.error(f"[REVIEW STATE] Failed review for PR #{pr_number}: {e}")

            raise

    async def _check_target_branch(
            self,
            pr_url: str,
            pr_details, files: List[FileChange],
            existing_comments: List
    ) -> bool:
        if not pr_details.target_branch or not files or len(files) == 0:
            return False

        target_branch_lower = pr_details.target_branch.lower()
        first_file = files[0]

        if "master" in target_branch_lower:
            logger.warning(f"[REVIEW] PR targets master branch: {pr_details.target_branch}")
            try:
                existing_warnings = [c for c in existing_comments
                                     if c.file_path == first_file.path
                                     and c.line == 1
                                     and MASTER_BRANCH_WARNING_MESSAGE in c.content]

                if not existing_warnings:
                    logger.info(f"[REVIEW] Posting master branch warning to {first_file.path}:1")
                    await self.devops.add_comment(
                        pr_url, first_file.path, 1, MASTER_BRANCH_WARNING_MESSAGE, first_file.change_tracking_id
                    )
                    return True
                else:
                    logger.info(f"[REVIEW] Master branch warning already exists, skipping")
            except Exception as e:
                logger.error(f"[REVIEW] Failed to post master branch warning: {e}")

        elif "develop" in target_branch_lower:
            logger.info(f"[REVIEW] PR targets develop branch: {pr_details.target_branch}")
            try:
                existing_warnings = [c for c in existing_comments
                                     if c.file_path == first_file.path
                                     and c.line == 1
                                     and DEVELOP_BRANCH_INFO_MESSAGE in c.content]

                if not existing_warnings:
                    logger.info(f"[REVIEW] Posting develop branch info message to {first_file.path}:1")
                    await self.devops.add_comment(
                        pr_url, first_file.path, 1, DEVELOP_BRANCH_INFO_MESSAGE, first_file.change_tracking_id
                    )
                else:
                    logger.info(f"[REVIEW] Develop branch info message already exists, skipping")
            except Exception as e:
                logger.error(f"[REVIEW] Failed to post develop branch info message: {e}")

        return False

    async def _run_thread_manager(
            self, pr_url: str, active_bot_comments: List, file_service: CachedFileService
    ) -> str:
        if not self.single_thread_manager:
            return VOTE_APPROVE

        logger.info(f"[REVIEW] Found {len(active_bot_comments)} active bot comments")

        if len(active_bot_comments) == 0:
            logger.info(f"[REVIEW] No active bot comments to process, skipping thread manager")
            return VOTE_APPROVE

        logger.info(f"[REVIEW] Running {len(active_bot_comments)} single thread managers in parallel...")

        from src.agent.single_thread_manager_agent import SingleThreadManagerAgent
        thread_data_list = [
            SingleThreadManagerAgent.prepare_thread_data(comment)
            for comment in active_bot_comments
        ]

        async def process_single_thread(thread_data: dict):
            if "created_at_iteration" not in thread_data or thread_data["created_at_iteration"] is None:
                raise ValueError(f"Thread {thread_data['thread_id']} missing created_at_iteration")

            current_diff = await file_service.get_diff(thread_data["file_path"])
            historical_diff = await file_service.get_diff_at_iteration(
                thread_data["file_path"],
                thread_data["created_at_iteration"]
            )

            async with self._session_semaphore:
                return await self.single_thread_manager.manage_thread(
                    pr_url, thread_data, current_diff, historical_diff
                )

        tasks = [process_single_thread(td) for td in thread_data_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        threads_processed = 0
        threads_resolved = 0
        errors = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[REVIEW] Thread {thread_data_list[i]['thread_id']} failed: {result}")
                errors.append(result)
            else:
                threads_processed += 1
                if result.resolved:
                    threads_resolved += 1
                    logger.info(f"[REVIEW] Thread {result.thread_id} resolved (session: {result.session_id})")
                else:
                    logger.info(f"[REVIEW] Thread {result.thread_id} kept open (session: {result.session_id})")

        unresolved_issues = threads_processed - threads_resolved

        logger.info(
            f"[REVIEW] Thread manager: {threads_processed} processed, "
            f"{threads_resolved} resolved, {unresolved_issues} unresolved"
        )

        # Determine verdict based on unresolved threads
        if unresolved_issues > 0:
            thread_manager_verdict = VOTE_WAIT_FOR_AUTHOR
        else:
            thread_manager_verdict = VOTE_APPROVE

        logger.info(f"[REVIEW] Thread manager verdict: {thread_manager_verdict}")
        return thread_manager_verdict

    async def _run_code_review_agents(
            self, pr_url: str, files: List[FileChange], all_bot_comments: List[PRComment],
            file_service: CachedFileService, kb_available: bool = True
    ) -> None:
        """
        Run code review agents with enhanced duplicate detection.

        Flow:
        1. Create pending pool and pre-load existing comments
        2. Start background duplicate manager
        3. Run agents (comments intercepted → added to pending_check)
        4. Wait for duplicate checks to complete
        5. Batch publish unique comments
        """
        # 1. Create components
        pending_pool = PendingCommentsPool()

        logger.info("[PENDING-POOL] Created pending pool for PR review")

        # Pre-load ALL bot comments (active + resolved) for comprehensive duplicate detection
        if all_bot_comments:
            await pending_pool.load_existing_comments(
                all_bot_comments,
                self.devops,
                pr_url
            )
            active_count = len([c for c in all_bot_comments if not c.is_resolved])
            resolved_count = len([c for c in all_bot_comments if c.is_resolved])
            logger.info(
                f"[PENDING-POOL] Pre-loaded {len(all_bot_comments)} existing comments "
                f"({active_count} active, {resolved_count} resolved)"
            )

        # 2. Create and start duplicate manager (if AI client available)
        duplicate_manager = None
        if self._ai_client:
            checker = DuplicateCommentCheckerAgent(self._ai_client)

            # Create embedding client for fast similarity detection (if configured)
            embedding_client = None
            if config.embedding.endpoint:
                embedding_client = EmbeddingClient(
                    endpoint=config.embedding.endpoint,
                    model=config.embedding.model,
                    api_key=config.embedding.api_key,
                    ssl_cert_path=config.embedding.ssl_cert_path
                )
                logger.info(
                    f"[DUPLICATE-MANAGER] Embedding client initialized: "
                    f"{config.embedding.endpoint}, model={config.embedding.model}"
                )

            duplicate_manager = DuplicateCommentManager(
                pending_pool, checker, pr_url, embedding_client
            )
            await duplicate_manager.start()
            logger.info("[DUPLICATE-MANAGER] Started background duplicate detection")

        try:
            # 3. Run per-file agents
            active_files = [f for f in files if f.change_type != CHANGE_TYPE_DELETE]
            logger.info(
                f"[REVIEW] Running {len(self.per_file_agents)} agents on {len(active_files)} files..."
            )

            # Current iteration - fetched once for all agents
            # Note: Azure DevOps API doesn't expose iteration count in PR details directly
            # For now, use None (comments will still work, just without iteration context)
            current_iteration = None

            for agent in self.per_file_agents:
                agent_name = type(agent).__name__

                await self._review_agent_on_files(
                    pr_url, agent, active_files, pending_pool, current_iteration, file_service,
                    kb_available=kb_available
                )

                pool_size = len(pending_pool)
                logger.info(f"[REVIEW] Agent {agent_name} completed: {pool_size} comments in pool")

            # 4. Run per-PR agents
            if self.per_pr_agents:
                logger.info(f"[REVIEW] Running {len(self.per_pr_agents)} per-PR agents...")

                await self._review_pr_parallel(
                    pr_url, files, pending_pool, current_iteration,
                    kb_available=kb_available
                )

                pool_size = len(pending_pool)
                logger.info(f"[REVIEW] Per-PR agents completed: {pool_size} comments in pool")

            # 5. Wait for duplicate detection to complete
            if duplicate_manager:
                logger.info("[DUPLICATE-MANAGER] Waiting for duplicate detection to complete...")
                await duplicate_manager.wait_for_completion()

        finally:
            # Stop duplicate manager
            if duplicate_manager:
                await duplicate_manager.stop()

        publisher = BatchPublisher(self.devops)
        result = await publisher.publish_all(pending_pool)

        logger.info(
            f"[PENDING-POOL] Final summary: {result.success_count} published, {result.failure_count} failed"
        )

    def _calculate_final_verdict(
            self,
            thread_manager_verdict: str,
            total_issues: int,
            master_warning_posted: bool
    ) -> str:
        code_review_verdict = VOTE_APPROVE
        if total_issues > 0 or master_warning_posted:
            code_review_verdict = VOTE_WAIT_FOR_AUTHOR

        if thread_manager_verdict == VOTE_REJECT or code_review_verdict == VOTE_REJECT:
            vote = VOTE_REJECT
        elif thread_manager_verdict == VOTE_WAIT_FOR_AUTHOR or code_review_verdict == VOTE_WAIT_FOR_AUTHOR:
            vote = VOTE_WAIT_FOR_AUTHOR
        else:
            vote = VOTE_APPROVE

        logger.info(
            f"[REVIEW] Final verdict: {vote} (thread_manager={thread_manager_verdict}, code_review={code_review_verdict})"
        )

        return vote

    async def _reset_vote(self, pr_url: str, pr_status: str) -> None:
        """Reset vote to signal review has started."""
        if pr_status != "active":
            logger.info(f"[REVIEW] Skipping vote reset for non-active PR (status: {pr_status})")
            return

        logger.info(f"[REVIEW] Resetting vote to signal review started")
        try:
            await self.devops.set_approval(pr_url, VOTE_RESET)
            logger.info(f"[REVIEW] Vote reset successfully")
        except Exception as e:
            logger.warning(f"[REVIEW] Warning: Could not reset vote: {e}")

    async def _set_pr_approval(self, pr_url: str, vote: str, pr_status: str) -> None:
        if pr_status != "active":
            logger.info(f"[REVIEW] Skipping approval for non-active PR (status: {pr_status})")
            return

        logger.info(f"[REVIEW] Attempting to set approval: {vote}")
        try:
            await self.devops.set_approval(pr_url, vote)
            logger.info(f"[REVIEW] Set approval vote: {vote}")
        except Exception as e:
            logger.warning(f"[REVIEW] Warning: Could not set approval (PR might be closed): {e}")

    def _get_file_lock(self, file_path: str) -> asyncio.Lock:
        if file_path not in self._file_locks:
            self._file_locks[file_path] = asyncio.Lock()
        return self._file_locks[file_path]

    @staticmethod
    def _is_false_positive(comment: "PRComment") -> bool:
        """
        Determine if a resolved comment was dismissed as false positive by a reviewer.

        Logic:
        - If resolved with ONLY the bot's comment (no replies) → reviewer clicked Resolve
          without engaging → FALSE POSITIVE (suppress)
        - If resolved with replies → author engaged/fixed → NOT false positive (can re-flag)
        """
        if not comment.all_comments or len(comment.all_comments) <= 1:
            logger.debug(
                f"[FALSE-POSITIVE] thread_id={comment.thread_id}: "
                f"Resolved with no replies → FALSE POSITIVE (suppressed)"
            )
            return True

        logger.debug(
            f"[FALSE-POSITIVE] thread_id={comment.thread_id}: "
            f"{len(comment.all_comments)} comments in thread → author engaged, NOT false positive"
        )
        return False

    async def _review_agent_on_files(
            self,
            pr_url: str,
            agent: "SingleFileAgent",
            files: List[FileChange],
            pending_pool: PendingCommentsPool,
            current_iteration: Optional[int],
            file_service: CachedFileService,
            kb_available: bool = True
    ) -> List[ReviewSummary]:
        agent_name = type(agent).__name__

        files_to_review = [f for f in files if agent.should_review_file(f.path)]
        skipped_count = len(files) - len(files_to_review)

        logger.info(
            f"[AGENT-FIRST] {agent_name} starting review on {len(files_to_review)} files "
            f"(skipped {skipped_count})"
        )

        if skipped_count > 0:
            logger.debug(f"[AGENT-FIRST] {agent_name} skipped {skipped_count} files based on pattern")

        all_file_paths = [f.path for f in files]

        review_tasks = [
            self._review_single_file(
                pr_url, agent, file, agent_name, all_file_paths, pending_pool, current_iteration, file_service,
                kb_available=kb_available
            )
            for file in files_to_review
        ]

        results = await asyncio.gather(*review_tasks)

        summaries = []
        for i, result in enumerate(results):
            summaries.append(result)
            if result.issues_posted > 0:
                session_info = f" session={result.session_id}" if result.session_id else ""
                logger.info(
                    f"[AGENT-FIRST] {agent_name} completed {files_to_review[i].path}: "
                    f"{result.issues_posted} issues{session_info}"
                )

        logger.info(
            f"[AGENT-FIRST] {agent_name} completed: {sum(s.issues_posted for s in summaries)} "
            f"total issues"
        )
        return summaries

    async def _review_single_file(
            self,
            pr_url: str,
            agent: "SingleFileAgent",
            file: FileChange,
            agent_name: str,
            all_file_paths: List[str],
            pending_pool: PendingCommentsPool,
            current_iteration: Optional[int],
            file_service: CachedFileService,
            kb_available: bool = True
    ) -> ReviewSummary:
        file_lock = self._get_file_lock(file.path)

        async with file_lock:
            logger.debug(f"[AGENT-FIRST] {agent_name} acquired lock for {file.path}")

            diff = await file_service.get_diff(file.path)

            async with self._session_semaphore:
                logger.debug(f"[AGENT-FIRST] {agent_name} reviewing {file.path}")
                result = await agent.review(
                    file.path, diff, pr_url, file.change_tracking_id, self.devops,
                    all_file_paths, pending_pool, current_iteration,
                    kb_available=kb_available
                )
                return result

    async def _review_pr_parallel(
            self, pr_url: str, files: List[FileChange],
            pending_pool: PendingCommentsPool,
            current_iteration: Optional[int] = None,
            kb_available: bool = True
    ) -> List[ReviewSummary]:
        active_files = [f for f in files if f.change_type != CHANGE_TYPE_DELETE]

        tasks = [
            agent.review_pr(pr_url, active_files, self.devops, pending_pool, current_iteration,
                            kb_available=kb_available)
            for agent in self.per_pr_agents
        ]

        results = await asyncio.gather(*tasks)

        summaries = []
        for i, result in enumerate(results):
            summaries.append(result)
            if result.issues_posted > 0:
                agent_name = self.per_pr_agents[i]._get_agent_name()
                session_info = f" session={result.session_id}" if result.session_id else ""
                logger.info(
                    f"[AGENT-PRE] {agent_name} completed: {result.issues_posted} "
                    f"issues{session_info}"
                )

        return summaries
