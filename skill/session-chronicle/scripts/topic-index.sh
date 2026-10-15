#!/usr/bin/env bash
# Bounded read-only startup orientation; never block session startup.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "${SCRIPT_DIR}/_memory_read.py" index
exit 0
