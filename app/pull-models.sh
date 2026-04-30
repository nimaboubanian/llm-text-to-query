#!/bin/sh
set -e

case "$1" in
  chat)
    echo "Pulling default model: $DEFAULT_MODEL"
    ollama pull "$DEFAULT_MODEL"
    if [ -n "$FRONTDESK_MODEL" ] && [ "$FRONTDESK_MODEL" != "$DEFAULT_MODEL" ]; then
      echo "Pulling front-desk model: $FRONTDESK_MODEL"
      ollama pull "$FRONTDESK_MODEL"
    fi
    ;;
  benchmark)
    if [ -z "$BENCHMARK_MODELS" ]; then
      echo "No BENCHMARK_MODELS set. Read README.md to know how to set them."
      exit 1
    fi
    echo "Pulling benchmark models: $BENCHMARK_MODELS"
    echo "$BENCHMARK_MODELS" | tr ',' '\n' | while read -r model; do
      model=$(echo "$model" | xargs)
      [ -n "$model" ] && ollama pull "$model"
    done
    ;;
  *)
    echo "Usage: pull-models <chat|benchmark>"
    exit 1
    ;;
esac
