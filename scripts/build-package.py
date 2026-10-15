#!/usr/bin/env python3
"""Build an allowlisted, physical UAT source package using only the stdlib."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile


PACKAGE_ID = "session-chronicle"
VERSION = "0.2.0"
SKILLS = (PACKAGE_ID, PACKAGE_ID + "-bootstrap", PACKAGE_ID + "-refactor")
DESTINATIONS = {
    "opencode": ".opencode/plugins/session-chronicle",
    "claude-code": ".claude/hooks/session-chronicle",
    "codex": ".codex/hooks/session-chronicle",
    "pi": ".pi/extensions/session-chronicle",
}
CORE_SOURCE = Path("skill/session-chronicle/scripts")
BOOTSTRAP_SCANNER = Path("skills/session-chronicle-bootstrap/scripts/scan-history.py")
PACKAGE_DOCUMENTS = (
    "README.md",
    "docs/package-consumption.md",
    "docs/portability-plan.md",
    "docs/runtime-contracts.md",
    "docs/legacy-data.md",
    "docs/capability-matrix.md",
    "docs/uat-integration-request.md",
    "docs/verification.md",
    *(f"adapters/{target}/README.md" for target in DESTINATIONS),
)
LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "COPYING.txt")
REQUIRED_RUNTIME = (
    CORE_SOURCE / "chronicle.py",
    BOOTSTRAP_SCANNER,
    Path("adapters/opencode/index.ts"),
    Path("adapters/opencode/entry.ts"),
    Path("adapters/pi/index.ts"),
    Path("adapters/pi/entry.ts"),
    Path("adapters/claude-code/hook.py"),
    Path("adapters/codex/hook.py"),
)


def physical_file(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Expected a contained source path: {relative}")
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"Package inputs must be physical, not symlinks: {relative}")
    if not path.is_file():
        raise ValueError(f"Missing package input: {relative}")
    return path


def runtime_name(path: Path) -> bool:
    return not (
        path.name.startswith((".", "test_"))
        or path.stem.endswith((".test", "_test", ".spec"))
        or path.name in {"conftest.py", "test.py", "checkpoint-nudge.py"}
    )


def inventory(root: Path) -> dict[str, str]:
    """Source → staged path; allowlisted runtime, schemas and physical instructions."""
    selected = {relative: relative for relative in PACKAGE_DOCUMENTS}
    for name in LICENSE_FILES:
        if (root / name).exists() or (root / name).is_symlink():
            selected[name] = name
    for path in sorted((root / "schemas").glob("*.json")):
        if runtime_name(path):
            relative = path.relative_to(root).as_posix()
            selected[relative] = relative
    for path in sorted((root / CORE_SOURCE).glob("*")):
        if path.suffix in {".py", ".sh"} and runtime_name(path):
            selected[path.relative_to(root).as_posix()] = "core/" + path.name
    for target in (*DESTINATIONS, "shared"):
        for path in sorted((root / "adapters" / target).glob("*")):
            if path.suffix in {".ts", ".py", ".json", ".mjs"} and runtime_name(path):
                relative = path.relative_to(root).as_posix()
                selected[relative] = relative
    for skill in SKILLS:
        base = root / "skills" / skill
        selected[f"skills/{skill}/SKILL.md"] = f"skills/{skill}/SKILL.md"
        for path in sorted((base / "references").glob("*")):
            if path.suffix in {".md", ".json", ".txt"} and runtime_name(path):
                relative = path.relative_to(root).as_posix()
                selected[relative] = relative
    selected[BOOTSTRAP_SCANNER.as_posix()] = BOOTSTRAP_SCANNER.as_posix()
    for relative in selected:
        physical_file(root, Path(relative))
    return dict(sorted(selected.items()))


def runtime_maps(selected: dict[str, str], staged: bool = False) -> dict:
    maps = {}
    for harness, destination in DESTINATIONS.items():
        files = {}
        for source, packaged in selected.items():
            if Path(source).name == "README.md":
                continue
            if packaged.startswith("core/"):
                target = destination + "/" + packaged
            elif source.startswith((f"adapters/{harness}/", "adapters/shared/")):
                target = destination + "/" + packaged
                if source == f"adapters/{harness}/entry.ts":
                    target = destination + "/index.ts"
            else:
                continue
            files[packaged if staged else source] = target
        maps[harness] = dict(sorted(files.items()))
    return maps


def manifest(root: Path, selected: dict[str, str], staged: bool = False) -> dict:
    value = json.loads(physical_file(root, Path("plugin.yaml")).read_text())
    if (value.get("id"), value.get("version")) != (PACKAGE_ID, VERSION):
        raise ValueError("Package manifest must identify session-chronicle version 0.2.0")
    if set(value.get("adapters", {})) != set(DESTINATIONS):
        raise ValueError("Package manifest must declare exactly four adapters")
    for harness, files in runtime_maps(selected, staged).items():
        value["adapters"][harness]["files"] = files
    return value


def json_bytes(value: dict) -> bytes:
    # JSON is a YAML 1.2 subset: no build-time PyYAML dependency or aliases.
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def refresh_manifest(root: Path) -> None:
    selected = inventory(root)
    (root / "plugin.yaml").write_bytes(json_bytes(manifest(root, selected)))


def stage_package(root: Path, output: Path) -> dict:
    root = root.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("Package stage must not already exist")
    if output.resolve().is_relative_to(root):
        raise ValueError("Package stage must be outside the source checkout")
    selected = inventory(root)
    for relative in REQUIRED_RUNTIME:
        physical_file(root, relative)
    package_manifest = manifest(root, selected, staged=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".chronicle-package-", dir=output.parent))
    try:
        for source, relative in selected.items():
            content = physical_file(root, Path(source)).read_bytes()
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o755 if content.startswith(b"#!") else 0o644)
            if relative.startswith("core/"):
                skill_script = temporary / "skills/session-chronicle/scripts" / destination.name
                skill_script.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(destination, skill_script)
                skill_script.chmod(destination.stat().st_mode & 0o777)
        (temporary / "plugin.yaml").write_bytes(json_bytes(package_manifest))
        (temporary / "plugin.yaml").chmod(0o644)
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return package_report(output)


def package_report(stage: Path) -> dict:
    files = {
        path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(stage.rglob("*")) if path.is_file()
    }
    return {
        "id": PACKAGE_ID, "version": VERSION, "files": files,
        "content_sha256": hashlib.sha256(json_bytes(files)).hexdigest(),
    }


def archive_package(stage: Path, output: Path) -> str:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Package archive must not already exist")
    if output.resolve().is_relative_to(stage.resolve()):
        raise ValueError("Archive must be outside the package stage")
    descriptor, name = tempfile.mkstemp(prefix=".chronicle-archive-", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            write_archive(stage, raw)
            raw.flush()
            os.fsync(raw.fileno())
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        # A same-filesystem hard link publishes complete bytes without replacing a
        # competing archive or symlink, even if one appeared after the first check.
        os.link(temporary, output)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def write_archive(stage: Path, raw) -> None:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(stage.rglob("*"), key=lambda item: item.relative_to(stage).as_posix()):
                if path.is_symlink():
                    raise ValueError("Package stage cannot contain symlinks")
                if path.is_dir():
                    continue
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError("Package stage cannot contain special files")
                content = path.read_bytes()
                entry = tarfile.TarInfo(path.relative_to(stage).as_posix())
                entry.size = len(content)
                entry.mode = 0o755 if content.startswith(b"#!") else 0o644
                entry.mtime = entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                archive.addfile(entry, io.BytesIO(content))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="New disposable stage outside the source checkout")
    parser.add_argument("--archive", type=Path, help="New deterministic .tar.gz file")
    parser.add_argument("--write-manifest", action="store_true", help="Refresh root artifact maps")
    args = parser.parse_args()
    if not args.output and not args.write_manifest:
        parser.error("--output or --write-manifest is required")
    if args.archive and not args.output:
        parser.error("--archive requires --output")
    try:
        if args.write_manifest:
            refresh_manifest(args.source.resolve())
        if args.output:
            report = stage_package(args.source, args.output)
            if args.archive:
                report["archive_sha256"] = archive_package(args.output, args.archive)
            print(json.dumps(report, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Package build failed: {error}\n")


if __name__ == "__main__":
    main()
