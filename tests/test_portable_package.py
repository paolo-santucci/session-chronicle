"""Dependency-free packaging checks; fixture adapters are inert source bytes."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chronicle_package_builder", ROOT / "scripts/build-package.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None


def write(root: Path, relative: str, content: bytes = b"fixture\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def fixture_source(root: Path) -> Path:
    root.mkdir()
    write(root, "plugin.yaml", (ROOT / "plugin.yaml").read_bytes())
    for relative in builder.PACKAGE_DOCUMENTS:
        write(root, relative, b"physical package instructions\n")
    write(root, "schemas/envelope.schema.json", b'{"type": "object"}\n')
    for path in builder.REQUIRED_RUNTIME:
        write(root, path.as_posix(), b"# inert packaging fixture; never executed\n")
    write(root, "adapters/shared/client.ts", b"// inert fixture\n")
    for skill in builder.SKILLS:
        write(root, f"skills/{skill}/SKILL.md", b"# inert packaging fixture\n")
        write(root, f"skills/{skill}/references/guide.md", b"physical resource\n")
    return root


class PortablePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chronicle-package-test-", dir=TEMP_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = fixture_source(self.base / "source")

    def test_stage_excludes_dirty_checkout_state_and_tests(self):
        excluded = (
            ".git/config", ".env", "docs/sessions/private.md", "docs/topics/topic.md",
            "docs/.drafts/draft.json", ".uat/events.jsonl", ".opencode/sessions/native.json",
            "node_modules/package/index.ts", "tests/test_private.py",
            "skill/session-chronicle/scripts/test_capture.py",
            "skill/session-chronicle/scripts/checkpoint-nudge.py",
            "skill/session-chronicle/scripts/__pycache__/private.pyc",
            "adapters/opencode/index.test.ts", "adapters/pi/runtime/state.json",
            "skills/session-chronicle/scripts/test_private.py",
        )
        for relative in excluded:
            write(self.source, relative, b"DO NOT SHIP\n")
        (self.source / "unrelated-symlink").symlink_to(self.base)
        stage = self.base / "stage"
        report = builder.stage_package(self.source, stage)
        self.assertFalse(any(path.is_symlink() for path in stage.rglob("*")))
        self.assertFalse(any(b"DO NOT SHIP" in path.read_bytes() for path in stage.rglob("*") if path.is_file()))
        self.assertEqual((report["id"], report["version"]), ("session-chronicle", "0.2.0"))
        self.assertTrue((stage / "core/chronicle.py").is_file())
        self.assertEqual((stage / "core/chronicle.py").read_bytes(),
                         (stage / "skills/session-chronicle/scripts/chronicle.py").read_bytes())
        self.assertTrue((stage / "skills/session-chronicle-bootstrap/scripts/scan-history.py").is_file())
        self.assertFalse((stage / "skill").exists())
        self.assertTrue((self.source / "skill/session-chronicle/scripts/checkpoint-nudge.py").is_file())
        self.assertFalse(any(path.name == "checkpoint-nudge.py" for path in stage.rglob("*")))

    def test_stage_rejects_symlinked_runtime_input(self):
        source = self.source / "adapters/pi/index.ts"
        source.unlink()
        source.symlink_to(write(self.base, "outside.ts"))
        with self.assertRaisesRegex(ValueError, "physical"):
            builder.stage_package(self.source, self.base / "stage")
        self.assertFalse((self.base / "stage").exists())

    def test_stage_rejects_symlinked_parent_directory(self):
        source = self.source / "adapters/shared"
        source.rename(self.base / "shared")
        source.symlink_to(self.base / "shared", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "physical"):
            builder.stage_package(self.source, self.base / "stage")

    def test_stage_rejects_symlinked_skill_resource(self):
        path = self.source / "skills/session-chronicle/references/guide.md"
        path.unlink()
        path.symlink_to(write(self.base, "external.md"))
        with self.assertRaisesRegex(ValueError, "physical"):
            builder.stage_package(self.source, self.base / "stage")

    def test_stage_requires_complete_adapter_inventory(self):
        (self.source / "adapters/codex/hook.py").unlink()
        with self.assertRaisesRegex(ValueError, "Missing package input"):
            builder.stage_package(self.source, self.base / "stage")

    def test_existing_stage_and_source_tree_are_never_overwritten(self):
        stage = self.base / "stage"
        sentinel = write(stage, "keep", b"unchanged")
        with self.assertRaisesRegex(ValueError, "already exist"):
            builder.stage_package(self.source, stage)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        with self.assertRaisesRegex(ValueError, "outside the source"):
            builder.stage_package(self.source, self.source / "dist")

    def test_manifest_maps_physical_sources_and_relocates_core(self):
        builder.refresh_manifest(self.source)
        source_manifest = json.loads((self.source / "plugin.yaml").read_text())
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        staged_manifest = json.loads((stage / "plugin.yaml").read_text())
        self.assertEqual(set(staged_manifest["adapters"]), set(builder.DESTINATIONS))
        for harness, base in builder.DESTINATIONS.items():
            source_files = source_manifest["adapters"][harness]["files"]
            staged_files = staged_manifest["adapters"][harness]["files"]
            self.assertIn("skill/session-chronicle/scripts/chronicle.py", source_files)
            self.assertEqual(staged_files["core/chronicle.py"], base + "/core/chronicle.py")
            self.assertEqual(set(source_files.values()), set(staged_files.values()))
            for source, destination in staged_files.items():
                self.assertTrue((stage / source).is_file(), source)
                self.assertTrue(destination.startswith(base + "/"), destination)
                self.assertFalse(source.endswith("README.md") or source.startswith(("docs/", "schemas/")))
            if harness in {"opencode", "pi"}:
                self.assertEqual(staged_files[f"adapters/{harness}/entry.ts"], base + "/index.ts")

    def test_archives_are_byte_identical_despite_source_metadata_changes(self):
        first = self.base / "first"
        report = builder.stage_package(self.source, first)
        first_sha = builder.archive_package(first, self.base / "first.tar.gz")
        for path in self.source.rglob("*"):
            if path.is_file():
                os.utime(path, (123456789, 123456789))
                path.chmod(0o700)
        second = self.base / "second"
        self.assertEqual(builder.stage_package(self.source, second), report)
        second_sha = builder.archive_package(second, self.base / "second.tar.gz")
        self.assertEqual(first_sha, second_sha)
        self.assertEqual((self.base / "first.tar.gz").read_bytes(), (self.base / "second.tar.gz").read_bytes())
        with tarfile.open(self.base / "first.tar.gz") as archive:
            entries = archive.getmembers()
            self.assertEqual([entry.name for entry in entries], sorted(entry.name for entry in entries))
            self.assertIn("plugin.yaml", archive.getnames())
            self.assertTrue(all(entry.isfile() and entry.uid == entry.gid == entry.mtime == 0 for entry in entries))

    def test_archive_refuses_to_overwrite_a_pin(self):
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        archive = write(self.base, "pinned.tar.gz", b"pinned")
        with self.assertRaises(FileExistsError):
            builder.archive_package(stage, archive)
        self.assertEqual(archive.read_bytes(), b"pinned")

    def test_archive_failure_leaves_no_pin_or_temporary_file_and_can_be_retried(self):
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        link = stage / "zzz-invalid-symlink"
        link.symlink_to(self.base / "missing")
        output = self.base / "retry.tar.gz"
        with self.assertRaisesRegex(ValueError, "symlinks"):
            builder.archive_package(stage, output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.base.glob(".chronicle-archive-*")), [])
        link.unlink()
        self.assertEqual(len(builder.archive_package(stage, output)), 64)
        with tarfile.open(output) as archive:
            self.assertIn("plugin.yaml", archive.getnames())

    def test_archive_refuses_existing_symlink_without_touching_target(self):
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        target = write(self.base, "target", b"preserved")
        output = self.base / "pin.tar.gz"
        output.symlink_to(target)
        with self.assertRaises(FileExistsError):
            builder.archive_package(stage, output)
        self.assertTrue(output.is_symlink())
        self.assertEqual(target.read_bytes(), b"preserved")

    def test_archive_publication_preserves_a_competing_pin_and_cleans_temporary_file(self):
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        output = self.base / "pin.tar.gz"
        link = os.link

        def competing_publish(source, destination):
            Path(destination).symlink_to(self.base / "missing-target")
            link(source, destination)

        with patch.object(builder.os, "link", side_effect=competing_publish):
            with self.assertRaises(FileExistsError):
                builder.archive_package(stage, output)
        self.assertTrue(output.is_symlink())
        self.assertEqual(output.readlink(), self.base / "missing-target")
        self.assertEqual(list(self.base.glob(".chronicle-archive-*")), [])

    def test_archive_contains_physical_schemas_instructions_and_existing_license(self):
        write(self.source, "LICENSE", b"fixture license\n")
        stage = self.base / "stage"
        builder.stage_package(self.source, stage)
        output = self.base / "bundle.tar.gz"
        builder.archive_package(stage, output)
        with tarfile.open(output) as archive:
            for relative in (*builder.PACKAGE_DOCUMENTS, "schemas/envelope.schema.json", "LICENSE"):
                self.assertTrue(archive.getmember(relative).isfile(), relative)
                self.assertEqual(archive.extractfile(relative).read(), (self.source / relative).read_bytes())
            self.assertTrue(all(entry.isfile() and ".." not in Path(entry.name).parts for entry in archive.getmembers()))

    def test_document_symlink_to_sibling_is_rejected(self):
        path = self.source / "docs/runtime-contracts.md"
        path.unlink()
        path.symlink_to(write(self.base, "sibling/runtime-contracts.md"))
        with self.assertRaisesRegex(ValueError, "physical"):
            builder.stage_package(self.source, self.base / "stage")


if __name__ == "__main__":
    unittest.main()
