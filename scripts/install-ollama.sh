#!/usr/bin/env bash
# Optional: install Ollama and pull a model for Hark's transcript cleanup.
set -euo pipefail

MODELS=()
PULL=1
URL=${OLLAMA_URL:-http://localhost:11434}

usage() {
    cat <<'EOF'
Usage: bash scripts/install-ollama.sh [--model NAME]... [--no-pull]

  --model NAME   model to pull (repeatable); default: qwen2.5:3b
                 faster alternative on CPU: qwen2.5:1.5b
  --no-pull      only install/start Ollama
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODELS+=("${2:?--model needs a name}"); shift ;;
        --no-pull) PULL=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
[[ ${#MODELS[@]} -eq 0 ]] && MODELS=(qwen2.5:3b)

log() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }

if command -v ollama >/dev/null 2>&1; then
    log "Ollama already installed ($(ollama --version 2>/dev/null | tail -n1))"
else
    log "Installing Ollama using the official script (https://ollama.com/install.sh, asks for sudo)"
    curl -fsSL https://ollama.com/install.sh | sh
fi

log "Waiting for the Ollama server at $URL"
for _ in $(seq 1 15); do
    if curl -fsS "$URL/api/version" >/dev/null 2>&1; then break; fi
    sleep 1
done
if ! curl -fsS "$URL/api/version" >/dev/null 2>&1; then
    echo "Ollama isn't responding. Start it with: sudo systemctl enable --now ollama" >&2
    echo "(or run 'ollama serve' in another terminal), then re-run this script." >&2
    exit 1
fi

if [[ $PULL -eq 1 ]]; then
    for model in "${MODELS[@]}"; do
        log "Pulling $model"
        ollama pull "$model"
    done
fi

log "Done. Installed models:"
ollama list
