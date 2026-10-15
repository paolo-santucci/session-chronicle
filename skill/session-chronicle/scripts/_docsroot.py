#!/usr/bin/env python3
"""Single source of truth for resolving <docs-root>.

`docs-root:` is read from the project instruction file's YAML frontmatter.
AGENTS.md is consulted first and CLAUDE.md second, so a project carrying a
Claude Code chronicle keeps working without an edit.

Every consumer treats "the notes directory does not exist" as "there are no
notes yet", so a wrong docs-root is indistinguishable from a fresh project:
the read path goes quiet, capture-signals.py creates its draft buffer in the
wrong place, and note-lint.py stops recognising notes as notes — which
silently disables the append-only and secret guards. `detect_orphan()` exists
to make that state visible instead of inferring consent from silence.

stdlib only.
"""
import os
import re
import glob
from pathlib import Path

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
DEFAULT_DOCS_ROOT = "docs"
SCAN_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "target", "dist", "build"}


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _declared_in(path):
    m = re.match(r"^---\s*\n(.*?)\n---", _read(path), re.S)
    if not m:
        return ""
    mm = re.search(r"^docs-root:\s*(.*)$", m.group(1), re.M)
    return mm.group(1).strip().strip("'\"") if mm else ""


def resolve(proj):
    """Return (base_abspath, declaring_file_or_None)."""
    for name in INSTRUCTION_FILES:
        declared = _declared_in(os.path.join(proj, name))
        if declared:
            return validated_base(proj, declared), name
    return validated_base(proj, DEFAULT_DOCS_ROOT), None


def validated_base(proj, declared):
    project = Path(proj).resolve()
    relative = Path(declared)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("docs-root must be a project-relative path without parent traversal")
    base = project / relative
    if any(not path.resolve().is_relative_to(project) for path in
           (base, base / ".drafts", base / ".drafts" / "pending", base / "sessions", base / "topics",
            base / "pending", base / "continuations")):
        raise ValueError("docs-root and memory directories must resolve inside the project")
    managed = [project / name for name in (".opencode", ".claude", ".codex", ".pi", ".agents")]
    memory = (base, base / ".drafts", base / ".drafts" / "pending", base / "sessions", base / "topics",
              base / "pending", base / "continuations")
    if any(path.resolve().is_relative_to(config.resolve()) or config.resolve().is_relative_to(path.resolve())
           for path in memory for config in managed):
        raise ValueError("docs-root must not overlap managed harness configuration")
    return str(base)


def resolve_base(proj):
    return resolve(proj)[0]


def has_notes(base):
    return bool(glob.glob(os.path.join(base, "sessions", "*.md"))
                or glob.glob(os.path.join(base, "topics", "*.md")))


def detect_orphan(proj):
    """Chronicle notes that exist somewhere other than the resolved docs-root.

    Returns (base, declaring_file, [orphan_paths]). A non-empty orphan list means
    the resolution is wrong: notes are on disk but nothing will read or guard them.
    """
    base, source = resolve(proj)
    if has_notes(base):
        return base, source, []
    seen = {os.path.realpath(base)}
    orphans = []
    for cand in _candidates(proj):
        real = os.path.realpath(cand)
        if real in seen:
            continue
        seen.add(real)
        if has_notes(cand):
            orphans.append(os.path.relpath(cand, proj))
    return base, source, orphans


def _candidates(proj):
    """Every plausible docs-root: each top-level directory and its `docs/` child."""
    try:
        entries = sorted(os.listdir(proj))
    except Exception:
        return
    for name in entries:
        if name in SCAN_SKIP:
            continue
        path = os.path.join(proj, name)
        if not os.path.isdir(path):
            continue
        yield path
        nested = os.path.join(path, "docs")
        if os.path.isdir(nested):
            yield nested


def orphan_warning(proj):
    """One-line diagnosis, or "" when the resolution looks sound."""
    base, source, orphans = detect_orphan(proj)
    if not orphans:
        return ""
    where = "declared in %s" % source if source else (
        "not declared in %s — defaulted" % " or ".join(INSTRUCTION_FILES))
    return (
        "session-chronicle: docs-root resolves to '%s' (%s), which holds no notes, "
        "but a chronicle exists at %s. Capture, retrieval and the append-only/secret "
        "guards are all operating on the wrong directory. Fix the 'docs-root:' "
        "frontmatter in %s."
        % (os.path.relpath(base, proj), where, ", ".join("'%s'" % o for o in orphans),
           INSTRUCTION_FILES[0])
    )


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if a != "--check"]
    project = args[0] if args else os.environ.get("PROJECT_ROOT") or os.getcwd()
    try:
        if "--check" in sys.argv[1:]:
            warning = orphan_warning(project)
            if warning:
                print(warning)
        else:
            print(os.path.relpath(resolve_base(project), project))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
