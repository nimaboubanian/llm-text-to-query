FROM python:3.12-slim-bookworm AS base

# System dependencies for psycopg2 (PostgreSQL driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv — pinned version for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.7.8 /uv /uvx /bin/

# Bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1
# Copy instead of link (cache mount is on a separate filesystem)
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml/uv.lock change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Put the venv on PATH so we don't need `uv run` at runtime
ENV PATH="/app/.venv/bin:$PATH"

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["benchmark-orchestrator", "--help"]
