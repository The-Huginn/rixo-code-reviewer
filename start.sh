#!/bin/bash

set -e

: "${MCP_SERVER_URL:?MCP_SERVER_URL must be set (e.g. http://your-mcp-host:8000/mcp)}"
: "${LITELLM_API_KEY:?LITELLM_API_KEY must be set}"

echo "Registering MCP server with Claude CLI..."
claude mcp add rixo-dev-mcp "$MCP_SERVER_URL" -t http -s user -H "x-litellm-api-key: Bearer ${LITELLM_API_KEY}"

echo "Starting uvicorn server..."
exec python -m uvicorn main:app --host 0.0.0.0 --port 8888 --workers 1 --log-config=logging.conf
