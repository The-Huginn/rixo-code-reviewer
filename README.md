# RIXO Code Reviewer

Automated PR code review service using Claude Code CLI and a multi-agent
architecture. Listens for Azure DevOps PR webhook events, dispatches per-file
and cross-file review agents, and posts comments back to the PR.

Developed in cooperation with [Rixo](https://www.rixo.cz).

Deployment-specific details (private CA cert, internal hostnames, hardcoded
tokens, internal microservice names) are kept out of the repository and must
be supplied via environment variables — see [Configuration](#configuration)
for the full list.

## Getting Started

1. Install Python 3.12.
2. Install system-level dependencies:

   ```bash
   apt-get install -y --no-install-recommends gcc libpq-dev python3-dev
   ```

3. Install Python deps with Poetry inside a project-local venv:

   ```bash
   python3 -m venv ./.venv
   source .venv/bin/activate
   pip install -U pip setuptools poetry
   poetry install
   ```

4. Install the Claude Code CLI (used by the review agents):

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

5. Configure environment (see below), then run:

   ```bash
   poetry run python main.py
   ```

## Configuration

### Required environment variables

| Variable             | Used by                 | Purpose                                                                            |
| -------------------- | ----------------------- | ---------------------------------------------------------------------------------- |
| `MCP_SERVER_URL`     | `start.sh`              | URL of the companion MCP server (e.g. an instance of `rixo-dev-mcp`).              |
| `LITELLM_API_KEY`    | `start.sh`, embedding   | API key for the LiteLLM proxy (or your direct LLM provider key).                   |
| `CONFIG_ENV`         | `main.py`               | Selects which YAML profile to load from `resource/`. The k8s deployment uses `k8s`. Local dev defaults work with the bundled `application.yml`. |

### Optional environment variables (defaults live in `resource/application.yml`)

| Variable                  | Default                       | Purpose                                                         |
| ------------------------- | ----------------------------- | --------------------------------------------------------------- |
| `MCP_API_BASE_URL`        | `http://localhost:8080`       | Base URL used to reach the MCP HTTP API for PR operations.      |
| `MCP_API_SSL_CERT_PATH`   | _(unset)_                     | Path to a private-CA PEM, if MCP is served behind one.          |
| `EMBEDDING_ENDPOINT`      | `https://api.openai.com`      | LiteLLM/OpenAI-compatible endpoint for text embeddings.         |
| `EMBEDDING_MODEL`         | `text-embedding-3-large`      | Embedding model to use.                                         |
| `EMBEDDING_SSL_CERT_PATH` | _(unset)_                     | Path to a private-CA PEM, if the embedding endpoint uses one.   |

### Per-deployment configuration in `resource/application.yml`

Some settings are environment-specific lists and live in
`resource/application.yml` rather than in env vars:

```yaml
review:
  allowed_repositories: []   # repositories whose PRs are reviewed (empty = deny-by-default)
  ignored_authors: []        # PR author IDs to skip (e.g. release bots)
```

Azure DevOps authentication is handled via `DefaultAzureCredential` and
relies on the standard `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` /
`AZURE_CLIENT_SECRET` env vars (or Workload Identity / Managed Identity in
cluster).

### What you need to supply

- **Private CA certificate** (optional). If your LiteLLM / embedding
  endpoint is terminated behind a private CA, drop the PEM into
  `resource/certs/` and uncomment the two `COPY` / `update-ca-certificates`
  lines near the top of the runtime stage of the `Dockerfile`.
- **LiteLLM bearer token**: set `LITELLM_API_KEY` on the deployment. `start.sh`
  reads it from the environment.
- **Embedding endpoint**: defaults to `https://api.openai.com`; override via
  `EMBEDDING_ENDPOINT` if you're proxying through LiteLLM or a private host.
- **Repository whitelist & ignored authors**: edit
  `resource/application.yml` (`review.allowed_repositories` and
  `review.ignored_authors`). The whitelist is deny-by-default — only
  listed repositories' PRs are reviewed.
- **CI/CD**: no build or deploy scripts are bundled. Bring your own
  pipeline.

## Session Debugging

All Claude sessions are logged to `logs/sessions/{uuid}.json`.

Replay any review:

```bash
claude --resume <session-id>
```
