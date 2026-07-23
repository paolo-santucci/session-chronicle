#!/usr/bin/env python3
"""Audit the session-memory graph (anti-entropy). stdlib only.

Modes (combine freely; default = run all, human summary):
  --orphans                       topic notes with 0 backlinks in sessions/
  --dups                          topic slugs/aliases that are near-duplicates (same stem)
  --dangling                      [[wikilinks]] in sessions/ with no topic note (count each)
  --materialization-candidates    slugs in >= --threshold N (default 2) distinct sessions, no note
  --stale                         topic notes whose `updated:` is older than --days D (default 90)
  --json                          machine output
  --base DIR                      memory root (contains sessions/ and topics/); default '.'
"""
import sys, os, re, glob, json, datetime


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _fm(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text or "", re.S)
    return m.group(1) if m else ""


def fm_get(fm, key):
    m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fm or "", re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def stem(s):
    # Conservative English plural fold (mirrors slugify.stem): only fold when the
    # stem stays >= 4 chars, and never strip bare 'e'/'i'. Avoids false-positive
    # --dups groupings like core/cors. Erring toward NO merge is the safe direction.
    for suf in ("ies", "es", "s"):
        if s.endswith(suf) and len(s) - len(suf) >= 4:
            return s[:-len(suf)]
    return s


def aliases(fm):
    out = []
    m = re.search(r"^aliases:\s*\[(.*?)\]", fm, re.M)
    if m:
        out += [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    m2 = re.search(r"^aliases:\s*\n((?:\s*-\s+.*\n?)+)", fm, re.M)
    if m2:
        out += [re.sub(r"^\s*-\s+", "", ln).strip().strip("'\"") for ln in m2.group(1).splitlines() if ln.strip()]
    return [a for a in out if a]


def load(base):
    topics = {}
    for f in glob.glob(os.path.join(base, "topics", "*.md")):
        slug = os.path.splitext(os.path.basename(f))[0]
        topics[slug] = _fm(_read(f))
    sess = {}
    for f in glob.glob(os.path.join(base, "sessions", "*.md")):
        sid = os.path.splitext(os.path.basename(f))[0]
        sess[sid] = set(re.findall(r"\[\[([a-z0-9][a-z0-9-]*)\]\]", _read(f)))
    return topics, sess


def name_index(topics):
    idx = {}
    for slug, fm in topics.items():
        idx[slug] = slug
        for a in aliases(fm):
            idx[a] = slug
    return idx


def main(argv):
    base = argv[argv.index("--base") + 1] if "--base" in argv else "."
    topics, sess = load(base)
    idx = name_index(topics)
    flags = ("--orphans", "--dups", "--dangling", "--materialization-candidates", "--stale")
    want_all = not any(f in argv for f in flags)
    res = {}

    if want_all or "--orphans" in argv:
        counts = {s: 0 for s in topics}
        for links in sess.values():
            for c in {idx[ln] for ln in links if ln in idx}:
                counts[c] += 1
        res["orphans"] = sorted([s for s, c in counts.items() if c == 0])

    if want_all or "--dups" in argv:
        groups = {}
        for slug, fm in topics.items():
            for n in [slug] + aliases(fm):
                groups.setdefault(stem(n), set()).add(slug)
        res["dups"] = sorted([sorted(v) for v in groups.values() if len(v) > 1])

    if want_all or "--dangling" in argv:
        dangling = {}
        for links in sess.values():
            for ln in links:
                if ln not in idx:
                    dangling[ln] = dangling.get(ln, 0) + 1
        res["dangling"] = dict(sorted(dangling.items(), key=lambda x: -x[1]))

    if want_all or "--materialization-candidates" in argv:
        thr = int(argv[argv.index("--threshold") + 1]) if "--threshold" in argv else 2
        cand = {}
        for links in sess.values():
            for ln in set(links):
                if ln not in idx:
                    cand[ln] = cand.get(ln, 0) + 1
        res["materialization_candidates"] = sorted([s for s, c in cand.items() if c >= thr])
        res["_threshold"] = thr

    if want_all or "--stale" in argv:
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 90
        today = datetime.date.today()
        stale = []
        for slug, fm in topics.items():
            try:
                if (today - datetime.date.fromisoformat(fm_get(fm, "updated"))).days > days:
                    stale.append(slug)
            except Exception:
                pass
        res["stale"] = sorted(stale)
        res["_stale_days"] = days

    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for k, v in res.items():
            if k.startswith("_"):
                continue
            print("== %s ==" % k)
            if isinstance(v, dict):
                for kk, vv in (v.items() or []):
                    print("  %s: %s" % (kk, vv))
                if not v:
                    print("  (none)")
            elif v:
                for item in v:
                    print("  %s" % (item,))
            else:
                print("  (none)")


if __name__ == "__main__":
    main(sys.argv[1:])
