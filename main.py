import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agent import SingleThreadManagerAgent
from src.agent.impl import (
    StyleReviewAgent,
    ArchitectureReviewAgent,
    TestReviewAgent,
    FileIntegrityReviewAgent,
    SQLReviewAgent,
    DocumentationReviewAgent,
    SecurityReviewAgent,
    ImportsConstantsReviewAgent
)
from src.client.ai import ClaudeCodeClient, ClaudeSDKClient
from src.client.azure import AzureDevOpsClient
from src.client.http_client import create_mcp_http_client
from src.config import config
from src.controller import healthz_controller, webhook_controller
from src.service import RuleLoaderService, PRReviewService, IndexedRepoService

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

http_client = None
ai_client = None
devops_client = None
rule_loader = None
single_thread_manager = None
per_file_agents = None
per_pr_agents = None
review_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, ai_client, devops_client, rule_loader, single_thread_manager, per_file_agents, per_pr_agents, review_service

    logger.info("Initializing RIXO Code Reviewer...")
    logger.info(f"AI Provider: {config.ai.provider}")

    http_client = create_mcp_http_client()

    # Initialize AI client based on provider configuration
    if config.ai.provider == "claude-code-cli":
        ai_client = ClaudeCodeClient()
        logger.info("Using ClaudeCodeClient (CLI-based)")
    elif config.ai.provider == "claude-code-sdk":
        ai_client = ClaudeSDKClient()
        logger.info("Using ClaudeSDKClient (SDK-based)")
    else:
        raise ValueError(f"Unknown AI provider: {config.ai.provider}. Valid options: claude-code-cli, claude-code-sdk")

    devops_client = AzureDevOpsClient(http_client)
    rule_loader = RuleLoaderService(http_client)

    logger.info("Initializing agents with rule loader...")

    single_thread_manager = SingleThreadManagerAgent(ai_client)

    per_file_agents = [
        StyleReviewAgent(ai_client, rule_loader),
        TestReviewAgent(ai_client, rule_loader),
        FileIntegrityReviewAgent(ai_client, rule_loader),
        SQLReviewAgent(ai_client, rule_loader),
        SecurityReviewAgent(ai_client, rule_loader),
        ImportsConstantsReviewAgent(ai_client, rule_loader)
    ]

    per_pr_agents = [
        ArchitectureReviewAgent(ai_client, rule_loader),
        DocumentationReviewAgent(ai_client, rule_loader)
    ]

    logger.info("Fetching rules for all agents...")
    all_agents = per_file_agents + per_pr_agents
    await asyncio.gather(*[agent.fetch_rules() for agent in all_agents])
    logger.info(f"Rules loaded for {len(all_agents)} agents")

    indexed_repo_service = IndexedRepoService(http_client)
    review_service = PRReviewService(
        devops_client, per_file_agents, per_pr_agents, single_thread_manager, ai_client,
        indexed_repo_service=indexed_repo_service
    )

    logger.info(f"Initialized thread manager, {len(per_file_agents)} per-file agents, and {len(per_pr_agents)} per-PR agents")

    # Set dependencies after initialization
    webhook_controller.set_review_service_provider(get_review_service)

    yield

    await http_client.aclose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="RIXO Code Reviewer",
    description="Automated PR code review service using Claude Code and multi-agent architecture",
    version="1.0.0",
    lifespan=lifespan
)


def get_review_service():
    return review_service


app.include_router(healthz_controller.router)
app.include_router(webhook_controller.router)


@app.get("/")
def root():
    return {
        "service": "RIXO Code Reviewer",
        "status": "running",
        "version": "1.0.0",
        "single_thread_manager": type(single_thread_manager).__name__,
        "per_file_agents": [type(agent).__name__ for agent in per_file_agents],
        "per_pr_agents": [type(agent).__name__ for agent in per_pr_agents],
        "ai_provider": config.ai.provider
    }


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting server on {config.app.host}:{config.app.port}")
    uvicorn.run(app, host=config.app.host, port=config.app.port)
