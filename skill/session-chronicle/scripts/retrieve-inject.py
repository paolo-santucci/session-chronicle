#!/usr/bin/env python3
"""UserPromptSubmit hook — the READ-PATH of the session-memory system.

Deterministically (lexically) matches the user's prompt against the project's
session/topic notes and injects the top-k note *bodies* (frontmatter stripped,
budgeted) to stdout, so the agent actually re-reads relevant memory. The budget is
measured in CHARACTERS (a cheap proxy for tokens, ~4 chars/token), not tokens.

Ranking refinements (all zero injected-token cost):
- Body relevance is BM25 (k1=1.5, b=0.75, flat IDF — no corpus-wide df pass):
  term-frequency saturation stops one repeated rare term from dominating, and
  length normalisation stops long notes from outranking short ones on raw counts.
- SYNONYMS expands the query internally (acronym <-> spelt-out form), so "JWT"
  matches a note that only says "json web token". The expansion is never injected.
- Ranking candidates are recency-tiered and capped at MEMORY_INJECT_MAX_SCAN.
  Automatic retrieval excludes factual-evidence headers before that cap;
  discovery/header classification still grows with the number of files.
- TYPE_BOOST weights distilled topic notes above raw session logs via the
  frontmatter `type:` field (enum here is session|topic — importance lives in
  the note kind, not in a decision/learning taxonomy).

Read-only. stdlib only (no PyYAML — must never crash a session).
NEVER exits non-zero: on UserPromptSubmit a non-zero exit can block the prompt,
so on any error this prints nothing and exits 0.

Tunables (env): MEMORY_INJECT_BUDGET_CHARS (default 6000), MEMORY_INJECT_TOPK
(default 3), MEMORY_INJECT_MAX_SCAN (default 60 files ~= 2 months at 1 note/day).
Explicit callers can set include_factual: true in the input JSON.
"""
import sys, os, json, re, glob
from pathlib import Path
from collections import Counter

from _docsroot import resolve_base
from _session_notes import preferred_paths
from _topic_graph import active_topic, parse_fields, read_frontmatter

BUDGET = int(os.environ.get("MEMORY_INJECT_BUDGET_CHARS", "6000"))
TOP_K = int(os.environ.get("MEMORY_INJECT_TOPK", "3"))
MAX_SCAN = int(os.environ.get("MEMORY_INJECT_MAX_SCAN", "60"))

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
quei nel nella alla dal sul agli delle ed anche se ma piu cosa quando dove perche
""".split())


def read(path):
    return Path(path).read_text(encoding="utf-8")


def split_fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text or "", re.S)
    if m:
        return m.group(1), m.group(2)
    return "", text or ""


def fm_get(fm, key):
    value = parse_fields(fm or "").get(key, "")
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


def retrieve(proj, prompt, include_evidence=False):
    prompt = prompt.strip()
    if not prompt:
        return

    base = resolve_base(proj)

    files = glob.glob(os.path.join(base, "sessions", "*.md")) + glob.glob(os.path.join(base, "topics", "*.md"))
    if not files:
        return
    files.sort(key=mtime, reverse=True)
    for path in files:
        if Path(path).is_symlink() or not Path(path).resolve().is_relative_to(Path(base).resolve()):
            raise ValueError("Retrieved memory must be local to docs-root")
        read_frontmatter(path)  # A read failure is not an empty search.
    files = preferred_paths(files, base, include_evidence)
    files = [path for path in files if "/topics/" not in path.replace("\\", "/")
             or active_topic(parse_fields(read_frontmatter(path)))]

    qset = set(toks(prompt))
    if not qset:
        return
    qset |= {t for tok in list(qset)
             for t in SYNONYMS.get(tok, "").split()
             if len(t) > 2 and t not in STOP}

    docs = []
    scanned = 0
    for f in files:
        if scanned >= MAX_SCAN:
            break
        scanned += 1
        text = read(f)
        if not text:
            continue
        fm, body = split_fm(text)
        btoks = toks(body)
        if not btoks:
            continue
        docs.append((f, fm, body, Counter(btoks), len(btoks)))
    if not docs:
        return
    avg_dl = sum(d[4] for d in docs) / len(docs)

    scored = []
    for f, fm, body, bc, dlen in docs:
        score = bm25(qset, bc, dlen, avg_dl)                   # body relevance
        boost = 2 if fm_get(fm, "note-kind") == "structure" else TYPE_BOOST.get(fm_get(fm, "type"), 1)
        score += boost * len(qset & set(bc))  # structure maps remain lighter than atomic claims
        score += 3 * len(qset & set(toks(fm_get(fm, "title"))))  # title boost
        slug = os.path.splitext(os.path.basename(f))[0]
        score += 3 * len(qset & set(toks(slug + " " + fm_get(fm, "topics"))))  # slug/topics boost
        if score > 0:
            is_topic = "/topics/" in f.replace("\\", "/")
            scored.append((score, is_topic, f, fm_get(fm, "title") or slug, body.strip()))

    if not scored:
        return

    # higher score first; on tie prefer topics (distilled) over raw sessions
    scored.sort(key=lambda x: (-x[0], not x[1]))

    out, used = [], 0
    for score, is_topic, f, title, body in scored[:TOP_K]:
        remaining = BUDGET - used
        if remaining < 200:
            break
        kind = "topic" if is_topic else "session"
        slug = os.path.splitext(os.path.basename(f))[0]
        snippet = body if len(body) <= remaining else body[:remaining].rsplit("\n", 1)[0] + "\n…(truncated)"
        block = "### [%s] %s (%s)\n%s" % (kind, title, slug, snippet)
        out.append(block)
        used += len(block)

    if out:
        return (
            "## Project memory — auto-retrieved for this prompt (read-only)\n"
            "_Relevant prior sessions/topics. Use memory_recall / memory-recall.sh <slug> for graph-aware "
            "topic links, alias/redirect resolution and supporting source sessions._\n\n"
            + "\n\n".join(out) + "\n"
        )


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
