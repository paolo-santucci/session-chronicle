#!/usr/bin/env python3
"""UserPromptSubmit hook — the READ-PATH of the session-memory system.

Deterministically (lexically) matches the user's prompt against the project's
session/topic notes and injects the top-k note *bodies* (frontmatter stripped,
budgeted) to stdout, so the agent actually re-reads relevant memory. The budget is
measured in CHARACTERS (a cheap proxy for tokens, ~4 chars/token), not tokens.

Retrieval is split into phases; only path work that must precede ranking happens early:
- P0 — the query guard. The prompt is tokenised and synonym-expanded *before*
  `resolve_base`, before any glob and before any header read, so a prompt that
  tokenises to nothing does no filesystem work at all (FR-07). A single surviving
  token still runs full retrieval (FR-08).
- P1 — eligibility, header-only, fail-closed. One `base_real` per call, every
  candidate's real path checked against it (a symlink escaping docs-root is
  rejected), each header read once into a per-call map and parsed once per
  frontmatter text, then partitioned through `_session_notes.select_candidates`
  (factual exclusion, inactive topics, identity map). An unsafe path or an
  unreadable header raises: a read failure must not read as "no match".
- P2 — bounded scan and ranking. Topics take the first slots, sessions fill the
  rest up to MAX_SCAN, each selected body is read exactly once, BM25 + boosts
  score it, `exclude` is subtracted inside ranking (after sorting, before the
  TOP_K slice) so an excluded hit is replaced rather than shrinking the result,
  and the sort keys end with the path as a stable tiebreak.
- P3 — deferred provenance validation. Ranked candidates are walked in rank order
  with one `source_cache` per call and one decision per identity: a unique
  validating semantic summary suppresses its presentation regardless of score, two
  summaries or two presentations suppress both, and a failing summary falls back to
  its unique presentation. Filling continues past a failure until TOP_K blocks are
  emitted (FR-33, FR-34, FR-35).
- Rendering — `render()` is the ONLY budget authority: it counts the preamble, the
  heading, each header line, each provenance line, the separators, the truncation
  marker and the untrusted envelope (`envelope_len`), so `untrusted()` only escapes
  and wraps and never cuts (FR-17, FR-18, NFR-07).

Ranking refinements (all zero injected-token cost):
- Body relevance is BM25 (k1=1.5, b=0.75, flat IDF — no corpus-wide df pass):
  term-frequency saturation stops one repeated rare term from dominating, and
  length normalisation stops long notes from outranking short ones on raw counts.
- SYNONYMS expands the query internally (acronym <-> spelt-out form), so "JWT"
  matches a note that only says "json web token". The expansion is never injected.
- Ranking candidates are recency-tiered and capped at MEMORY_INJECT_MAX_SCAN.
  Automatic retrieval excludes factual-evidence headers before that cap;
  discovery/header classification still grows with the number of files.
- Topic notes are prioritised inside the recency cap rather than crowded out by
  it: topic candidates are selected first, and only the remaining budget goes to
  session notes. They are the distilled layer and are rarely touched, so a pure
  newest-first window would silently retire them as sessions accumulate. Total
  body reads stay bounded by MEMORY_INJECT_MAX_SCAN.
- TYPE_BOOST weights distilled topic notes above raw session logs via the
  frontmatter `type:` field (enum here is session|topic — importance lives in
  the note kind, not in a decision/learning taxonomy).

Wire contract. A block is emitted only when its own `kind:stem` reference passes
`_topic_graph.note_ref` (FR-26): a hand-authored note whose filename stem is not a valid note
reference (`API-notes`, `notes (draft)`, `v1.2-migration`, an over-long stem) is dropped whole,
body included, because a slug the adapter cannot record would be re-injected on every prompt
(FR-22). Eligibility needs that predicate to be the only one — a second regex here would drift
from `exclude` validation.

Layout divergence (intentional, and noted here because it lives in `_portable.py`):
`retrieve_operation` does not call `storage_layout()`, while `find` does. So `retrieve` also
reads notes hard-linked into `docs/` that `find` rejects as a broken layout, and a layout
failure reaches the caller as `worker_failed` (via the generic retrieval failure) instead of
`validation_failed`. Both behaviours are deliberate; do not "normalise" them from this file.

Read-only. stdlib only (no PyYAML — must never crash a session).
NEVER exits non-zero: on UserPromptSubmit a non-zero exit can block the prompt,
so on any error this prints nothing and exits 0.

Tunables (env): MEMORY_INJECT_BUDGET_CHARS (default 6000), MEMORY_INJECT_TOPK
(default 3), MEMORY_INJECT_MAX_SCAN (default 60 files ~= 2 months at 1 note/day).
Explicit callers can set include_factual: true in the input JSON.
"""
import sys, os, json, re, glob
from datetime import date
from pathlib import Path
from collections import Counter

from _docsroot import resolve_base
from _memory_markers import RETRIEVAL_HEADING, UNTRUSTED_OVERHEAD, envelope_len, escape
from _session_notes import (SUMMARY_KINDS, identity_of, record_kind_of, select_candidates,
                            validate_view)
from _topic_graph import note_ref, parse_fields, read_frontmatter, string_list

BUDGET = int(os.environ.get("MEMORY_INJECT_BUDGET_CHARS", "6000"))
TOP_K = int(os.environ.get("MEMORY_INJECT_TOPK", "3"))
MAX_SCAN = int(os.environ.get("MEMORY_INJECT_MAX_SCAN", "60"))

PATH_MESSAGE = "Retrieved memory must be local to docs-root"

PREAMBLE = ("_Relevant prior sessions/topics. Use memory_recall / memory-recall.sh <slug> for graph-aware "
            "topic links, alias/redirect resolution and supporting source sessions._")

# The one truncation marker; the renderer budgets for it before it is appended.
MARKER = "…(truncated)"

# An `updated` value renders only through a validated date prefix (FR-13).
UPDATED_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])")

# CR, LF, U+2028/U+2029 and C0 controls would all end a rendered header line (FR-15).
CONTROL = re.compile("[\x00-\x1f\u2028\u2029]")

SYNONYMS = {
    "jwt": "json web token",
    "api": "endpoint route",
    "endpoint": "api route",
    "k8s": "kubernetes",
    "kubernetes": "k8s",
    "db": "database",
    "database": "db",
    "auth": "authentication authorization login",
    "authentication": "auth login",
    "ci": "continuous integration pipeline",
    "crud": "create read update delete",
    "uri": "url endpoint",
    "url": "uri endpoint",
    "yaml": "yml",
    "yml": "yaml",
    "config": "configuration settings",
    "configuration": "config settings",
    "repo": "repository",
    "repository": "repo",
}

TYPE_BOOST = {"topic": 4, "session": 1}

# Common IT + EN stopwords; tokens shorter than 3 chars are also dropped.
STOP = set("""
the a an and or of to in on for with is are was were be been being this that these those it its as at by
from into your you our they them his her she he not but can will would should could have has had do does did
le la lo gli un una uno di da del della dei delle che con per non si come piu sono stato essere questo quella
quei nel nella alla dal sul agli delle ed anche se ma piu cosa quando dove perche vai
""".split())


def read(path):
    return Path(path).read_text(encoding="utf-8")


def split_fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text or "", re.S)
    if m:
        return m.group(1), m.group(2)
    return "", text or ""


def field_value(fields, key):
    value = fields.get(key, "")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(value)
    return value if isinstance(value, str) else ""


def toks(s):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 2 and t not in STOP]


def mtime(f):
    try:
        return os.path.getmtime(f)
    except Exception:
        return 0.0


def bm25(query_tokens, doc_counter, doc_len, avg_dl, k1=1.5, b=0.75):
    score = 0.0
    for t in query_tokens:
        tf = doc_counter.get(t, 0)
        if tf:
            score += (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_dl))
    return score


def query_terms(prompt):
    """The query's tokens plus the SYNONYMS expansion; runs before any filesystem access.

    Called first by `ranked_context`, so a prompt that tokenises to nothing returns
    from retrieval before `resolve_base`, any glob or any header read (FR-07).
    """
    terms = set(toks(prompt))
    if not terms:
        return set()
    return terms | {t for token in list(terms)
                    for t in SYNONYMS.get(token, "").split()
                    if len(t) > 2 and t not in STOP}


def one_line(value):
    """Collapse CR, LF, U+2028, U+2029 and C0 controls, so a title cannot forge a header."""
    return CONTROL.sub(" ", value if isinstance(value, str) else "")


def display_date(value):
    """The validated ISO date prefix of an `updated` value, or "" when absent or malformed."""
    match = UPDATED_DATE.match(value.strip()) if isinstance(value, str) else None
    if not match:
        return ""
    try:
        date(*(int(part) for part in match.groups()))
    except ValueError:
        return ""
    return match.group(0)[:10]


def provenance_line(fields):
    """`sources: <n> · updated <date>`; never a source identifier or a path (FR-12, FR-13)."""
    declared = fields if isinstance(fields, dict) else {}
    sources = declared.get("sources")
    if isinstance(sources, str):
        count = 1 if sources.strip() else 0
    else:
        count = len(string_list(declared, "sources"))
    line = "sources: %d" % count if count else "sources: none"
    updated = display_date(declared.get("updated"))
    return line + (" · updated " + updated if updated else "")


def _escaped_prefix(text, width):
    """The longest prefix of `text` whose escaped form fits `width` characters."""
    used = 0
    for index, character in enumerate(text):
        used += len(escape(character))
        if used > width:
            return text[:index]
    return text


def _boundary_prefix(text, separator, width):
    """The longest prefix of `text` ending just before `separator`, within `width`."""
    best, used, start = "", 0, 0
    while True:
        index = text.find(separator, start)
        if index == -1:
            return best
        used += len(escape(text[start:index]))
        if used > width:
            return best
        best = text[:index]
        used += len(escape(separator))
        start = index + len(separator)


def fit_snippet(body, remaining):
    """The truncation ladder — paragraph, then line, then a hard cut (FR-16).

    Post-conditions: the snippet is non-empty whenever `remaining >= 1`, `cut` implies the
    snippet ends with `MARKER`, and `envelope_len(snippet) <= remaining` — the last one only
    from the marker-cost floor upwards. Below it (no room for `MARKER`, its introducing
    newline and one content character) the degenerate branch returns one content character
    unmarked, which can still exceed `remaining`; `render()` never asks for such a budget,
    because it drops a block whose remaining budget cannot hold `envelope_len(MARKER + "\\nx")`.
    """
    text = body if isinstance(body, str) else ""
    if remaining < 1:
        return "", False
    if envelope_len(text) <= remaining:
        return text, False
    # Budget for the content only: the marker and the newline that introduces it are paid here.
    width = remaining - UNTRUSTED_OVERHEAD - len(escape(MARKER)) - 1
    if width < 1:
        # No room to signal a cut; still never return an empty snippet for a non-empty body.
        return (text[:1], False) if text else ("", False)
    for separator in ("\n\n", "\n"):
        kept = _boundary_prefix(text, separator, width)
        if kept.strip():
            return kept.rstrip() + "\n" + MARKER, True
    kept = _escaped_prefix(text, width)
    while kept and not kept.strip():
        kept = kept[:-1]
    return (kept or text[:1]) + "\n" + MARKER, True


def render(blocks, budget):
    """The single budget authority: `(text, slugs)` sized to the untrusted envelope.

    Counts the preamble, heading, each block's header and provenance lines, the `\\n\\n`
    separators, the truncation marker and the envelope via `envelope_len`. A block whose
    remaining budget cannot hold its header, provenance, the marker and one character is
    dropped whole and its slug is not reported (FR-17, FR-18, FR-19, FR-22). A block whose
    own `kind:stem` reference is not a `note_ref` is dropped the same way, body included: a
    slug the adapter cannot record would be re-injected on every prompt (FR-26).
    """
    items = [item for item in blocks or () if item]
    if not items or budget is None or budget <= 0:
        return "", []
    head = RETRIEVAL_HEADING + "\n" + PREAMBLE + "\n\n"
    emitted, slugs = [], []
    for item in items:
        kind = one_line(item.get("kind"))
        slug = one_line(item.get("slug"))
        reference = "%s:%s" % (kind, slug)
        if not note_ref(reference):
            continue
        header = "### [%s] %s (%s)" % (kind, one_line(item.get("title")), slug)
        scaffold = header + "\n" + provenance_line(item.get("fields")) + "\n"
        head_of_block = head + ("\n\n".join(emitted) + "\n\n" if emitted else "")
        remaining = budget - envelope_len(head_of_block + scaffold + "\n")
        if remaining < envelope_len(MARKER + "\nx"):
            continue
        snippet, _cut = fit_snippet(item.get("body"), remaining)
        if not snippet:
            continue
        emitted.append(scaffold + snippet)
        slugs.append(reference)
    if not emitted:
        return "", []
    return head + "\n\n".join(emitted) + "\n", slugs


class HeaderCache:
    """Per-call frontmatter memo: one open per path, one parse per frontmatter text.

    Deliberately per-call — no module-level cache and no on-disk cache (FR-09), so a note
    rewritten between two invocations is read again instead of being served stale.

    Known limitation (FR-09, bounded): the headers are already parsed once by
    `select_candidates` (`usable_fields`, over every file), so a header inside the scan window
    is parsed a second time here for the ranked subset — plus one regex pass per field via the
    shared accessor. Threading the first parse through is deliberately not done: it would widen
    `select_candidates`'s return shape, which `preferred_paths`, `chronicle-doctor` and the
    pinned selection tests all consume. The double parse is bounded by `MAX_SCAN`.
    """

    def __init__(self):
        self.by_path = {}
        self.by_text = {}

    def text(self, path):
        if path not in self.by_path:
            self.by_path[path] = read_frontmatter(path)  # A read failure is not an empty search.
        return self.by_path[path]

    def fields(self, frontmatter):
        if frontmatter not in self.by_text:
            self.by_text[frontmatter] = parse_fields(frontmatter or "")
        return self.by_text[frontmatter]


def local_path(path, base, base_real):
    """The candidate's real path below docs-root; a path or link escaping it raises.

    `base_real` is resolved once per call: a per-file `realpath()` would make the cost
    grow with the corpus (NFR-03), so the real path is reconstructed from the part
    below `base` and the candidate and its directory are checked for symbolic links —
    a link is the only way a path inside a real memory directory can leave `base_real`
    (FR-11, EC-05).
    """
    relative = os.path.relpath(path, base)
    if relative.startswith(os.pardir) or os.path.isabs(relative):
        raise ValueError(PATH_MESSAGE)
    if os.path.islink(path) or os.path.islink(os.path.dirname(path)):
        raise ValueError(PATH_MESSAGE)
    real = os.path.normpath(os.path.join(base_real, relative))
    if os.path.commonpath([base_real, real]) != base_real:
        raise ValueError(PATH_MESSAGE)
    return real


def candidate_files(base):
    """Every note below docs-root, newest first: the recency tier P1 is given."""
    files = glob.glob(os.path.join(base, "sessions", "*.md")) + glob.glob(os.path.join(base, "topics", "*.md"))
    files.sort(key=mtime, reverse=True)
    return files


def scan_window(eligible, base):
    """Topics take the first slots of the scan budget; sessions fill the rest (FR-32)."""
    topics_dir = os.path.join(base, "topics")
    topics = [path for path in eligible if os.path.dirname(path) == topics_dir]
    sessions = [path for path in eligible if os.path.dirname(path) != topics_dir]
    return topics[:MAX_SCAN] + sessions[:max(0, MAX_SCAN - len(topics))]


def exclude_refs(exclude):
    """The `kind:stem` (or bare stem) references to suppress, total over any input."""
    return {value.strip() for value in exclude or () if isinstance(value, str) and value.strip()}


def ranked_context(proj, prompt, include_evidence=False, exclude=()):
    """P1 + P2 plus the identity map P3 resolves against, bounded by MAX_SCAN."""
    empty = {"candidates": [], "identities": {}, "headers": {}, "base": ""}
    terms = query_terms(prompt)
    if not terms:
        return empty
    base = resolve_base(proj)
    base_real = os.path.realpath(base)
    files = candidate_files(base)
    if not files:
        return empty
    headers = HeaderCache()
    frontmatter = {}
    for path in files:
        real = local_path(path, base, base_real)
        frontmatter[real] = headers.text(real)  # unsafe path or unreadable header raises here
    selection = select_candidates(list(frontmatter.items()), base_real, include_evidence)

    docs = []
    for path in scan_window(selection["eligible"], base_real):
        try:
            text = read(path)
        except (OSError, UnicodeError):
            continue  # a body that cannot be read skips the candidate; headers still raise (EC-07)
        if not text:
            continue
        _, body = split_fm(text)
        body_tokens = toks(body)
        if not body_tokens:
            continue
        docs.append((path, body, Counter(body_tokens), len(body_tokens)))
    context = {"candidates": [], "identities": selection["identities"], "headers": frontmatter, "base": base_real}
    if not docs:
        return context
    average_length = sum(doc[3] for doc in docs) / len(docs)

    candidates = []
    for path, body, counter, length in docs:
        fields = headers.fields(frontmatter[path])
        score = bm25(terms, counter, length, average_length)      # body relevance
        boost = 2 if field_value(fields, "note-kind") == "structure" else TYPE_BOOST.get(field_value(fields, "type"), 1)
        score += boost * len(terms & set(counter))  # structure maps remain lighter than atomic claims
        slug = os.path.splitext(os.path.basename(path))[0]
        score += 3 * len(terms & set(toks(field_value(fields, "title"))))       # title boost
        score += 3 * len(terms & set(toks(slug + " " + field_value(fields, "topics"))))  # slug/topics boost
        if score <= 0:
            continue
        kind = "topic" if os.path.dirname(path) == os.path.join(base_real, "topics") else "session"
        candidates.append({"path": path, "slug": slug, "kind": kind, "base": base_real,
                           "title": field_value(fields, "title") or slug, "body": body.strip(),
                           "frontmatter": frontmatter[path], "fields": fields, "score": score,
                           # Identity and record kind come from the accessor the partition used,
                           # never from a second parse of the same header (FR-31, FR-34).
                           "identity": identity_of(frontmatter[path]),
                           "record_kind": record_kind_of(frontmatter[path])})

    # higher score first; on tie prefer topics (distilled) over raw sessions; path is the stable tiebreak
    candidates.sort(key=lambda item: (-item["score"], item["kind"] != "topic", item["path"]))
    excluded = exclude_refs(exclude)
    context["candidates"] = [item for item in candidates
                             if item["slug"] not in excluded
                             and "%s:%s" % (item["kind"], item["slug"]) not in excluded]
    return context


def ranked_candidates(proj, prompt, include_evidence=False, exclude=()):
    """Test seam — `ranked_context(...)["candidates"][:TOP_K]`, not a production entry point.

    Production goes `retrieve_matches` -> `fill_blocks`, so P3 runs; this slice exists only so
    a test can assert the ranking order and the body-read cap without P3 in the way. `exclude`
    is applied inside ranking — after eligibility and sorting, before the TOP_K slice — so an
    excluded hit is replaced by the next ranked candidate instead of shrinking the result
    (FR-21).
    """
    return ranked_context(proj, prompt, include_evidence, exclude)["candidates"][:TOP_K]


def identity_view(identity, group, headers, base, source_cache):
    """The one view an identity may present, or None when it may present none (FR-34).

    Validates at most two paths (the summary, then the presentation fallback) from the
    headers already read, sharing the caller's per-call `source_cache`.
    """
    summaries, presentations = group["summaries"], group["presentations"]
    if len(summaries) == 1 and validate_view(summaries[0], headers[summaries[0]], base, source_cache):
        return summaries[0]
    if len(presentations) == 1 and validate_view(presentations[0], headers[presentations[0]], base, source_cache):
        return presentations[0]
    return None


def view_allowed(candidate, context, source_cache, decisions):
    """True when this candidate is the view its identity resolved to, validated once (FR-33).

    Only a summary or a presentation is subject to per-identity suppression: an ordinary note
    that happens to carry a `session-id` is not a view of that identity and must not be hidden
    because a summary for it validated (FR-34).
    """
    if candidate.get("record_kind") not in SUMMARY_KINDS:
        return True
    identity = candidate.get("identity") or ""
    group = context["identities"].get(identity)
    if not identity or group is None:
        return True
    if identity not in decisions:
        decisions[identity] = identity_view(identity, group, context["headers"], context["base"], source_cache)
    return decisions[identity] == candidate["path"]


def fill_blocks(context, limit=None):
    """P3: fill to `TOP_K` in rank order, one source cache and one decision per identity.

    A validation failure skips that identity and the walk continues, so `TOP_K` notes are
    still returned whenever `TOP_K` eligible candidates validate (FR-33, FR-35).
    """
    bucket = TOP_K if limit is None else limit
    source_cache, decisions, blocks = {}, {}, []
    for candidate in context["candidates"]:
        if len(blocks) >= bucket:
            break
        if view_allowed(candidate, context, source_cache, decisions):
            blocks.append(candidate)
    return blocks


def retrieve_matches(proj, prompt, include_evidence=False, exclude=(), budget=None):
    """The retrieval entry: the rendered block and the slugs it actually emitted."""
    limit = BUDGET if budget is None else int(budget)
    context = ranked_context(proj, prompt, include_evidence, exclude)
    if not context["candidates"]:
        return {"text": "", "slugs": []}
    text, slugs = render(fill_blocks(context), limit)
    return {"text": text, "slugs": slugs}


def retrieve(proj, prompt, include_evidence=False):
    """Thin `str | None` wrapper so the CLI and `_portable` keep their existing contract."""
    return retrieve_matches(proj, prompt, include_evidence)["text"] or None


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    project = os.environ.get("PROJECT_ROOT") or data.get("cwd") or os.getcwd()
    result = retrieve(project, data.get("prompt") or "",
                      data.get("include_factual") is True or data.get("includeEvidence") is True)
    if result:
        sys.stdout.write(result)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
