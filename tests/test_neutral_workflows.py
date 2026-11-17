"""Neutral resource/schema checks and real filesystem history-scan fixtures.

Git results are mocked: these tests never change or inspect a repository. UAT
validation is optional; UAT_ROOT may select its read-only checkout and interpreter.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CORE = ROOT / "skill/session-chronicle/scripts"
SCANNER = SKILLS / "session-chronicle-bootstrap/scripts/scan-history.py"
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scanner = load_module("neutral_history_scanner", SCANNER)
UAT_ROOT = Path(os.environ.get("UAT_ROOT", ROOT.parent / "universal-agentic-toolkit"))
OPTIONAL_IMPORTS = frozenset({"uat", "yaml", "jsonschema"})


def optional_module(name, optional=OPTIONAL_IMPORTS):
    """Import ``name``, returning ``None`` when an optional dependency is absent.

    Declared-optional dependencies degrade to ``None`` so the module still
    imports; anything else re-raises, because a genuinely missing non-optional
    module must fail loudly rather than be swallowed. A named helper (instead of
    an inline ``try`` at module scope) keeps that negative half directly
    testable: OQ-29.

    The comparison is on the *root* package: a dotted import such as
    ``uat.adapters.common`` reports the whole dotted name in ``error.name``, so a
    partially present UAT checkout must degrade the same way an absent one does
    instead of collapsing every packaging test into one collection error
    (FR-39, EC-36).
    """
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        root = (error.name or "").split(".")[0]
        if root not in optional:
            raise
        return None


# A probe on the expected file keeps collection independent of sys.path: a
# missing checkout leaves every test collectable and cleanly skipped, while a
# missing *non-optional* module still raises (FR-39, EC-36).
UAT_AVAILABLE = (UAT_ROOT / "uat/adapters/common.py").is_file()
Artifacts = BASELINES = read_definition = None
if UAT_AVAILABLE:
    if str(UAT_ROOT) not in sys.path:
        sys.path.insert(0, str(UAT_ROOT))
    uat_common = optional_module("uat.adapters.common")
    uat_definitions = optional_module("uat.definitions")
    if uat_common is not None and uat_definitions is not None:
        Artifacts, BASELINES = uat_common.Artifacts, uat_common.BASELINES
        read_definition = uat_definitions.read_definition
    else:
        UAT_AVAILABLE = False


COLLECTION_PROBE = """
import json
import unittest

loader = unittest.TestLoader()


def flatten(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from flatten(entry)
        else:
            yield entry


ids = [test.id() for test in flatten(loader.discover(".", pattern="test_neutral_workflows.py"))]
module = __import__("test_neutral_workflows")
print(json.dumps({
    "ids": ids,
    "collapsed": [name for name in ids if "_FailedTest" in name],
    "uat_available": bool(module.UAT_AVAILABLE),
    "bindings_absent": (module.Artifacts, module.BASELINES, module.read_definition) == (None, None, None),
}))
"""

FAKE_UAT_COMMON = '''
BASELINES = {"opencode": "2026-01-01"}


class Artifacts:
    """Inert stand-in: proves the gate opens, never a harness selection."""

    def __init__(self, payload, version):
        self.payload = payload
        self.version = version
        self.skill_root = "fixture/skills"

    def bind(self, text):
        return text.replace("{{path:skills}}", self.skill_root)
'''

FAKE_UAT_DEFINITIONS = '''
class Definition:
    """Inert stand-in mirroring the real reader's observable attributes."""

    def __init__(self, path):
        self.id = path.parent.name
        self.body = path.read_text()
        self.resources = [path]
        self.metadata = {
            "invocation": "explicit",
            "requires": {
                "plugins": ["session-chronicle"],
                "skills": [] if self.id == "session-chronicle" else ["session-chronicle"],
            },
        }

    def as_record(self):
        return {"id": self.id, "metadata": self.metadata}


def read_definition(path, _parent):
    return Definition(path)
'''


def stage_fake_uat_checkout(root):
    """Create a minimal ``uat`` package so the existence gate can open."""
    for package in (root / "uat", root / "uat/adapters"):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "uat/adapters/common.py").write_text(FAKE_UAT_COMMON, encoding="utf-8")
    (root / "uat/definitions.py").write_text(FAKE_UAT_DEFINITIONS, encoding="utf-8")
    return root


class NeutralResourcesTests(unittest.TestCase):
    def test_shared_references_preserve_compatibility_schema_byte_for_byte(self):
        originals = list((ROOT / "skill/session-chronicle/references").glob("*.md"))
        originals += list((ROOT / "skill/session-chronicle-refactor/references").glob("*.md"))
        self.assertEqual(len(originals), 8)
        for original in originals:
            with self.subTest(resource=original.name):
                neutral = SKILLS / original.relative_to(ROOT / "skill")
                self.assertFalse(neutral.is_symlink())
                self.assertEqual(neutral.read_bytes(), original.read_bytes())

    def test_neutral_paths_and_bindings_do_not_leak_host_contracts(self):
        for definition in SKILLS.glob("*/SKILL.md"):
            with self.subTest(skill=definition.parent.name):
                text = definition.read_text()
                self.assertNotRegex(text, r"\.(?:opencode|claude|codex|pi|agents)/")
                self.assertNotIn("allowed-tools:", text)
                self.assertNotRegex(text, r"\{\{tool:memory[_\.]")
                self.assertNotIn("*** Begin Patch", text)
                tokens = set(re.findall(r"\{\{([^}]+)\}\}", text))
                self.assertEqual(tokens, {"path:skills"})

    def test_builder_supplies_every_bound_resource_and_single_source_core_copy(self):
        builder = load_module("neutral_workflow_package_builder", ROOT / "scripts/build-package.py")
        with tempfile.TemporaryDirectory(prefix="chronicle-workflow-stage-", dir=TEMP_ROOT) as temporary:
            stage = Path(temporary) / "package"
            builder.stage_package(ROOT, stage)
            for definition in SKILLS.glob("*/SKILL.md"):
                paths = re.findall(r"\{\{path:skills\}\}/([A-Za-z0-9_./-]+)", definition.read_text())
                for relative in paths:
                    target = stage / "skills" / relative
                    self.assertTrue(target.exists(), relative)
                    self.assertFalse(target.is_symlink(), relative)
            for core in (stage / "core").iterdir():
                self.assertEqual(core.read_bytes(),
                                 (stage / "skills/session-chronicle/scripts" / core.name).read_bytes())
            staged_scanner = stage / SCANNER.relative_to(ROOT)
            self.assertEqual(staged_scanner.read_bytes(), SCANNER.read_bytes())
            packaged = load_module("builder_packaged_scanner", staged_scanner)
            project = Path(temporary) / "project"
            project.mkdir()
            self.assertEqual(packaged.load_resolver(None)(str(project)), str(project / "docs"))

    @unittest.skipUnless(UAT_AVAILABLE, "Optional UAT/PyYAML/jsonschema unavailable")
    def test_real_uat_loader_validates_dependencies_and_all_native_bindings(self):
        definitions = [read_definition(path, path.parent) for path in sorted(SKILLS.glob("*/SKILL.md"))]
        self.assertEqual({item.id for item in definitions}, {
            "session-chronicle", "session-chronicle-bootstrap", "session-chronicle-refactor"})
        for item in definitions:
            self.assertEqual(item.metadata["invocation"], "explicit")
            self.assertEqual(item.metadata["requires"]["plugins"], ["session-chronicle"])
            expected = [] if item.id == "session-chronicle" else ["session-chronicle"]
            self.assertEqual(item.metadata["requires"]["skills"], expected)
            self.assertTrue(item.resources, item.id)
        for harness, version in BASELINES.items():
            artifacts = Artifacts({"harness": harness, "skills": [item.as_record() for item in definitions]}, version)
            for item in definitions:
                with self.subTest(harness=harness, skill=item.id):
                    rendered = artifacts.bind(item.body)
                    self.assertNotIn("{{", rendered)
                    self.assertIn(artifacts.skill_root, rendered)


class HistoryScannerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chronicle-neutral-", dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.project = self.base / "project with spaces"
        self.project.mkdir()
        self.resolver = scanner.load_resolver(CORE)
        self.write("AGENTS.md", "---\ndocs-root: knowledge\n---\n")

    def write(self, relative, content):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git_results(self, log="", shallow="false", failure=None):
        def run(arguments, **kwargs):
            self.assertEqual(arguments[:3], ["git", "-C", str(self.project)])
            self.assertEqual(kwargs["timeout"], 10)
            self.assertNotIn("shell", kwargs)
            if failure:
                raise failure
            output = shallow + "\n" if arguments[3] == "rev-parse" else log
            return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")
        return patch.object(scanner.subprocess, "run", side_effect=run)

    def scan(self, **kwargs):
        return scanner.scan(self.project, self.resolver, **kwargs)

    def test_ordered_manifest_includes_all_legacy_sources_and_preserves_files(self):
        self.write("knowledge/specs/spec.md", "---\ndate: 2026-01-02\ntitle: Specification\n---\n")
        self.write("knowledge/plans/plan.md", "---\ndate: 2026-01-03\n---\n")
        self.write("knowledge/decisions/choice.md", "---\ndate: 2026-01-04\n---\n")
        self.write("knowledge/reports/report.md", "---\ndate: 2026-01-05\n---\n")
        self.write("knowledge/context.md", "No date known.\n")
        self.write("STATUS.yaml", 'recently-completed:\n  - date: "2026-01-06"\n    summary: "A result"\nnext: []\n')
        self.write("knowledge/sessions/existing.md", "Closed historical entry.\n")
        before = {path: path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        with self.git_results("2026-01-01\x1fabc1234\x1fInitial work\n"):
            result = self.scan()
        self.assertTrue(result["complete"], result["errors"])
        self.assertEqual(result["docs_root"], "knowledge")
        self.assertTrue(result["sessions_populated"])
        self.assertEqual([item["kind"] for item in result["items"]],
                         ["commit", "spec", "plan", "decision", "report", "status", "report"])
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in result["items"] if "path" in item))
        self.assertEqual(before, {path: path.read_bytes() for path in self.project.rglob("*") if path.is_file()})

    def test_shallow_history_keeps_observed_items_but_is_incomplete(self):
        with self.git_results("2026-01-01\x1fabc1234\x1fPartial history\n", shallow="true"):
            result = self.scan()
        self.assertFalse(result["complete"])
        self.assertEqual((result["count"], result["errors"]),
                         (1, [{"source": "git", "code": "shallow_history"}]))

    def test_git_failure_is_not_successful_empty_history(self):
        failed = subprocess.CompletedProcess([], 128, stdout="", stderr="sensitive diagnostic")
        with patch.object(scanner.subprocess, "run", return_value=failed):
            result = self.scan()
        self.assertEqual(result["errors"], [{"source": "git", "code": "git_command_failed"}])
        self.assertFalse(result["complete"])
        self.assertNotIn("sensitive diagnostic", json.dumps(result))

    def test_git_timeout_and_missing_executable_are_explicit_failures(self):
        for failure in (subprocess.TimeoutExpired("git", 10), FileNotFoundError("git")):
            with self.subTest(failure=type(failure).__name__), self.git_results(failure=failure):
                result = self.scan()
            self.assertFalse(result["complete"])
            self.assertEqual(result["errors"][0]["code"], "git_unavailable_or_timed_out")

    def test_limit_detects_truncation_instead_of_claiming_complete_history(self):
        log = "2026-01-01\x1fabc1234\x1fFirst\n2026-01-02\x1fdef1234\x1fSecond\n"
        with self.git_results(log):
            result = self.scan(git_limit=1)
        self.assertEqual((result["complete"], result["count"]), (False, 1))
        self.assertEqual(result["errors"], [{"source": "git", "code": "git_history_truncated", "limit": 1}])

    def test_complete_sparse_scan_is_distinguishable_from_failed_scan(self):
        with self.git_results():
            result = self.scan()
        self.assertEqual((result["complete"], result["count"], result["errors"], result["sessions_populated"]),
                         (True, 0, [], False))

    def test_unreadable_document_retains_other_sources_and_reports_incompleteness(self):
        bad = self.write("knowledge/specs/broken.md", "")
        bad.write_bytes(b"\xff")
        self.write("knowledge/plans/good.md", "---\ndate: 2026-01-01\n---\nPlan\n")
        with self.git_results():
            result = self.scan()
        self.assertEqual((result["complete"], result["count"]), (False, 1))
        self.assertEqual(result["errors"], [{"source": "knowledge/specs/broken.md", "code": "UnicodeDecodeError"}])

    def test_unreadable_directory_cannot_be_reported_as_empty(self):
        original = Path.iterdir
        def denied(path):
            if path.name == "specs":
                raise PermissionError("denied")
            return original(path)
        with self.git_results(), patch.object(Path, "iterdir", denied):
            result = self.scan()
        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"], [{"source": "knowledge/specs", "code": "PermissionError"}])

    def test_escaping_source_and_docs_root_are_not_read(self):
        external = self.base / "outside.md"
        external.write_text("private source")
        source = self.project / "knowledge/specs/link.md"
        source.parent.mkdir(parents=True)
        source.symlink_to(external)
        with self.git_results():
            result = self.scan()
        self.assertFalse(result["complete"])
        self.assertNotIn("private source", json.dumps(result))
        self.write("AGENTS.md", "---\ndocs-root: ../outside\n---\n")
        result = self.scan()
        self.assertEqual((result["complete"], result["docs_root"]), (False, None))

    def test_malformed_git_and_status_records_require_review(self):
        self.write("STATUS.yaml", "recently-completed:\n  - unsupported: content\n")
        with self.git_results("not a commit record\n"):
            result = self.scan()
        self.assertEqual({item["code"] for item in result["errors"]},
                         {"unsupported_status_history_shape", "invalid_git_record"})

    def test_packaged_scanner_resolves_generated_sibling_resources_without_checkout(self):
        installed = self.base / "installed"
        scanner_path = installed / "skills/session-chronicle-bootstrap/scripts/scan-history.py"
        core_path = installed / "skills/session-chronicle/scripts/_docsroot.py"
        for source, target in ((SCANNER, scanner_path), (CORE / "_docsroot.py", core_path)):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        packaged = load_module("packaged_neutral_scanner", scanner_path)
        resolver = packaged.load_resolver(None)
        self.assertEqual(resolver(str(self.project)), str(self.project / "knowledge"))
        core_path.unlink()
        with self.assertRaisesRegex(ValueError, "shared_core_missing"):
            packaged.load_resolver(None)

    def test_cli_reports_missing_core_as_nonzero_json_not_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = scanner.main(["--project", str(self.project), "--core-dir", str(self.base / "missing")])
        result = json.loads(output.getvalue())
        self.assertEqual((code, result["complete"], result["errors"][0]["code"]),
                         (2, False, "shared_core_missing"))

    def test_cli_propagates_incomplete_scan_exit_status(self):
        output = io.StringIO()
        with self.git_results(shallow="true"), contextlib.redirect_stdout(output):
            code = scanner.main(["--project", str(self.project), "--core-dir", str(CORE)])
        self.assertEqual((code, json.loads(output.getvalue())["complete"]), (2, False))


UAT_PROBE = "uat/adapters/common.py"
PACKAGING_CLASSES = (NeutralResourcesTests, HistoryScannerTests)
PACKAGING_CLASS_NAMES = tuple(f"test_neutral_workflows.{case.__name__}" for case in PACKAGING_CLASSES)
PACKAGING_TEST_IDS = tuple(
    f"test_neutral_workflows.{case.__name__}.{name}"
    for case in PACKAGING_CLASSES
    for name in unittest.TestLoader().getTestCaseNames(case)
)
PACKAGING_COUNT = 17


class OptionalModuleHelperTests(unittest.TestCase):
    """The declared-optional import helper is named and directly callable (OQ-29)."""

    def test_returns_none_when_a_declared_optional_dependency_is_absent(self):
        absent = "chronicle_absent_optional_probe"
        self.assertIsNone(optional_module(absent, optional=frozenset({absent})))

    def test_returns_the_module_when_the_import_succeeds(self):
        self.assertIs(optional_module("json"), json)

    def test_reraises_when_a_genuinely_missing_module_is_not_declared_optional(self):
        with self.assertRaises(ModuleNotFoundError):
            optional_module("chronicle_absent_required_probe")

    def test_reraises_a_synthetic_error_whose_name_is_not_declared_optional(self):
        synthetic = ModuleNotFoundError("No module named 'yamlx'", name="yamlx")
        with patch.object(importlib, "import_module", side_effect=synthetic), \
                self.assertRaises(ModuleNotFoundError) as raised:
            optional_module("yaml")
        self.assertEqual(raised.exception.name, "yamlx")

    def test_a_dotted_optional_import_degrades_on_its_root_package(self):
        # FR-39/EC-36: the dotted name is what the import machinery reports, so the
        # gate has to look at the root package or a partial UAT checkout re-collapses
        # the seventeen packaging tests into one collection error.
        dotted = ModuleNotFoundError("No module named 'uat.adapters.common'",
                                     name="uat.adapters.common")
        with patch.object(importlib, "import_module", side_effect=dotted):
            self.assertIsNone(optional_module("uat.adapters.common"))

    def test_a_dotted_import_of_a_missing_optional_root_degrades(self):
        absent = "chronicle_absent_optional_probe"
        self.assertIsNone(optional_module(absent + ".submodule",
                                          optional=frozenset({absent})))


class OptionalUatGateTests(unittest.TestCase):
    """Packaging tests must collect individually whether or not ``uat`` exists.

    A module-scope ``ModuleNotFoundError`` collapses every test into one
    ``_FailedTest``; the fixture checkout below keeps the outcome independent of
    the developer's neighbouring UAT tree.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chronicle-uat-gate-", dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.fixture = Path(temporary.name)

    def run_packaging_tests(self, uat_root):
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", *PACKAGING_CLASS_NAMES],
            cwd=ROOT / "tests", env={**os.environ, "UAT_ROOT": str(uat_root)},
            text=True, capture_output=True, timeout=60)

    def test_the_packaging_classes_hold_seventeen_named_tests(self):
        self.assertEqual(len(PACKAGING_TEST_IDS), PACKAGING_COUNT)

    def test_packaging_tests_collect_individually_when_uat_is_absent(self):
        self.assertFalse((self.fixture / UAT_PROBE).is_file())
        probe = subprocess.run(
            [sys.executable, "-B", "-c", COLLECTION_PROBE],
            cwd=ROOT / "tests", env={**os.environ, "UAT_ROOT": str(self.fixture)},
            text=True, capture_output=True, timeout=60)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        collected = json.loads(probe.stdout)
        self.assertFalse(collected["uat_available"])
        self.assertTrue(collected["bindings_absent"])
        self.assertEqual(collected["collapsed"], [])
        self.assertEqual(sorted(set(PACKAGING_TEST_IDS) - set(collected["ids"])), [])

    def test_packaging_tests_skip_cleanly_when_uat_is_absent(self):
        completed = self.run_packaging_tests(self.fixture)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"Ran {PACKAGING_COUNT} tests", completed.stderr)
        self.assertIn("OK (skipped=1)", completed.stderr)

    def test_packaging_tests_execute_when_uat_is_present(self):
        stage_fake_uat_checkout(self.fixture)
        completed = self.run_packaging_tests(self.fixture)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"Ran {PACKAGING_COUNT} tests", completed.stderr)
        self.assertIn("\nOK\n", completed.stderr)
        self.assertNotIn("_FailedTest", completed.stderr)


if __name__ == "__main__":
    unittest.main()
