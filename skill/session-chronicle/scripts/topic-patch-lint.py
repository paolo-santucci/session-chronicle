#!/usr/bin/env python3
"""Read-only native patch preflight for complete typed topic notes.

stdin: {cwd, sessionID, patchText}; PROJECT_ROOT selects the project when set.
Success is silent (exit 0); rejection is actionable stderr (exit 2).
This checks a snapshot, not a transaction or a lock on the later native write.
"""
import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path

from _docsroot import resolve_base
from _session_notes import note_lint
from _topic_graph import parse_note, proposed_graph_findings, valid_slug

SUBSET_HELP = (
    "Use Add File with complete +content, or Update File with one bare @@, "
    "all -original lines then all +replacement lines. Read the complete current file first; "
    "context, partial hunks, moves, deletions and non-topic edits are not supported."
)


def sections(patch_text):
    if not isinstance(patch_text, str) or "\r" in patch_text or "\0" in patch_text:
        raise ValueError("patchText must be LF-only text without NUL characters. " + SUBSET_HELP)
    lines = patch_text.split("\n")
    if lines[-1:] == [""]:
        lines.pop()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("Expected the exact *** Begin Patch / *** End Patch envelope. " + SUBSET_HELP)
    index = 1
    while index < len(lines) - 1:
        header = lines[index]
        operation = next((name for name in ("Add", "Update") if header.startswith(f"*** {name} File: ")), None)
        if not operation:
            raise ValueError("Only Add File and whole-file Update File operations are accepted. " + SUBSET_HELP)
        filename = header[len(f"*** {operation} File: "):]
        index += 1
        start = index
        while index < len(lines) - 1 and (not lines[index].startswith("*** ") or lines[index] == "*** End of File"):
            index += 1
        yield operation, filename, lines[start:index]


def topic_target(filename, project, cwd, base):
    if not filename or filename != filename.strip():
        raise ValueError("Topic patch paths must be non-empty and have no surrounding whitespace.")
    relative = Path(filename)
    if ".." in relative.parts:
        raise ValueError("Topic patch paths cannot contain parent traversal.")
    path = relative if relative.is_absolute() else cwd / relative
    if not path.is_relative_to(project) or path.parent != base / "topics":
        raise ValueError("Every operation must target a .md file directly inside the project's topics directory.")
    if path.suffix != ".md" or not valid_slug(path.stem):
        raise ValueError("Topic patch filenames must be kebab-case slugs with a .md extension.")
    for component in (path, *path.parents):
        if component == project:
            break
        if component.is_symlink():
            raise ValueError("Topic patch targets and their parents cannot be symbolic links.")
    if not path.resolve().is_relative_to(project):
        raise ValueError("Topic patch target escapes the project.")
    return path


def replacement(lines, original):
    if not lines or lines[0] != "@@":
        raise ValueError("Whole-file Update File requires exactly one bare @@ hunk. " + SUBSET_HELP)
    content = lines[1:]
    end_marker = bool(content and content[-1] == "*** End of File")
    if end_marker:
        content = content[:-1]
    old, new = [], []
    adding = False
    for line in content:
        if line.startswith("+"):
            adding = True
            new.append(line[1:])
        elif line.startswith("-") and not adding:
            old.append(line[1:])
        else:
            raise ValueError("Unsupported partial/context/multiple-hunk update. " + SUBSET_HELP)
    if not old or not new:
        raise ValueError("Update File must include every original and replacement line. " + SUBSET_HELP)
    if not original.endswith("\n") and not end_marker:
        raise ValueError("An original without a final LF requires *** End of File after the replacement lines.")
    reconstructed = "\n".join(old) + ("\n" if original.endswith("\n") else "")
    if reconstructed != original:
        raise ValueError("Stale or partial original: -lines must match the entire current file exactly. " + SUBSET_HELP)
    return "\n".join(new) + "\n"


def reconstruct(operation, path, lines):
    if operation == "Add":
        if path.exists():
            raise ValueError("Add File target already exists; use a complete Update File operation.")
        if not lines or any(not line.startswith("+") for line in lines):
            raise ValueError("Add File accepts only +lines for the complete new topic. " + SUBSET_HELP)
        return "\n".join(line[1:] for line in lines) + "\n"
    if not path.is_file():
        raise ValueError("Update File requires an existing regular topic file.")
    if path.stat().st_nlink != 1:
        raise ValueError("Hard-linked topic targets are unsupported because writes could affect another file.")
    original = path.read_bytes().decode("utf-8")
    if "\r" in original or "\0" in original:
        raise ValueError("Whole-file topic updates require LF-only UTF-8 originals without NUL characters.")
    fields, _ = parse_note(original)
    if fields.get("type") != "topic" or any(key in fields for key in ("record-kind", "batch-id", "session-id")):
        raise ValueError("Existing target must be a topic, not a session or factual source record.")
    return replacement(lines, original)


def proposed_notes(patch_text, project, cwd, base):
    proposed = {}
    for operation, filename, lines in sections(patch_text):
        path = topic_target(filename, project, cwd, base)
        if path in proposed:
            raise ValueError("Duplicate topic patch target: " + path.name)
        text = reconstruct(operation, path, lines)
        fields, _ = parse_note(text)
        if fields.get("note-kind") not in ("atomic", "structure", "redirect"):
            raise ValueError("Every proposed note must retain type: topic and a valid note-kind; downgrades are forbidden.")
        if fields.get("type") != "topic" or any(key in fields for key in ("record-kind", "batch-id", "session-id")):
            raise ValueError("Topic patches cannot create or mix session/factual record identities.")
        secrets = note_lint.secret_findings(text)
        if secrets:
            raise ValueError("Proposed topic contains secret-like patterns: " + ", ".join(secrets)
                             + ". Replace them with [REDACTED-*] placeholders.")
        proposed[path] = text
    if not proposed:
        raise ValueError("Topic patch must contain at least one complete typed topic operation.")
    return proposed


def preflight(data):
    if not isinstance(data, dict):
        raise ValueError("Expected an object containing cwd, sessionID and patchText.")
    project_value = os.environ.get("PROJECT_ROOT") or data.get("cwd") or os.getcwd()
    if not isinstance(project_value, str) or not isinstance(data.get("cwd", project_value), str):
        raise ValueError("Project and working-directory paths must be strings.")
    project = Path(project_value).resolve()
    cwd = Path(data.get("cwd") or project).absolute()
    base = Path(resolve_base(project)).absolute()
    proposed = proposed_notes(data.get("patchText"), project, cwd, base)
    findings = proposed_graph_findings(proposed, base, project)
    if findings:
        raise ValueError("; ".join(item["slug"] + " " + item["code"] + ": " + item["message"] for item in findings))


if __name__ == "__main__":
    try:
        preflight(json.load(sys.stdin))
    except (ValueError, OSError, UnicodeError) as error:
        print("session-memory topic-patch-lint: " + str(error), file=sys.stderr)
        sys.exit(2)
    except Exception as error:
        print("session-memory topic-patch-lint: preflight failed (" + type(error).__name__ + ")", file=sys.stderr)
        sys.exit(2)
