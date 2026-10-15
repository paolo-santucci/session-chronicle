#!/usr/bin/env python3
"""Synchronize wikilink topics on validated mutable memory notes."""
import os
from pathlib import Path
import re
import sys

from _checkpoint import writer_lock, update_presentation
from _docsroot import resolve_base
from _session_notes import note_lint, summary_findings


def validate_mutable_note(path, base):
    if path.is_symlink() or note_lint.classify(path, base) not in ("session", "topic"):
        raise ValueError("Expected a local session or topic note inside docs-root")
    text = path.read_text(encoding="utf-8")
    fm, _ = note_lint.split_fm(text)
    kind = note_lint.fm_get(fm, "record-kind")
    if kind in ("factual-evidence", "session-presentation") or note_lint.fm_get(fm, "status") == "closed":
        raise ValueError("Closed, factual-evidence and generated presentation notes are immutable")
    if kind == "semantic-summary":
        if note_lint.fm_get(fm, "session-id").startswith("chronicle:"):
            raise ValueError("Portable semantic summaries require trusted context and the guarded semantic writer")
        findings = summary_findings(path, base)
        findings += note_lint.semantic_write_findings(
            path, text, text, note_lint.fm_get(fm, "session-id"), base)
        if findings:
            raise ValueError("; ".join(findings))
    elif kind or note_lint.fm_get(fm, "type") not in ("session", "topic"):
        raise ValueError("Expected a semantic summary or generic session/topic note")
    elif note_lint.fm_get(fm, "type") == "session" and note_lint.fm_get(fm, "status") != "open":
        raise ValueError("Generic session notes must be explicitly open")
    return text


def main(argv):
    if len(argv) != 1:
        raise ValueError("usage: sync-topics-field.py <session-file>")
    base = resolve_base(os.environ.get("PROJECT_ROOT") or os.getcwd())
    path = Path(argv[0])
    with writer_lock(base):
        text = validate_mutable_note(path, base)
        fm, body = note_lint.split_fm(text)
        links = sorted(set(re.findall(r"\[\[([a-z0-9][a-z0-9-]*)\]\]", body)))
        new_line = "topics: [" + ", ".join(links) + "]"
        if re.search(r"^topics:.*$", fm, re.M):
            updated = re.sub(r"^topics:.*$", new_line, fm, count=1, flags=re.M)
        else:
            updated = fm.rstrip("\n") + "\n" + new_line
        update_presentation(path, text.replace(fm, updated, 1))
    print(new_line)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, OSError) as error:
        print("session-memory sync-topics: " + str(error), file=sys.stderr)
        sys.exit(2)
