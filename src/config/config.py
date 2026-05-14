import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class AIConfig:
    provider: str
    claude_cli_timeout: int = 600
    claude_code_model: str = None


@dataclass
class EmbeddingConfig:
    endpoint: str
    model: str = "text-embedding-3-small"
    api_key: str = None
    ssl_cert_path: str = None


@dataclass
class AppConfig:
    environment: str
    host: str
    port: int
    max_parallel_sessions: int = 10
    max_mcp_concurrent_requests: int = 5


@dataclass
class McpApiConfig:
    base_url: str
    ssl_cert_path: str = None


@dataclass
class ReviewConfig:
    allowed_repositories: List[str] = field(default_factory=list)
    ignored_authors: List[str] = field(default_factory=list)


class Config:

    def __init__(self, config_file: Path):
        with open(config_file) as f:
            data = yaml.safe_load(f)

        self.app = AppConfig(**data["app"])
        self.ai = AIConfig(
            provider=data["ai"]["provider"],
            claude_cli_timeout=data["ai"].get("claude_cli_timeout", 600),
            claude_code_model=data["ai"].get("claude_code_model")
        )

        mcp_api_data = data.get("mcp_api", {})
        mcp_api_base_url = mcp_api_data.get("base_url")
        mcp_api_ssl_cert = mcp_api_data.get("ssl_cert_path")
        if mcp_api_ssl_cert:
            if not os.path.isabs(mcp_api_ssl_cert):
                project_root = Path(__file__).parent.parent.parent
                mcp_api_ssl_cert = str(project_root / mcp_api_ssl_cert)
            else:
                mcp_api_ssl_cert = os.path.expanduser(mcp_api_ssl_cert)
        self.mcp_api = McpApiConfig(base_url=mcp_api_base_url, ssl_cert_path=mcp_api_ssl_cert)

        # Embedding configuration
        embedding_data = data.get("embedding", {})
        embedding_endpoint = embedding_data.get("endpoint") or os.getenv("EMBEDDING_ENDPOINT")
        embedding_ssl_cert = embedding_data.get("ssl_cert_path")
        if embedding_ssl_cert:
            if not os.path.isabs(embedding_ssl_cert):
                project_root = Path(__file__).parent.parent.parent
                embedding_ssl_cert = str(project_root / embedding_ssl_cert)
            else:
                embedding_ssl_cert = os.path.expanduser(embedding_ssl_cert)
        self.embedding = EmbeddingConfig(
            endpoint=embedding_endpoint,
            model=embedding_data.get("model", "text-embedding-3-small"),
            api_key=embedding_data.get("api_key") or os.getenv("LITELLM_API_KEY"),
            ssl_cert_path=embedding_ssl_cert
        )

        review_data = data.get("review", {})
        self.review = ReviewConfig(
            allowed_repositories=list(review_data.get("allowed_repositories") or []),
            ignored_authors=list(review_data.get("ignored_authors") or []),
        )


# Check for environment-specific config (e.g., application.docker.yml)
config_env = os.getenv("CONFIG_ENV", "")
if config_env:
    CONFIG_FILE = Path(__file__).parent.parent.parent / "resource" / f"application.{config_env}.yml"
else:
    CONFIG_FILE = Path(__file__).parent.parent.parent / "resource" / "application.yml"

if CONFIG_FILE.exists():
    config = Config(CONFIG_FILE)
else:
    raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
