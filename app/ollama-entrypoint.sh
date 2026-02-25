#!/bin/sh
set -e

DEFAULT_MODEL="${DEFAULT_MODEL:-qwen2.5-coder:7b}"

echo "Starting Ollama server..."
echo "Model to pull: $DEFAULT_MODEL"

# Start ollama serve in background
ollama serve &
SERVER_PID=$!

# Wait for ollama to be ready
sleep 5

# Pull the default model
echo "Pulling model: $DEFAULT_MODEL"
ollama pull "$DEFAULT_MODEL" || echo "Model pull failed (may already exist)"

echo "Ollama is ready with model: $DEFAULT_MODEL"

# Bring server to foreground
wait $SERVER_PID
