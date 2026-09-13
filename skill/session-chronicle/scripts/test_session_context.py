import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import _checkpoint as store
from _session_notes import preferred_paths
import test_memory_contracts


spec = importlib.util.spec_from_file_location("session_context", Path(__file__).with_name("session-context.py"))
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class SessionContextTests(unittest.TestCase):
    setUp = test_memory_contracts.MemoryContractTests.setUp
    run_script = test_memory_contracts.MemoryContractTests.run_script
    capture = test_memory_contracts.MemoryContractTests.capture
    summary = test_memory_contracts.MemoryContractTests.summary
    def resolve(self, identity="session-one"):
        result = self.run_script("session-context.py", {"project_root": str(self.project), "session_id": identity})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def capture_session(self, identity="session-one"):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Octopus migration", "sessionID": identity})

    def write_summary(self, state, identity="session-one"):
        path = self.project / state["target"]
        path.write_text(self.summary("record-kind: semantic-summary\nsession-id: " + json.dumps(identity)
                                    + "\nsources: " + json.dumps(state["sources"]) + "\n")
                        .replace("id: summary\n", "id: " + path.stem + "\n")
                        .replace("Verified conversation.", "Octopus verified semantic prose."))
        return path

    def assert_failure(self, identity="session-one"):
        result = self.run_script("session-context.py", {"project_root": str(self.project), "session_id": identity})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("message", json.loads(result.stdout)["error"])

    def test_same_title_sessions_and_repeated_resolve(self):
        self.capture_session()
        self.capture_session("session-two")
        first, second = self.resolve(), self.resolve("session-two")
        self.assertNotEqual(first["target"], second["target"])
        self.assertNotEqual(first["presentation"], second["presentation"])
        self.assertEqual(first, self.resolve())
        self.assertIsNone(first["semantic_summary"])
        self.assertFalse((self.project / first["target"]).exists())

    def test_cross_midnight_preserves_existing_target_and_prose(self):
        self.capture_session()
        first = self.resolve()
        summary = self.write_summary(first)
        renamed = summary
        original = renamed.read_bytes()
        evidence = {path: path.read_bytes() for path in self.sessions.glob("*--evidence-*.md")}
        draft = self.base / ".drafts" / "2030-01-01.draft.jsonl"
        draft.write_text(json.dumps({"kind": "prompt", "text": "Later", "session_id": "session-one"}) + "\n")
        second = self.resolve()
        self.assertEqual(second["target"], renamed.relative_to(self.project).as_posix())
        self.assertEqual(second["semantic_summary"], second["target"])
        self.assertEqual(second["presentation"], first["presentation"])
        self.assertEqual(len(second["sources"]), 2)
        self.assertEqual(renamed.read_bytes(), original)
        self.assertEqual(evidence, {path: path.read_bytes() for path in evidence})

    def test_invalid_identity_does_not_checkpoint(self):
        self.capture_session()
        drafts = {path: path.read_bytes() for path in (self.base / ".drafts").glob("*.jsonl")}
        for identity in (None, "", "   ", 17):
            self.assert_failure(identity)
        self.assertEqual(drafts, {path: path.read_bytes() for path in drafts})
        self.assertEqual(list(self.sessions.glob("*.md")), [])

    def test_foreign_sources_and_wrong_identity_are_not_adopted(self):
        self.capture_session()
        own = self.resolve()
        self.capture_session("foreign")
        foreign = self.resolve("foreign")
        self.assertEqual(len(own["sources"]), 1)
        self.assertNotEqual(own["sources"], foreign["sources"])
        summary = self.write_summary({**own, "sources": own["sources"] + foreign["sources"]})
        self.assert_failure()
        summary.unlink()
        self.write_summary(own, "foreign")
        self.assert_failure()

    def test_duplicate_closed_and_missing_identity_fail_without_mutation(self):
        self.capture_session()
        state = self.resolve()
        summary = self.write_summary(state)
        original = summary.read_text()
        duplicate = summary.with_name("duplicate.md")
        duplicate.write_text(original)
        self.assert_failure()
        duplicate.unlink()
        for text in (original.replace("status: open", "status: closed"),
                     original.replace('session-id: "session-one"\n', "")):
            summary.write_text(text)
            snapshot = {path: path.read_bytes() for path in self.sessions.glob("*.md")}
            self.assert_failure()
            self.assertEqual(snapshot, {path: path.read_bytes() for path in snapshot})

    def test_failed_checkpoint_returns_error_and_preserves_summary_and_evidence(self):
        self.capture_session()
        summary = self.write_summary(self.resolve())
        snapshot = {path: path.read_bytes() for path in self.sessions.glob("*.md")}
        (self.base / ".drafts" / "2030-01-01.draft.jsonl").write_text('{"kind":')
        self.assert_failure()
        self.assertEqual(snapshot, {path: path.read_bytes() for path in snapshot})
        with patch.object(context, "checkpoint", side_effect=OSError("checkpoint unavailable")):
            with self.assertRaisesRegex(OSError, "checkpoint unavailable"):
                context.resolve_context({"project_root": str(self.project), "session_id": "session-one"})

    def test_lint_blocks_identity_change_and_foreign_sources_before_write(self):
        self.capture_session()
        state = self.resolve()
        summary = self.write_summary(state)
        for old, new in (("session-one", "foreign"), ("record-kind: semantic-summary", "record-kind: ")):
            result = self.run_script("note-lint.py", {"hook_event_name": "PreToolUse", "tool_name": "Edit", "sessionID": "session-one",
                "tool_input": {"file_path": str(summary), "old_string": old, "new_string": new}})
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_retrieval_and_index_dedupe_before_budget_and_fallback(self):
        self.capture_session()
        state = self.resolve()
        summary = self.write_summary(state)
        result = self.run_script("retrieve-inject.py", {"prompt": "octopus"}, {"MEMORY_INJECT_MAX_SCAN": "1"})
        self.assertIn("verified semantic prose", result.stdout)
        self.assertNotIn("Derived, bounded", result.stdout)
        paths = list(self.sessions.glob("*.md"))
        self.assertEqual(preferred_paths(paths, self.base), [summary])
        summary.write_text(summary.read_text().replace("session-one", "wrong"))
        fallback = preferred_paths(paths, self.base)
        self.assertEqual(fallback, [self.project / state["presentation"]])
        evidence = preferred_paths(paths, self.base, include_evidence=True)
        self.assertEqual(len(evidence), 2)

    def test_shell_index_prefers_summary_and_duplicate_summaries_fall_back(self):
        self.capture_session()
        state = self.resolve()
        summary = self.write_summary(state)
        for index in range(7):
            (self.sessions / f"2020-01-0{index + 1}--legacy.md").write_text(self.summary())
        command = ["bash", str(Path(__file__).with_name("topic-index.sh"))]
        result = subprocess.run(command, capture_output=True, text=True,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=10)
        entries = [line for line in result.stdout.splitlines() if line.startswith("- ")]
        self.assertEqual(len(entries), 8)
        self.assertIn(summary.stem, result.stdout)
        self.assertNotIn(Path(state["presentation"]).stem, result.stdout)
        summary.with_name("duplicate.md").write_bytes(summary.read_bytes())
        result = subprocess.run(command, capture_output=True, text=True,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=10)
        self.assertNotIn(summary.stem, result.stdout)
        self.assertIn(Path(state["presentation"]).stem, result.stdout)

    def test_empty_session_has_stable_uncreated_target(self):
        state = self.resolve()
        self.assertEqual(state["sources"], [])
        self.assertIsNone(state["presentation"])
        self.assertEqual(state, self.resolve())

    def test_json_escaped_sdk_identity_round_trips(self):
        identity = 'session/"quoted"\\unicode-λ'
        self.capture_session(identity)
        state = self.resolve(identity)
        self.write_summary(state, identity)
        self.assertEqual(self.resolve(identity)["semantic_summary"], state["target"])

    def test_malformed_persisted_evidence_fails_without_changes(self):
        self.capture_session()
        state = self.resolve()
        source = self.sessions / (state["sources"][0] + ".md")
        source.write_text(source.read_text().replace('"kind": "prompt"', '"kind": null'))
        original = source.read_bytes()
        self.assert_failure()
        self.assertEqual(source.read_bytes(), original)
