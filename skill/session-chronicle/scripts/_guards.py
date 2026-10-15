"""Snapshot guards and a lock/CAS writer for cooperating semantic-note callers."""
import hashlib
import os
from pathlib import Path
import re

from _checkpoint import update_presentation, writer_lock
from _session_notes import note_lint


def memory_target(project, base, filename):
    path = Path(os.path.abspath(os.path.join(project, filename)))
    roots = [Path(base) / folder for folder in ("sessions", "topics", ".drafts", "pending", "continuations")]
    if any(path.is_relative_to(root) or path.resolve().is_relative_to(root.resolve()) for root in roots):
        return True
    if path.is_file() and path.stat().st_nlink > 1:
        identity = (path.stat().st_dev, path.stat().st_ino)
        for root in roots:
            for candidate in root.rglob("*"):
                if candidate.is_file() and (candidate.stat().st_dev, candidate.stat().st_ino) == identity:
                    return True
    return False


def protected_mutation(context, arguments, base):
    if arguments["kind"] != "patch":
        return memory_target(context["workspace"], base, arguments["path"])
    paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", arguments["patch"], re.M)
    if not paths:
        raise ValueError("Patch has no classifiable mutation targets")
    return any(memory_target(context["workspace"], base, path) for path in paths)


def local_target(project, base, filename):
    path = Path(project, filename).absolute()
    if ".." in path.parts:
        raise ValueError("Guard paths cannot contain parent traversal")
    protected = memory_target(project, base, filename)
    if protected:
        for component in (path, *path.parents):
            if component == Path(project):
                break
            if component.is_symlink():
                raise ValueError("Memory mutation paths cannot contain symbolic links")
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError("Memory mutation requires a regular file without hard links")
    return path


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def guard(context, arguments, base):
    if not protected_mutation(context, arguments, base):
        return {"allowed": True, "atomic": False}
    if context["role"] == "unknown":
        from _portable import CoreError
        raise CoreError("unknown_provenance", "Protected memory mutation requires a known runtime role")
    if arguments["kind"] == "patch":
        # Patch grammar is shared with the compatibility wrapper, without its native context parser.
        from _portable import load_script
        from _topic_graph import proposed_graph_findings
        patch = load_script("topic-patch-lint")
        project = Path(context["workspace"])
        if arguments.get("phase", "pre") != "pre":
            raise ValueError("Complete-topic patch validation is preflight only")
        proposed = patch.proposed_notes(arguments["patch"], project, project, Path(base))
        findings = proposed_graph_findings(proposed, base, project)
        if findings:
            raise ValueError("; ".join(item["code"] + ": " + item["message"] for item in findings))
        return {"allowed": True, "atomic": False,
                "snapshots": {str(path): fingerprint(path) for path in proposed}}
    path = local_target(context["workspace"], base, arguments["path"])
    if arguments["kind"] == "edit" and arguments.get("phase", "pre") == "pre" and note_lint.classify(path, base):
        existing = path.read_text(encoding="utf-8")
        occurrences = existing.count(arguments["old_text"])
        if not occurrences or (occurrences > 1 and not arguments.get("replace_all")):
            raise ValueError("Edit requires an exact, unambiguous original or replace_all")
    note_lint.validate_change(context["workspace"], context["qualified_id"], arguments)
    return {"allowed": True, "atomic": False, "sha256": fingerprint(path)}


def guarded_semantic_replace(context, arguments, base, expected_sha256):
    """Atomic for cooperating writers only; native preflight is not this transaction."""
    if context["role"] != "primary" or arguments.get("kind") != "replace":
        raise ValueError("Semantic transaction requires primary context and complete replacement")
    with writer_lock(base):
        path = local_target(context["workspace"], base, arguments["path"])
        if fingerprint(path) != expected_sha256:
            raise ValueError("Stale semantic snapshot; reload before writing")
        fm, _ = note_lint.split_fm(arguments["content"])
        if note_lint.fm_get(fm, "record-kind") != "semantic-summary":
            raise ValueError("Semantic transaction requires a semantic-summary")
        guard(context, dict(arguments, phase="pre"), base)
        update_presentation(path, arguments["content"])
        return {"sha256": fingerprint(path)}
