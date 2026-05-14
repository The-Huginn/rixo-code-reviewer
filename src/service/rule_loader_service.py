import json
import logging
from typing import List

import httpx

from src.config import config

logger = logging.getLogger(__name__)


class RuleLoaderService:

    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client
        self.base_url = config.mcp_api.base_url

    async def load_rules(self, rule_groups: List[str], framework: str = "spring") -> str:
        rules_content = []

        for group in rule_groups:
            try:
                response = await self.http_client.post(
                    f"{self.base_url}/api/get_rule_group",
                    json={"group": group, "framework": framework}
                )
                response.raise_for_status()
                result = response.json()

                if isinstance(result, str):
                    result = json.loads(result)

                if isinstance(result, dict):
                    for file_name, content in result.items():
                        rules_content.append(f"# {file_name}\n\n{content}")

                logger.info(f"Loaded rules for group '{group}'")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.warning(f"Rule group '{group}' not found, skipping")
                else:
                    logger.error(f"HTTP error loading rules for group '{group}': {e}")
            except Exception as e:
                logger.error(f"Error loading rules for group '{group}': {e}")

        return "\n\n".join(rules_content)
