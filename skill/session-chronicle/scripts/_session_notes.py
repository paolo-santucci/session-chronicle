"""Shared validation and selection of session views."""
import importlib.util
from pathlib import Path

from _topic_graph import active_topic, parse_fields, read_frontmatter


spec = importlib.util.spec_from_file_location("note_lint", Path(__file__).with_name("note-lint.py"))
note_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note_lint)

SUMMARY_KINDS = ("semantic-summary", "session-presentation")
FACTUAL = "factual-evidence"


def load_note(path):
    return note_lint.split_fm(Path(path).read_text(encoding="utf-8"))


def summary_findings(path, base, source_cache=None, *, fm=None):
    """Findings for one session view.

    `fm` is the frontmatter the caller already read: it is validated as given and the note is
    never re-read, so a header-only caller (retrieval) pays no second read. Without `fm` the
    whole note is loaded and its body must be non-empty, as before.
    """
    body = None
    if fm is None:
        fm, body = load_note(path)
    findings = note_lint.record_findings(fm, base, source_cache)
    if note_lint.fm_get(fm, "id") != Path(path).stem:
        findings.append("session view id must match its filename")
    if any(not note_lint.fm_get(fm, key) for key in ("id", "date", "title", "session-id")):
        findings.append("summary requires id, date, title and session-id")
    if note_lint.fm_get(fm, "status") not in ("open", "closed") or (body is not None and not body.strip()):
        findings.append("summary requires open|closed status and a non-empty body")
    return findings


def usable_fields(frontmatter):
    """Fields of an already-read header; None when the header cannot be parsed at all.

    A header with no fields is a legacy note without frontmatter and stays selectable; a header
    that claims fields but does not parse is not a candidate. Neither case re-reads the note.
    """
    text = frontmatter if isinstance(frontmatter, str) else ""
    fields = {key: value for key, value in parse_fields(text).items() if not key.startswith(":")}
    if fields or not text.strip():
        return fields
    return None


def record_kind_of(frontmatter):
    """The `record-kind` of an already-read header (`""` for a legacy or ordinary note)."""
    return note_lint.fm_get(frontmatter, "record-kind")


def identity_of(frontmatter):
    """The `session-id` of an already-read header — the ONE identity extraction.

    Both phases must call this: the partition below groups identities with it and retrieval
    derives the candidate's identity with it. Two parsers of the same header (`fm_get` here,
    `parse_fields` there) disagree on a hand-edited scalar such as `session-id: 'a''b'`, the
    lookup misses and a summary and its presentation are both emitted (FR-34).
    """
    return note_lint.fm_get(frontmatter, "session-id")


def select_candidates(headers, base, include_evidence=False):
    """Phase 1 of retrieval: the eligibility partition over headers the caller already read.

    `headers` is a sequence of (path, frontmatter_text) pairs. Pure and total: no file I/O, no
    note re-reading, no provenance validation and no swallowed error. Factual evidence is
    excluded unless `include_evidence`, inactive topics are dropped, and summaries and
    presentations are grouped per identity (an absent session-id groups under ""). `base` is
    kept for call-site symmetry with `preferred_paths` even though eligibility needs no
    filesystem root: dropping it would ripple into `chronicle-doctor` and the selection tests.
    """
    eligible = []
    identities = {}
    for path, frontmatter in headers:
        text = frontmatter if isinstance(frontmatter, str) else ""
        fields = usable_fields(text)
        if fields is None or not active_topic(fields):
            continue
        kind = record_kind_of(text)
        if kind == FACTUAL and not include_evidence:
            continue
        eligible.append(path)
        if kind in SUMMARY_KINDS:
            identity = identity_of(text)
            group = identities.setdefault(identity, {"summaries": [], "presentations": []})
            group["summaries" if kind == "semantic-summary" else "presentations"].append(path)
    return {"eligible": eligible, "identities": identities}


def validate_view(path, fm, base, source_cache):
    """True when a note may be presented using the header it was read with.

    Ordinary notes need no provenance check. A summary or presentation is validated from the
    given frontmatter, never by re-reading the note, and shares the caller's per-call cache.
    """
    if record_kind_of(fm) not in SUMMARY_KINDS:
        return True
    return not summary_findings(path, base, source_cache, fm=fm)


def preferred_paths(paths, base, include_evidence=False):
    """The index's selector: eager, fully validated, input-ordered.

    Per-path read errors are swallowed here (a missing note must not break the index); a
    validated unique summary for an identity suppresses its presentation, and an identity with
    two summaries or two presentations contributes neither.
    """
    # Each selection has a fresh validation snapshot; never trust a cache across calls.
    source_cache = {}
    headers = []
    for path in paths:
        try:
            headers.append((path, read_frontmatter(path)))
        except (OSError, UnicodeError, ValueError):
            continue
    selection = select_candidates(headers, base, include_evidence)
    eligible = set(selection["eligible"])
    identities = selection["identities"]
    headers_of = dict(headers)

    preferred = {}
    for identity, group in identities.items():
        summaries = group["summaries"]
        if identity and len(summaries) == 1 and validate_view(summaries[0], headers_of[summaries[0]],
                                                             base, source_cache):
            preferred[identity] = summaries[0]

    selected = []
    for path, fm in headers:
        if path not in eligible:
            continue
        kind = record_kind_of(fm)
        identity = identity_of(fm)
        if kind == "semantic-summary" and preferred.get(identity) != path:
            continue
        if kind == "session-presentation":
            if identity in preferred or len(identities[identity]["presentations"]) != 1:
                continue
            if not validate_view(path, fm, base, source_cache):
                continue
        selected.append(path)
    return selected


def print_recent_sessions(base, paths=None):
    if paths is None:
        paths = preferred_paths(sorted((Path(base) / "sessions").glob("*.md")), base)
    entries = [(path, read_frontmatter(path)) for path in paths]
    entries.sort(key=lambda entry: (note_lint.fm_get(entry[1], "started")
                 or note_lint.fm_get(entry[1], "date") or entry[0].name[:10], entry[0].name), reverse=True)
    for path, fm in entries[:8]:
        title = note_lint.fm_get(fm, "title")
        print(f"- {path.stem}" + (f" — {title}" if title else ""))


if __name__ == "__main__":
    import sys

    print_recent_sessions(sys.argv[1])
