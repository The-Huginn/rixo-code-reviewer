FROM python:3.12-slim AS builder

RUN apt-get update  \
    && apt-get install -y --no-install-recommends gcc libpq-dev python3-dev  \
    && apt-get clean

WORKDIR /tmp
COPY poetry.lock pyproject.toml ./

RUN pip install --upgrade pip && pip install poetry --no-cache-dir

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=0 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN --mount=type=cache,target=$POETRY_CACHE_DIR poetry install --no-root --without dev

FROM python:3.12-slim AS runtime

# Install system dependencies including Node.js and Azure CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    && mkdir -p /etc/apt/keyrings \
    # Install Node.js (for Claude Code CLI)
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    # Install Azure CLI
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

ENV PYTHONUNBUFFERED=1 \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# Install your certificate or comment this line
COPY resource/certs/custom-ca.crt /usr/local/share/ca-certificates/custom-ca.crt
RUN update-ca-certificates

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . ./

RUN mkdir -p logs/sessions

# Create user with host UID for proper file permissions
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd -g ${USER_GID} appusers \
    && adduser --disabled-password --gecos '' --uid ${USER_UID} --gid ${USER_GID} appuser \
    && chown -R appuser:appusers /app

USER appuser

# Create directories and symlinks so MCP server and tools can be accessed from appuser home
RUN mkdir -p /home/appuser/.claude \
    && ln -s /app/.claude/tools /home/appuser/.claude/tools \
    && ln -s /app/.claude/mcp /home/appuser/.claude/mcp

EXPOSE 8888

CMD ["./start.sh"]
