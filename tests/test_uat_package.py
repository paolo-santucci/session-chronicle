"""Real UAT loading/rendering integration; no native execution or deployment.

UAT_ROOT selects a read-only checkout; the sibling checkout is the default.
Use its .venv/bin/python -B to supply PyYAML/jsonschema without installing here.
Fixture model bindings are inert placeholders, never model selections or launches.
"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
UAT_ROOT = Path(os.environ.get("UAT_ROOT", ROOT.parent / "universal-agentic-toolkit"))
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
SPEC = importlib.util.spec_from_file_location("chronicle_package_builder", ROOT / "scripts/build-package.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

UAT_AVAILABLE = (UAT_ROOT / "uat/packages.py").is_file()
UAT_REASON = "UAT checkout absent; set UAT_ROOT or use the sibling checkout"
if UAT_AVAILABLE:
    sys.path.insert(0, str(UAT_ROOT))
    try:
        from uat.adapters.common import BASELINES
        from uat.compiler import compile_roster
        from uat.definitions import Definition, Library, read_definition, validate_metadata
        from uat.deployment import compatibility_report, export_artifacts, install
        from uat.errors import ToolkitError
        from uat.packages import add_package, unpack_package
        from uat.resolution import resolve
    except ModuleNotFoundError as error:
        if error.name not in {"yaml", "jsonschema"}:
            raise
        UAT_AVAILABLE = False
        UAT_REASON = f"Optional UAT dependency missing: {error.name}; run with UAT's .venv/bin/python -B"


def metadata(kind: str, identity: str, **fields) -> dict:
    return {"schema-version": 1, "kind": kind, "id": identity,
            "description": "Inert package integration fixture", **fields}


def fixture_library(root: Path):
    root.mkdir()
    bindings = root / "bindings"
    bindings.mkdir()
    for harness in BASELINES:
        (bindings / f"{harness}.yaml").write_text(json.dumps({
            "schema-version": 1, "harness": harness,
            "models": {"fixture/inert": "fixture/inert"},
        }))
    library = Library(root)
    library.add("rosters", Definition(metadata(
        "roster", "package-test", agents=[],
        skills=["session-chronicle-bootstrap", "session-chronicle-refactor"],
        plugins=["session-chronicle", "status-inject"],
    )))
    library.add("profiles", Definition(metadata(
        "model-profile", "inert-profile", default="fixture/inert", assignments={},
    )))
    for plugin in ("agent-statistics", "status-inject"):
        library.add("plugins", read_definition(UAT_ROOT / "library/plugins" / f"{plugin}.yaml"))
    return library


@unittest.skipUnless(UAT_AVAILABLE, UAT_REASON)
class UATPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="chronicle-uat-test-", dir=TEMP_ROOT)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name)
        cls.stage = cls.base / "package"
        builder.stage_package(ROOT, cls.stage)
        cls.archive = cls.base / "session-chronicle-0.2.0.tar.gz"
        cls.sha256 = builder.archive_package(cls.stage, cls.archive)

    def setUp(self):
        self.temporary_test = tempfile.TemporaryDirectory(prefix="case-", dir=self.base)
        self.addCleanup(self.temporary_test.cleanup)
        self.case = Path(self.temporary_test.name)
        self.library = fixture_library(self.case / "library")
        self.package = add_package(self.library, self.stage)

    def compile(self, harness):
        return compile_roster(self.library, "package-test", "inert-profile", harness,
                              BASELINES[harness], statistics=True)

    def test_source_manifest_is_schema_valid_and_maps_current_physical_inventory(self):
        definition = read_definition(ROOT / "plugin.yaml")
        self.assertEqual((definition.id, definition.metadata["version"]), ("session-chronicle", "0.2.0"))
        self.assertEqual(set(definition.metadata["adapters"]), set(BASELINES))
        expected = builder.runtime_maps(builder.inventory(ROOT))
        required = {
            "chronicle.capture", "chronicle.retrieval",
            "chronicle.session-context", "chronicle.protected-history",
        }
        self.assertEqual(set(definition.metadata["capabilities"]["required"]), required)
        unsupported = {
            "opencode": {"chronicle.capture"},
            "claude-code": {"chronicle.capture", "chronicle.session-context"},
            "codex": {"chronicle.capture", "chronicle.session-context"},
            "pi": required,
        }
        staged = self.library.get("plugins", "session-chronicle").metadata
        for harness, adapter in definition.metadata["adapters"].items():
            self.assertEqual(adapter["files"], expected[harness], "Run build-package.py --write-manifest")
            for source in adapter["files"]:
                builder.physical_file(ROOT, Path(source))
            self.assertEqual(adapter["capabilities"], {
                capability: "unsupported" if capability in unsupported[harness] else "unverified"
                for capability in required
            })
            self.assertEqual(staged["adapters"][harness]["capabilities"], adapter["capabilities"])
            self.assertEqual(staged["adapters"][harness]["activation"], adapter["activation"])
        self.assertEqual(staged["capabilities"], definition.metadata["capabilities"])

    def test_package_selection_resolves_all_skills_and_native_status_statistics(self):
        selected = resolve(self.library, "package-test", statistics=True)
        self.assertEqual(set(selected["skills"]), set(builder.SKILLS))
        self.assertEqual(set(selected["plugins"]), {"session-chronicle", "agent-statistics", "status-inject"})
        self.assertEqual(self.package["version"], "0.2.0")
        self.assertFalse(selected["plugins"]["session-chronicle"].metadata["requires"].get("skills"))

    def test_loading_without_selection_does_not_enable_chronicle(self):
        roster = self.library.get("rosters", "package-test")
        value = deepcopy(roster.metadata)
        value.update(skills=[], plugins=["status-inject"])
        self.library.entries["rosters"][roster.id] = Definition(value)
        deployment, rendered, _ = self.compile("opencode")
        self.assertNotIn("session-chronicle", {item["id"] for item in deployment["plugins"]})
        self.assertFalse(any("session-chronicle" in path for path in rendered["files"]))

    def test_skill_selection_pulls_in_runtime_plugin_without_a_cycle(self):
        roster = self.library.get("rosters", "package-test")
        value = deepcopy(roster.metadata)
        value.update(skills=["session-chronicle-bootstrap"], plugins=["status-inject"])
        self.library.entries["rosters"][roster.id] = Definition(value)
        selected = resolve(self.library, "package-test")
        self.assertEqual(set(selected["skills"]), {"session-chronicle-bootstrap", "session-chronicle"})
        self.assertIn("session-chronicle", selected["plugins"])

    def test_skill_resources_are_physical_and_maintenance_scripts_share_core_bytes(self):
        required = (
            "session-chronicle/references/atomic-topic-contract.md",
            "session-chronicle/references/atomicity-examples.md",
            "session-chronicle/references/session-note-template.md",
            "session-chronicle/references/topic-note-template.md",
            "session-chronicle/references/topic-structure-template.md",
            "session-chronicle/references/topic-redirect-template.md",
            "session-chronicle/references/zettelkasten-method.md",
            "session-chronicle-refactor/references/report-template.md",
            "session-chronicle-bootstrap/scripts/scan-history.py",
        )
        for relative in required:
            path = self.stage / "skills" / relative
            self.assertTrue(path.is_file() and not path.is_symlink(), relative)
        for core in (self.stage / "core").iterdir():
            self.assertEqual(core.read_bytes(), (self.stage / "skills/session-chronicle/scripts" / core.name).read_bytes())
        for harness in BASELINES:
            _, rendered, _ = self.compile(harness)
            prefix = {"opencode": ".opencode", "claude-code": ".claude", "codex": ".agents", "pi": ".pi"}[harness]
            for relative in required:
                self.assertIn(f"{prefix}/skills/{relative}", rendered["files"])

    def test_four_targets_render_package_bytes_without_overwriting_native_integration(self):
        for harness in BASELINES:
            with self.subTest(harness=harness):
                deployment, rendered, report = self.compile(harness)
                plugin = next(item for item in deployment["plugins"] if item["id"] == "session-chronicle")
                mappings = plugin["metadata"]["adapters"][harness]["files"]
                self.assertTrue(mappings)
                for source, target in mappings.items():
                    self.assertEqual(rendered["files"][target], (self.stage / source).read_bytes())
                    self.assertTrue(target.startswith(builder.DESTINATIONS[harness] + "/"))
                if harness in {"claude-code", "codex"}:
                    path = ".claude/settings.json" if harness == "claude-code" else ".codex/hooks.json"
                    native = json.loads(rendered["files"][path])
                    self.assertIn("SessionStart", native["hooks"])
                    self.assertIn("PostToolUse", native["hooks"])
                    self.assertNotIn("session-chronicle", rendered["files"][path])
                else:
                    prefix = ".opencode/plugins" if harness == "opencode" else ".pi/extensions"
                    self.assertIn(prefix + "/uat/index.ts", rendered["files"])
                    self.assertIn(prefix + "/session-chronicle/index.ts", rendered["files"])
                self.assertTrue(deployment["statistics"])
                self.assertIn("status.context", report["required"])
                self.assertIn("statistics.capture", report["required"])

    def test_external_required_capabilities_block_sync_without_writing_workspace(self):
        workspace = self.case / "workspace"
        workspace.mkdir()
        sentinel = workspace / "keep.txt"
        sentinel.write_bytes(b"untouched")
        required = self.library.get("plugins", "session-chronicle").metadata["capabilities"]["required"]
        self.assertTrue(required)
        for harness in BASELINES:
            with self.subTest(harness=harness):
                deployment, rendered, report = self.compile(harness)
                blockers = {item["capability"]: item["status"] for item in report["blockers"]}
                self.assertFalse(report["deployable"])
                self.assertTrue(all(blockers[capability] == "unsupported" for capability in required))
                with self.assertRaisesRegex(ToolkitError, "Required capabilities lack runtime qualification"):
                    install(workspace, deployment, rendered)
        self.assertEqual(list(workspace.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"untouched")

    def test_missing_required_capability_is_unverified_and_blocks(self):
        deployment, rendered, _ = self.compile("opencode")
        required = self.library.get("plugins", "session-chronicle").metadata["capabilities"]["required"][0]
        rendered["capabilities"].pop(required)
        report = compatibility_report(deployment, rendered)
        self.assertIn({"capability": required, "status": "unverified"}, report["blockers"])

    def test_uat_allowlist_marks_synthetic_unverified_external_capability_unsupported(self):
        capability = "fixture.external-capability"
        plugin = Definition(metadata(
            "plugin", "inert-external", version="0.0.0", requires={},
            capabilities={"required": [capability], "optional": []},
            adapters={harness: {"capabilities": {capability: "unverified"}} for harness in BASELINES},
        ))
        validate_metadata(plugin.metadata)
        self.library.add("plugins", plugin)
        roster = self.library.get("rosters", "package-test")
        selection = deepcopy(roster.metadata)
        selection["plugins"].append(plugin.id)
        self.library.entries["rosters"][roster.id] = Definition(selection)
        for harness in BASELINES:
            with self.subTest(harness=harness):
                _, rendered, report = self.compile(harness)
                self.assertEqual(plugin.metadata["adapters"][harness]["capabilities"][capability], "unverified")
                self.assertEqual(rendered["capabilities"][capability], "unsupported")
                self.assertIn({"capability": capability, "status": "unsupported"}, report["blockers"])

    def test_plugin_artifact_collision_is_rejected(self):
        plugin = self.library.get("plugins", "session-chronicle")
        value = deepcopy(plugin.metadata)
        value["adapters"]["opencode"]["files"]["core/chronicle.py"] = "opencode.json"
        self.library.entries["plugins"][plugin.id] = Definition(value, resources=plugin.resources)
        with self.assertRaisesRegex(ToolkitError, "Plugin artifact collision: opencode.json"):
            self.compile("opencode")

    def test_duplicate_package_identity_is_rejected(self):
        with self.assertRaisesRegex(ToolkitError, "Duplicate plugins identity"):
            add_package(self.library, self.stage)

    def test_dependency_cycle_is_rejected(self):
        plugin = self.library.get("plugins", "session-chronicle")
        value = deepcopy(plugin.metadata)
        value.setdefault("requires", {})["skills"] = ["session-chronicle"]
        self.library.entries["plugins"][plugin.id] = Definition(value, resources=plugin.resources)
        with self.assertRaisesRegex(ToolkitError, "Dependency cycle"):
            resolve(self.library, "package-test")

    def test_excluded_required_skill_is_rejected(self):
        roster = self.library.get("rosters", "package-test")
        value = deepcopy(roster.metadata)
        value["exclude"] = {"skills": ["session-chronicle-refactor"]}
        self.library.entries["rosters"][roster.id] = Definition(value)
        with self.assertRaisesRegex(ToolkitError, "explicitly excluded"):
            resolve(self.library, "package-test")

    def test_unknown_memory_policy_operation_is_not_invented(self):
        agent = metadata("agent", "inert-agent", execution="primary", requires={}, capabilities={},
                         policy={"default": "deny", "rules": [
                             {"capability": "memory.find", "resource": "*", "effect": "allow"},
                         ]})
        with self.assertRaisesRegex(ToolkitError, "Invalid policy"):
            validate_metadata(agent)

    def test_native_artifact_bindings_remain_literal_bytes_and_change_fingerprint(self):
        _, _, original = self.compile("opencode")
        plugin = self.library.get("plugins", "session-chronicle")
        resources = dict(plugin.resources)
        resources["core/chronicle.py"] += b"\n# {{tool:not-a-binding}} \x00\xff\n"
        self.library.entries["plugins"][plugin.id] = Definition(plugin.metadata, resources=resources)
        _, rendered, changed = self.compile("opencode")
        target = builder.DESTINATIONS["opencode"] + "/core/chronicle.py"
        self.assertEqual(rendered["files"][target], resources["core/chronicle.py"])
        self.assertNotEqual(original["fingerprint"], changed["fingerprint"])

    def test_pinned_local_archive_loads_with_real_unpack_package(self):
        destination = self.case / "unpacked"
        lock = unpack_package(self.archive.read_bytes(), self.sha256, "0.2.0", destination)
        library = fixture_library(self.case / "archive-library")
        package = add_package(library, destination)
        self.assertEqual((lock["id"], lock["version"], lock["sha256"]),
                         ("session-chronicle", "0.2.0", self.sha256))
        self.assertEqual(package["id"], "session-chronicle")
        for harness, version in BASELINES.items():
            _, _, report = compile_roster(library, "package-test", "inert-profile", harness, version)
            self.assertFalse(report["deployable"])
        for relative, digest in builder.package_report(self.stage)["files"].items():
            self.assertEqual((destination / relative).read_bytes(), (self.stage / relative).read_bytes(), digest)

    def test_real_archive_contains_physical_schemas_and_activation_instructions(self):
        schemas = [path.relative_to(ROOT).as_posix() for path in (ROOT / "schemas").glob("*.json")]
        self.assertTrue(schemas)
        with tarfile.open(self.archive) as archive:
            for relative in (*builder.PACKAGE_DOCUMENTS, *schemas):
                self.assertTrue(archive.getmember(relative).isfile(), relative)
                self.assertEqual(archive.extractfile(relative).read(), (self.stage / relative).read_bytes())
            self.assertFalse(any(Path(entry.name).name == "checkpoint-nudge.py" for entry in archive.getmembers()))
            self.assertTrue(all(entry.isfile() and ".." not in Path(entry.name).parts for entry in archive.getmembers()))

    def test_wrong_archive_digest_and_version_are_rejected_without_destination(self):
        destination = self.case / "unpacked"
        with self.assertRaisesRegex(ToolkitError, "pinned digest"):
            unpack_package(self.archive.read_bytes(), "0" * 64, "0.2.0", destination)
        with self.assertRaisesRegex(ToolkitError, "pinned plugin version"):
            unpack_package(self.archive.read_bytes(), self.sha256, "9.9.9", destination)
        self.assertFalse(destination.exists())

    def test_export_preserves_memory_state_and_other_harness_files(self):
        workspace = self.case / "workspace"
        preserved = (
            "docs/sessions/session.md", "docs/topics/topic.md", "docs/.drafts/draft.json",
            "docs/.drafts/pending/batch.json", "docs/continuations/link.json",
            ".uat/adapter-event-times/id", ".opencode/sessions/native.json",
            ".claude/settings.json", ".codex/hooks.json", ".pi/settings.json",
            "AGENTS.md", "STATUS.yaml",
        )
        for relative in preserved:
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"existing state: " + relative.encode())
        before = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
        for harness in BASELINES:
            deployment, rendered, report = self.compile(harness)
            with self.assertRaisesRegex(ToolkitError, "empty destination"):
                export_artifacts(workspace, deployment, rendered, report)
            export_artifacts(self.case / f"export-{harness}", deployment, rendered, report)
            for surface in rendered["replace_paths"]:
                for state in ("docs", ".uat", ".opencode/sessions"):
                    self.assertFalse(Path(surface).is_relative_to(state) or Path(state).is_relative_to(surface))
        after = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_packaged_core_rejects_docs_root_overlapping_configuration(self):
        workspace = self.case / "workspace"
        workspace.mkdir()
        for docs_root in (".", ".opencode", ".claude/hooks", ".codex", ".pi/extensions", ".agents/skills"):
            with self.subTest(docs_root=docs_root):
                (workspace / "AGENTS.md").write_text(f"---\ndocs-root: {docs_root}\n---\n")
                result = subprocess.run(
                    [sys.executable, "-B", str(self.stage / "core/_docsroot.py"), str(workspace)],
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must not overlap", result.stderr)


if __name__ == "__main__":
    unittest.main()
