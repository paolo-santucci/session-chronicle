#!/usr/bin/env bash
# Standalone installer. It deliberately refuses UAT's replacement surfaces.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKER_NAME=".session-chronicle-install.json"
MARKER_VERSION=2
for required in bun python3; do command -v "$required" >/dev/null 2>&1 || { echo "error: $required is required" >&2; exit 1; }; done

BUNDLED_SKILLS=(); for path in "$REPO_ROOT"/skill/*; do [ -f "$path/SKILL.md" ] && BUNDLED_SKILLS+=("$(basename "$path")"); done
BUNDLED_COMMANDS=(); for path in "$REPO_ROOT"/command/*.md; do [ -f "$path" ] && BUNDLED_COMMANDS+=("$(basename "$path")"); done
[ "${#BUNDLED_SKILLS[@]}" -gt 0 ] || { echo "error: no legacy standalone skills found" >&2; exit 1; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '==> %s\n' "$*"; }
usage() { cat <<'EOF'
Usage: scripts/install-local.sh <project-dir> [--force]
       scripts/install-local.sh --global [--force]

The staged module contains the portable plugin manifest and adapters. Native
OpenCode installation uses only legacy skill/ and command/ definitions. --force
is required for unidentified or locally modified installer paths and never
overrides a UAT deployment manifest.
EOF
}

TARGET=""; GLOBAL=0; FORCE=0
for arg in "$@"; do case "$arg" in --global) GLOBAL=1;; --force) FORCE=1;; -h|--help) usage; exit 0;; -*) die "unknown flag: $arg";; *) [ -z "$TARGET" ] || die "unexpected extra argument: $arg"; TARGET="$arg";; esac; done
if [ "$GLOBAL" -eq 1 ]; then
  [ -z "$TARGET" ] || die "pass either <project-dir> or --global, not both"
  OPENCODE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
else
  [ -n "$TARGET" ] && [ -d "$TARGET" ] || die "target project directory does not exist"
  TARGET="$(cd "$TARGET" && pwd)"; OPENCODE_DIR="$TARGET/.opencode"
fi
SRC_DIR="$OPENCODE_DIR/session-chronicle"; PLUGINS_DIR="$OPENCODE_DIR/plugins"; SKILLS_DIR="$OPENCODE_DIR/skills"; COMMANDS_DIR="$OPENCODE_DIR/commands"
MARKER="$SRC_DIR/$MARKER_NAME"

exists_or_link() { [ -e "$1" ] || [ -L "$1" ]; }
check_safe_ancestors() { # Do not traverse a deployment path through a symlink.
  local path="$1"
  while :; do
    [ ! -L "$path" ] || die "refusing unsafe symlink path: $path"
    [ "$path" = "$OPENCODE_DIR" ] && break
    path="$(dirname "$path")"
  done
}

# UAT's real deployment state lives at WORKSPACE/.uat/deployments/<harness>.json.
# An OpenCode UAT deployment replaces plugin/skill surfaces wholesale, so a valid
# manifest blocks this standalone route regardless of its plugin list. A present,
# symlinked, or malformed manifest also blocks: its ownership is ambiguous.
uat_manifest="$TARGET/.uat/deployments/opencode.json"
if [ "$GLOBAL" -eq 0 ] && exists_or_link "$uat_manifest"; then
  [ ! -L "$uat_manifest" ] || die "refusing UAT deployment manifest symlink: $uat_manifest"
  python3 - "$uat_manifest" <<'PY' || die "refusing malformed UAT deployment manifest: $uat_manifest"
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
    assert value["schema-version"] == 1
    assert value["harness"] == "opencode"
    assert isinstance(value["replace_paths"], list)
except (OSError, ValueError, KeyError, TypeError, AssertionError):
    raise SystemExit(1)
PY
  die "refusing standalone install: UAT owns OpenCode deployment surfaces via $uat_manifest"
fi

marker_owns_unchanged() { # $1 logical path, $2 actual path
  [ -f "$MARKER" ] && [ ! -L "$MARKER" ] || return 1
  python3 - "$MARKER" "$1" "$2" <<'PY'
import hashlib, json, os, sys
marker, logical, target = sys.argv[1:]
try:
    value = json.load(open(marker, encoding="utf-8"))
    assert value["installer"] in ("session-chronicle", "opencode-session-chronicle")
    assert value["version"] == 2
    expected = value["owned"][logical]
except (OSError, ValueError, KeyError, TypeError, AssertionError):
    raise SystemExit(1)
def digest(path, skip_marker=False):
    if os.path.islink(path): raise ValueError("symlink")
    h = hashlib.sha256()
    if os.path.isfile(path):
        h.update(b"F\0" + open(path, "rb").read()); return h.hexdigest()
    for base, dirs, files in os.walk(path):
        dirs.sort(); files.sort()
        for name in dirs + files:
            item = os.path.join(base, name)
            if os.path.islink(item): raise ValueError("symlink")
            rel = os.path.relpath(item, path)
            if skip_marker and rel == ".session-chronicle-install.json": continue
            h.update(("D\0" if os.path.isdir(item) else "F\0").encode() + rel.encode() + b"\0")
            if os.path.isfile(item): h.update(open(item, "rb").read())
    return h.hexdigest()
try: raise SystemExit(0 if digest(target, logical == "session-chronicle") == expected else 1)
except (OSError, ValueError): raise SystemExit(1)
PY
}
preflight_collision() { # $1 logical path $2 physical path
  check_safe_ancestors "$2"
  exists_or_link "$2" || return 0
  marker_owns_unchanged "$1" "$2" && return 0
  [ "$FORCE" -eq 1 ] || die "collision or local modification at $2; review it and use --force explicitly"
}

preflight_collision session-chronicle "$SRC_DIR"
preflight_collision plugins/session-chronicle.ts "$PLUGINS_DIR/session-chronicle.ts"
for name in "${BUNDLED_SKILLS[@]}"; do preflight_collision "skills/$name" "$SKILLS_DIR/$name"; done
for name in "${BUNDLED_COMMANDS[@]}"; do preflight_collision "commands/$name" "$COMMANDS_DIR/$name"; done

TMP_BASE="${TMPDIR:-/tmp}"
[ -d /tmp/opencode ] && [ "$TMP_BASE" = /tmp ] && TMP_BASE=/tmp/opencode
STAGE="$(mktemp -d "$TMP_BASE/session-chronicle-install.XXXXXX")"
cleanup_stage() { rm -rf "$STAGE"; }
trap cleanup_stage EXIT
STAGE_MODULE="$STAGE/session-chronicle"; mkdir -p "$STAGE_MODULE"

# This is an explicit release-input allowlist, not a claim that every copied
# checkout file is tracked. Reject symlinked inputs rather than following them.
for item in index.ts package.json bun.lock tsconfig.json README.md plugin.yaml adapters scripts skill command skills schemas; do
  source="$REPO_ROOT/$item"; [ -e "$source" ] || continue
  [ ! -L "$source" ] || die "refusing symlinked release input: $source"
  find "$source" -type l -print -quit | grep -q . && die "refusing release input containing symlink: $source"
  find "$source" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -iname '*credential*' -o -iname '*secret*' \) -print -quit | grep -q . && die "refusing potential secret in release input: $source"
  cp -R "$source" "$STAGE_MODULE/"
done
find "$STAGE_MODULE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE_MODULE" -name '*.pyc' -type f -delete
info "resolving dependencies in staged module"
(cd "$STAGE_MODULE" && bun install --production --frozen-lockfile --ignore-scripts >/dev/null) || die "bun install failed; target was not modified"

mkdir -p "$STAGE/plugins" "$STAGE/skills" "$STAGE/commands"
printf 'export { default } from "../session-chronicle/index.ts"\n' >"$STAGE/plugins/session-chronicle.ts"
for name in "${BUNDLED_SKILLS[@]}"; do cp -R "$REPO_ROOT/skill/$name" "$STAGE/skills/"; done
for name in "${BUNDLED_COMMANDS[@]}"; do cp "$REPO_ROOT/command/$name" "$STAGE/commands/"; done

DESTS=("$SRC_DIR" "$PLUGINS_DIR/session-chronicle.ts"); LOGICAL=(session-chronicle plugins/session-chronicle.ts)
SOURCES=("$STAGE_MODULE" "$STAGE/plugins/session-chronicle.ts")
for name in "${BUNDLED_SKILLS[@]}"; do DESTS+=("$SKILLS_DIR/$name"); LOGICAL+=("skills/$name"); SOURCES+=("$STAGE/skills/$name"); done
for name in "${BUNDLED_COMMANDS[@]}"; do DESTS+=("$COMMANDS_DIR/$name"); LOGICAL+=("commands/$name"); SOURCES+=("$STAGE/commands/$name"); done

# The marker records exact target paths and content digests. Its own bytes are
# excluded from the module digest to avoid a self-referential hash.
python3 - "$STAGE_MODULE/$MARKER_NAME" "${LOGICAL[@]}" -- "${SOURCES[@]}" <<'PY'
import hashlib, json, os, sys
marker = sys.argv[1]; args = sys.argv[2:]; cut = args.index("--"); logical, paths = args[:cut], args[cut+1:]
def digest(path, skip=False):
    h=hashlib.sha256()
    if os.path.isfile(path): return hashlib.sha256(open(path,"rb").read()).hexdigest()
    for base, dirs, files in os.walk(path):
        dirs.sort(); files.sort()
        for name in dirs+files:
            item=os.path.join(base,name); rel=os.path.relpath(item,path)
            if skip and rel==".session-chronicle-install.json": continue
            h.update(("D\0" if os.path.isdir(item) else "F\0").encode()+rel.encode()+b"\0")
            if os.path.isfile(item): h.update(open(item,"rb").read())
    return h.hexdigest()
owned={key:digest(path, key=="session-chronicle") for key,path in zip(logical,paths)}
json.dump({"installer":"session-chronicle","version":2,"owned":owned}, open(marker,"w",encoding="utf-8"), sort_keys=True)
PY

# Best-effort rollback covers ordinary failures and signals; a process or host
# crash during multi-path replacement cannot be atomic. Backups stay beside the
# target (same filesystem) and are retained if restoration itself fails.
mkdir -p "$OPENCODE_DIR"
BACKUP="$(mktemp -d "$OPENCODE_DIR/.session-chronicle-install-backup.XXXXXX")"
attempted=(); restoring=0; keep_backup=0
restore() {
  [ "$restoring" -eq 0 ] || return; restoring=1; set +e
  for ((i=${#DESTS[@]}-1; i>=0; i--)); do
    # The physical backup is the authority: a signal can arrive after mv has
    # returned but before shell bookkeeping resumes. Never nest it under a
    # partially installed destination.
    if exists_or_link "$BACKUP/$i"; then
      if rm -rf "${DESTS[i]}" && ! exists_or_link "${DESTS[i]}" && mkdir -p "$(dirname "${DESTS[i]}")"; then
        mv "$BACKUP/$i" "${DESTS[i]}" || keep_backup=1
      else
        keep_backup=1
      fi
    elif [ "${attempted[i]:-0}" = 1 ]; then
      rm -rf "${DESTS[i]}"
    fi
  done
  [ "$keep_backup" -eq 0 ] || printf 'error: rollback incomplete; preserve and inspect %s\n' "$BACKUP" >&2
}
finish() {
  status=$?
  trap - EXIT INT TERM
  [ "$status" -eq 0 ] || restore
  rm -rf "$STAGE"
  [ "${keep_backup:-0}" -eq 0 ] && rm -rf "${BACKUP:-}"
  exit "$status"
}
on_signal() {
  status="$1"
  trap - EXIT INT TERM
  restore
  rm -rf "$STAGE"
  [ "${keep_backup:-0}" -eq 0 ] && rm -rf "${BACKUP:-}"
  exit "$status"
}
trap finish EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM
for i in "${!DESTS[@]}"; do
  dest="${DESTS[i]}"; mkdir -p "$(dirname "$dest")" || die "could not create destination parent"
  if exists_or_link "$dest"; then mv "$dest" "$BACKUP/$i" || die "could not back up $dest"; fi
  # Set before mv: SIGINT/SIGTERM may run after its child has completed but
  # before this shell can record a successful replacement.
  attempted[i]=1
  if ! mv "${SOURCES[i]}" "$dest"; then die "could not install $dest; attempting rollback"; fi
done
info "done: standalone module, OpenCode shim, legacy skills, and commands installed"
