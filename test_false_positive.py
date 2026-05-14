#!/usr/bin/env python3
"""Test false positive detection logic."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from src.client.http_client import create_mcp_http_client
from src.client.azure.azure_devops_client import AzureDevOpsClient

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

def is_false_positive(comment) -> bool:
    """New logic: resolved with no replies = false positive."""
    if not comment.all_comments or len(comment.all_comments) <= 1:
        return True
    return False

async def main():
    async with create_mcp_http_client(timeout=120) as http:
        devops = AzureDevOpsClient(http)

        print("Fetching bot comments (including resolved)...")
        all_bot_comments = await devops.get_bot_comments(PR_URL, include_resolved=True)

        active = [c for c in all_bot_comments if not c.is_resolved]
        resolved = [c for c in all_bot_comments if c.is_resolved]

        print(f"\nTotal bot comments: {len(all_bot_comments)}")
        print(f"Active (unresolved): {len(active)}")
        print(f"Resolved: {len(resolved)}")

        false_positives = []
        fixed_by_author = []

        for c in resolved:
            num_comments = len(c.all_comments) if c.all_comments else 0
            if is_false_positive(c):
                false_positives.append(c)
                print(f"  FALSE POSITIVE: thread {c.thread_id}, {c.file_path}:{c.line}, {num_comments} comments")
            else:
                fixed_by_author.append(c)
                print(f"  FIXED BY AUTHOR: thread {c.thread_id}, {c.file_path}:{c.line}, {num_comments} comments")

        print(f"\n=== SUMMARY ===")
        print(f"False positives (suppressed): {len(false_positives)}")
        print(f"Fixed by author: {len(fixed_by_author)}")
        print(f"Active: {len(active)}")
        print(f"Total for duplicate detection: {len(active) + len(false_positives)}")

if __name__ == "__main__":
    asyncio.run(main())
