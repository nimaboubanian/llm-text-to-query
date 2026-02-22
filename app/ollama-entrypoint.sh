#!/bin/sh
set -e

# Try to read default_model from config.yaml first
if [ -f "/config.yaml" ] && [ -r "/config.yaml" ]; then
    # Extract default_model value using grep/sed (simple YAML parsing)
    MODEL_FROM_YAML=$(grep -E '^\s*default_model:\s*' /config.yaml 2>/dev/null | sed -E "s/^\s*default_model:\s*//; s/\s*#.*//; s/[\"']//g" | tr -d '\n\r')
    if [ -n "$MODEL_FROM_YAML" ]; then
        DEFAULT_MODEL="$MODEL_FROM_YAML"
        echo "📋 Using model from config.yaml: $DEFAULT_MODEL"
    fi
fi

# Fallback to environment variable or hardcoded default
DEFAULT_MODEL="${DEFAULT_MODEL:-qwen2.5-coder:7b}"

echo "🚀 Starting Ollama server..."
echo "📦 Model to pull: $DEFAULT_MODEL"

# Start ollama serve in background
ollama serve &
SERVER_PID=$!

# Wait for ollama to be ready
echo "⏳ Waiting for Ollama to start..."
sleep 5

# Pull the default model
echo "⬇️  Pulling model: $DEFAULT_MODEL"
ollama pull "$DEFAULT_MODEL" || echo "⚠️  Model pull failed (may already exist)"

echo "✅ Ollama is ready with model: $DEFAULT_MODEL"

# Bring server to foreground
wait $SERVER_PID
