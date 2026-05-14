import json
import logging
import traceback
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import Optional, Callable
from src.service import PRReviewService

logger = logging.getLogger(__name__)

router = APIRouter()

_get_review_service: Optional[Callable[[], PRReviewService]] = None


def get_review_service() -> PRReviewService:
    if _get_review_service is None:
        raise RuntimeError("Review service not initialized")
    return _get_review_service()


class PullRequestWebhook(BaseModel):
    eventType: str
    message: Optional[dict] = None  # Contains text description of the event
    resource: dict


class DirectReviewRequest(BaseModel):
    pr_url: str


async def _review_with_error_handling(review_service: PRReviewService, pr_url: str):
    try:
        await review_service.review_pr(pr_url)
    except Exception as e:
        logger.error(f"ERROR in background review task: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())


# Not used yet, prepared for future use in Azure git actions integration
# Author to ignore
IGNORED_AUTHORS = ["your-org-automated-bot"]


@router.post("/webhook/pr")
async def handle_pr_webhook(
        payload: PullRequestWebhook,
        background_tasks: BackgroundTasks,
        review_service: PRReviewService = Depends(get_review_service)
):
    # Log full payload for debugging webhook events
    logger.info(f"Webhook payload: {json.dumps(payload.model_dump(), indent=2, default=str)}")

    if payload.eventType not in ["git.pullrequest.created", "git.pullrequest.updated"]:
        return {"status": "ignored", "reason": "not a PR event"}

    # Only review on PR creation or source branch updates (code pushes)
    # Ignore: reviewer changes, approvals, completions, etc.
    message_text = payload.message.get("text", "") if payload.message else ""
    is_pr_created = "created pull request" in message_text
    is_source_branch_updated = "updated the source branch of pull request" in message_text

    if not is_pr_created and not is_source_branch_updated:
        logger.info(f"Ignoring PR event: not a creation or source branch update. Message: {message_text[:100]}")
        return {"status": "ignored", "reason": "not a PR creation or source branch update"}

    # Ignore PRs created by automated tools
    created_by = payload.resource.get("createdBy", {}).get("displayName", "")
    if created_by in IGNORED_AUTHORS:
        logger.info(f"Ignoring PR event from automated tool: {created_by}")
        return {"status": "ignored", "reason": f"PR created by ignored author: {created_by}"}

    # Extract web URL from _links.web.href (user-facing PR URL)
    # Example: https://dev.azure.com/your-org/apps/_git/acme-service-a/pullrequest/25402
    pr_url = payload.resource.get("_links", {}).get("web", {}).get("href")
    if not pr_url:
        raise HTTPException(status_code=400, detail="Missing PR URL in webhook payload (_links.web.href)")

    if not review_service.can_start_review(pr_url):
        return {"status": "in_progress", "message": "Review already in progress", "pr_url": pr_url}

    background_tasks.add_task(_review_with_error_handling, review_service, pr_url)

    return {"status": "in_progress", "message": "Review started", "pr_url": pr_url}


@router.post("/review")
async def handle_direct_review(
        request: DirectReviewRequest,
        background_tasks: BackgroundTasks,
        review_service: PRReviewService = Depends(get_review_service)
):
    if not review_service.can_start_review(request.pr_url):
        return {"status": "in_progress", "message": "Review already in progress", "pr_url": request.pr_url}

    background_tasks.add_task(_review_with_error_handling, review_service, request.pr_url)
    return {"status": "in_progress", "message": "Review started", "pr_url": request.pr_url}


@router.get("/review-status")
async def get_review_status(
        pr_url: str,
        review_service: PRReviewService = Depends(get_review_service)
):
    decoded_url = unquote(pr_url)
    state = review_service.get_review_state(decoded_url)

    if not state:
        raise HTTPException(status_code=404, detail="Review not found")

    return state.to_dict()


def set_review_service_provider(provider: Callable[[], PRReviewService]):
    global _get_review_service
    _get_review_service = provider
