#!/usr/bin/env python3
"""Realign a session note's frontmatter `topics:` to the [[wikilinks]] in its body.
Deterministic; lets the skill avoid hand-editing the field. stdlib only.

  sync-topics-field.py <session-file.md>

No-op if the file has no frontmatter. Rewrites only the inline `topics:` line.
"""
import sys, re


def main(argv):
    if not argv:
        sys.stderr.write("usage: sync-topics-field.py <session-file>\n")
        sys.exit(2)
    path = argv[0]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.S)
    if not m:
        return  # no frontmatter
    head, fm, fence, body = m.groups()
    links = sorted(set(re.findall(r"\[\[([a-z0-9][a-z0-9-]*)\]\]", body)))
    new_line = "topics: [" + ", ".join(links) + "]"
    if re.search(r"^topics:.*$", fm, re.M):
        fm = re.sub(r"^topics:.*$", new_line, fm, count=1, flags=re.M)
    else:
        fm = fm.rstrip("\n") + "\n" + new_line
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + fm + fence + body)
    print(new_line)


if __name__ == "__main__":
    main(sys.argv[1:])
