#!/bin/sh
set -e

# Fix ownership of benchmark data volume (runs as root)
if [ -d "/app/benchmark/data" ]; then
    # Check if directory is owned by root
    if [ "$(stat -c '%u' /app/benchmark/data)" = "0" ]; then
        echo "Fixing ownership of /app/benchmark/data..."
        chown -R appuser:appuser /app/benchmark/data
    fi
fi

# Also fix the venv volume
if [ -d "/app/.venv" ]; then
    if [ "$(stat -c '%u' /app/.venv)" = "0" ]; then
        echo "Fixing ownership of /app/.venv..."
        chown -R appuser:appuser /app/.venv
    fi
fi

# Switch to appuser and run the command, preserving environment and PATH
echo "Starting benchmark orchestrator..."
# Use su with -p to preserve environment, and explicitly set PATH
exec su -p -c 'export PATH="/bin:/usr/bin:$PATH"; exec "$@"' appuser -- "$@"
