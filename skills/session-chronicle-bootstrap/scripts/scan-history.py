#!/usr/bin/env python3
"""Read-only history manifest; incomplete scans are explicit, never empty success.

Shared core resources come from the packaged session-chronicle skill, or the exact
directory disclosed by the installation via --core-dir. No checkout discovery.
"""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True


class ScanError(ValueError):
    """A source could not be completely scanned."""


def load_resolver(core_dir):
    directory = Path(core_dir) if core_dir else (
        Path(__file__).resolve().parents[2] / "session-chronicle" / "scripts")
    module_path = directory / "_docsroot.py"
    if not module_path.is_file():
        raise ScanError("shared_core_missing")
    spec = importlib.util.spec_from_file_location("chronicle_scan_docsroot", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve_base


def confined(path, project):
    if not path.resolve().is_relative_to(project):
        raise ScanError("source_outside_project")
    return path


def read_source(path, project):
    return confined(path, project).read_text(encoding="utf-8")


def markdown_files(directory, project):
    confined(directory, project)
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        if directory.is_symlink():
            raise ScanError("broken_source_directory")
        return []
    return [path for path in entries if path.suffix == ".md"]


def frontmatter_value(text, key):
    block = re.match(r"\A---[ \t]*\n(.*?)\n---(?:\n|$)", text, re.S)
    if not block:
        return ""
    match = re.search(r"^" + re.escape(key) + r":[ \t]*(.*)$", block[1], re.M)
    return match[1].strip().strip("'\"") if match else ""


def checked_date(value):
    if value:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ScanError("invalid_source_date")
        datetime.date.fromisoformat(value)
    return value


def document_item(path, project, kind):
    text = read_source(path, project)
    return {"kind": kind, "path": path.relative_to(project).as_posix(),
            "date": checked_date(frontmatter_value(text, "date")),
            "title": frontmatter_value(text, "title") or path.stem}


def error_record(source, error):
    code = str(error) if isinstance(error, ScanError) else type(error).__name__
    return {"source": source, "code": code}


def scan_documents(project, base, errors):
    items = []
    for kind, folder in (("spec", "specs"), ("plan", "plans"), ("decision", "decisions"),
                         ("report", "reports"), ("report", "")):
        directory = base / folder
        try:
            paths = markdown_files(directory, project)
        except (OSError, ValueError) as error:
            errors.append(error_record(directory.relative_to(project).as_posix(), error))
            continue
        for path in paths:
            try:
                items.append(document_item(path, project, kind))
            except (OSError, UnicodeError, ValueError) as error:
                errors.append(error_record(path.relative_to(project).as_posix(), error))
    return items


def status_items(project):
    path = project / "STATUS.yaml"
    if not path.exists() and not path.is_symlink():
        return []
    text = read_source(path, project)
    match = re.search(r"^recently-completed:[ \t]*(.*?)(?=^\S|\Z)", text, re.S | re.M)
    if not match or match[1].strip() in ("", "[]"):
        return []
    entries = re.split(r"\n(?=[ \t]+-[ \t]+date:)", "\n" + match[1].strip("\n"))
    items = []
    for entry in filter(str.strip, entries):
        item = re.fullmatch(r"\s*-\s*date:[ \t]*([^\n]+)\n\s+summary:[ \t]*(.+?)\s*", entry, re.S)
        if not item:
            raise ScanError("unsupported_status_history_shape")
        date = checked_date(item[1].strip().strip("'\""))
        title = re.sub(r"\s+", " ", item[2]).strip().strip("'\"")[:200]
        items.append({"kind": "status", "path": "STATUS.yaml", "date": date, "title": title})
    return items


def git_output(project, arguments):
    try:
        result = subprocess.run(["git", "-C", str(project), *arguments],
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise ScanError("git_unavailable_or_timed_out") from error
    if result.returncode:
        raise ScanError("git_command_failed")
    return result.stdout


def git_commits(project, limit, errors):
    shallow = git_output(project, ["rev-parse", "--is-shallow-repository"]).strip()
    if shallow not in ("true", "false"):
        raise ScanError("invalid_git_shallow_result")
    if shallow == "true":
        errors.append({"source": "git", "code": "shallow_history"})
    output = git_output(project, ["log", "--date=short", "--pretty=%ad%x1f%h%x1f%s", "-n", str(limit + 1)])
    lines = output.splitlines()
    if len(lines) > limit:
        errors.append({"source": "git", "code": "git_history_truncated", "limit": limit})
    items = []
    for line in lines[:limit]:
        fields = line.split("\x1f", 2)
        if len(fields) != 3 or not re.fullmatch(r"[a-f0-9]{4,64}", fields[1]):
            raise ScanError("invalid_git_record")
        items.append({"kind": "commit", "date": checked_date(fields[0]),
                      "sha": fields[1], "title": fields[2]})
    return items


def scan(project, resolve_base, git_limit=200):
    project = Path(project).resolve()
    errors, items = [], []
    manifest = {"project": str(project), "docs_root": None, "sessions_populated": None}
    try:
        if not project.is_dir():
            raise ScanError("project_directory_missing")
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = project / name
            if path.exists() or path.is_symlink():
                read_source(path, project)
        base = Path(resolve_base(str(project)))
        confined(base, project)
        manifest["docs_root"] = base.relative_to(project).as_posix()
        manifest["sessions_populated"] = bool(markdown_files(base / "sessions", project))
        items.extend(scan_documents(project, base, errors))
        for source, operation in (("STATUS.yaml", lambda: status_items(project)),
                                  ("git", lambda: git_commits(project, git_limit, errors))):
            try:
                items.extend(operation())
            except (OSError, UnicodeError, ValueError) as error:
                errors.append(error_record(source, error))
    except (OSError, UnicodeError, ValueError) as error:
        errors.append(error_record("project", error))
    items.sort(key=lambda item: item.get("date") or "9999-99-99")
    return {**manifest, "complete": not errors, "errors": errors, "count": len(items), "items": items}


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--core-dir", type=Path, help="installation-disclosed shared core directory")
    parser.add_argument("--git-limit", type=positive_integer, default=200)
    args = parser.parse_args(argv)
    try:
        resolver = load_resolver(args.core_dir)
    except (OSError, ValueError, ImportError) as error:
        result = {"project": str(args.project.resolve()), "docs_root": None,
                  "sessions_populated": None, "complete": False,
                  "errors": [error_record("shared_core", error)], "count": 0, "items": []}
    else:
        result = scan(args.project, resolver, args.git_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
