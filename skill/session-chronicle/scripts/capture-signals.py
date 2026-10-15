#!/usr/bin/env python3
"""PostToolUse + UserPromptSubmit hook — passive capture of session signals.

The feeder of the session-memory write-path: mirrors meaningful tool activity
(file writes/edits, significant bash commands, user prompts) into an uncommitted
draft buffer at <docs-root>/.drafts/<today>.draft.jsonl. checkpoint.py seals and
publishes immutable factual batches without a model. Semantic enrichment is optional.

Zero API calls, zero context tokens: this hook never writes to stdout (on
UserPromptSubmit any stdout would be injected into context). Noise control:
trivial bash commands (ls/cat/pwd/echo/cd) are skipped, file signals under
.drafts/, sessions/, and topics/ are skipped; consecutive duplicate signals
within a draft are collapsed by hash. Unpublished evidence is never age-pruned.
SESSION_CHRONICLE_CAPTURE_PROMPTS and SESSION_CHRONICLE_CAPTURE_BASH independently
disable future channel capture when set to 0, false, no, or off. Existing data
is retained. Redaction is heuristic, not a confidentiality guarantee.

Writes use atomic full-file replacement under the shared writer lock. A malformed
existing buffer blocks capture unchanged: preserve the original and repair it
explicitly before retrying; this wrapper never truncates or repairs evidence.
stdlib only; failures exit non-zero so the adapter can report capture loss.
"""
import sys, os, json, re, hashlib, datetime, shlex
from pathlib import Path

from _docsroot import resolve_base
from _checkpoint import append_record, validated_draft, writer_lock, redact, sync_directory
from _capture import is_maintenance_command

NOISE_RE = re.compile(r"^\s*(ls|cat|pwd|echo|cd)\b")


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def build_signal(data):
    if data.get("hook_event_name") == "UserPromptSubmit":
        if os.environ.get("SESSION_CHRONICLE_CAPTURE_PROMPTS", "1").lower() in ("0", "false", "no", "off"):
            return None
        text = (data.get("prompt") or "").strip()
        return {"kind": "prompt", "text": redact(text)} if text else None
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if tool in ("Write", "Edit"):
        path = inp.get("file_path", "")
        return {"kind": "file", "op": tool, "path": path} if path else None
    if tool == "Bash":
        if os.environ.get("SESSION_CHRONICLE_CAPTURE_BASH", "1").lower() in ("0", "false", "no", "off"):
            return None
        cmd = (inp.get("command") or "").strip()
        if not cmd or NOISE_RE.match(cmd):
            return None
        return {"kind": "bash", "cmd": redact(cmd)}
    return None


def last_hash(draft):
    lines = read(draft).strip().splitlines()
    if not lines:
        return ""
    try:
        return json.loads(lines[-1]).get("_h", "")
    except Exception:
        return ""


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

    proj = os.environ.get("PROJECT_ROOT") or data.get("cwd") or os.getcwd()
    base = resolve_base(proj)
    if sig["kind"] == "file":
        path = os.path.realpath(os.path.join(proj, sig["path"]))
        if any(path.startswith(os.path.realpath(os.path.join(base, folder)) + os.sep)
               for folder in (".drafts", "sessions", "topics")):
            return
    if sig["kind"] == "prompt" and sig["text"].startswith("/session-chronicle"):
        return
    if sig["kind"] == "bash" and is_maintenance_command(
            (data.get("tool_input") or {}).get("command", ""),
            os.path.join(proj, (data.get("tool_input") or {}).get("workdir") or data.get("cwd") or proj)):
        return
    sig = json.loads(redact(json.dumps(sig)))
    sig["sessionID"] = data.get("sessionID")
    sig["eventID"] = data.get("eventID")
    with writer_lock(base) as draft_dir:
        draft = draft_dir / (datetime.date.today().isoformat() + ".draft.jsonl")
        _, records = validated_draft(draft)
        h = hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()
        if records and h == records[-1].get("_h"):
            with draft.open("rb") as source:
                os.fsync(source.fileno())
            sync_directory(draft_dir)
            return
        sig["_h"] = h
        sig["ts"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        append_record(draft, sig)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"session-chronicle: capture failed ({type(error).__name__}); preserve buffers and inspect/repair before retrying", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
