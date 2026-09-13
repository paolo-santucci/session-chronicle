import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import _checkpoint as store
from _docsroot import resolve_base
from _session_notes import preferred_paths
import test_session_context


class WriteBoundaryTests(unittest.TestCase):
    setUp = test_session_context.SessionContextTests.setUp
    run_script = test_session_context.SessionContextTests.run_script
    capture = test_session_context.SessionContextTests.capture
    summary = test_session_context.SessionContextTests.summary
    resolve = test_session_context.SessionContextTests.resolve
    capture_session = test_session_context.SessionContextTests.capture_session
    write_summary = test_session_context.SessionContextTests.write_summary

    def prewrite(self, path, text, identity="session-one"):
        return self.run_script("note-lint.py", {"hook_event_name": "PreToolUse", "tool_name": "Write",
            "sessionID": identity, "tool_input": {"file_path": str(path), "content": text}})

    def sync(self, path):
        return subprocess.run(["python3", str(Path(__file__).with_name("sync-topics-field.py")), str(path)],
                              text=True, capture_output=True, timeout=10,
                              env={**os.environ, "PROJECT_ROOT": str(self.project)})

    def test_docsroot_rejects_absolute_traversal_and_external_symlinks_before_writes(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external)
            (self.project / "escape").symlink_to(outside, target_is_directory=True)
            for declared in ("/", str(outside), "../escape", "safe/../../escape", "escape"):
                with self.subTest(declared=declared):
                    (self.project / "AGENTS.md").write_text(f"---\ndocs-root: {declared}\n---\n")
                    with self.assertRaises(ValueError):
                        resolve_base(self.project)
                    for script, payload in (("checkpoint.py", {}), ("capture-signals.py", {
                            "hook_event_name": "UserPromptSubmit", "prompt": "must not write"})):
                        result = self.run_script(script, payload)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(list(outside.iterdir()), [])
            (self.project / "AGENTS.md").unlink()
            (self.base / ".drafts").symlink_to(outside, target_is_directory=True)
            self.assertNotEqual(self.run_script("checkpoint.py", {}).returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])

    def test_trusted_sdk_identity_and_deterministic_new_path_are_mandatory(self):
        self.capture_session()
        state = self.resolve()
        path = self.write_summary(state)
        text = path.read_text()
        path.unlink()
        for identity in (None, "", "foreign"):
            self.assertEqual(self.prewrite(path, text, identity).returncode, 2)
        self.assertEqual(self.prewrite(path, text).returncode, 0)
        arbitrary = path.with_name("arbitrary.md")
        arbitrary_text = text.replace(path.stem, arbitrary.stem)
        self.assertEqual(self.prewrite(arbitrary, arbitrary_text).returncode, 2)
        self.assertEqual(self.prewrite(path, text.replace("id: " + path.stem, "id: wrong")).returncode, 2)

    def test_existing_valid_noncanonical_summary_can_update_but_identity_cannot(self):
        self.capture_session()
        state = self.resolve()
        path = self.write_summary(state)
        old = path.with_name("2020-01-01--stable.md")
        old.write_text(path.read_text().replace(path.stem, old.stem))
        path.unlink()
        self.assertEqual(self.resolve()["target"], old.relative_to(self.project).as_posix())
        self.assertEqual(self.prewrite(old, old.read_text() + "More prose.\n").returncode, 0)
        edit = self.run_script("note-lint.py", {"hook_event_name": "PreToolUse", "tool_name": "Edit",
            "sessionID": "session-one", "tool_input": {"file_path": str(old),
            "old_string": "Octopus", "new_string": "Revised Octopus"}})
        self.assertEqual(edit.returncode, 0)
        self.assertEqual(self.prewrite(old, old.read_text().replace(old.stem, "changed")).returncode, 2)
        self.assertEqual(self.prewrite(old, old.read_text().replace("session-one", "foreign"), "foreign").returncode, 2)

    def test_agent_cannot_create_factual_evidence(self):
        self.capture_session()
        state = self.resolve()
        source = self.sessions / (state["sources"][0] + ".md")
        self.assertEqual(self.prewrite(self.sessions / "forged.md", source.read_text()).returncode, 2)
        self.assertEqual(self.prewrite(source, source.read_text()).returncode, 2)

    def test_sync_blocks_immutable_and_invalid_notes_without_mutation(self):
        self.capture_session()
        state = self.resolve()
        summary = self.write_summary(state)
        evidence = self.sessions / (state["sources"][0] + ".md")
        presentation = self.project / state["presentation"]
        closed = self.sessions / "closed.md"
        closed.write_text(self.summary().replace("status: open", "status: closed"))
        invalid = self.sessions / "invalid.md"
        invalid.write_text(summary.read_text())
        for path in (evidence, presentation, closed, invalid):
            original = path.read_bytes()
            self.assertEqual(self.sync(path).returncode, 2)
            self.assertEqual(path.read_bytes(), original)
        invalid.unlink()
        summary.write_text(summary.read_text() + "\n[[tested-topic]]\n")
        self.assertEqual(self.sync(summary).returncode, 0)
        self.assertIn("topics: [tested-topic]", summary.read_text())

    def test_sync_retains_generic_open_session_and_topic_compatibility(self):
        for kind in ("session", "topic"):
            path = self.sessions / (kind + ".md")
            path.write_text(self.summary().replace("type: session", "type: " + kind) + "\n[[topic-link]]\n")
            self.assertEqual(self.sync(path).returncode, 0)
            self.assertIn("topics: [topic-link]", path.read_text())

    def test_invalid_record_identity_prevents_all_batch_publication(self):
        pending = self.base / ".drafts" / "pending"
        pending.mkdir(parents=True)
        for index, identity in enumerate(({"sessionID": "valid"}, {"sessionID": 17},
                                           {"sessionID": "one", "session_id": "two"})):
            path = pending / f"2026-01-01--evidence-{index:032x}.jsonl"
            path.write_text(json.dumps({"kind": "prompt", "text": "captured", **identity}) + "\n")
        original = {path: path.read_bytes() for path in pending.glob("*.jsonl")}
        with self.assertRaises(ValueError):
            store.checkpoint(self.base)
        self.assertEqual(list(self.sessions.glob("*.md")), [])
        self.assertEqual(original, {path: path.read_bytes() for path in original})

    def test_presentation_collisions_never_overwrite_existing_note_or_publish_evidence(self):
        pending = self.base / ".drafts" / "pending"
        pending.mkdir(parents=True)
        batch = pending / ("2026-01-01--evidence-" + "a" * 32 + ".jsonl")
        batch.write_text(json.dumps({"kind": "prompt", "sessionID": "session-one"}) + "\n")
        target = self.sessions / ("2026-01-01--" + store.session_name("session-one") + ".md")
        for text in ("Existing prose", self.summary(), self.summary(
                "record-kind: session-presentation\nsession-id: foreign\nprovenance: captured_signals\n")):
            target.write_text(text)
            with self.assertRaisesRegex(ValueError, "collision"):
                store.checkpoint(self.base)
            self.assertEqual(target.read_text(), text)
            self.assertTrue(batch.exists())
            self.assertFalse((self.sessions / (batch.stem + ".md")).exists())

    def test_duplicate_presentations_are_omitted_by_retrieval_and_index(self):
        self.capture_session()
        state = self.resolve()
        presentation = self.project / state["presentation"]
        duplicate = presentation.with_name("duplicate.md")
        duplicate.write_text(presentation.read_text().replace(presentation.stem, duplicate.stem))
        self.assertEqual(preferred_paths(list(self.sessions.glob("*.md")), self.base), [])
        self.assertEqual(self.run_script("retrieve-inject.py", {"prompt": "octopus"}).stdout, "")
        result = subprocess.run(["bash", str(Path(__file__).with_name("topic-index.sh"))],
                                text=True, capture_output=True, timeout=10,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)})
        self.assertFalse(any(line.startswith("- ") for line in result.stdout.splitlines()))

    def test_corrupt_existing_presentation_fields_block_before_new_publication(self):
        self.capture_session()
        state = self.resolve()
        presentation = self.project / state["presentation"]
        original = presentation.read_text()
        self.capture_session()
        for old, new in (("id: " + presentation.stem, "id: wrong"),
                         ("provenance: captured_signals", "provenance: inferred"),
                         ("status: open", "status: closed")):
            presentation.write_text(original.replace(old, new))
            before = {path: path.read_bytes() for path in self.sessions.glob("*.md")}
            with self.assertRaises(ValueError):
                store.checkpoint(self.base)
            self.assertEqual(before, {path: path.read_bytes() for path in self.sessions.glob("*.md")})
            self.assertTrue(list((self.base / ".drafts" / "pending").glob("*.jsonl")))
