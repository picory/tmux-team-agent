#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
RUNTIME_HOME="${CMUX_RUNTIME_HOME:-$HOME/.cmux-runtime}"

python3 "$RUNTIME_HOME/lib/runtime.py" watch --project-dir "$PROJECT_DIR"
