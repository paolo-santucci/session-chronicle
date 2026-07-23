#!/usr/bin/env python3
"""Stop hook — active nudge to crystallise a finished unit of work.

Fires (exit 2, message to Claude) only when NO recent (today/yesterday) OPEN
sessions/ entry is being journaled, and either:
  (a) today's draft buffer (<docs-root>/.drafts/<today>.draft.jsonl, written
      passively by capture-signals.py) holds >= MEMORY_DRAFT_NUDGE_MIN signals
      (default 3) — the message asks to crystallise that concrete evidence; or
  (b) a commit was made today — the original generic reminder (fallback when
      the capture hook is not registered on this target).

Self-limiting: honours `stop_hook_active` to avoid loops, and goes quiet as soon
as a recent open entry exists (session-chronicle truncates the draft on
crystallisation, so a closed session cannot re-trigger via stale signals).

stdlib only. Exit 2 = surface message. Exit 0 = nothing to do / error (never
break the turn on our own bug).
"""
import sys, os, json, re, glob, subprocess, datetime


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if data.get("stop_hook_active"):
        return  # already in a stop-hook continuation; don't loop

    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    cm = ""
    try:
        with open(os.path.join(proj, "CLAUDE.md"), encoding="utf-8", errors="replace") as fh:
            cm = fh.read()
    except Exception:
        pass
    dr = ""
    m = re.match(r"^---\s*\n(.*?)\n---", cm, re.S)
    if m:
        mm = re.search(r"^docs-root:\s*(.*)$", m.group(1), re.M)
        if mm:
            dr = mm.group(1).strip().strip("'\"")
    base = os.path.join(proj, dr or ".claude/docs")

    # Stay quiet only if a *recent* (today or yesterday) session entry is still
    # `status: open`. The yesterday window covers a session that started before
    # midnight and remains current after the date rolled over — keying on a
    # `<today>--*.md` glob would false-nudge there. An open entry older than that is
    # a forgotten close, NOT the current session, so it must NOT suppress the nudge.
    today = datetime.date.today()
    recent = {today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()}
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
            return  # a recent open session is being journaled — stay quiet

    draft = os.path.join(base, ".drafts", today.isoformat() + ".draft.jsonl")
    try:
        with open(draft, encoding="utf-8", errors="replace") as fh:
            draft_count = sum(1 for line in fh if line.strip())
    except Exception:
        draft_count = 0
    if draft_count >= int(os.environ.get("MEMORY_DRAFT_NUDGE_MIN", "3")):
        sys.stderr.write(
            "session-memory: %d tool signal(s) buffered in %s. Run /update-status "
            "(it hands off to /session-chronicle) to crystallise them into a "
            "sessions/ entry before finishing.\n"
            % (draft_count, os.path.relpath(draft, proj)))
        sys.exit(2)

    try:
        out = subprocess.run(["git", "-C", proj, "log", "--since=midnight", "--oneline"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            sys.stderr.write(
                "session-memory: you committed today but there is no recent (today/yesterday) "
                "OPEN sessions/ journal entry. Run /update-status (it hands off to "
                "/session-chronicle) to checkpoint this session before finishing.\n")
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
