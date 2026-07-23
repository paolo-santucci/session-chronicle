#!/usr/bin/env python3
"""List/count the session entries that backlink a topic slug (and its aliases). stdlib only.

  backlinks.py <slug> [--base DIR] [--count] [--json]
"""
import sys, os, re, glob, json


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text or "", re.S)
    return m.group(1) if m else ""


def aliases_of_topic(base, slug):
    fm = _fm(_read(os.path.join(base, "topics", slug + ".md")))
    out = []
    m = re.search(r"^aliases:\s*\[(.*?)\]", fm, re.M)
    if m:
        out += [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    m2 = re.search(r"^aliases:\s*\n((?:\s*-\s+.*\n?)+)", fm, re.M)
    if m2:
        out += [re.sub(r"^\s*-\s+", "", ln).strip().strip("'\"") for ln in m2.group(1).splitlines() if ln.strip()]
    return [a for a in out if a]


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.stderr.write("usage: backlinks.py <slug> [--base DIR] [--count] [--json]\n")
        sys.exit(2)
    slug = argv[0]
    base = argv[argv.index("--base") + 1] if "--base" in argv else "."
    names = set([slug] + aliases_of_topic(base, slug))
    pat = re.compile(r"\[\[(" + "|".join(re.escape(n) for n in names) + r")\]\]")
    hits = [os.path.splitext(os.path.basename(f))[0]
            for f in sorted(glob.glob(os.path.join(base, "sessions", "*.md"))) if pat.search(_read(f))]
    if "--json" in argv:
        print(json.dumps({"slug": slug, "count": len(hits), "sessions": hits}))
    elif "--count" in argv:
        print(len(hits))
    else:
        for h in hits:
            print(h)


if __name__ == "__main__":
    main(sys.argv[1:])
