#!/bin/bash
# ============================================================
# setup_models.sh — Download required AI models for AutoFormFiller
# Run this after docker-compose up on first deployment.
# ============================================================

set -e

OLLAMA_HOST=${OLLAMA_HOST:-http://localhost:11434}

echo "=== AutoFormFiller Model Setup ==="
echo "Ollama host: $OLLAMA_HOST"

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
for i in $(seq 1 30); do
    if curl -sf "$OLLAMA_HOST/api/tags" > /dev/null 2>&1; then
        echo "Ollama is ready."
        break
    fi
    echo "  Attempt $i/30 — waiting 5s..."
    sleep 5
done

# Pull primary LLM: Qwen2.5-7B-Instruct (4-bit quantized, ~4.5GB)
echo ""
echo "[1/2] Pulling primary LLM: qwen2.5:7b-instruct-q4_K_M (~4.5GB)..."
curl -X POST "$OLLAMA_HOST/api/pull" \
    -H 'Content-Type: application/json' \
    -d '{"name": "qwen2.5:7b-instruct-q4_K_M"}'

echo ""
echo "Primary LLM pulled successfully."

# Optional: Pull fallback LLM
if [ "${PULL_FALLBACK_MODEL:-false}" = "true" ]; then
    echo ""
    echo "[2/2] Pulling fallback LLM: llama3.1:8b-instruct-q4_K_M (~4.9GB)..."
    curl -X POST "$OLLAMA_HOST/api/pull" \
        -H 'Content-Type: application/json' \
        -d '{"name": "llama3.1:8b-instruct-q4_K_M"}'
    echo "Fallback LLM pulled successfully."
else
    echo "[2/2] Skipping fallback model (set PULL_FALLBACK_MODEL=true to enable)."
fi

echo ""
echo "=== Model setup complete! ==="
echo "Available models:"
curl -s "$OLLAMA_HOST/api/tags" | python3 -c "import sys,json; [print(' -', m['name']) for m in json.load(sys.stdin).get('models', [])]"
