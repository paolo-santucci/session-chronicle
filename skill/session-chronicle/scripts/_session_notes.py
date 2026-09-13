"""Shared validation and selection of session views."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("note_lint", Path(__file__).with_name("note-lint.py"))
note_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note_lint)


def load_note(path):
    return note_lint.split_fm(Path(path).read_text(encoding="utf-8"))


def summary_findings(path, base):
    fm, body = load_note(path)
    findings = note_lint.record_findings(fm, base)
    if note_lint.fm_get(fm, "id") != Path(path).stem:
        findings.append("session view id must match its filename")
    if any(not note_lint.fm_get(fm, key) for key in ("id", "date", "title", "session-id")):
        findings.append("summary requires id, date, title and session-id")
    if note_lint.fm_get(fm, "status") not in ("open", "closed") or not body.strip():
        findings.append("summary requires open|closed status and a non-empty body")
    return findings


def preferred_paths(paths, base, include_evidence=False):
    notes = [(path, load_note(path)[0]) for path in paths]
    summaries = {}
    presentations = {}
    for path, fm in notes:
        if note_lint.fm_get(fm, "record-kind") == "semantic-summary":
            identity = note_lint.fm_get(fm, "session-id")
            summaries.setdefault(identity, []).append(path)
        if note_lint.fm_get(fm, "record-kind") == "session-presentation":
            identity = note_lint.fm_get(fm, "session-id")
            presentations.setdefault(identity, []).append(path)
    preferred = {identity: matches[0] for identity, matches in summaries.items()
                 if identity and len(matches) == 1 and not summary_findings(matches[0], base)}
    selected = []
    for path, fm in notes:
        kind = note_lint.fm_get(fm, "record-kind")
        identity = note_lint.fm_get(fm, "session-id")
        if kind == "factual-evidence" and not include_evidence:
            continue
        if kind == "semantic-summary" and preferred.get(identity) != path:
            continue
        if kind == "session-presentation":
            if identity in preferred or len(presentations[identity]) != 1:
                continue
            if summary_findings(path, base):
                continue
        selected.append(path)
    return selected


def print_recent_sessions(base):
    paths = sorted((Path(base) / "sessions").glob("*.md"))
    paths = preferred_paths(paths, base)
    entries = [(path, load_note(path)[0]) for path in paths]
    entries.sort(key=lambda entry: (note_lint.fm_get(entry[1], "started")
                 or note_lint.fm_get(entry[1], "date") or entry[0].name[:10], entry[0].name), reverse=True)
    for path, fm in entries[:8]:
        title = note_lint.fm_get(fm, "title")
        print(f"- {path.stem}" + (f" — {title}" if title else ""))


if __name__ == "__main__":
    import sys

    print_recent_sessions(sys.argv[1])
