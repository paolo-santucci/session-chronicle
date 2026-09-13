#!/usr/bin/env bash
# SessionStart hook — orientation only.
# Emits a COMPACT index of project memory (topic slugs + recent session titles) to stdout,
# which the plugin injects as a synthetic message part. Not the note bodies — orientation;
# the UserPromptSubmit hook (retrieve-inject.py) injects bodies on demand.
# Read-only, deterministic, never fails the session (always exits 0).
set -o pipefail 2>/dev/null

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ="${PROJECT_ROOT:-$PWD}"
DOCS_ROOT=$(python3 "${SCRIPT_DIR}/_docsroot.py" "$PROJ" 2>/dev/null) || DOCS_ROOT=""
BASE="${PROJ}/${DOCS_ROOT:-docs}"
SESS="${BASE}/sessions"
TOP="${BASE}/topics"

if [ ! -d "$SESS" ] && [ ! -d "$TOP" ]; then
  python3 "${SCRIPT_DIR}/_docsroot.py" --check "$PROJ" 2>/dev/null
  exit 0
fi

title_of() {
  awk -F': ' '/^title:/{sub(/^title:[[:space:]]*/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$1" 2>/dev/null
}
line_for() {
  local f="$1" slug t
  slug=$(basename "$f" .md)
  t=$(title_of "$f")
  if [ -n "$t" ]; then echo "- ${slug} — ${t}"; else echo "- ${slug}"; fi
}

echo "## Project memory index (auto, read-only)"

if [ -d "$TOP" ]; then
  n=$(find "$TOP" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  if [ "${n:-0}" -gt 0 ]; then
    echo "### Topics (${n}) — read \`${DOCS_ROOT:-docs}/topics/<slug>.md\` for detail"
    find "$TOP" -maxdepth 1 -name '*.md' 2>/dev/null | sort | while read -r f; do line_for "$f"; done
  fi
fi

started_of() {
  awk -F': ' '/^started:/{sub(/^started:[[:space:]]*/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$1" 2>/dev/null
}
record_kind_of() {
  awk 'NR == 1 {if ($0 !~ /^---[[:space:]]*$/) exit; next}
    /^---[[:space:]]*$/ {exit}
    /^record-kind:/ {sub(/^record-kind:[[:space:]]*/, ""); sub(/[[:space:]]+$/, "");
      gsub(/^["'\'']|["'\'']$/, ""); print; exit}' "$1" 2>/dev/null
}
if [ -d "$SESS" ]; then
  echo "### Recent sessions (latest 8)"
  python3 "${SCRIPT_DIR}/_session_notes.py" "$BASE" 2>/dev/null
fi

# Inline health check (only surfaces when thresholds are exceeded, ~30 tokens):
# without it memory-audit.py is never run and entropy accumulates silently.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STALE_MAX="${MEMORY_HEALTH_STALE_MAX:-5}"
DANGLING_MAX="${MEMORY_HEALTH_DANGLING_MAX:-10}"
HEALTH=$(python3 "${SCRIPT_DIR}/memory-audit.py" --stale --days 90 --dangling --base "$BASE" --json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('stale',[])), len(d.get('dangling',{})))" 2>/dev/null)
n_stale=$(echo "$HEALTH" | cut -d' ' -f1)
n_dangling=$(echo "$HEALTH" | cut -d' ' -f2)
if [ "${n_stale:-0}" -gt "$STALE_MAX" ] 2>/dev/null || [ "${n_dangling:-0}" -gt "$DANGLING_MAX" ] 2>/dev/null; then
  echo "_Health: ${n_stale} stale topic notes (>90d), ${n_dangling} dangling links. Triage: \`memory-audit.py --base ${DOCS_ROOT:-docs}\`_"
fi

echo "_Recall a subject's full history: read its topic note, then grep sessions/ for [[slug]]._"
exit 0
