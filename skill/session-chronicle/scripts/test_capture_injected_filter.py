"""Injected memory markers are stripped in both prompt writers through one predicate."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _capture
import _memory_markers as markers
import _portable as core

SCRIPTS = Path(__file__).resolve().parent
GENUINE = "Refactor the parser"
RETRIEVAL_BLOCK = (
    markers.RETRIEVAL_HEADING + "\n"
    "_Relevant prior sessions/topics. Use memory_recall / memory-recall.sh <slug> for graph-aware "
    "topic links, alias/redirect resolution and supporting source sessions._\n\n"
    "### [session] Octopus architecture (2026-10-15--session-octopus)\n"
    "Octopus architecture is a user-stated observation.\n"
)
UNTRUSTED_WRAPPER = (
    markers.UNTRUSTED_START
    + "### [session] Octopus architecture (2026-10-15--session-octopus)\n"
    "Octopus architecture is a user-stated observation."
    + markers.UNTRUSTED_END
)
INDEX_BLOCK = (
    markers.INDEX_HEADING + "\n"
    "### [session] Octopus architecture (2026-10-15--session-octopus)\n"
    "Octopus architecture is a user-stated observation.\n"
)
MARKER_ONLY = (RETRIEVAL_BLOCK, UNTRUSTED_WRAPPER, INDEX_BLOCK)
SKIPPED = {"status": "skipped", "reason": "capture_policy"}
# Every module that renders or cuts the envelope must consume the one leaf constant set.
MARKER_CONSUMERS = ("_capture.py", "capture-signals.py", "_portable.py", "retrieve-inject.py")


def load_hook():
    specification = importlib.util.spec_from_file_location("capture_signals", SCRIPTS / "capture-signals.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.base = self.project / "docs"
        (self.project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n")
        self.hook = load_hook()

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def records(self):
        return [json.loads(line) for draft in sorted((self.base / ".drafts").glob("*.draft.jsonl"))
                for line in draft.read_text(encoding="utf-8").splitlines() if line.strip()]

    def capture(self, text, event_id="event-1"):
        envelope = {"schema_version": 1, "operation": "capture",
                    "context": {"harness": "opencode", "session_id": "filter-session",
                                "workspace": str(self.project), "role": "primary"},
                    "arguments": {"operation": "prompt.submit", "event_id": event_id, "text": text,
                                  "status": "completed", "origin": "user"}}
        return core.response(envelope)

    def select(self, text):
        return _capture.select_signal({"operation": "prompt.submit", "text": text},
                                      str(self.project), str(self.base))

    def hook_prompt(self, text):
        return self.hook.build_signal({"hook_event_name": "UserPromptSubmit", "prompt": text})


class PromptWriterTests(Fixture):
    def test_retrieval_block_is_cut_from_genuine_prompt_text(self):
        self.assertEqual(self.select(GENUINE + "\n\n" + RETRIEVAL_BLOCK),
                         {"kind": "prompt", "text": GENUINE})

    def test_marker_only_prompts_are_skipped_by_the_capture_entry_point(self):
        baseline = self.snapshot()
        for index, text in enumerate(MARKER_ONLY):
            with self.subTest(marker=index):
                self.assertEqual(self.capture(text, f"marker-{index}"),
                                 {"ok": True, "result": SKIPPED})
        self.assertEqual(self.records(), [])
        self.assertEqual(self.snapshot(), baseline)

    def test_skip_carries_no_text_digest_or_dedup_key_and_writes_nothing(self):
        baseline = self.snapshot()
        reply = self.capture(RETRIEVAL_BLOCK)
        result = reply["result"]
        self.assertEqual(set(result), {"status", "reason"})
        for key in ("text", "cmd", "path", "_h", "digest", "hash", "signal"):
            self.assertNotIn(key, result)
        self.assertEqual(self.snapshot(), baseline)
        self.assertFalse(any(b'"_h"' in data for data in self.snapshot().values()))

    def test_secret_before_the_marker_is_redacted_exactly_once(self):
        secret = "sk-" + "a" * 24
        text = f"rotate the {secret} key\n\n" + RETRIEVAL_BLOCK
        self.assertEqual(self.select(text), {"kind": "prompt", "text": "rotate the [REDACTED-API-KEY] key"})
        self.assertEqual(self.capture(text)["result"]["status"], "captured")
        persisted = self.records()[0]["text"]
        self.assertEqual(persisted, "rotate the [REDACTED-API-KEY] key")
        self.assertEqual(persisted.count("[REDACTED"), 1)
        self.assertNotIn("[REDACTED][REDACTED]", persisted)

    def test_whitespace_before_the_marker_is_empty(self):
        self.assertIsNone(self.select("\n\n" + RETRIEVAL_BLOCK))
        self.assertEqual(self.capture("\n\n" + RETRIEVAL_BLOCK)["result"], SKIPPED)
        self.assertEqual(self.records(), [])

    def test_hook_writer_yields_the_same_text_as_the_core_writer(self):
        secret = "sk-" + "a" * 24
        inputs = (GENUINE + "\n\n" + RETRIEVAL_BLOCK, "\n\n" + RETRIEVAL_BLOCK,
                  f"{GENUINE} {secret}\n\n" + UNTRUSTED_WRAPPER, INDEX_BLOCK, GENUINE * 4)
        for text in inputs:
            with self.subTest(prompt=text[:20]):
                self.assertEqual(self.hook_prompt(text), self.select(text))

    def test_hook_writer_cli_drops_a_marker_only_prompt_without_writing(self):
        baseline = self.snapshot()
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "capture-signals.py")],
                                input=json.dumps({"hook_event_name": "UserPromptSubmit",
                                                  "prompt": RETRIEVAL_BLOCK,
                                                  "sessionID": "filter-session", "eventID": "marker"}),
                                text=True, capture_output=True,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.snapshot(), baseline)
        self.assertFalse(list(self.project.rglob("*.draft.jsonl")))
        self.assertFalse(any(b'"_h"' in data for data in self.snapshot().values()))

    def test_no_marker_prompt_is_captured_in_full_and_unbounded(self):
        text = GENUINE + "-" + "x" * 5000
        self.assertEqual(self.select(text), {"kind": "prompt", "text": text})
        self.assertEqual(self.hook_prompt(text), {"kind": "prompt", "text": text})
        self.assertEqual(self.capture(text)["result"]["status"], "captured")
        self.assertEqual(self.records()[0]["text"], text)


class CommandWriterTests(Fixture):
    def test_bash_command_embedding_the_block_is_stripped_in_both_writers(self):
        command = "python3 -m pytest tests" + "\n\n" + RETRIEVAL_BLOCK
        expected = {"kind": "bash", "cmd": "python3 -m pytest tests"}
        self.assertEqual(_capture.select_signal({"operation": "process.exec", "command": command},
                                                str(self.project), str(self.base)), expected)
        self.assertEqual(self.hook.build_signal({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": command}}), expected)

    def test_marker_only_bash_command_is_dropped_in_both_writers(self):
        self.assertIsNone(_capture.select_signal({"operation": "process.exec", "command": RETRIEVAL_BLOCK},
                                                 str(self.project), str(self.base)))
        self.assertIsNone(self.hook.build_signal({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": RETRIEVAL_BLOCK}}))

    def test_maintenance_command_with_an_injected_block_is_skipped_by_both_writers(self):
        # The gate must see the stripped command: a raw one keeps the newline and is never maintenance.
        command = 'python3 -B "%s"' % (SCRIPTS / "checkpoint.py") + "\n\n" + RETRIEVAL_BLOCK
        self.assertIsNone(_capture.select_signal({"operation": "process.exec", "command": command},
                                                 str(self.project), str(self.base)))
        baseline = self.snapshot()
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "capture-signals.py")],
                                input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                                  "tool_input": {"command": command},
                                                  "cwd": str(self.project),
                                                  "sessionID": "filter-session", "eventID": "maintenance"}),
                                text=True, capture_output=True,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.snapshot(), baseline)
        self.assertFalse(list(self.project.rglob("*.draft.jsonl")))

    def test_the_doctor_helper_is_treated_as_maintenance_by_the_core_writer(self):
        command = 'python3 -B "%s"' % (SCRIPTS / "chronicle-doctor.py")
        self.assertTrue(_capture.is_maintenance_command(command, self.project))
        self.assertIsNone(_capture.select_signal({"operation": "process.exec", "command": command},
                                                 str(self.project), str(self.base)))

    def test_file_signals_stay_untouched(self):
        self.assertEqual(_capture.select_signal({"operation": "files.write", "path": "source.py"},
                                                str(self.project), str(self.base)),
                         {"kind": "file", "op": "files.write", "path": "source.py"})
        self.assertEqual(self.hook.build_signal({"hook_event_name": "PostToolUse", "tool_name": "Write",
                                                 "tool_input": {"file_path": "source.py"}}),
                         {"kind": "file", "op": "Write", "path": "source.py"})


class SharedPredicateTests(Fixture):
    def test_both_writers_import_the_leaf_predicate_and_hold_no_marker_literal(self):
        literals = (markers.PROJECT_MEMORY_PREFIX, markers.RETRIEVAL_HEADING, markers.INDEX_HEADING,
                    "<chronicle-untrusted>", "</chronicle-untrusted>")
        for name in ("_capture.py", "capture-signals.py"):
            with self.subTest(writer=name):
                source = (SCRIPTS / name).read_text(encoding="utf-8")
                self.assertIn("from _memory_markers import strip_injected", source)
        for name in MARKER_CONSUMERS:
            with self.subTest(consumer=name):
                source = (SCRIPTS / name).read_text(encoding="utf-8")
                for literal in literals:
                    self.assertNotIn(literal, source)

    def test_portable_envelope_delimiters_are_the_leaf_objects(self):
        self.assertIs(core.UNTRUSTED_START, markers.UNTRUSTED_START)
        self.assertIs(core.UNTRUSTED_END, markers.UNTRUSTED_END)


if __name__ == "__main__":
    unittest.main()
