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

# Pull front-desk model
if [ -n "$FRONTDESK_MODEL" ] && [ "$FRONTDESK_MODEL" != "$DEFAULT_MODEL" ]; then
  echo "Pulling front-desk model: $FRONTDESK_MODEL"
  ollama pull "$FRONTDESK_MODEL" || echo "Pull failed for: $FRONTDESK_MODEL"
fi

# Pull benchmark models
if [ -n "$BENCHMARK_MODELS" ]; then
  echo "Pulling benchmark models: $BENCHMARK_MODELS"
  echo "$BENCHMARK_MODELS" | tr ',' '\n' | while read -r model; do
    model=$(echo "$model" | xargs)
    if [ -n "$model" ] && [ "$model" != "$DEFAULT_MODEL" ]; then
      echo "Pulling benchmark model: $model"
      ollama pull "$model" || echo "Pull failed for: $model"
    fi
  done
fi

echo "Ollama is ready with model: $DEFAULT_MODEL"

# Bring server to foreground
wait $SERVER_PID
