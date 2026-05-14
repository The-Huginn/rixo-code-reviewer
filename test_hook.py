#!/usr/bin/env python3
"""Quick test of hook format fix."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from src.service.pr_review_service import PRReviewService
from src.client.http_client import create_mcp_http_client
from src.client.azure.azure_devops_client import AzureDevOpsClient
from src.client.ai.claude_sdk_client import ClaudeSDKClient
from src.service.rule_loader_service import RuleLoaderService
from src.agent.impl.test_review_agent import TestReviewAgent

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    print("Testing hook format fix...")

    async with create_mcp_http_client(timeout=600) as http:
        devops = AzureDevOpsClient(http)
        ai_client = ClaudeSDKClient()
        rule_loader = RuleLoaderService(http)

        agent = TestReviewAgent(ai_client, rule_loader)
        await agent.fetch_rules()

        service = PRReviewService(
            devops_client=devops,
            per_file_agents=[agent],
            per_pr_agents=[],
            single_thread_manager=None,
            ai_client=ai_client
        )

        result = await service.review_pr(PR_URL)
        print(f"Review completed: {result}")

if __name__ == "__main__":
    asyncio.run(main())
