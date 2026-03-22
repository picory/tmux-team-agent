#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$REPO_ROOT/runtime/lib/runtime.py" setup --repo-root "$REPO_ROOT" --project-dir "$PWD"
