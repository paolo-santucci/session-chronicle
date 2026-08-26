#!/usr/bin/env python3
"""Idle hook — decide whether a checkpoint is due and surface it.

Fires (exit 2, message on stderr) when either:
  (a) today's draft buffer (<docs-root>/.drafts/<today>.draft.jsonl, written
      passively by capture-signals.py) holds >= MEMORY_DRAFT_NUDGE_MIN signals
      (default 3) — the message asks to crystallise that concrete evidence; or
  (b) a commit was made today with no recent (today/yesterday) OPEN sessions/
      entry — the original generic reminder (fallback when the capture hook is
      not registered on this target).

The draft branch deliberately ignores an existing recent `open` entry: the
correct self-limiter for the deterministic trigger is draft truncation on
crystallisation, so a fresh batch of work must still be journaled into the day's
open entry. The `open` gate applies only to the commit-today fallback, keeping a
healthy journaled session from being re-nudged on every commit.

Honours `stop_hook_active` to avoid loops. stdlib only. Exit 2 = surface
message. Exit 0 = nothing to do / error (never break the turn on our own bug).
"""
import sys, os, json, re, glob, subprocess, datetime

from _docsroot import resolve_base


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if data.get("stop_hook_active"):
        return  # already in a stop-hook continuation; don't loop

    proj = os.environ.get("PROJECT_ROOT") or data.get("cwd") or os.getcwd()
    base = resolve_base(proj)

    today = datetime.date.today()
    recent = {today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()}
    has_recent_open = False
    for f in glob.glob(os.path.join(base, "sessions", "*.md")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                head = fh.read(2000)
        except Exception:
            continue
        sm = re.search(r"^status:\s*(\S+)", head, re.M)
        if not (sm and sm.group(1).strip().strip("'\"") == "open"):
            continue
        dm = re.search(r"^date:\s*(\S+)", head, re.M)
        d = dm.group(1).strip().strip("'\"") if dm else os.path.basename(f)[:10]
        if d in recent:
            has_recent_open = True
            break

    draft = os.path.join(base, ".drafts", today.isoformat() + ".draft.jsonl")
    try:
        with open(draft, encoding="utf-8", errors="replace") as fh:
            draft_count = sum(1 for line in fh if line.strip())
    except Exception:
        draft_count = 0
    if draft_count >= int(os.environ.get("MEMORY_DRAFT_NUDGE_MIN", "3")):
        sys.stderr.write(
            "session-memory: %d tool signal(s) buffered in %s. Run /session-chronicle "
            "to crystallise them into a sessions/ entry before finishing.\n"
            % (draft_count, os.path.relpath(draft, proj)))
        sys.exit(2)

    if not has_recent_open:
        try:
            out = subprocess.run(["git", "-C", proj, "log", "--since=midnight", "--oneline"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                sys.stderr.write(
                    "session-memory: you committed today but there is no recent (today/yesterday) "
                    "OPEN sessions/ journal entry. Run /session-chronicle to checkpoint "
                    "this session before finishing.\n")
                sys.exit(2)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
