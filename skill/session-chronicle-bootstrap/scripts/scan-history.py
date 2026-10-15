#!/usr/bin/env python3
"""Scan a project's history to seed the session-memory backfill. stdlib only.

Emits an ordered JSON manifest of historical artifacts (specs, plans, decisions, top-level
reports, STATUS recently-completed, git commits) for the LLM to synthesise an initial
chronology + first topic notes from. Also reports whether <docs-root>/sessions/ is already
populated (idempotency guard for the bootstrap skill).

  scan-history.py [--project DIR]
"""
import sys, os, re, glob, json, subprocess

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir,
    "session-chronicle", "scripts"))
from _docsroot import resolve_base


def read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def fm_block(text):
    m = re.match(r"^---\s*\n(.*?)\n---", text or "", re.S)
    return m.group(1) if m else ""


def fm_get(fm, key):
    m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fm or "", re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def scan_docs(base, kind, subdir):
    items = []
    for f in sorted(glob.glob(os.path.join(base, subdir, "*.md"))):
        fm = fm_block(read(f))
        items.append({"kind": kind, "path": f, "date": fm_get(fm, "date"),
                      "title": fm_get(fm, "title") or os.path.splitext(os.path.basename(f))[0]})
    return items


def status_items(proj):
    txt = read(os.path.join(proj, "STATUS.yaml"))
    out = []
    m = re.search(r"^recently-completed:\s*\n(.*?)(?=^\S|\Z)", txt, re.S | re.M)
    if not m:
        return out
    for em in re.finditer(r"-\s*date:\s*(\S+)\s*\n\s*summary:\s*(.+?)(?=\n\s*-\s*date:|\Z)", m.group(1), re.S):
        out.append({"kind": "status", "date": em.group(1).strip(),
                    "title": re.sub(r"\s+", " ", em.group(2)).strip().strip('"')[:200]})
    return out


def git_commits(proj, limit=200):
    try:
        out = subprocess.run(["git", "-C", proj, "log", "--date=short", "--pretty=%ad%x1f%h%x1f%s",
                              "-n", str(limit)], capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return []
        items = []
        for ln in out.stdout.splitlines():
            p = ln.split("\x1f")
            if len(p) == 3:
                items.append({"kind": "commit", "date": p[0], "sha": p[1], "title": p[2]})
        return items
    except Exception:
        return []


def main(argv):
    proj = argv[argv.index("--project") + 1] if "--project" in argv else (
        os.environ.get("PWD") or os.getcwd())
    base = resolve_base(proj)
    dr = os.path.relpath(base, proj)
    items = (scan_docs(base, "spec", "specs") + scan_docs(base, "plan", "plans")
             + scan_docs(base, "decision", "decisions")
             + scan_docs(base, "report", "reports") + scan_docs(base, "report", "")
             + status_items(proj) + git_commits(proj))
    items.sort(key=lambda x: (x.get("date") or "9999-99-99"))
    print(json.dumps({
        "project": proj, "docs_root": dr,
        "sessions_populated": bool(glob.glob(os.path.join(base, "sessions", "*.md"))),
        "count": len(items), "items": items}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
