#!/usr/bin/env python3
"""Test to see ALL threads."""
import asyncio
import httpx

PR_URL = 'https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25498'

async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        print("=== Getting ALL comments (no filtering) ===")
        response = await client.post(
            "http://localhost:8080/api/get_pr_comments",
            json={"pr_url": PR_URL, "only_bot_comments": False}
        )
        result = response.json()
        threads = result if isinstance(result, list) else result.get("comments", [])
        
        print(f"Total threads: {len(threads)}")
        
        bot_name = "rixo-code-reviewer"
        bot_threads = []
        other_threads = []
        
        for thread in threads:
            thread_id = thread.get('id')
            status = thread.get('status')
            comments = thread.get('comments', [])
            
            if not comments:
                continue
                
            first_comment = comments[0]
            author_data = first_comment.get('author', {})
            
            # Check different ways the author might be represented
            display_name = author_data.get('displayName', '') if isinstance(author_data, dict) else str(author_data)
            unique_name = author_data.get('uniqueName', '') if isinstance(author_data, dict) else ''
            
            file_path = thread.get('threadContext', {}).get('filePath', 'N/A')
            line = thread.get('threadContext', {}).get('line', 0)
            
            is_bot = bot_name in display_name or bot_name in unique_name
            
            thread_info = {
                'id': thread_id,
                'status': status,
                'file': f"{file_path}:{line}",
                'num_comments': len(comments),
                'author': display_name,
                'is_bot': is_bot
            }
            
            if is_bot:
                bot_threads.append(thread_info)
            else:
                other_threads.append(thread_info)
        
        print(f"\n=== BOT THREADS ({len(bot_threads)}) ===")
        for t in bot_threads:
            print(f"Thread {t['id']}: {t['status']}, {t['file']}, {t['num_comments']} comments, author: {t['author']}")
        
        print(f"\n=== OTHER THREADS ({len(other_threads)}) ===")
        for t in other_threads:
            print(f"Thread {t['id']}: {t['status']}, {t['file']}, {t['num_comments']} comments, author: {t['author']}")

if __name__ == "__main__":
    asyncio.run(main())
