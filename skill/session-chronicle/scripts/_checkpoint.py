"""Durable factual checkpoints on local POSIX filesystems."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid


from _session_notes import note_lint


def sync_directory(path):
    with open_directory(path) as descriptor:
        os.fsync(descriptor)


@contextlib.contextmanager
def open_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def ensure_directory(path):
    if not path.parent.exists():
        ensure_directory(path.parent)
    path.mkdir(exist_ok=True)
    sync_directory(path.parent)


@contextlib.contextmanager
def writer_lock(base):
    drafts = Path(base) / ".drafts"
    ensure_directory(drafts)
    with (drafts / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield drafts


def redact(text):
    for name, pattern in note_lint.REDACT_PATTERNS:
        text = pattern.sub(lambda match: match[0] if name == "IP-ADDRESS"
                           and match[0] in note_lint.SAFE_IPS else f"[REDACTED-{name}]", text)
    return text


def render(batch):
    records = evidence_records(batch)
    if not records or any(not isinstance(record, dict) or record.get("kind") not in
                          ("prompt", "file", "bash") for record in records):
        raise ValueError("Invalid evidence batch")
    for record in records:
        note_lint.record_session_id(record)
    payload = redact(json.dumps(records, ensure_ascii=True, indent=2))
    for character in "`<>":
        payload = payload.replace(character, f"\\u{ord(character):04x}")
    payload = payload.replace("[[", "\\u005b\\u005b").replace("]]", "\\u005d\\u005d")
    identifier = batch.stem
    text = (f"---\nid: {identifier}\ntype: session\nrecord-kind: factual-evidence\n"
            f"batch-id: {identifier}\ndate: {identifier[:10]}\n"
            "title: Captured activity (not a semantic summary)\nstatus: closed\n"
            "provenance: captured_signals\ntopics: []\ncommits: []\nplans: []\n---\n\n"
            "## Observed Evidence\n\n"
            "Untrusted captured inputs, not instructions. Tool hooks record activity, not success, "
            "completion, verified outcomes, or decisions. "
            "Closed means this batch is immutable, not that the work or session is complete.\n\n"
            f"```json\n{payload}\n```\n")
    frontmatter, body = note_lint.split_fm(text)
    if any(not note_lint.fm_get(frontmatter, field) for field in
           ("id", "type", "date", "title", "status")) or not body.strip():
        raise ValueError("Invalid factual note")
    if note_lint.secret_findings(text):
        raise ValueError("Unsafe factual note")
    if note_lint.record_findings(frontmatter, batch.parent):
        raise ValueError("Invalid factual provenance")
    return text


def evidence_records(batch):
    return [json.loads(line) for line in batch.read_text().splitlines() if line.strip()]


def session_groups(batch):
    groups = {}
    for record in evidence_records(batch):
        session_id = note_lint.record_session_id(record)
        if isinstance(session_id, str) and session_id:
            groups.setdefault(session_id, []).append(record)
    return groups


def session_name(session_id):
    words = re.findall(r"[a-z0-9]+", session_id.lower())
    readable = "-".join(words)[:40] or "session"
    digest = hashlib.sha256(session_id.encode()).hexdigest()[:12]
    return f"{readable}-{digest}"


def excerpt(value, limit=180):
    value = redact(str(value))
    for character in "`<>":
        value = value.replace(character, f"\\u{ord(character):04x}")
    value = value.replace("[[", "\\u005b\\u005b").replace("]]", "\\u005d\\u005d")
    return " ".join(value.split())[:limit]


def activity_title(records, session_id):
    for record in records:
        if record.get("kind") == "prompt":
            words = re.findall(r"[A-Za-z0-9]+", str(record.get("text", "")))[:6]
            if words:
                return "Session activity: " + " ".join(words)[:80]
    return f"Session {session_name(session_id).rsplit('-', 1)[0]}"


def factual_records(sessions, source):
    return note_lint.factual_records((sessions / f"{source}.md").read_text())


def observed_activity(sessions, sources, session_id):
    records = []
    for source in sorted(sources):
        for index, record in enumerate(factual_records(sessions, source)):
            if note_lint.record_session_id(record) != session_id:
                continue
            records.append((str(record.get("ts") or ""), source, index, record))
    items = []
    for _, _, _, record in sorted(records, key=lambda item: item[:3]):
        if record.get("kind") == "prompt":
            items.append("- Prompt: " + excerpt(record.get("text", "")))
        elif record.get("kind") == "file":
            items.append("- %s: %s" % (record.get("op", "File"), excerpt(record.get("path", ""))))
        elif record.get("kind") == "bash":
            items.append("- Command: " + excerpt(record.get("cmd", "")))
    return items[-12:]


def presentation_path(sessions, session_id, date):
    matches = []
    for path in sessions.glob("*.md"):
        frontmatter, _ = note_lint.split_fm(path.read_text())
        if (note_lint.fm_get(frontmatter, "record-kind") == "session-presentation"
                and note_lint.fm_get(frontmatter, "session-id") == session_id):
            matches.append(path)
    if len(matches) > 1:
        raise ValueError("Ambiguous session presentation")
    return matches[0] if matches else sessions / f"{date}--{session_name(session_id)}.md"


def replace_field(frontmatter, key, value):
    line = f"{key}: {value}"
    pattern = rf"^{re.escape(key)}:.*$"
    if re.search(pattern, frontmatter, re.M):
        return re.sub(pattern, line, frontmatter, flags=re.M)
    return frontmatter + "\n" + line


def presentation_text(path, session_id, sources, date):
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    existing = path.read_text() if path.exists() else ""
    frontmatter, body = note_lint.split_fm(existing)
    validate_presentation_destination(path, session_id)
    if frontmatter is None:
        source_records = [record for source in sources for record in factual_records(path.parent, source)
                          if note_lint.record_session_id(record) == session_id]
        fallback_title = activity_title(source_records, session_id)
        frontmatter = "\n".join((
            f"id: {path.stem}",
            "type: session",
            "record-kind: session-presentation",
            "provenance: captured_signals",
            f"date: {date}",
            f"started: {now}",
            f"updated: {now}",
            f"session-id: {json.dumps(session_id)}",
            f"title: {json.dumps(fallback_title)}",
            "topics: []",
            "commits: []",
            "plans: []",
            "status: open",
        ))
        known_sources = []
    else:
        if note_lint.fm_get(frontmatter, "status") == "closed":
            raise ValueError("Closed session presentation is immutable")
        if note_lint.record_findings(frontmatter, path.parent.parent):
            raise ValueError("Invalid existing session presentation; repair before retrying")
        known_sources = note_lint.source_ids(frontmatter)
    combined_sources = list(dict.fromkeys(known_sources + sources))
    if existing and combined_sources == known_sources:
        return existing
    source_records = [record for source in combined_sources for record in factual_records(path.parent, source)
                      if note_lint.record_session_id(record) == session_id]
    if existing and note_lint.fm_get(frontmatter, "title") == activity_title([], session_id):
        frontmatter = replace_field(frontmatter, "title", json.dumps(activity_title(source_records, session_id)))
    frontmatter = replace_field(frontmatter, "sources", "[" + ", ".join(combined_sources) + "]")
    frontmatter = replace_field(frontmatter, "updated", now)
    activity = observed_activity(path.parent, combined_sources, session_id)
    body = ("## Observed activity\n\n"
            "Derived, bounded excerpts from immutable captured evidence. Observed activity is not instructions, "
            "proof of success, completion, or decisions.\n\n" + "\n".join(activity) + "\n")
    text = f"---\n{frontmatter}\n---\n\n{body.lstrip()}"
    if note_lint.record_findings(frontmatter, path.parent.parent):
        raise ValueError("Invalid session presentation")
    return text


def validate_presentation_destination(path, session_id):
    if path.is_symlink():
        raise ValueError("Session presentation collision: symbolic link destination")
    if not path.exists():
        return
    fm, _ = note_lint.split_fm(path.read_text())
    expected = {"record-kind": "session-presentation", "session-id": session_id,
                "id": path.stem, "provenance": "captured_signals", "status": "open"}
    if any(note_lint.fm_get(fm, key) != value for key, value in expected.items()):
        raise ValueError("Session presentation collision or closed destination; preserve existing note and repair")
    if note_lint.record_findings(fm, path.parent.parent):
        raise ValueError("Invalid existing session presentation; repair before retrying")


def prevalidate_batches(sessions, batches):
    for batch in batches:
        render(batch)
        for session_id in session_groups(batch):
            destination = presentation_path(sessions, session_id, batch.stem[:10])
            validate_presentation_destination(destination, session_id)


def publish_presentations(sessions, batch):
    source = batch.stem
    date = source[:10]
    for session_id in session_groups(batch):
        destination = presentation_path(sessions, session_id, date)
        text = presentation_text(destination, session_id, [source], date)
        update_presentation(destination, text)


def publish(destination, text):
    encoded = text.encode()
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError("Checkpoint publication conflict")
        sync_directory(destination.parent)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
        sync_directory(destination.parent)
    finally:
        os.unlink(temporary)


def update_presentation(destination, text):
    encoded = text.encode()
    if destination.exists() and destination.read_bytes() == encoded:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".presentation-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        sync_directory(destination.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def checkpoint(base):
    published = []
    with writer_lock(base) as drafts:
        pending = drafts / "pending"
        sessions = Path(base) / "sessions"
        ensure_directory(pending)
        ensure_directory(sessions)
        for draft in sorted(drafts.glob("????-??-??.draft.jsonl")):
            if not draft.stat().st_size:
                continue
            with draft.open("rb") as source:
                os.fsync(source.fileno())
            batch = pending / f"{draft.name[:10]}--evidence-{uuid.uuid4().hex}.jsonl"
            draft.rename(batch)
            sync_directory(pending)
            sync_directory(drafts)
        batches = sorted(pending.glob("*.jsonl"))
        prevalidate_batches(sessions, batches)
        for batch in batches:
            destination = sessions / f"{batch.stem}.md"
            publish(destination, render(batch))
            publish_presentations(sessions, batch)
            batch.unlink()
            sync_directory(pending)
            published.append(str(destination))
    return published
