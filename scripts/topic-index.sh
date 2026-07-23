#!/usr/bin/env bash
# SessionStart hook — orientation only.
# Emits a COMPACT index of project memory (topic slugs + recent session titles) to stdout,
# which Claude Code injects as session-start context. Not the note bodies — orientation;
# the UserPromptSubmit hook (retrieve-inject.py) injects bodies on demand.
# Read-only, deterministic, never fails the session (always exits 0).
set -o pipefail 2>/dev/null

PROJ="${CLAUDE_PROJECT_DIR:-$PWD}"
DOCS_ROOT=$(awk '/^---$/{f++; next} f==1 && /^docs-root:[[:space:]]*/{sub(/^docs-root:[[:space:]]*/, ""); gsub(/["'\''[:space:]]/, ""); print; exit}' "${PROJ}/CLAUDE.md" 2>/dev/null)
BASE="${PROJ}/${DOCS_ROOT:-.claude/docs}"
SESS="${BASE}/sessions"
TOP="${BASE}/topics"

[ -d "$SESS" ] || [ -d "$TOP" ] || exit 0

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
    echo "### Topics (${n}) — read \`${DOCS_ROOT:-.claude/docs}/topics/<slug>.md\` for detail"
    find "$TOP" -maxdepth 1 -name '*.md' 2>/dev/null | sort | while read -r f; do line_for "$f"; done
  fi
fi

started_of() {
  awk -F': ' '/^started:/{sub(/^started:[[:space:]]*/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$1" 2>/dev/null
}
if [ -d "$SESS" ]; then
  echo "### Recent sessions (latest 8)"
  # Order chronologically by the `started:` timestamp (falls back to the filename's
  # leading YYYY-MM-DD date for legacy entries that predate the field). This is what
  # disambiguates multiple sessions on the same day; a bare filename sort cannot.
  find "$SESS" -maxdepth 1 -name '*.md' 2>/dev/null | while read -r f; do
    k=$(started_of "$f")
    [ -n "$k" ] || k=$(basename "$f" | cut -c1-10)
    printf '%s\t%s\n' "$k" "$f"
  done | sort -rk1,1 | head -8 | cut -f2- | while read -r f; do line_for "$f"; done
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
  echo "_Health: ${n_stale} stale topic notes (>90d), ${n_dangling} dangling links. Triage: \`memory-audit.py --base ${DOCS_ROOT:-.claude/docs}\`_"
fi

echo "_Recall a subject's full history: read its topic note, then grep sessions/ for [[slug]]._"
exit 0
