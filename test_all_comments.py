#!/usr/bin/env python3
"""Test to see all PR comments."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from src.client.http_client import create_mcp_http_client
from src.client.azure.azure_devops_client import AzureDevOpsClient

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    async with create_mcp_http_client(timeout=120) as http:
        devops = AzureDevOpsClient(http)
        
        print("Fetching ALL comments (not filtered to bot)...")
        # Get all comments using the MCP tool directly
        import json
        result = await devops._http_client.request(
            "mcp__rixo-dev-mcp__get_pr_comments",
            pr_url=PR_URL,
            only_bot_comments=False
        )
        
        all_threads = result if isinstance(result, list) else []
        
        print(f"\nTotal threads: {len(all_threads)}")
        
        for thread in all_threads:
            status = thread.get('status', 'unknown')
            comments = thread.get('comments', [])
            first_comment = comments[0] if comments else {}
            author = first_comment.get('author', {}).get('displayName', 'Unknown')
            content_preview = first_comment.get('content', '')[:100]
            thread_context = thread.get('threadContext', {})
            file_path = thread_context.get('filePath', 'N/A')
            
            print(f"\nThread {thread.get('id')}: {status}")
            print(f"  Author: {author}")
            print(f"  File: {file_path}")
            print(f"  Comments: {len(comments)}")
            print(f"  Preview: {content_preview}")

if __name__ == "__main__":
    asyncio.run(main())
