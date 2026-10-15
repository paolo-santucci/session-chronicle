#!/usr/bin/env python3
"""PreToolUse / PostToolUse hook for session-memory notes — the WRITE-PATH guard.

Acts only on files under <docs-root>/sessions/ or <docs-root>/topics/; anything
else exits 0 (not our concern).

  PreToolUse  (Write|Edit): block edits to a CLOSED session entry (append-only),
              and block content carrying secret-like patterns (tokens, keys,
              IPs) — memory notes are long-lived and re-injected into context,
              so a leaked credential would resurface on every retrieval. The caller
              is told which pattern kinds matched and asked to re-submit with
              [REDACTED-*] placeholders. Loopback/any-host IPs are exempt
              (SAFE_IPS) to avoid blocking harmless localhost mentions.
  PostToolUse (Write|Edit): validate frontmatter schema + mandatory provenance.

Exit 2 = block / report violation (stderr is surfaced by the plugin).
Exit 0 = ok, or not a memory note. Validator errors fail closed.
stdlib only (no PyYAML).
"""
import sys, os, json, re, datetime
import hashlib
from pathlib import Path

from _docsroot import resolve_base
from _identity import AmbiguousIdentity, canonical_identity, parse_identity
from _storage_paths import regular_file
from _topic_graph import parse_note, proposed_topic_findings, without_comment

REDACT_PATTERNS = [
    ("GITHUB-TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("API-KEY", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("AWS-KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("SLACK-TOKEN", re.compile(r"xox[bp]-[A-Za-z0-9-]{10,}")),
    ("PRIVATE-KEY", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
    ("IP-ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]
SAFE_IPS = {"127.0.0.1", "0.0.0.0"}


def secret_findings(content):
    found = []
    for name, pat in REDACT_PATTERNS:
        hits = pat.findall(content)
        if name == "IP-ADDRESS":
            hits = [h for h in hits if h not in SAFE_IPS]
        if hits:
            found.append("%s x%d" % (name, len(hits)))
    return found


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return None


def split_fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text or "", re.S)
    if m:
        return m.group(1), m.group(2)
    return None, text or ""


def fm_get(fm, key):
    if not fm:
        return ""
    matches = re.findall(r"^%s:[ \t]*(.*)$" % re.escape(key), fm, re.M)
    if len(matches) != 1:
        return ""
    try:
        value = without_comment(matches[0]).strip()
    except ValueError:
        return ""
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, str) else ""
        except ValueError:
            return ""
    return value.strip("'")


def fm_has(fm, key):
    """True if key is present with a non-empty inline value OR a following YAML list item."""
    if not fm:
        return False
    m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fm, re.M)
    if not m:
        return False
    inline = m.group(1).strip().strip("'\"")
    if inline and inline not in ("[]", "null", "~"):
        return True
    return bool(re.match(r"\s*\n\s*-\s+\S", fm[m.end():]))


def classify(path, base):
    p = os.path.realpath(path)
    for folder in (".drafts", "pending", "continuations"):
        protected = os.path.realpath(os.path.join(base, folder))
        if p == protected or p.startswith(protected + os.sep):
            return "protected"
    if p.startswith(os.path.realpath(os.path.join(base, "sessions")) + os.sep):
        return "session"
    if p.startswith(os.path.realpath(os.path.join(base, "topics")) + os.sep):
        return "topic"
    return None


def is_batch_id(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}--evidence-[a-f0-9]{32}", value):
        return False
    try:
        datetime.date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def source_ids(fm):
    if len(re.findall(r"^sources:", fm or "", re.M)) != 1:
        return []
    match = re.search(r"^sources:[ \t]*(.*)$", fm or "", re.M)
    if not match:
        return []
    inline = match[1].strip()
    if inline.startswith("[") and inline.endswith("]"):
        values = inline[1:-1].split(",")
    elif not inline:
        block = re.match(r"(?:\n[ \t]+-[ \t]+[^\n]+)+", fm[match.end():])
        values = re.findall(r"^[ \t]+-[ \t]+(.+)$", block[0], re.M) if block else []
    else:
        return []
    return [value.strip().strip("'\"") for value in values if value.strip()]


def record_findings(fm, base, source_cache=None):
    kind = fm_get(fm, "record-kind")
    if not kind:
        return []
    if kind == "factual-evidence":
        batch = fm_get(fm, "batch-id")
        expected = {"id": batch, "type": "session", "date": batch[:10],
                    "status": "closed", "provenance": "captured_signals"}
        if not is_batch_id(batch) or any(fm_get(fm, key) != value for key, value in expected.items()):
            return ["factual evidence requires a valid batch-id matching id/date, type session, closed status and captured_signals provenance"]
        return []
    if kind not in ("semantic-summary", "session-presentation"):
        return ["record-kind must be factual-evidence|semantic-summary|session-presentation"]
    sources = source_ids(fm)
    if not sources or len(sources) != len(set(sources)) or any(not is_batch_id(source) for source in sources):
        return [f"{kind} sources must be a non-empty list of factual batch IDs"]
    cache = {} if source_cache is None else source_cache
    validated = []
    for source in sources:
        key = (os.path.abspath(base), source)
        if key not in cache:
            cache[key] = factual_source_validation(source, base)
        error, identities = cache[key]
        if error:
            return [f"{kind} {error}"]
        validated.append(identities)
    if fm_get(fm, "type") != "session":
        return [f"{kind} type must be session"]
    session_id = fm_get(fm, "session-id")
    if not session_id.strip():
        return [f"{kind} requires a non-empty stable session-id"]
    if kind == "session-presentation" and fm_get(fm, "provenance") != "captured_signals":
        return ["session-presentation requires captured_signals provenance"]
    for identities in validated:
        if session_id not in identities:
            return [f"{kind} sources must contain the matching session-id"]
    return []


def factual_source_validation(source, base):
    path = os.path.join(base, "sessions", source + ".md")
    if os.path.islink(path):
        return "sources must be local factual files, not symbolic links", frozenset()
    text = read(path)
    fm, body = split_fm(text)
    if (fm_get(fm, "record-kind") != "factual-evidence" or fm_get(fm, "id") != source
            or not body.strip() or record_findings(fm, base)):
        return "sources must reference persisted valid factual records", frozenset()
    try:
        regular_file(path, publication_temporaries=True)
        records = factual_records(text)
        return "", frozenset(record_session_id(record) for record in records)
    except ValueError:
        return "source contains malformed factual data; repair the source before retrying", frozenset()


def record_session_id(record):
    if not isinstance(record, dict):
        raise ValueError("Factual session identity requires an object record")
    values = [record[key] for key in ("session_id", "sessionID") if record.get(key) is not None]
    if any(not isinstance(value, str) for value in values) or len(set(values)) > 1:
        raise ValueError("Conflicting or invalid factual session identity")
    identity = values[0] if values else ""
    if "identity" in record:
        parse_identity(identity)
        if canonical_identity(record["identity"]) != identity:
            raise ValueError("Factual identity metadata does not match session identity")
    if "event_id" in record:
        if ("identity" not in record or not isinstance(record["event_id"], str)
                or not record["event_id"].strip()):
            raise ValueError("Portable event requires original identity and stable event_id")
    return identity


def record_identity_key(record):
    """Only original identity metadata can qualify a historical identifier."""
    return ("qualified" if "identity" in record else "legacy", record_session_id(record))


def require_unambiguous_identity(record):
    kind, identity = record_identity_key(record)
    if kind == "legacy" and identity.startswith("chronicle:"):
        raise AmbiguousIdentity("Ambiguous reserved-prefix legacy identity; preserve bytes and require an explicit additive mapping")
    return identity


def qualified_source_identities(source, base):
    error, _ = factual_source_validation(source, base)
    if error:
        raise ValueError(error)
    records = factual_records((Path(base) / "sessions" / (source + ".md")).read_text(encoding="utf-8"))
    return {identity for record in records for kind, identity in [record_identity_key(record)] if kind == "qualified"}


def factual_records(text):
    _, body = split_fm(text)
    matches = re.findall(r"```json\n(.*?)\n```", body, re.S)
    if len(matches) != 1:
        raise ValueError("Factual source requires exactly one JSON evidence array")
    records = json.loads(matches[0])
    if not isinstance(records, list) or not records:
        raise ValueError("Factual source requires a non-empty evidence array")
    for record in records:
        if not isinstance(record, dict) or record.get("kind") not in ("prompt", "file", "bash"):
            raise ValueError("Malformed factual record")
        record_session_id(record)
    return records


def summary_name(identity):
    return "session--" + hashlib.sha256(identity.encode()).hexdigest() + "--summary.md"


def semantic_write_findings(path, proposed, existing, identity, base):
    fm, body = split_fm(proposed)
    old_fm, old_body = split_fm(existing)
    findings = record_findings(fm, base)
    if isinstance(identity, str) and identity.startswith("chronicle:"):
        try:
            if any(identity not in qualified_source_identities(source, base) for source in source_ids(fm)):
                findings.append("qualified semantic-summary requires metadata-qualified source identity")
        except ValueError:
            findings.append("qualified semantic-summary requires valid factual sources")
    if not isinstance(identity, str) or not identity.strip() or fm_get(fm, "session-id") != identity:
        findings.append("semantic-summary session-id must equal the non-empty trusted SDK sessionID")
    if fm_get(fm, "id") != Path(path).stem:
        findings.append("semantic-summary id must match its filename")
    if Path(path).resolve().parent != (Path(base) / "sessions").resolve() or Path(path).is_symlink():
        findings.append("semantic-summary target must be a local file directly inside sessions")
    if not body.strip() or any(not fm_get(fm, key) for key in ("date", "title")):
        findings.append("semantic-summary requires date, title and body")
    if fm_get(fm, "status") not in ("open", "closed"):
        findings.append("semantic-summary status must be open|closed")
    if existing is None:
        if isinstance(identity, str) and Path(path).name != summary_name(identity):
            findings.append("new semantic-summary must use the deterministic SDK session target")
    elif (fm_get(old_fm, "record-kind") != "semantic-summary"
          or fm_get(old_fm, "id") != fm_get(fm, "id") or record_findings(old_fm, base)
          or not old_body.strip() or any(not fm_get(old_fm, key) for key in ("date", "title"))
          or fm_get(old_fm, "status") != "open"):
        findings.append("existing target must already be a valid semantic-summary with the same id")
    for candidate in (Path(base) / "sessions").glob("*.md"):
        other_fm, _ = split_fm(read(candidate))
        if (candidate.resolve() != Path(path).resolve() and fm_get(other_fm, "record-kind") == "semantic-summary"
                and fm_get(other_fm, "session-id") == identity):
            findings.append("duplicate semantic-summary session-id; resolve existing target first")
    return findings


def block(msg):
    raise ValueError(msg)


def validate_change(proj, identity, arguments):
    """Validate a neutral replace/edit snapshot; callers own the actual write."""
    path = arguments["path"]
    path = os.path.abspath(os.path.join(proj, path))
    base = resolve_base(proj)
    lexical_kind = next((folder for folder in ("sessions", "topics", ".drafts", "pending", "continuations")
                         if Path(path).is_relative_to(Path(base) / folder)), None)
    if lexical_kind and (not Path(path).resolve().is_relative_to(Path(proj).resolve())
                         or Path(path).is_symlink()):
        block("memory note target must be a local file inside the project, not a symbolic link")
    kind = classify(path, base)
    if kind == "protected":
        block("drafts, pending evidence and continuation records are writer-owned")
    if not kind:
        return  # not a memory note

    phase = arguments.get("phase", "pre")

    if phase == "pre":
        content = (arguments.get("content") or "") + "\n" + (arguments.get("new_text") or "")
        existing = Path(path).read_text(encoding="utf-8") if Path(path).exists() else None
        old_string = arguments.get("old_text") or ""
        new_string = arguments.get("new_text") or ""
        if existing is not None and old_string:
            content += "\n" + existing.replace(old_string, new_string)
        proposed = arguments.get("content", "") if arguments["kind"] == "replace" else (
            (existing or "").replace(old_string, new_string, -1 if arguments.get("replace_all") else 1)
            if old_string else existing or "")
        proposed_fm, _ = split_fm(proposed)
        existing_fm, _ = split_fm(existing)
        topic_fields, _ = parse_note(proposed)
        old_topic_fields, _ = parse_note(existing or "")
        if kind == "topic" and "note-kind" in old_topic_fields and "note-kind" not in topic_fields:
            block("typed topic cannot drop note-kind to bypass structural validation")
        if kind == "topic" and "note-kind" in topic_fields:
            findings = proposed_topic_findings(path, proposed, resolve_base(proj), proj)
            if findings:
                block("; ".join(item["code"] + ": " + item["message"] for item in findings))
        if fm_get(existing_fm, "record-kind") == "semantic-summary":
            if (fm_get(proposed_fm, "record-kind") != "semantic-summary"
                    or fm_get(existing_fm, "session-id") != fm_get(proposed_fm, "session-id")):
                block("semantic-summary session-id and record-kind are immutable; restore the original identity")
        if fm_get(proposed_fm, "record-kind") == "semantic-summary":
            findings = semantic_write_findings(path, proposed, existing, identity, resolve_base(proj))
            if findings:
                block("; ".join(findings))
        if fm_get(proposed_fm, "record-kind") == "factual-evidence":
            block("factual-evidence files may only be created by the checkpoint writer")
        if re.search(r"^record-kind:\s*['\"]?session-presentation\b", content, re.M):
            block("session-presentation files are generated by the checkpoint writer and cannot be created by an agent")
        found = secret_findings(content)
        if found:
            block("content for '%s' contains secret-like pattern(s): %s. Memory notes must "
                  "never store secrets — replace each with a [REDACTED-<KIND>] placeholder "
                  "and re-submit." % (os.path.basename(path), ", ".join(found)))
        if existing is not None and kind == "session":
            fm, _ = split_fm(existing)
            if fm_get(fm, "record-kind") == "factual-evidence":
                block("factual-evidence files are immutable and cannot be edited by an agent")
            if fm_get(fm, "record-kind") == "session-presentation":
                block("'%s' is a generated session presentation and may only be updated by the checkpoint writer. "
                      "Create a separate semantic summary instead." % os.path.basename(path))
            if fm_get(fm, "status") == "closed":
                block("'%s' is a CLOSED session entry — the chronology is append-only and closed "
                      "entries are immutable. Create a NEW session entry instead of editing this one."
                      % os.path.basename(path))
        return  # allow

    if phase == "post":
        text = Path(path).read_text(encoding="utf-8")
        fm, body = split_fm(text)
        if fm is None:
            block("'%s' has no YAML frontmatter. Memory notes require a '---' fenced block." % os.path.basename(path))

        missing = []
        if kind == "session":
            for k in ("id", "type", "date", "title", "status"):
                if not fm_get(fm, k):
                    missing.append(k)
            st = fm_get(fm, "status")
            if st and st not in ("open", "closed"):
                missing.append("status must be open|closed")
            missing.extend(record_findings(fm, resolve_base(proj)))
            if fm_get(fm, "record-kind") in ("semantic-summary", "session-presentation") and fm_get(fm, "id") != os.path.splitext(os.path.basename(path))[0]:
                missing.append("id must match the session view filename")
        else:  # topic
            topic_fields, _ = parse_note(text)
            if "note-kind" in topic_fields:
                missing.extend(item["message"] for item in proposed_topic_findings(
                    path, text, resolve_base(proj), proj))
            for k in ("id", "type", "title"):
                if not fm_get(fm, k):
                    missing.append(k)
            # Provenance is MANDATORY and must be CONCRETE — the template ships a
            # `provenance: derived_from_*` default, so accepting that alone would let a
            # placeholder pass. Require non-empty `sources:` whenever provenance is
            # derived_from_*; only `stated_by_user` may omit sources.
            prov = fm_get(fm, "provenance")
            has_sources = fm_has(fm, "sources")
            if prov in ("derived_from_sessions", "derived_from_plan"):
                if not has_sources:
                    missing.append("sources (non-empty) — required when provenance is derived_from_*")
            elif prov == "stated_by_user":
                pass  # user-stated topics need no source paths
            elif not has_sources:
                missing.append("sources or provenance (provenance is MANDATORY)")
        if not body.strip():
            missing.append("body (note must have content)")

        if missing:
            block("'%s' (%s note) missing required field(s): %s" % (os.path.basename(path), kind, ", ".join(missing)))
        return


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Write", "Edit"):
        return
    inp = data.get("tool_input") or {}
    if not inp.get("file_path"):
        return
    project = os.environ.get("PROJECT_ROOT") or data.get("cwd") or os.getcwd()
    phase = {"PreToolUse": "pre", "PostToolUse": "post"}.get(data.get("hook_event_name"))
    if phase:
        validate_change(project, data.get("sessionID"), {
            "kind": "replace" if data["tool_name"] == "Write" else "edit", "path": inp["file_path"],
            "phase": phase, "content": inp.get("content", ""), "old_text": inp.get("old_string", ""),
            "new_text": inp.get("new_string", ""), "replace_all": inp.get("replace_all", False)})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except ValueError as error:
        print("session-memory note-lint: " + str(error), file=sys.stderr)
        sys.exit(2)
    except Exception:
        print("session-memory note-lint: validator failed; mutation cannot be approved", file=sys.stderr)
        sys.exit(2)
