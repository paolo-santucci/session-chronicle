#!/usr/bin/env python3
"""Validate shipped skill/ and command/ definitions, excluding installed copies.

Exit 0 when clean (warnings allowed), 1 on validation or dependency errors.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BASH_BLOCK_RE = re.compile(r"^[ \t]*```bash[ \t]*\n(.*?)^[ \t]*```[ \t]*$", re.M | re.S)
SHELL_LITERAL_RE = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"|\\.|(?<!\S)#.*")
GREP_CALL_RE = re.compile(
    r"(?:^|[|;&(]|\$\()\s*(?:(?:if|while|until|then|do|else|elif|!|\{)\s+)*"
    r"grep(?=$|[\s;&|<>()])"
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: object, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: object, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                None, None, "mapping key must be hashable", key_node.start_mark
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate YAML key: {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


if yaml is not None:
    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
    )


def read_definition(path: Path, report: Report) -> tuple[dict, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        report.error(path, f"cannot read definition: {exc}")
        return None
    match = FM_RE.match(text)
    if match is None:
        report.error(path, "no YAML frontmatter")
        return None
    try:
        metadata = yaml.load(match.group(1), Loader=UniqueKeyLoader)
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        report.error(path, f"frontmatter does not parse: {exc}")
        return None
    if not isinstance(metadata, dict) or any(not isinstance(key, str) for key in metadata):
        report.error(path, "frontmatter must be a mapping with string keys")
        return None
    return metadata, text[match.end():]


def check_metadata(path: Path, metadata: dict, report: Report) -> None:
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        report.error(path, "`description` must be a nonempty string describing its purpose")
    if "user-invocable" in metadata and not isinstance(metadata["user-invocable"], bool):
        report.error(path, "`user-invocable` must be a boolean")
    for key in ("allowed-tools", "license", "compatibility"):
        if key in metadata and not isinstance(metadata[key], str):
            report.error(path, f"`{key}` must be a string")
    if "metadata" in metadata:
        values = metadata["metadata"]
        if not isinstance(values, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in values.items()
        ):
            report.error(path, "`metadata` must be a mapping of strings to strings")


def check_no_grep(path: Path, body: str, report: Report) -> None:
    for block in BASH_BLOCK_RE.findall(body):
        for line in block.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if GREP_CALL_RE.search(SHELL_LITERAL_RE.sub("literal", line)):
                report.error(path, "`grep` in a bash block violates the workspace rule; "
                             f"use `rg`: {line.strip()[:70]}")


def root_entries(root: Path, report: Report) -> list[Path]:
    try:
        return sorted(path for path in root.iterdir() if not path.name.startswith("."))
    except OSError as exc:
        report.error(root, f"cannot read required directory: {exc}")
        return []


def check_skill(path: Path, commands: set[str], report: Report) -> None:
    definition = read_definition(path / "SKILL.md", report)
    if definition is None:
        return
    metadata, body = definition
    name = metadata.get("name")
    if not isinstance(name, str) or len(name) > 64 or not SKILL_NAME_RE.fullmatch(name):
        report.error(path, "`name` must be 1–64 lowercase letters/digits with single separating hyphens")
    if name != path.name:
        report.error(path, f"`name` is {name!r} but the directory is {path.name!r}")
    check_metadata(path / "SKILL.md", metadata, report)
    check_no_grep(path / "SKILL.md", body, report)
    if metadata.get("user-invocable") is not False and path.name not in commands:
        report.warn(path, "user-invocable but has no command shim in command/")


def validate(repo: Path, report: Report) -> tuple[int, int]:
    skills = [path for path in root_entries(repo / "skill", report) if path.is_dir()]
    commands = [path for path in root_entries(repo / "command", report) if path.suffix == ".md"]
    if not skills:
        report.error(repo / "skill", "no skill directories found")
    if not commands:
        report.error(repo / "command", "no command definitions found")
    skill_names = {path.name for path in skills}
    for path in commands:
        if path.stem not in skill_names:
            report.error(path, f"command shim has no matching skill '{path.stem}'")
        definition = read_definition(path, report)
        if definition is not None:
            metadata, body = definition
            check_metadata(path, metadata, report)
            check_no_grep(path, body, report)
    for path in skills:
        check_skill(path, {command.stem for command in commands}, report)
    return len(skills), len(commands)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress warnings")
    args = parser.parse_args()
    if yaml is None:
        print("PyYAML is required for linting. Install the dev dependency with: "
              "python3 -m pip install -r scripts/requirements-lint.txt", file=sys.stderr)
        return 1
    report = Report()
    try:
        skills, commands = validate(args.repo, report)
    except OSError as exc:
        report.error(args.repo, f"cannot inspect definitions: {exc}")
        skills, commands = 0, 0
    for warning in ([] if args.quiet else report.warnings):
        print(f"  ~ {warning}")
    for error in report.errors:
        print(f"  ! {error}", file=sys.stderr)
    print(f"\n{commands} commands, {skills} skills — "
          f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
