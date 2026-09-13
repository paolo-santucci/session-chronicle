import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import _checkpoint as store


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.base = self.project / "docs"

    def capture(self, **data):
        result = subprocess.run(
            ["python3", str(Path(__file__).with_name("capture-signals.py"))],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Working on tests", **data}),
            text=True, capture_output=True, env={**os.environ, "PROJECT_ROOT": str(self.project)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def notes(self):
        return sorted((self.base / "sessions").glob("*.md"))

    def test_duplicate_dispatch_is_noop(self):
        self.capture(sessionID="session-one", eventID="message-one")
        first = store.checkpoint(self.base)
        original = self.notes()[0].read_bytes()
        self.assertEqual(store.checkpoint(self.base), [])
        self.assertEqual([str(note) for note in self.notes() if "record-kind: factual-evidence" in note.read_text()], first)
        self.assertEqual(self.notes()[0].read_bytes(), original)

    def test_session_presentation_upserts_stable_identity_with_safe_fallback(self):
        self.capture(sessionID="Session / unsafe title", eventID="first")
        store.checkpoint(self.base)
        self.capture(sessionID="Session / unsafe title", eventID="second")
        store.checkpoint(self.base)
        presentations = [note for note in self.notes() if "record-kind: session-presentation" in note.read_text()]
        self.assertEqual(len(presentations), 1)
        self.assertRegex(presentations[0].name, r"^\d{4}-\d{2}-\d{2}--session-unsafe-title-[a-f0-9]{12}\.md$")
        text = presentations[0].read_text()
        self.assertIn('session-id: "Session / unsafe title"', text)
        self.assertIn('title: "Session activity: Working on tests"', text)
        self.assertEqual(text.count("--evidence-"), 2)
        self.assertIn("- Prompt: Working on tests", text)

    def test_session_presentation_retains_recent_bounded_activity(self):
        pending = self.base / ".drafts" / "pending"
        pending.mkdir(parents=True)
        for index in range(13):
            batch = pending / f"2026-01-01--evidence-{index:032x}.jsonl"
            batch.write_text(json.dumps({"kind": "prompt", "text": f"activity-{index}",
                                         "sessionID": "session-one", "ts": f"2026-01-01T00:00:{index:02d}+00:00"}) + "\n")
            store.checkpoint(self.base)
        presentation = next(note for note in self.notes() if "record-kind: session-presentation" in note.read_text())
        text = presentation.read_text()
        self.assertNotIn("activity-0", text)
        self.assertIn("activity-12", text)

    def test_session_presentation_orders_activity_by_timestamp_not_batch_name(self):
        pending = self.base / ".drafts" / "pending"
        pending.mkdir(parents=True)
        for index in range(13):
            batch = pending / f"2026-01-01--evidence-{index:032x}.jsonl"
            activity = 13 - index
            batch.write_text(json.dumps({"kind": "prompt", "text": f"activity-{activity}",
                                         "sessionID": "session-one", "ts": f"2026-01-01T00:00:{activity:02d}+00:00"}) + "\n")
        store.checkpoint(self.base)
        presentation = next(note for note in self.notes() if "record-kind: session-presentation" in note.read_text())
        text = presentation.read_text()
        self.assertNotIn("- Prompt: activity-1\n", text)
        self.assertIn("activity-13", text)

    def test_prompt_upgrades_a_file_only_fallback_title(self):
        self.capture(hook_event_name="PostToolUse", tool_name="Write", tool_input={"file_path": "source.py"},
                     sessionID="session-one")
        store.checkpoint(self.base)
        presentation = next(note for note in self.notes() if "record-kind: session-presentation" in note.read_text())
        self.assertIn('title: "Session session-one"', presentation.read_text())
        self.capture(prompt="Add searchable title", sessionID="session-one")
        store.checkpoint(self.base)
        self.assertIn('title: "Session activity: Add searchable title"', presentation.read_text())

    def test_session_presentation_does_not_adopt_ambiguous_history(self):
        self.capture(sessionID="session-one")
        identifier = "session-one"
        (self.base / "sessions").mkdir()
        for name in ("first", "second"):
            (self.base / "sessions" / f"{name}.md").write_text(
                "---\nid: " + name + "\ntype: session\nrecord-kind: session-presentation\n"
                "session-id: " + identifier + "\nstatus: open\n---\n\nExisting presentation.\n")
        with self.assertRaisesRegex(ValueError, "Ambiguous session presentation"):
            store.checkpoint(self.base)
        self.assertEqual(len(list((self.base / ".drafts/pending").glob("*.jsonl"))), 1)

    def test_distinct_sessions_with_matching_fallback_titles_remain_distinct(self):
        self.capture(sessionID="same/title")
        self.capture(sessionID="same title")
        store.checkpoint(self.base)
        presentations = [note for note in self.notes() if "record-kind: session-presentation" in note.read_text()]
        self.assertEqual(len(presentations), 2)
        self.assertEqual({note.read_text().split("title: ")[1].splitlines()[0] for note in presentations},
                         {'"Session activity: Working on tests"'})
        self.assertEqual({note.read_text().split("session-id: ")[1].splitlines()[0] for note in presentations},
                         {'"same/title"', '"same title"'})

    def test_failed_publication_recovers_stable_batch_and_new_events(self):
        self.capture(prompt="first")
        with patch.object(store, "publish", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                store.checkpoint(self.base)
        pending = next((self.base / ".drafts/pending").glob("*.jsonl"))
        self.capture(prompt="second")
        store.checkpoint(self.base)
        self.assertTrue((self.base / "sessions" / f"{pending.stem}.md").exists())
        self.assertEqual(len(self.notes()), 2)
        self.assertIn('"text": "second"', "".join(note.read_text() for note in self.notes()))

    def test_presentation_update_before_acknowledgement_recovers(self):
        self.capture(sessionID="session-one")
        update = store.update_presentation

        def fail_after_update(destination, text):
            update(destination, text)
            raise OSError("crash after presentation update")

        with patch.object(store, "update_presentation", fail_after_update):
            with self.assertRaises(OSError):
                store.checkpoint(self.base)
        pending = next((self.base / ".drafts/pending").glob("*.jsonl"))
        presentations = [note for note in self.notes() if "record-kind: session-presentation" in note.read_text()]
        self.assertEqual(len(presentations), 1)
        original = presentations[0].read_bytes()
        store.checkpoint(self.base)
        self.assertEqual(presentations[0].read_bytes(), original)
        self.assertFalse(pending.exists())

    def test_capture_preserves_full_redacted_prompt_and_command(self):
        prompt = "prompt-" + "x" * 400
        command = "command-" + "y" * 300
        self.capture(prompt=prompt)
        self.capture(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": command})
        text = "".join(draft.read_text() for draft in (self.base / ".drafts").glob("*.draft.jsonl"))
        self.assertIn(prompt, text)
        self.assertIn(command, text)

    def test_crash_after_publication_before_acknowledgement_is_idempotent(self):
        self.capture()
        unlink = Path.unlink

        def fail_acknowledgement(path, *args, **kwargs):
            if path.suffix == ".jsonl":
                raise OSError("crash before acknowledgement")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_acknowledgement):
            with self.assertRaises(OSError):
                store.checkpoint(self.base)
        original = self.notes()[0].read_bytes()
        store.checkpoint(self.base)
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(self.notes()[0].read_bytes(), original)
        self.assertEqual(list((self.base / ".drafts/pending").glob("*.jsonl")), [])

    def test_concurrent_append_is_not_acknowledged_with_previous_batch(self):
        self.capture(prompt="first")
        publish = store.publish
        with concurrent.futures.ThreadPoolExecutor() as pool:
            appended = []

            def append_during_publication(destination, text):
                appended.append(pool.submit(self.capture, prompt="appended"))
                publish(destination, text)

            with patch.object(store, "publish", append_during_publication):
                store.checkpoint(self.base)
            appended[0].result(timeout=10)
        self.assertEqual(len(self.notes()), 1)
        self.assertIn("appended", next((self.base / ".drafts").glob("*.draft.jsonl")).read_text())
        store.checkpoint(self.base)
        self.assertEqual(len(self.notes()), 2)

    def test_multiple_processes_share_one_writer(self):
        self.capture()
        command = ["python3", str(Path(__file__).with_name("checkpoint.py"))]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env={**os.environ, "PROJECT_ROOT": str(self.project)}) for _ in range(4)]
        for process in processes:
            _, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error)
        self.assertEqual(len(self.notes()), 1)

    def test_self_events_are_filtered(self):
        for folder in ("sessions", "topics", ".drafts"):
            self.capture(hook_event_name="PostToolUse", tool_name="Write",
                         tool_input={"file_path": f"docs/{folder}/note.md"})
        self.capture(prompt="/session-chronicle")
        self.capture(hook_event_name="PostToolUse", tool_name="Bash",
                     tool_input={"command": f"python3 {Path(__file__).with_name('checkpoint.py')}"})
        self.assertFalse(self.base.exists())

    def test_legacy_evidence_survives_age_and_is_redacted_and_validated(self):
        drafts = self.base / ".drafts"
        drafts.mkdir(parents=True)
        legacy = drafts / "2000-01-01.draft.jsonl"
        legacy.write_text(json.dumps({"kind": "bash", "cmd": "sk-" + "x" * 25}) + "\n")
        self.capture(prompt="``` [[injected-topic]] <instruction>")
        store.checkpoint(self.base)
        self.assertEqual(len(self.notes()), 2)
        for note in self.notes():
            text = note.read_text()
            self.assertIn("record-kind: factual-evidence", text)
            self.assertIn("commits: []", text)
            self.assertEqual(store.note_lint.secret_findings(text), [])
            self.assertNotIn("[[injected-topic]]", text)
            json.loads(text.split("```json\n")[1].split("\n```")[0])
            result = subprocess.run(["python3", str(Path(__file__).with_name("note-lint.py"))],
                                    input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write",
                                                      "tool_input": {"file_path": str(note)}}),
                                    text=True, capture_output=True,
                                    env={**os.environ, "PROJECT_ROOT": str(self.project)})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_evidence_is_retained_without_publication(self):
        drafts = self.base / ".drafts"
        drafts.mkdir(parents=True)
        (drafts / "2026-09-06.draft.jsonl").write_text('{"kind":')
        with self.assertRaises(ValueError):
            store.checkpoint(self.base)
        self.assertEqual(len(list((drafts / "pending").glob("*.jsonl"))), 1)
        self.assertEqual(self.notes(), [])

    def test_conflicting_publication_preserves_history_and_pending_evidence(self):
        self.capture()
        with patch.object(store, "publish", side_effect=OSError("publication failed")):
            with self.assertRaises(OSError):
                store.checkpoint(self.base)
        pending = next((self.base / ".drafts/pending").glob("*.jsonl"))
        destination = self.base / "sessions" / f"{pending.stem}.md"
        destination.write_text("Existing immutable history")
        with self.assertRaisesRegex(ValueError, "publication conflict"):
            store.checkpoint(self.base)
        self.assertEqual(destination.read_text(), "Existing immutable history")
        self.assertTrue(pending.exists())

    def test_failed_publication_directory_sync_does_not_acknowledge(self):
        self.capture()
        sync_directory = store.sync_directory

        def fail_published_directory_sync(path):
            if path == self.base / "sessions" and self.notes():
                raise OSError("directory sync failed")
            sync_directory(path)

        with patch.object(store, "sync_directory", fail_published_directory_sync):
            with self.assertRaises(OSError):
                store.checkpoint(self.base)
        self.assertEqual(len(list((self.base / ".drafts/pending").glob("*.jsonl"))), 1)
        store.checkpoint(self.base)
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(list((self.base / ".drafts/pending").glob("*.jsonl")), [])

    def test_process_exit_releases_lock_and_recovers_published_batch(self):
        self.capture()
        script = ("import os; from pathlib import Path; import _checkpoint as store; "
                  "publish = store.publish; "
                  "store.publish = lambda path, text: (publish(path, text), os._exit(17)); "
                  "store.checkpoint(Path(os.environ['PROJECT_ROOT']) / 'docs')")
        result = subprocess.run(["python3", "-c", script],
                                cwd=Path(__file__).parent,
                                env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=10)
        self.assertEqual(result.returncode, 17)
        store.checkpoint(self.base)
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(list((self.base / ".drafts/pending").glob("*.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
