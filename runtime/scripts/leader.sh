#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
RUNTIME_HOME="${CMUX_RUNTIME_HOME:-${AI_RUNTIME_HOME:-$HOME/.cmux-runtime}}"

python3 "$RUNTIME_HOME/lib/runtime.py" leader-session --project-dir "$PROJECT_DIR"
