import logging
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.client.azure import AzureDevOpsClient

logger = logging.getLogger(__name__)


class CachedFileService:

    def __init__(self, pr_url: str, devops_client: "AzureDevOpsClient"):
        self._pr_url = pr_url
        self._devops = devops_client
        self._cache: Dict[str, str] = {}

    async def get_diff(self, file_path: str) -> str:
        if file_path in self._cache:
            return self._cache[file_path]

        diff = await self._devops.get_file_diff(self._pr_url, file_path)
        self._cache[file_path] = diff
        return diff

    async def get_diff_at_iteration(self, file_path: str, iteration: int) -> str:
        return await self._devops.get_file_diff_at_iteration(self._pr_url, file_path, iteration)
