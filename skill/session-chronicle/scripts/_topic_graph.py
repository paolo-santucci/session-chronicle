"""Read-only topic graph and structural validation. No semantic truth claims."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from _docsroot import resolve_base

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REVIEW_NOTICE = "Structure checks cannot prove atomicity or factual truth; semantic review is required."
PARSE_ERRORS = ":parse-errors"
RESOLUTION_CODES = {"alias-collision", "duplicate-id", "redirect-cycle", "redirect-target",
                    "topic-path", "unreadable-topic"}


def valid_slug(value):
    return isinstance(value, str) and bool(SLUG.fullmatch(value))


def unquoted_positions(value):
    """Yield delimiters outside quoted scalar tokens, including YAML single quotes."""
    quote = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if quote == '"' and character == "\\":
                index += 2
                continue
            if character == quote:
                if quote == "'" and value[index:index + 2] == "''":
                    index += 2
                    continue
                quote = None
        elif character in "\"'" and (not value[:index].strip() or value[:index].rstrip().endswith(("[", ",", ":", "-"))):
            quote = character
        else:
            yield index, character
        index += 1
    if quote:
        raise ValueError("unterminated quoted scalar")


def without_comment(value):
    for index, character in unquoted_positions(value):
        if character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def scalar(value):
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        if not isinstance(decoded, str):
            raise ValueError("expected a string")
        return decoded
    if value.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            raise ValueError("invalid single-quoted scalar")
        return value[1:-1].replace("''", "'")
    if value.startswith(("[", "]", "{", "}", "|", ">", "&", "*", "!")) or re.search(r":\s", value):
        raise ValueError("unsupported YAML syntax; use a quoted scalar or a flat list")
    if value in ("null", "~", "true", "false") or re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None if value == "~" else json.loads(value)
    return value


def inline_value(value):
    if not value.startswith("["):
        return scalar(value)
    if not value.endswith("]"):
        raise ValueError("unterminated inline list")
    content = value[1:-1]
    if not content.strip():
        return []
    positions = [index for index, character in unquoted_positions(content) if character == ","]
    starts, ends = [0] + [index + 1 for index in positions], positions + [len(content)]
    values = [content[start:end].strip() for start, end in zip(starts, ends)]
    if any(not item for item in values):
        raise ValueError("empty inline list item")
    if any(character in "[]{}" for item in values for _, character in unquoted_positions(item)):
        raise ValueError("nested or malformed inline list; quote literal brackets")
    return [scalar(item) for item in values]


def parse_fields(frontmatter):
    fields, errors = {}, []
    list_key = None
    for line in frontmatter.splitlines():
        try:
            line = without_comment(line)
            if not line.strip():
                continue
            item = re.fullmatch(r"[ \t]+-[ \t]+(.+)", line)
            if item and list_key:
                if fields[list_key] == "":
                    fields[list_key] = []
                fields[list_key].append(scalar(item[1]))
                continue
            field = re.fullmatch(r"([\w-]+):[ \t]*(.*)", line)
            if not field:
                raise ValueError("unsupported frontmatter line; use flat fields and lists")
            key, value = field.groups()
            list_key = None
            if key in fields:
                fields[key] = None
                raise ValueError("duplicate field: " + key)
            fields[key] = None
            fields[key] = inline_value(value) if value else ""
            if not value:
                list_key = key
        except (ValueError, TypeError) as error:
            errors.append(str(error))
            list_key = None
    if errors:
        fields[PARSE_ERRORS] = errors
    return fields


def parse_note(text):
    match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)(.*)\Z", text, re.S)
    if not match:
        return {}, text
    return parse_fields(match[1]), match[2]


def read_frontmatter(path):
    # Binary lines avoid text-decoder read-ahead into an unused, possibly invalid evidence body.
    with Path(path).open("rb") as source:
        if source.readline().strip() != b"---":
            return ""
        lines = []
        for line in source:
            if line.strip() == b"---":
                return b"".join(lines).decode("utf-8")
            lines.append(line)
    raise ValueError("unterminated frontmatter")


def interpreted_body(body):
    """Exclude fenced examples/evidence, block quotes, and inline code."""
    lines = []
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            if re.match(r"^\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$", line):
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        if line.lstrip().startswith(">") or line.startswith(("    ", "\t")):
            continue
        lines.append(re.sub(r"(`+).*?\1", "", line))
    return "\n".join(lines)


def body_links(body):
    return set(re.findall(r"\[\[([^\]\n]+)\]\]", interpreted_body(body)))


def string_list(fields, key):
    value = fields.get(key, [])
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def source_path(project, source, proposed_paths=()):
    relative = Path(source.split("#", 1)[0])
    if not source or relative == Path(".") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("source must be a project-relative file without parent traversal")
    path = project / relative
    if not path.resolve().is_relative_to(project.resolve()):
        raise ValueError("source escapes project through a symbolic link")
    if not path.is_file() and path.resolve() not in proposed_paths:
        raise ValueError("source file does not exist")
    return path.resolve()


def project_for(base):
    if os.environ.get("PROJECT_ROOT"):
        return Path(os.environ["PROJECT_ROOT"]).resolve()
    base = Path(base).resolve()
    for candidate in (base, *base.parents):
        if any((candidate / name).is_file() for name in ("AGENTS.md", "CLAUDE.md")):
            if Path(resolve_base(candidate)).resolve() == base:
                return candidate
    return base.parent if base.name == "docs" else base


def active_topic(fields):
    return fields.get("note-kind") != "redirect" and fields.get("status", "active") not in ("merged", "superseded")


class TopicGraph:
    def __init__(self, base, project=None, proposed=None, *, include_evidence=True):
        self.base = Path(base).absolute()
        self.project = Path(project).resolve() if project else project_for(base)
        self.topics = {}
        self.records = {}
        self.findings = []
        self.names = {}
        self.unreadable = []
        self._selected_sessions = None
        self.proposed_paths = {Path(path).resolve() for path in proposed or {}}
        self._load(proposed or {}, include_evidence)
        self.topic_paths = {note["path"].resolve(): slug for slug, note in self.topics.items()}
        self._index_names()

    def finding(self, slug, code, message, severity="error"):
        self.findings.append(dict(slug=slug, code=code, severity=severity, message=message))

    def _load(self, proposed, include_evidence):
        paths = set()
        for folder in ("topics", "sessions"):
            paths.update(self._discover(self.base / folder))
        paths.update(Path(path).absolute() for path in proposed)
        overrides = {Path(path).absolute(): text for path, text in proposed.items()}
        for path in sorted(paths):
            if ".drafts" in path.relative_to(self.base).parts:
                continue
            try:
                if not path.resolve().is_relative_to(self.project):
                    raise ValueError("note resolves outside project")
                if not include_evidence and path.parent == self.base / "sessions" and path not in overrides:
                    fields = parse_fields(read_frontmatter(path))
                    if fields.get("record-kind") == "factual-evidence":
                        self.records[path] = dict(path=path, fields=fields, body="", sha256=None)
                        continue
                raw = overrides[path].encode() if path in overrides else path.read_bytes()
                fields, body = parse_note(raw.decode("utf-8"))
                record = dict(path=path, fields=fields, body=body, sha256=hashlib.sha256(raw).hexdigest())
                self.records[path] = record
                if path.relative_to(self.base).parts[0] == "topics":
                    if path.parent != self.base / "topics":
                        self.finding(path.stem, "topic-path", "Topics must be directly inside topics/.")
                    if path.stem in self.topics:
                        self.finding(path.stem, "duplicate-id", "Multiple topic files have the same slug.")
                    self.topics[path.stem] = record
            except (OSError, UnicodeError, ValueError) as error:
                self._unreadable(path, error)

    def _unreadable(self, path, error):
        relative = os.path.relpath(path, self.project)
        self.unreadable.append(dict(path=relative, error=str(error)))
        kind = "topic" if Path(path).is_relative_to(self.base / "topics") else "session"
        self.finding(Path(path).stem, "unreadable-" + kind, "Unreadable or unsafe note/directory: " + relative)

    def _discover(self, folder):
        def on_error(error):
            self._unreadable(Path(error.filename), error)

        if not folder.exists() and not folder.is_symlink():
            return
        if not folder.resolve().is_relative_to(self.project):
            self._unreadable(folder, "memory directory resolves outside project")
            return
        for root, directories, files in os.walk(folder, onerror=on_error):
            directories.sort()
            for directory in list(directories):
                path = Path(root) / directory
                if directory == ".drafts":
                    directories.remove(directory)
                elif path.is_symlink():
                    directories.remove(directory)
                    self._unreadable(path, "symbolic-link directories are not traversed")
            for filename in sorted(files):
                if filename.endswith(".md"):
                    yield Path(root) / filename

    def _index_names(self):
        for slug, note in self.topics.items():
            for name in [slug] + string_list(note["fields"], "aliases"):
                self.names.setdefault(name, set()).add(slug)
        for name, owners in sorted(self.names.items()):
            if len(owners) > 1:
                for slug in sorted(owners):
                    self.finding(slug, "alias-collision", f"Name {name!r} has multiple owners: {', '.join(sorted(owners))}.")

    def resolve(self, name):
        if not valid_slug(name):
            raise ValueError("Invalid topic slug; use a kebab-case filename slug.")
        visited = set()
        while name in self.names:
            owners = self.names[name]
            if len(owners) != 1:
                raise ValueError(f"Ambiguous topic name: {name}")
            slug = next(iter(owners))
            if slug in visited:
                raise ValueError(f"Redirect cycle at {slug}")
            visited.add(slug)
            fields = self.topics[slug]["fields"]
            if fields.get("note-kind") != "redirect":
                return slug
            name = fields.get("redirects-to", "")
            if not valid_slug(name) or name not in self.topics:
                raise ValueError(f"Missing or invalid redirect target for {slug}")
        return name

    def quality(self):
        findings = list(self.findings)
        for slug, note in sorted(self.topics.items()):
            findings.extend(topic_findings(slug, note, self))
        findings.extend(self._provenance_cycles())
        return sorted(findings, key=lambda item: (item["slug"], item["code"], item["message"]))

    def require_resolvable(self):
        errors = [item for item in self.quality() if item["code"] in RESOLUTION_CODES]
        if errors:
            raise ValueError("Invalid topic graph: " + "; ".join(item["message"] for item in errors))

    def source_topics(self, slug):
        targets = set()
        for source in string_list(self.topics[slug]["fields"], "sources"):
            try:
                path = self.source_path(source)
            except ValueError:
                continue
            if path in self.topic_paths:
                targets.add(self.topic_paths[path])
        return targets

    def source_path(self, source):
        return source_path(self.project, source, self.proposed_paths)

    def _provenance_cycles(self):
        findings = []
        edges = {slug: self.source_topics(slug) for slug in self.topics}
        for start in sorted(edges):
            pending, seen = list(edges[start]), set()
            while pending:
                node = pending.pop()
                if node == start:
                    findings.append(dict(slug=start, code="provenance-cycle", severity="error",
                                         message="Topic source cycle cannot establish independent provenance."))
                    break
                if node not in seen:
                    seen.add(node)
                    pending.extend(edges[node])
        return findings

    def session_views(self):
        # Lazy import keeps note-lint's proposed-graph checks independent of session validation.
        from _session_notes import preferred_paths
        if self._selected_sessions is None:
            paths = [path for path in self.records if path.parent == self.base / "sessions"]
            self._selected_sessions = preferred_paths(sorted(paths), self.base)
        return self._selected_sessions

    def session_links(self):
        identities = {}
        for path in self.session_views():
            note = self.records[path]
            identity = note["fields"].get("session-id")
            if not isinstance(identity, str) or not identity:
                identity = path.stem
            identities.setdefault(identity, set()).update(body_links(note["body"]))
        return identities

    def supporting_sessions(self, name):
        canonical = self.resolve(name)
        hits = set()
        for path in self.session_views():
            if any(self.resolve(link) == canonical for link in body_links(self.records[path]["body"]) if valid_slug(link)):
                hits.add(path.stem)
        pending, visited = [canonical], set()
        records = {path.resolve(): note for path, note in self.records.items()}
        while pending:
            slug = pending.pop()
            if slug in visited or slug not in self.topics:
                continue
            visited.add(slug)
            pending.extend(self.source_topics(slug) - visited)
            for source in string_list(self.topics[slug]["fields"], "sources"):
                try:
                    path = self.source_path(source)
                except ValueError:
                    continue
                if path in records and path.parent == (self.base / "sessions").resolve():
                    hits.add(path.stem)
        return sorted(hits)


def topic_findings(slug, note, graph):
    fields, body = note["fields"], note["body"]
    typed = "note-kind" in fields
    findings = []

    def add(code, message, severity=None):
        findings.append(dict(slug=slug, code=code, severity=severity or ("error" if typed else "warning"), message=message))

    for error in fields.get(PARSE_ERRORS, []):
        add("invalid-frontmatter", error)
    if typed and any(key in fields for key in ("record-kind", "batch-id", "session-id")):
        add("topic-record-mixing", "Typed topics cannot carry session/evidence identity fields.")

    if not typed:
        add("legacy-kind", "Legacy topic has no note-kind; review before migration.")
    elif fields.get("note-kind") not in ("atomic", "structure", "redirect"):
        add("invalid-kind", "note-kind must be atomic|structure|redirect.")
    if not valid_slug(slug) or fields.get("id") != slug:
        add("invalid-id", "id must equal the kebab-case filename slug.")
    if fields.get("type") != "topic":
        add("invalid-type", "type must remain topic.")
    for key in ("title", "provenance"):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            add("missing-" + key, key + " must be non-empty.")
    for key in ("created", "updated"):
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields.get(key, "") or ""):
                raise ValueError("invalid date syntax")
            datetime.date.fromisoformat(fields.get(key, ""))
        except (ValueError, TypeError):
            add("invalid-" + key, key + " must be an ISO date (YYYY-MM-DD).")
    status = fields.get("status", "active")
    if typed and "status" not in fields:
        add("missing-status", "Typed topics require an explicit lifecycle status.")
    if typed and fields.get("note-kind") in ("atomic", "structure") and status != "active":
        add("invalid-status", "Atomic and structure topics must have status: active.")
    elif status not in ("active", "merged", "superseded"):
        add("invalid-status", "Topic status must be active|merged|superseded.")
    sources = string_list(fields, "sources")
    if not sources:
        add("missing-sources", "sources must be a non-empty list of existing project-relative files.")
    for source in sources:
        try:
            graph.source_path(source)
        except ValueError as error:
            add("invalid-source", f"{source!r}: {error}")
    for key in ("aliases", "links", "tags", "supersedes"):
        values = string_list(fields, key)
        if (key in fields and not isinstance(fields[key], list)) or any(not valid_slug(value) for value in values):
            add("invalid-" + key, key + " must be a list of kebab-case slugs.")
        if isinstance(fields.get(key), list) and len(values) != len(fields[key]):
            add("invalid-" + key, key + " must contain only strings.")
        if len(values) != len(set(values)):
            add("duplicate-" + key, key + " must not contain duplicates.")
    links = body_links(body)
    if "links" not in fields or set(string_list(fields, "links")) != links:
        add("links-mismatch", "links must list exactly the body wikilinks outside code and quotations.")
    for link in sorted(links):
        try:
            target = graph.resolve(link)
            if target not in graph.topics:
                add("broken-topic-edge", f"Body topic target does not exist: {link}")
        except ValueError as error:
            add("broken-topic-edge", str(error))
    if fields.get("note-kind") == "redirect":
        target = fields.get("redirects-to")
        if status not in ("merged", "superseded"):
            add("redirect-status", "Redirect status must be merged|superseded.")
        if not valid_slug(target) or target not in graph.topics:
            add("redirect-target", "Redirect requires an existing canonical redirects-to slug.")
        elif target not in links or not re.search(r"\w", interpreted_body(body).replace(f"[[{target}]]", "")):
            add("redirect-context", "Redirect body must explain a contextual link to its target.")
        try:
            graph.resolve(slug)
        except ValueError as error:
            add("redirect-cycle" if "cycle" in str(error) else "redirect-target", str(error))
    if not interpreted_body(body).strip():
        add("empty-body", "Topic must have prose outside code/evidence.")
    words = len(re.findall(r"\b[\w'-]+\b", interpreted_body(body)))
    threshold = max(1, int(os.environ.get("MEMORY_TOPIC_REVIEW_WORDS", "300")))
    if words > threshold:
        add("review-length", f"Body has {words} words (review threshold {threshold}); review scope, do not auto-split.", "warning")
    return findings


def proposed_topic_findings(path, text, base, project):
    return proposed_graph_findings({path: text}, base, project)


def proposed_graph_findings(proposed, base, project):
    baseline = TopicGraph(base, project)
    graph = TopicGraph(base, project, proposed)
    prior = {json.dumps(item, sort_keys=True) for item in baseline.quality()}
    changed = {Path(path).stem for path in proposed}
    findings = []
    for item in graph.quality():
        is_new = json.dumps(item, sort_keys=True) not in prior
        if item["severity"] == "error" and (item["slug"] in changed or is_new):
            findings.append(item)
        elif is_new and item["code"] == "broken-topic-edge":
            # Legacy schema remains advisory, but a write must not newly break its inbound edges.
            findings.append({**item, "severity": "error"})
    for slug in changed:
        old_fields = baseline.topics.get(slug, {}).get("fields", {})
        new_fields = graph.topics.get(slug, {}).get("fields", {})
        if "note-kind" in old_fields and "note-kind" not in new_fields:
            findings.append(dict(slug=slug, code="kind-downgrade", severity="error",
                                 message="Typed topic cannot drop note-kind to bypass validation."))
    return findings
