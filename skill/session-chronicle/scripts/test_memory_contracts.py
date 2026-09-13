import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import _checkpoint as store


class MemoryContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.base = self.project / "docs"
        self.sessions = self.base / "sessions"
        self.sessions.mkdir(parents=True)

    def run_script(self, name, payload, environment=None):
        return subprocess.run(
            ["python3", str(Path(__file__).with_name(name))], input=json.dumps(payload),
            text=True, capture_output=True,
            env={**os.environ, "PROJECT_ROOT": str(self.project),
                 "SESSION_CHRONICLE_CAPTURE_PROMPTS": "1", "SESSION_CHRONICLE_CAPTURE_BASH": "1",
                 **(environment or {})}, timeout=10)

    def capture(self, payload, environment=None):
        result = self.run_script("capture-signals.py", payload, environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def records(self):
        return [json.loads(line) for draft in (self.base / ".drafts").glob("*.draft.jsonl")
                for line in draft.read_text().splitlines()]

    def factual_batch(self):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Observed input", "sessionID": "session-one"})
        return Path(store.checkpoint(self.base)[0])

    def lint(self, text):
        path = self.sessions / "summary.md"
        path.write_text(text)
        return self.run_script("note-lint.py", {"hook_event_name": "PostToolUse", "tool_name": "Write",
                                               "tool_input": {"file_path": str(path)}})

    def summary(self, extra=""):
        return ("---\nid: summary\ntype: session\ndate: 2026-09-06\n"
                "title: Summary\nstatus: open\n" + extra + "---\n\nVerified conversation.\n")

    def test_factual_backlog_does_not_consume_automatic_retrieval_budget(self):
        topics = self.base / "topics"
        topics.mkdir()
        for path in (self.sessions / "semantic.md", topics / "topic.md"):
            kind = "topic" if path.parent == topics else "session"
            path.write_text(f"---\ntype: {kind}\ntitle: Octopus\n---\nOctopus semantic knowledge.")
            os.utime(path, (1, 1))
        for index in range(65):
            (self.sessions / f"factual-{index}.md").write_text(
                "---\ntype: session\nrecord-kind: factual-evidence\n---\nOctopus raw evidence.")
        result = self.run_script("retrieve-inject.py", {"prompt": "octopus"},
                                 {"MEMORY_INJECT_MAX_SCAN": "60", "MEMORY_INJECT_TOPK": "3"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("(semantic)", result.stdout)
        self.assertIn("(topic)", result.stdout)
        self.assertNotIn("raw evidence", result.stdout)

    def test_explicit_retrieval_can_include_factual_records(self):
        (self.sessions / "evidence.md").write_text(
            "---\ntype: session\nrecord-kind: factual-evidence\n---\nOctopus raw evidence.")
        result = self.run_script("retrieve-inject.py", {"prompt": "octopus", "include_factual": True})
        self.assertIn("raw evidence", result.stdout)
        automatic = self.run_script("retrieve-inject.py", {"prompt": "octopus"})
        self.assertEqual(automatic.stdout, "")

    def test_session_presentation_is_searchable_without_factual_retrieval(self):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Track nebula migration", "sessionID": "session-one"})
        store.checkpoint(self.base)
        result = self.run_script("retrieve-inject.py", {"prompt": "nebula migration"})
        self.assertIn("Track nebula migration", result.stdout)
        self.assertIn("session-presentation", "".join(path.read_text() for path in self.sessions.glob("*.md")))

    def test_retrieval_escapes_presentation_excerpt_markup(self):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Find `quoted` <markup> zephyr", "sessionID": "session-one"})
        store.checkpoint(self.base)
        result = self.run_script("retrieve-inject.py", {"prompt": "zephyr"})
        self.assertIn("\\u0060quoted\\u0060", result.stdout)
        self.assertIn("\\u003cmarkup\\u003e", result.stdout)
        self.assertNotIn("`quoted`", result.stdout)

    def test_startup_index_selects_latest_eight_semantic_and_legacy_sessions(self):
        for day in range(1, 11):
            kind = ""
            (self.sessions / f"2020-01-{day:02}--history.md").write_text(
                f"---\ntype: session\n{kind}title: History {day:02}\n---\n"
                "A discussion of metadata:\nrecord-kind: factual-evidence\n")
        for day in range(1, 13):
            (self.sessions / f"2026-09-{day:02}--evidence.md").write_text(
                "---\ntype: session\nrecord-kind: 'factual-evidence'\n"
                f"started: 2026-09-{day:02}T12:00:00+00:00\ntitle: Factual {day:02}\n---\nObserved inputs.\n")
        result = subprocess.run(
            ["bash", str(Path(__file__).with_name("topic-index.sh"))], text=True, capture_output=True,
            env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = [line for line in result.stdout.splitlines() if line.startswith("- ")]
        self.assertEqual(len(entries), 8)
        self.assertEqual([line.split()[1] for line in entries],
                         [f"2020-01-{day:02}--history" for day in range(10, 2, -1)])
        self.assertNotIn("Factual", result.stdout)

    def test_semantic_sources_support_inline_and_block_lists(self):
        batch = self.factual_batch()
        for sources in (f"sources: [{batch.stem}]\n", f"sources:\n  - '{batch.stem}'\n"):
            with self.subTest(sources=sources):
                result = self.lint(self.summary("record-kind: semantic-summary\nsession-id: session-one\n" + sources))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_semantic_sources_reject_missing_invalid_and_unpersisted_ids(self):
        for sources in ("", "sources: []\n", "sources: [placeholder]\n", "sources: [../escape]\n",
                        "sources: [2026-09-06--evidence-" + "a" * 32 + "]\n"):
            with self.subTest(sources=sources):
                self.assertEqual(self.lint(self.summary("record-kind: semantic-summary\n" + sources)).returncode, 2)

    def test_session_presentation_rejects_agent_edits_and_invalid_identity(self):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Observed input", "sessionID": "session-one"})
        store.checkpoint(self.base)
        presentation = next(path for path in self.sessions.glob("*.md")
                            if "record-kind: session-presentation" in path.read_text())
        prewrite = self.run_script("note-lint.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(presentation), "new_string": "edited"},
        })
        self.assertEqual(prewrite.returncode, 2)
        forged = self.run_script("note-lint.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(self.sessions / "forged.md"),
                           "content": "---\nrecord-kind: session-presentation\n---\n"},
        })
        self.assertEqual(forged.returncode, 2)
        ordinary = self.run_script("note-lint.py", {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(self.sessions / "ordinary.md"),
                           "old_string": "Summary", "new_string": "Updated"},
        })
        self.assertEqual(ordinary.returncode, 0)
        invalid = presentation.read_text().replace("provenance: captured_signals", "provenance: inferred")
        presentation.write_text(invalid)
        result = self.run_script("note-lint.py", {
            "hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(presentation)},
        })
        self.assertEqual(result.returncode, 2)

    def test_semantic_sources_reject_generic_session_masquerading_as_batch(self):
        identifier = "2026-09-06--evidence-" + "a" * 32
        (self.sessions / f"{identifier}.md").write_text(self.summary())
        result = self.lint(self.summary(f"record-kind: semantic-summary\nsources: [{identifier}]\n"))
        self.assertEqual(result.returncode, 2)

    def test_factual_schema_rejects_invalid_provenance_and_batch_identity(self):
        batch = self.factual_batch().read_text()
        mutations = {
            "provenance: captured_signals": "provenance: inferred",
            "status: closed": "status: open",
            "type: session": "type: topic",
            "batch-id:": "missing-batch-id:",
            "id:": "id: wrong-",
        }
        for old, new in mutations.items():
            with self.subTest(field=old):
                self.assertEqual(self.lint(batch.replace(old, new, 1)).returncode, 2)

    def test_legacy_and_bootstrap_generic_sessions_remain_valid(self):
        for text in (self.summary(), self.summary("commits: [abcdef1]\nplans: [docs/plans/history.md]\n")):
            self.assertEqual(self.lint(text).returncode, 0)
        self.assertEqual(self.lint(self.summary("record-kind: invented\n")).returncode, 2)

    def test_template_declares_enrichment_fields_without_fabricated_sources(self):
        template = Path(__file__).parent.parent / "references/session-note-template.md"
        text = template.read_text()
        self.assertIn("record-kind: semantic-summary\n", text)
        self.assertIn("sources: []\n", text)

    def test_only_actual_bundled_maintenance_commands_are_filtered(self):
        script = Path(__file__).with_name("checkpoint.py").resolve()
        for command in (f'python3 "{script}"', f'PROJECT_ROOT="{self.project}" python3 "{script}"'):
            self.capture({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "tool_input": {"command": command}})
        self.assertEqual(self.records(), [])
        commands = ("python3 tests/checkpoint.py", "python3 tests/capture-signals.py",
                    "python3 checkpoint.py", f'printf "%s" "{script}"', f'python3 "{script}"&&pytest')
        for command in commands:
            self.capture({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "tool_input": {"command": command}})
        self.assertEqual(len(self.records()), len(commands))

    def test_capture_opt_outs_are_independent_and_leave_file_capture_enabled(self):
        for variable, excluded in (("SESSION_CHRONICLE_CAPTURE_PROMPTS", "prompt"),
                                   ("SESSION_CHRONICLE_CAPTURE_BASH", "bash")):
            with self.subTest(variable=variable):
                environment = {variable: "0"}
                self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Private prompt"}, environment)
                self.capture({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "pytest private_test.py"}}, environment)
                self.capture({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": "source.py"}}, environment)
                self.assertEqual({record["kind"] for record in self.records()}, {"prompt", "bash", "file"} - {excluded})
                store.checkpoint(self.base)

    def test_opt_out_does_not_delete_already_captured_evidence(self):
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "Earlier evidence"})
        self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "New private input"},
                     {"SESSION_CHRONICLE_CAPTURE_PROMPTS": "false"})
        text = Path(store.checkpoint(self.base)[0]).read_text()
        self.assertIn("Earlier evidence", text)
        self.assertNotIn("New private input", text)

    def test_representative_redaction_precedes_truncation(self):
        tokens = ["ghp_" + "x" * 24, "sk-" + "x" * 24, "AKIA" + "A" * 16,
                  "xoxb-" + "x" * 20, "-----BEGIN RSA PRIVATE KEY-----", "192.0.2.42"]
        for token in tokens:
            with self.subTest(token_kind=token[:4]):
                self.capture({"hook_event_name": "UserPromptSubmit", "prompt": "a" * 290 + " " + token})
                record = self.records()[-1]
                self.assertNotIn(token[:8], record["text"])
        self.capture({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                      "tool_input": {"command": "curl 127.0.0.1 --token " + tokens[1]}})
        record = self.records()[-1]
        self.assertIn("127.0.0.1", record["cmd"])
        self.assertIn("[REDACTED-API-KEY]", record["cmd"])
        self.assertEqual(store.note_lint.secret_findings(json.dumps(self.records())), [])


if __name__ == "__main__":
    unittest.main()
