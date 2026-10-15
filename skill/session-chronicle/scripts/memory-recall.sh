#!/usr/bin/env bash
# Read-only, graph-aware topic and supporting-session recall.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${SCRIPT_DIR}/_memory_read.py" recall "$@"
