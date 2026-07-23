#!/usr/bin/env python3
"""PreToolUse / PostToolUse hook for session-memory notes — the WRITE-PATH guard.

Acts only on files under <docs-root>/sessions/ or <docs-root>/topics/; anything
else exits 0 (not our concern).

  PreToolUse  (Write|Edit): block edits to a CLOSED session entry (append-only),
              and block content carrying secret-like patterns (tokens, keys,
              IPs) — memory notes are long-lived and re-injected into context,
              so a leaked credential would resurface on every retrieval. Claude
              is told which pattern kinds matched and asked to re-submit with
              [REDACTED-*] placeholders. Loopback/any-host IPs are exempt
              (SAFE_IPS) to avoid blocking harmless localhost mentions.
  PostToolUse (Write|Edit): validate frontmatter schema + mandatory provenance.

Exit 2 = block / report violation (stderr is shown to Claude).
Exit 0 = ok, or not a memory note, or an infrastructure error (never block real work
         on our own bugs).
stdlib only (no PyYAML).
"""
import sys, os, json, re

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
    m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fm, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


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


def resolve_base(proj):
    fm, _ = split_fm(read(os.path.join(proj, "CLAUDE.md")) or "")
    return os.path.join(proj, fm_get(fm, "docs-root") or ".claude/docs")


def classify(path, base):
    p = os.path.realpath(path)
    if p.startswith(os.path.realpath(os.path.join(base, "sessions")) + os.sep):
        return "session"
    if p.startswith(os.path.realpath(os.path.join(base, "topics")) + os.sep):
        return "topic"
    return None


def block(msg):
    sys.stderr.write("session-memory note-lint: " + msg + "\n")
    sys.exit(2)


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if data.get("tool_name") not in ("Write", "Edit"):
        return
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    kind = classify(path, resolve_base(proj))
    if not kind:
        return  # not a memory note

    event = data.get("hook_event_name", "")

    if event == "PreToolUse":
        inp = data.get("tool_input") or {}
        content = (inp.get("content") or "") + "\n" + (inp.get("new_string") or "")
        found = secret_findings(content)
        if found:
            block("content for '%s' contains secret-like pattern(s): %s. Memory notes must "
                  "never store secrets — replace each with a [REDACTED-<KIND>] placeholder "
                  "and re-submit." % (os.path.basename(path), ", ".join(found)))
        existing = read(path)
        if existing is not None and kind == "session":
            fm, _ = split_fm(existing)
            if fm_get(fm, "status") == "closed":
                block("'%s' is a CLOSED session entry — the chronology is append-only and closed "
                      "entries are immutable. Create a NEW session entry instead of editing this one."
                      % os.path.basename(path))
        return  # allow

    if event == "PostToolUse":
        text = read(path)
        if text is None:
            return
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
        else:  # topic
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


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # never block real work on our own errors
