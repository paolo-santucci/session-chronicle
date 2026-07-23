#!/usr/bin/env python3
"""PostToolUse + UserPromptSubmit hook — passive capture of session signals.

The feeder of the session-memory write-path: mirrors meaningful tool activity
(file writes/edits, significant bash commands, user prompts) into an uncommitted
draft buffer at <docs-root>/.drafts/<today>.draft.jsonl. The buffer is raw
evidence for exactly one crystallisation per session: on Stop, checkpoint-nudge.py
asks Claude once to distill it into a sessions/ entry; session-chronicle Step 3
consumes the draft and truncates it.

Zero API calls, zero context tokens: this hook never writes to stdout (on
UserPromptSubmit any stdout would be injected into context). Noise control:
trivial bash commands (ls/cat/pwd/echo/cd) are skipped, file signals under
.drafts/ itself are skipped, consecutive duplicate signals are collapsed by
hash, and draft files older than DRAFT_TTL_DAYS are pruned.

stdlib only; never exits non-zero — a capture bug must never break a session.
"""
import sys, os, json, re, glob, time, hashlib, datetime

DRAFT_DIRNAME = ".drafts"
DRAFT_TTL_DAYS = 7
NOISE_RE = re.compile(r"^\s*(ls|cat|pwd|echo|cd)\b")


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def docs_root(proj):
    m = re.match(r"^---\s*\n(.*?)\n---", read(os.path.join(proj, "CLAUDE.md")), re.S)
    if m:
        mm = re.search(r"^docs-root:\s*(.*)$", m.group(1), re.M)
        if mm:
            return mm.group(1).strip().strip("'\"")
    return ".claude/docs"


def build_signal(data):
    if data.get("hook_event_name") == "UserPromptSubmit":
        text = (data.get("prompt") or "").strip()
        return {"kind": "prompt", "text": text[:300]} if text else None
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if tool in ("Write", "Edit"):
        path = inp.get("file_path", "")
        return {"kind": "file", "op": tool, "path": path} if path else None
    if tool == "Bash":
        cmd = (inp.get("command") or "").strip()
        if not cmd or NOISE_RE.match(cmd):
            return None
        return {"kind": "bash", "cmd": cmd[:200]}
    return None


def last_hash(draft):
    lines = read(draft).strip().splitlines()
    if not lines:
        return ""
    try:
        return json.loads(lines[-1]).get("_h", "")
    except Exception:
        return ""


def prune(draft_dir):
    cutoff = time.time() - DRAFT_TTL_DAYS * 86400
    for f in glob.glob(os.path.join(draft_dir, "*.draft.jsonl")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.unlink(f)
        except Exception:
            pass


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if data.get("hook_event_name") not in ("PostToolUse", "UserPromptSubmit"):
        return
    if data.get("stop_hook_active"):
        return

    sig = build_signal(data)
    if not sig:
        return

    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    draft_dir = os.path.join(proj, docs_root(proj), DRAFT_DIRNAME)
    if sig["kind"] == "file" and os.path.realpath(sig["path"]).startswith(
            os.path.realpath(draft_dir) + os.sep):
        return
    os.makedirs(draft_dir, exist_ok=True)
    prune(draft_dir)

    draft = os.path.join(draft_dir, datetime.date.today().isoformat() + ".draft.jsonl")
    h = hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:12]
    if h == last_hash(draft):
        return
    sig["_h"] = h
    sig["ts"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(draft, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sig, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
