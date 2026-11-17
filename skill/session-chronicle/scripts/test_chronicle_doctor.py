import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import _session_notes
from _topic_graph import read_frontmatter


SCRIPTS = Path(__file__).parent
DOCTOR = SCRIPTS / "chronicle-doctor.py"
# The partition the doctor must consume, never re-implement (FR-37, EC-37).
PARTITION_NAMES = {"preferred_paths", "active_topic"}
# A hand-rolled copy of retrieval's eligibility partition: same candidate list, no shared API.
DUPLICATED_SELECTION = '''
from _session_notes import preferred_paths
from _topic_graph import active_topic, parse_fields, read_frontmatter


def retrieval_window(project, base):
    eligible = preferred_paths(files, base, False)
    return [path for path in eligible if active_topic(parse_fields(read_frontmatter(path)))]
'''


def referenced_names(source):
    """Every name a module reads or imports."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def called_names(source):
    """Every plain function name a module calls."""
    return {node.func.id for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def load_doctor():
    specification = importlib.util.spec_from_file_location("chronicle_doctor", DOCTOR)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def glob_notes(base):
    """The candidate corpus the doctor sees: sessions + topics, each note once."""
    return sorted(str(path) for path in list((base / "sessions").glob("*.md"))
                  + list((base / "topics").glob("*.md")))


class ChronicleDoctorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.base = self.project / "docs"
        (self.base / "sessions").mkdir(parents=True)
        (self.base / "topics").mkdir()
        (self.project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n")

    def install(self, version="0.2.1", loaded=True):
        module = self.project / ".opencode" / "session-chronicle"
        module.mkdir(parents=True)
        (module / "package.json").write_text(json.dumps({"version": version}))
        (module / ".session-chronicle-install.json").write_text("{}")
        if loaded:
            plugins = self.project / ".opencode" / "plugins"
            plugins.mkdir(parents=True)
            (plugins / "session-chronicle.ts").write_text('export {default} from "../session-chronicle/index.ts"')

    def doctor(self, *extra):
        return subprocess.run(
            ["python3", str(Path(__file__).with_name("chronicle-doctor.py")),
             "--project", str(self.project), "--json", *extra],
            text=True, capture_output=True, timeout=20)

    def report(self, *extra):
        result = self.doctor(*extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_loaded_empty_project_is_healthy(self):
        self.install()
        report = self.report()
        self.assertEqual(report["verdict"], "healthy")
        self.assertTrue(report["install"]["loaded"])
        self.assertEqual(report["sessions"]["total"], 0)
        self.assertTrue(any("no memory captured" in note for note in report["notes"]))

    def test_missing_plugin_entry_is_reported_as_not_loaded(self):
        self.install(loaded=False)
        report = self.report()
        self.assertEqual(report["verdict"], "not loaded")
        self.assertEqual(report["code"], 2)
        self.assertTrue(any("captures nothing" in problem for problem in report["problems"]))

    def test_stale_module_version_is_visible(self):
        self.install(version="0.1.0", loaded=False)
        report = self.report()
        self.assertEqual(report["install"]["module_version"], "0.1.0")

    def test_invalid_docs_root_is_reported_without_crashing(self):
        (self.project / "AGENTS.md").write_text("---\ndocs-root: ../escape\n---\n")
        report = self.report()
        self.assertEqual(report["verdict"], "invalid docs-root")
        self.assertEqual(report["code"], 3)
        self.assertTrue(any("invalid docs-root" in problem for problem in report["problems"]))

    def test_counts_records_and_reports_missing_summaries(self):
        self.install()
        (self.base / "sessions" / "evidence.md").write_text(
            "---\ntype: session\nrecord-kind: factual-evidence\n---\nObserved input.")
        (self.base / "sessions" / "presentation.md").write_text(
            "---\ntype: session\nrecord-kind: session-presentation\n---\nObserved activity.")
        (self.base / "topics" / "octopus.md").write_text(
            "---\ntype: topic\ntitle: Octopus\nnote-kind: atomic\n---\nOctopus knowledge.")
        report = self.report("--no-audit")
        self.assertEqual(report["sessions"]["by_kind"]["factual-evidence"], 1)
        self.assertEqual(report["sessions"]["by_kind"]["session-presentation"], 1)
        self.assertEqual(report["topics"]["by_kind"]["atomic"], 1)
        self.assertEqual(report["retrieval"]["topics_out_of_window"], 0)
        self.assertTrue(any("no semantic summaries" in warning for warning in report["warnings"]))

    def test_unreadable_note_is_counted_not_dropped(self):
        self.install()
        (self.base / "sessions" / "broken.md").write_bytes(b"\xff\xfe not utf-8")
        report = self.report("--no-audit")
        self.assertEqual(report["sessions"]["unreadable"], 1)

    def test_strict_mode_exits_non_zero_for_degraded_state(self):
        self.install()
        (self.base / "topics" / "legacy.md").write_text("---\ntype: topic\ntitle: Legacy\n---\nOld idea.")
        result = subprocess.run(
            ["python3", str(Path(__file__).with_name("chronicle-doctor.py")),
             "--project", str(self.project), "--strict", "--no-audit"],
            text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn("DEGRADED", result.stdout)

    def test_retrieval_window_reports_the_shared_candidate_list(self):
        self.install()
        (self.base / "sessions" / "plain.md").write_text(
            "---\ntype: session\ntitle: Plain\nstatus: open\n---\nProse.")
        (self.base / "sessions" / "evidence.md").write_text(
            "---\ntype: session\nrecord-kind: factual-evidence\n---\nRaw evidence.")
        (self.base / "sessions" / "summary.md").write_text(
            "---\ntype: session\nrecord-kind: semantic-summary\nsession-id: one\n---\nProse.")
        (self.base / "topics" / "active.md").write_text(
            "---\ntype: topic\ntitle: Active\nnote-kind: atomic\nstatus: active\n---\nProse.")
        (self.base / "topics" / "retired.md").write_text(
            "---\ntype: topic\ntitle: Retired\nnote-kind: atomic\nstatus: superseded\n---\nProse.")
        (self.base / "topics" / "redirect.md").write_text(
            "---\ntype: topic\ntitle: Old\nnote-kind: redirect\nstatus: merged\n---\nProse.")
        headers = [(str(path), read_frontmatter(path))
                   for path in glob_notes(self.base)]
        expected = _session_notes.select_candidates(headers, str(self.base))["eligible"]
        expected_topics = [path for path in expected if "/topics/" in path]

        doctor = load_doctor()
        with patch.object(doctor, "select_candidates",
                          wraps=_session_notes.select_candidates) as selector:
            window = doctor.retrieval_window(self.project, str(self.base))
        self.assertEqual(selector.call_count, 1)
        self.assertEqual(window["topics"], len(expected_topics))
        self.assertEqual(window["eligible_sessions"], len(expected) - len(expected_topics))
        self.assertEqual(window["topics"], 1)        # retired and redirect topics excluded
        self.assertEqual(window["eligible_sessions"], 2)  # factual evidence excluded

    def test_retrieval_window_consumes_the_shared_selector_structurally(self):
        source = DOCTOR.read_text(encoding="utf-8")
        references, calls = referenced_names(source), called_names(source)
        self.assertIn("select_candidates", references)
        self.assertIn("select_candidates", calls)
        self.assertEqual(references & PARTITION_NAMES, set(),
                         "the doctor must not re-implement retrieval's eligibility partition")
        self.assertIs(load_doctor().select_candidates, _session_notes.select_candidates)
        # The assertion is not vacuous: a duplicated implementation fails it even though its
        # candidate list would match the doctor's behaviourally (OQ-30).
        duplicated = DUPLICATED_SELECTION
        self.assertTrue(referenced_names(duplicated) & PARTITION_NAMES)
        self.assertNotIn("select_candidates", called_names(duplicated))


if __name__ == "__main__":
    unittest.main()
