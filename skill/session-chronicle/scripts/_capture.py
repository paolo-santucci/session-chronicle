"""Selective neutral events and replay-safe ingestion under the checkpoint lock."""
import datetime
import json
import os
from pathlib import Path
import re
import shlex

from _checkpoint import append_record, redact, sync_directory, writer_lock
from _session_notes import note_lint
from _storage_paths import regular_file, storage_layout

NOISE_RE = re.compile(r"^\s*(ls|cat|pwd|echo|cd)\b")
DISABLED = ("0", "false", "no", "off")
OPERATIONS = ("prompt.submit", "files.write", "files.edit", "files.patch", "process.exec")


def is_maintenance_command(command, cwd):
    if "\n" in command:
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0], re.S):
        tokens.pop(0)
    if tokens and os.path.basename(tokens[0]) in ("python", "python3", "bash"):
        interpreter = os.path.basename(tokens[0])
        tokens = tokens[1:]
        if interpreter in ("python", "python3") and tokens[:1] == ["-B"]:
            tokens = tokens[1:]
    if not tokens or any(re.fullmatch(r"[;&|<>()]+", token) for token in tokens):
        return False
    script = Path(cwd, tokens[0]).resolve()
    return script.parent == Path(__file__).resolve().parent and script.name in {
        "checkpoint.py", "capture-signals.py", "note-lint.py", "sync-topics-field.py",
        "topic-index.sh", "retrieve-inject.py", "memory-recall.sh", "memory-audit.py",
        "backlinks.py", "slugify.py", "_docsroot.py", "session-context.py", "_session_notes.py",
        "topic-maintenance.py", "topic-patch-lint.py", "_memory_read.py", "chronicle.py",
    }


def select_signal(arguments, project, base):
    operation = arguments["operation"]
    if operation == "prompt.submit":
        if os.environ.get("SESSION_CHRONICLE_CAPTURE_PROMPTS", "1").lower() in DISABLED:
            return None
        text = arguments["text"].strip()
        return {"kind": "prompt", "text": redact(text)} if text and not text.startswith("/session-chronicle") else None
    if operation.startswith("files."):
        path = Path(project, arguments["path"]).resolve()
        if any(path.is_relative_to((Path(base) / folder).resolve())
               for folder in (".drafts", "pending", "sessions", "topics", "continuations")):
            return None
        return {"kind": "file", "op": operation, "path": redact(arguments["path"])}
    if os.environ.get("SESSION_CHRONICLE_CAPTURE_BASH", "1").lower() in DISABLED:
        return None
    command = arguments["command"].strip()
    workdir = Path(project, arguments.get("workdir") or project)
    if not command or NOISE_RE.match(command) or is_maintenance_command(command, workdir):
        return None
    return {"kind": "bash", "cmd": redact(command)}


def stored_records(base):
    storage_layout(base)
    drafts = Path(base) / ".drafts"
    for path in sorted(drafts.glob("*.draft.jsonl")) + sorted((drafts / "pending").glob("*.jsonl")):
        regular_file(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict) or record.get("kind") not in ("prompt", "file", "bash"):
                    raise ValueError("Malformed evidence buffer; repair before ingestion")
                note_lint.record_session_id(record)
                yield path, record
    for path in sorted((Path(base) / "sessions").glob("*.md")):
        regular_file(path, publication_temporaries=True)
        text = path.read_text(encoding="utf-8")
        fm, _ = note_lint.split_fm(text)
        if note_lint.fm_get(fm, "record-kind") == "factual-evidence" or note_lint.is_batch_id(path.stem):
            if note_lint.record_findings(fm, base) or note_lint.fm_get(fm, "batch-id") != path.stem:
                raise ValueError("Invalid factual batch metadata; repair before ingestion")
            for record in note_lint.factual_records(text):
                yield path, record


class ReplayConflict(ValueError):
    pass


def replayed(base, candidate):
    found = False
    for path, record in stored_records(base):
        note_lint.require_unambiguous_identity(record)
        if (record.get("session_id"), record.get("event_id")) != (candidate["session_id"], candidate["event_id"]):
            continue
        admitted = {key: value for key, value in record.items() if key != "ts"}
        if admitted != candidate:
            raise ReplayConflict("Stable event identity was reused with a conflicting admitted payload")
        # Retry after an interrupted replace must sync before reporting durable success.
        with path.open("rb") as source:
            os.fsync(source.fileno())
        sync_directory(path.parent)
        found = True
    return found


def capture(context, arguments, base):
    signal = select_signal(arguments, context["workspace"], base)
    if signal is None:
        return {"status": "skipped", "reason": "capture_policy"}
    signal.update(identity=context["identity"], session_id=context["qualified_id"],
                  event_id=arguments["event_id"], operation=arguments["operation"],
                  origin=arguments["origin"], status=arguments["status"])
    if note_lint.secret_findings(json.dumps(signal)):
        raise ValueError("Event provenance contains secret-like values")
    with writer_lock(base) as drafts:
        if replayed(base, signal):
            return {"status": "duplicate", "session_id": context["qualified_id"]}
        signal["ts"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        draft = drafts / (datetime.date.today().isoformat() + ".draft.jsonl")
        # Atomic replacement avoids a torn append and needs no independent receipt ledger.
        append_record(draft, signal)
    return {"status": "captured", "session_id": context["qualified_id"]}
