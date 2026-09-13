#!/usr/bin/env bash
# memory-recall.sh <slug> [--topic|--sessions|--all]   (default: --all)
#
# One-call recall of a known subject: prints the topic note body and/or the list
# of session entries backlinking the slug (aliases included, via backlinks.py),
# so the LLM spends one tool call instead of a cat+grep chain.
# Read-only; always exits 0 on a resolvable environment (2 only on usage error).
set -o pipefail 2>/dev/null

SLUG="$1"
MODE="${2:---all}"
if [ -z "$SLUG" ]; then
  echo "usage: memory-recall.sh <slug> [--topic|--sessions|--all]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ="${PROJECT_ROOT:-$PWD}"
DOCS_ROOT=$(python3 "${SCRIPT_DIR}/_docsroot.py" "$PROJ" 2>/dev/null) || DOCS_ROOT=""
DOCS_ROOT="${DOCS_ROOT%/}"
BASE="${PROJ}/${DOCS_ROOT:-docs}"

if [ "$MODE" = "--topic" ] || [ "$MODE" = "--all" ]; then
  echo "## [topic] ${SLUG}"
  cat "${BASE}/topics/${SLUG}.md" 2>/dev/null || echo "(no topic note — subject not yet materialised)"
fi

if [ "$MODE" = "--sessions" ] || [ "$MODE" = "--all" ]; then
  echo ""
  echo "## sessions backlinking [[${SLUG}]] (read ${DOCS_ROOT:-docs}/sessions/<id>.md for detail)"
  HITS=$(python3 "${SCRIPT_DIR}/backlinks.py" "$SLUG" --base "$BASE" 2>/dev/null)
  if [ -n "$HITS" ]; then
    echo "$HITS" | sed 's/^/- /'
  else
    echo "(none)"
  fi
fi
exit 0
