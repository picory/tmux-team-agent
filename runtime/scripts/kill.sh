#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
AGENT_NAME="${2:?agent name is required}"
RUNTIME_HOME="${TMUX_RUNTIME_HOME:-$HOME/.tmux-runtime}"

python3 "$RUNTIME_HOME/lib/runtime.py" kill --project-dir "$PROJECT_DIR" --agent-name "$AGENT_NAME"
