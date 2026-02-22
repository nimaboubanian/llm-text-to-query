FROM python:3.12-slim

# System dependencies for database drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Copy dependency files for layer caching
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy the application source code
COPY --chown=appuser:appuser . .

# Set Python path to include src directory
ENV PYTHONPATH=/app/src
ENV UV_PROJECT_ENVIRONMENT=/tmp/.venv

# Switch to non-root user
USER appuser

# Default command
CMD ["uv", "run", "benchmark-orchestrator", "--help"]
