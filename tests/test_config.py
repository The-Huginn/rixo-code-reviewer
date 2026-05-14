import os
import tempfile
from pathlib import Path

from src.config.config import Config


def test_config_loads_from_yaml():
    yaml_content = """
app:
  environment: test
  host: 127.0.0.1
  port: 9000
  max_parallel_sessions: 5
  max_mcp_concurrent_requests: 3

ai:
  provider: claude-code
  claude_cli_timeout: 600

mcp_api:
  base_url: https://test-api.example.com
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(yaml_content)
        config_file = f.name

    try:
        config = Config(Path(config_file))

        # Test app config
        assert config.app.environment == "test"
        assert config.app.host == "127.0.0.1"
        assert config.app.port == 9000
        assert config.app.max_parallel_sessions == 5
        assert config.app.max_mcp_concurrent_requests == 3

        # Test AI config
        assert config.ai.provider == "claude-code"
        assert config.ai.claude_cli_timeout == 600

        # Test MCP API config
        assert config.mcp_api.base_url == "https://test-api.example.com"

    finally:
        os.unlink(config_file)


def test_config_with_ssl_cert():
    yaml_content = """
app:
  environment: test
  host: 0.0.0.0
  port: 8080

ai:
  provider: claude-code-sdk
  claude_cli_timeout: 900
  claude_code_model: claude-sonnet-4-20250514

mcp_api:
  base_url: https://example.com
  ssl_cert_path: /tmp/test-cert.crt
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(yaml_content)
        config_file = f.name

    try:
        config = Config(Path(config_file))

        # Test AI config with model
        assert config.ai.provider == "claude-code-sdk"
        assert config.ai.claude_code_model == "claude-sonnet-4-20250514"

        # Test MCP API config with SSL
        assert config.mcp_api.base_url == "https://example.com"
        assert config.mcp_api.ssl_cert_path == "/tmp/test-cert.crt"

    finally:
        os.unlink(config_file)


def test_config_defaults():
    yaml_content = """
app:
  environment: production
  host: 0.0.0.0
  port: 8080

ai:
  provider: claude-code

mcp_api:
  base_url: https://api.example.com
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(yaml_content)
        config_file = f.name

    try:
        config = Config(Path(config_file))

        # Test default values
        assert config.app.max_parallel_sessions == 10  # default
        assert config.app.max_mcp_concurrent_requests == 5  # default
        assert config.ai.claude_cli_timeout == 600  # default
        assert config.ai.claude_code_model is None  # default
        assert config.mcp_api.ssl_cert_path is None  # default

    finally:
        os.unlink(config_file)
