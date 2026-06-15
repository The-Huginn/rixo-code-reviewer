import logging
from typing import List, Optional

import httpx

from src.config import config

logger = logging.getLogger(__name__)


class IndexedRepoService:
    """Checks which repositories are indexed in the knowledge base."""

    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client
        self.base_url = config.mcp_api.base_url

    async def get_indexed_repositories(self) -> Optional[List[str]]:
        try:
            response = await self.http_client.get(
                f"{self.base_url}/api/repositories"
            )
            response.raise_for_status()
            data = response.json()
            repos: List[str] = data.get("repositories", [])
            logger.info(f"Indexed repositories: {repos}")
            return repos
        except Exception as e:
            logger.warning(f"Failed to fetch indexed repositories: {e}")
            return None

    async def is_repo_indexed(self, repo_name: str) -> bool:
        repos = await self.get_indexed_repositories()
        if repos is None:
            return True
        return repo_name in repos
