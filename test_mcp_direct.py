#!/usr/bin/env python3
"""Test MCP API directly."""
import asyncio
import httpx

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        # Test with include_resolved parameter
        print("=== Testing with only_bot_comments=True, include_resolved=True ===")
        response = await client.post(
            "http://localhost:8080/api/get_pr_comments",
            json={"pr_url": PR_URL, "only_bot_comments": True, "include_resolved": True}
        )
        result = response.json()
        threads = result.get("comments", []) if isinstance(result, dict) else result
        print(f"Total threads: {len(threads)}")
        
        for thread in threads:
            thread_id = thread.get('id')
            status = thread.get('status')
            comments = thread.get('comments', [])
            file_path = thread.get('threadContext', {}).get('filePath', 'N/A')
            line = thread.get('threadContext', {}).get('line', 0)
            
            print(f"\nThread {thread_id}: {status}")
            print(f"  File: {file_path}:{line}")
            print(f"  Comments: {len(comments)}")
            for i, c in enumerate(comments):
                author = c.get('author', 'Unknown')
                print(f"    [{i+1}] {author}")

if __name__ == "__main__":
    asyncio.run(main())
