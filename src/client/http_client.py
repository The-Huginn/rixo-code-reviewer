import logging

import httpx

from src.config import config

logger = logging.getLogger(__name__)


def create_mcp_http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    verify = config.mcp_api.ssl_cert_path if config.mcp_api.ssl_cert_path else True

    logger.info(f"Creating MCP HTTP client for base URL: {config.mcp_api.base_url}")
    if config.mcp_api.ssl_cert_path:
        logger.info(f"Using SSL certificate: {config.mcp_api.ssl_cert_path}")

    # Disable connection pooling to prevent MCP server resource exhaustion
    # Each request will create a fresh connection and close it immediately
    return httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        limits=httpx.Limits(
            max_keepalive_connections=0,  # Disable keep-alive
            max_connections=config.app.max_mcp_concurrent_requests
        )
    )