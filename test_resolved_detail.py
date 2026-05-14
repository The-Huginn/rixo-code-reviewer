#!/usr/bin/env python3
"""Test to see resolved thread details."""
import asyncio
import httpx
import json

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        print("=== Getting bot comments with include_resolved=True ===")
        response = await client.post(
            "http://localhost:8080/api/get_pr_comments",
            json={"pr_url": PR_URL, "only_bot_comments": True, "include_resolved": True}
        )
        result = response.json()
        threads = result.get("comments", []) if isinstance(result, dict) else result
        
        print(f"Total threads: {len(threads)}\n")
        
        for thread in threads:
            thread_id = thread.get('id')
            status = thread.get('status')
            comments = thread.get('comments', [])
            
            print(f"=== Thread {thread_id} (status: {status}) ===")
            print(f"Full thread data:")
            print(json.dumps(thread, indent=2, default=str))
            print("\n")

if __name__ == "__main__":
    asyncio.run(main())
