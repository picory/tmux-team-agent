#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
ROLE="${2:?role is required}"
AGENT_NAME="${3:-}"
TASK_ID="${4:-}"
RUNTIME_HOME="${CMUX_RUNTIME_HOME:-$HOME/.cmux-runtime}"

cmd=(
  python3 "$RUNTIME_HOME/lib/runtime.py" spawn
  --project-dir "$PROJECT_DIR"
  --role "$ROLE"
)

if [[ -n "$AGENT_NAME" ]]; then
  cmd+=(--agent-name "$AGENT_NAME")
fi

if [[ -n "$TASK_ID" ]]; then
  cmd+=(--task-id "$TASK_ID")
fi

"${cmd[@]}"
