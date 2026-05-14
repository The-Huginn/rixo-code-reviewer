#!/usr/bin/env python3
"""Test to see all PR comments including resolved."""
import asyncio
import json

from src.client.http_client import create_mcp_http_client

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    async with create_mcp_http_client(timeout=120) as http:
        # Call MCP directly to get ALL threads including resolved
        result = await http.request(
            "mcp__rixo-dev-mcp__get_pr_comments",
            pr_url=PR_URL,
            only_bot_comments=False
        )
        
        threads = result if isinstance(result, list) else []
        
        active = [t for t in threads if t.get('status') == 'active']
        resolved = [t for t in threads if t.get('status') != 'active']
        
        bot_threads = [t for t in threads if t['comments'][0].get('author') == 'rixo-code-reviewer']
        bot_active = [t for t in bot_threads if t.get('status') == 'active']
        bot_resolved = [t for t in bot_threads if t.get('status') != 'active']
        
        print(f"Total threads: {len(threads)}")
        print(f"  Active: {len(active)}")
        print(f"  Resolved: {len(resolved)}")
        print(f"\nBot threads: {len(bot_threads)}")
        print(f"  Active: {len(bot_active)}")
        print(f"  Resolved: {len(bot_resolved)}")
        
        print("\n=== BOT RESOLVED THREADS ===")
        for thread in bot_resolved:
            thread_id = thread.get('id')
            comments = thread.get('comments', [])
            num_comments = len(comments)
            file_path = thread.get('threadContext', {}).get('filePath', 'N/A')
            line = thread.get('threadContext', {}).get('line', 'N/A')
            
            is_false_positive = num_comments <= 1
            
            print(f"\nThread {thread_id}: {file_path}:{line}")
            print(f"  Comments: {num_comments}")
            print(f"  Classification: {'FALSE POSITIVE' if is_false_positive else 'FIXED BY AUTHOR'}")
            
            for i, comment in enumerate(comments):
                author = comment.get('author', 'Unknown')
                content_preview = comment.get('content', '')[:80]
                print(f"    [{i+1}] {author}: {content_preview}...")

if __name__ == "__main__":
    asyncio.run(main())
