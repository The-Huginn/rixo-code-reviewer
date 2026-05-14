import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List

import httpx

from src.config import config
from src.constants import THREAD_STATUS_ACTIVE

logger = logging.getLogger(__name__)


@dataclass
class PRDetails:
    pr_id: int
    title: str
    description: str
    source_branch: str
    target_branch: str
    author: str
    repository: str
    status: str


@dataclass
class FileChange:
    path: str
    change_type: str
    change_tracking_id: int


@dataclass
class PRComment:
    thread_id: int
    file_path: str
    line: int
    content: str
    author: str
    is_resolved: bool
    iteration_context: dict = None
    change_tracking_id: int = None
    all_comments: list = None  # All comments in thread including replies


class AzureDevOpsClient:

    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client
        self.base_url = config.mcp_api.base_url
        # Rate-limit MCP API calls to prevent server overload
        self._mcp_semaphore = asyncio.Semaphore(config.app.max_mcp_concurrent_requests)
        logger.info(
            f"Azure DevOps client initialized with base URL: {self.base_url}, max concurrent requests: {config.app.max_mcp_concurrent_requests}")

    async def get_pr_details(self, pr_url: str) -> PRDetails:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_details",
                json={"pr_url": pr_url}
            )
            response.raise_for_status()
            result = response.json()

            return PRDetails(
                pr_id=result["pullRequestId"],
                title=result["title"],
                description=result.get("description", "")[:500],
                source_branch=result["sourceRefName"],
                target_branch=result["targetRefName"],
                author=result.get("createdBy", {}).get("displayName", "unknown"),
                repository=result.get("repository", {}).get("name", ""),
                status=result.get("status", "active")
            )

    async def get_pr_files(self, pr_url: str) -> List[FileChange]:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_files",
                json={"pr_url": pr_url}
            )
            response.raise_for_status()
            result_str = response.json()

            result = json.loads(result_str) if isinstance(result_str, str) else result_str
            return [
                FileChange(
                    path=f["path"],
                    change_type=f["changeType"],
                    change_tracking_id=f["changeTrackingId"]
                )
                for f in result["files"]
            ]

    async def get_file_diff(self, pr_url: str, file_path: str) -> str:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_file_diff",
                json={"pr_url": pr_url, "file_path": file_path}
            )
            response.raise_for_status()
            result = response.json()

            if isinstance(result, dict):
                return result.get("diff", "")
            return result

    async def get_file_diff_at_iteration(self, pr_url: str, file_path: str, iteration: int) -> str:
        """Get diff for a specific file at a specific PR iteration."""
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_file_diff_at_iteration",
                json={"pr_url": pr_url, "file_path": file_path, "iteration": iteration}
            )
            response.raise_for_status()
            result = response.json()

            if isinstance(result, dict):
                return result.get("diff", "")
            return result

    async def set_approval(self, pr_url: str, vote: str) -> dict:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/set_pr_approval",
                json={"pr_url": pr_url, "vote": vote}
            )
            response.raise_for_status()
            result_str = response.json()

            return json.loads(result_str) if isinstance(result_str, str) else result_str

    def _parse_comment_threads(self, threads: List[dict]) -> List[PRComment]:
        comments = []
        for thread in threads:
            try:
                if not thread.get("comments"):
                    continue

                first_comment = thread["comments"][0]
                thread_context = thread.get("threadContext", {})

                if isinstance(first_comment, dict):
                    content = first_comment.get("content", "")
                    author_data = first_comment.get("author", {})
                    author = author_data.get("displayName", "") if isinstance(author_data, dict) else ""
                else:
                    content = str(first_comment) if first_comment else ""
                    author = ""

                # Extract iteration context and change tracking ID
                iteration_context = thread.get("iterationContext")
                change_tracking_id = thread.get("changeTrackingId")

                # Extract all comments in thread (for detecting author replies)
                all_comments = thread.get("comments", [])

                comments.append(PRComment(
                    thread_id=thread["id"],
                    file_path=thread_context.get("filePath", ""),
                    line=thread_context.get("rightFileEnd", {}).get("line", 0),
                    content=content,
                    author=author,
                    is_resolved=thread.get("status") != THREAD_STATUS_ACTIVE,
                    iteration_context=iteration_context,
                    change_tracking_id=change_tracking_id,
                    all_comments=all_comments
                ))
            except Exception as e:
                logger.error(f"Error parsing thread {thread.get('id')}: {e}")
                logger.error(f"First comment type: {type(first_comment)}, value: {first_comment}")
                continue
        return comments

    async def get_bot_comments(self, pr_url: str, include_resolved: bool) -> List[PRComment]:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_comments",
                json={"pr_url": pr_url, "only_bot_comments": True, "include_resolved": include_resolved}
            )
            response.raise_for_status()
            result = response.json()

            threads = result.get("comments", []) if isinstance(result, dict) else result
            return self._parse_comment_threads(threads)

    async def get_comments(self, pr_url: str) -> List[PRComment]:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/get_pr_comments",
                json={"pr_url": pr_url}
            )
            response.raise_for_status()
            result = response.json()

            threads = result.get("comments", []) if isinstance(result, dict) else result
            return self._parse_comment_threads(threads)

    async def add_comment(self, pr_url: str, file_path: str, line: int, comment: str, change_tracking_id: int) -> dict:
        async with self._mcp_semaphore:
            response = await self.http_client.post(
                f"{self.base_url}/api/add_pr_comment",
                json={
                    "pr_url": pr_url,
                    "file_path": file_path,
                    "line_start": line,
                    "comment": comment,
                    "change_tracking_id": change_tracking_id
                }
            )
            response.raise_for_status()
            return response.json()
