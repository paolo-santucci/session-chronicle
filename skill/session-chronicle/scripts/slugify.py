#!/usr/bin/env python3
"""Canonical slug normalisation + dedup resolution for topic notes. stdlib only.

  slugify.py "Some Title"                       -> canonical slug
  slugify.py --resolve "Title" --base DIR       -> existing canonical slug if the title
                                                   matches an existing topic note, one of its
                                                   aliases, or a (conservative) stem near-
                                                   duplicate; else the fresh canonical slug.

stdout is always JUST the slug (safe to capture in $(...)).
On --resolve, the MATCH TYPE is written to stderr as `match: exact|alias|stem|new` so a
caller can require human confirmation before UPSERTing on a `stem` match (which is a
heuristic and may be a false positive).
"""
import sys, re, unicodedata

from _topic_graph import TopicGraph


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def stem(slug):
    """Conservative English plural fold for near-duplicate detection.

    Slugs are always English/kebab (project convention), so only English plural
    suffixes are folded — and only when the resulting stem stays >= 4 chars. This
    avoids the old over-folding that collapsed distinct short slugs (e.g. core/cors
    -> 'cor') and the asymmetry from stripping bare 'e'/'i' (api -> 'ap'). Erring
    toward NO merge is the safe direction: a missed merge creates a separate note
    (recoverable via aliases); a wrong merge silently misroutes a concept.
    """
    for suf in ("ies", "es", "s"):
        if slug.endswith(suf) and len(slug) - len(suf) >= 4:
            return slug[:-len(suf)]
    return slug


def resolve(title, base):
    """Return (slug, how) where how in {exact, alias, stem, new}.

    Exact slug and alias matches are trustworthy. A `stem` match is heuristic —
    the caller should confirm before UPSERTing into it. Exact/alias are preferred
    over stem (a file is scanned for all three before stem can win across files).
    """
    cand = slugify(title)
    graph = TopicGraph(base, include_evidence=False)
    graph.require_resolvable()
    canonical = graph.resolve(cand)
    if cand in graph.names:
        return canonical, "exact" if cand == canonical else "alias"
    matches = {graph.resolve(name) for name in graph.names if stem(name) == stem(cand)}
    if len(matches) > 1:
        raise ValueError("Ambiguous stem match: " + ", ".join(sorted(matches)))
    if matches:
        return matches.pop(), "stem"
    return cand, "new"


def main(argv):
    if "--resolve" in argv:
        title = argv[argv.index("--resolve") + 1]
        base = argv[argv.index("--base") + 1] if "--base" in argv else "."
        slug, how = resolve(title, base)
        print(slug)
        sys.stderr.write("match: %s\n" % how)
    else:
        print(slugify(argv[0] if argv else ""))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
