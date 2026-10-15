#!/usr/bin/env python3
"""Resolve the current SDK session's enrichment target after a safe checkpoint."""
import json
import re
from pathlib import Path
import sys

from _checkpoint import checkpoint
from _docsroot import resolve_base
from _session_notes import load_note, note_lint, summary_findings


def session_state(base, session_id):
    sessions = base / "sessions"
    sources, summaries, presentations = [], [], []
    for path in sorted(sessions.glob("*.md")):
        if not path.resolve().is_relative_to(sessions.resolve()):
            raise ValueError("Session note escapes sessions directory; repair the link")
        fm, _ = load_note(path)
        kind = note_lint.fm_get(fm, "record-kind")
        if not kind and re.search(r"^record-kind:[ \t]*['\"]?(semantic-summary|session-presentation|factual-evidence)",
                                  path.read_text(), re.M):
            raise ValueError("Malformed session record frontmatter; repair before retrying")
        if kind == "factual-evidence" or note_lint.is_batch_id(path.stem):
            records = note_lint.factual_records(path.read_text())
            if note_lint.record_findings(fm, base) or note_lint.fm_get(fm, "batch-id") != path.stem:
                raise ValueError("Invalid factual batch metadata; repair before retrying")
            identities = [note_lint.require_unambiguous_identity(record) for record in records]
            if session_id in identities:
                sources.append(path.stem)
        elif kind in ("semantic-summary", "session-presentation"):
            identity = note_lint.fm_get(fm, "session-id")
            if not identity.strip():
                raise ValueError("Session view has missing or malformed session-id; repair before retrying")
            if identity != session_id:
                continue
            findings = summary_findings(path, base)
            if findings:
                raise ValueError("Invalid matching session view: " + "; ".join(findings))
            if note_lint.fm_get(fm, "status") == "closed":
                raise ValueError("Matching session view is closed and immutable; use a new SDK session")
            (summaries if kind == "semantic-summary" else presentations).append(path)
    if len(summaries) > 1 or len(presentations) > 1:
        raise ValueError("Duplicate matching session views; resolve duplicate identities before retrying")
    target = summaries[0] if summaries else sessions / note_lint.summary_name(session_id)
    if not summaries and (target.exists() or target.is_symlink()):
        raise ValueError("Deterministic target is occupied by a different note; resolve the collision")
    return sources, summaries, presentations, target


def resolve_context(data):
    if not isinstance(data, dict):
        raise ValueError("Input must be an object with project_root and session_id strings")
    root, identity = data.get("project_root"), data.get("session_id")
    if not isinstance(root, str) or not root.strip() or not isinstance(identity, str) or not identity.strip():
        raise ValueError("Provide non-empty project_root and the actual SDK session_id")
    project = Path(root).resolve()
    if not project.is_dir():
        raise ValueError("project_root must be an existing directory")
    base = Path(resolve_base(str(project))).resolve()
    if not base.is_relative_to(project) or not (base / "sessions").resolve().is_relative_to(project):
        raise ValueError("docs-root and sessions must remain inside project_root")
    session_state(base, identity)
    checkpoint(base)
    sources, summaries, presentations, target = session_state(base, identity)
    relative = lambda path: path.relative_to(project).as_posix() if path else None
    return {"session_id": identity, "presentation": relative(presentations[0] if presentations else None),
            "semantic_summary": relative(summaries[0] if summaries else None),
            "target": relative(target), "sources": sources}


def main():
    try:
        result = resolve_context(json.load(sys.stdin))
    except (ValueError, OSError, TypeError) as error:
        print(json.dumps({"error": {"code": "session_context_failed",
                                   "message": str(error) + "; resolve the data or checkpoint failure before retrying"}}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
