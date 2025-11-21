FROM python:3.10-slim

# System dependencies for PostgreSQL
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into the SYSTEM python environment
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy the rest of the application
COPY . .

# Handled by docker-compose
CMD ["python", "main.py"]
