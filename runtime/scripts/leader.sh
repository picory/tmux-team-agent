#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
RUNTIME_HOME="${AI_RUNTIME_HOME:-$HOME/.ai-runtime}"

python3 "$RUNTIME_HOME/lib/runtime.py" leader-loop --project-dir "$PROJECT_DIR"
