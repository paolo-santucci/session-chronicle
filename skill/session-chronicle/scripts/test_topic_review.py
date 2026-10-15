import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import _session_notes
from _topic_graph import TopicGraph
import test_topic_graph as fixtures
from test_topic_patch import load_script


class TopicReviewTests(unittest.TestCase):
    setUp = fixtures.TopicGraphTests.setUp
    topic_text = fixtures.TopicGraphTests.topic_text
    topic = fixtures.TopicGraphTests.topic
    session = fixtures.TopicGraphTests.session
    run_cli = fixtures.TopicGraphTests.run_cli
    lint = fixtures.TopicGraphTests.lint

    def test_unrelated_quality_errors_do_not_disable_healthy_resolution(self):
        self.topic("healthy", aliases=["healthy-alias"])
        self.topic("broken", created="not-a-date", sources=["missing.md"], links=["absent"], body="")
        self.session("discussion-file", "We selected [[healthy-alias]].", "sdk-session-identity")
        commands = [("memory-recall.sh", "healthy-alias"),
                    ("backlinks.py", "healthy-alias", "--base", self.base, "--json"),
                    ("slugify.py", "--resolve", "healthy-alias", "--base", self.base)]
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("healthy", result.stdout)
        backlinks = json.loads(self.run_cli(*commands[1]).stdout)
        self.assertEqual(backlinks["sessions"], ["discussion-file"])
        self.assertEqual(backlinks["count"], 1)
        self.assertNotIn("sdk-session-identity", backlinks["sessions"])
        validation = self.run_cli("topic-maintenance.py", "validate", "--project", self.project)
        self.assertEqual(validation.returncode, 1)
        self.assertIn("invalid-created", validation.stdout)
        self.assertIn("invalid-source", validation.stdout)

    def test_unreadable_session_header_does_not_disable_healthy_resolution(self):
        self.topic("healthy", aliases=["healthy-alias"])
        self.session("discussion-file", "We selected [[healthy-alias]].")
        (self.sessions / "broken.md").write_bytes(b"---\ntitle: \xff\n---\n")
        commands = [("memory-recall.sh", "healthy-alias"),
                    ("backlinks.py", "healthy-alias", "--base", self.base, "--json"),
                    ("slugify.py", "--resolve", "healthy-alias", "--base", self.base)]
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("healthy", result.stdout)
        self.assertEqual(json.loads(self.run_cli(*commands[1]).stdout)["sessions"], ["discussion-file"])
        for command in (("topic-maintenance.py", "inventory", "--project", self.project),
                        ("memory-audit.py", "--quality", "--base", self.base, "--json")):
            self.assertIn("unreadable-session", self.run_cli(*command).stdout)

    def test_unreadable_topic_still_blocks_resolution(self):
        self.topic("healthy")
        (self.topics / "broken.md").write_bytes(b"---\ntitle: \xff\n---\n")
        result = self.run_cli("memory-recall.sh", "healthy")
        self.assertNotEqual(result.returncode, 0)
        graph = TopicGraph(self.base, self.project)
        self.assertIn("unreadable-topic", {item["code"] for item in graph.quality()})

    def test_resolution_critical_collisions_remain_errors(self):
        self.topic("one", aliases=["collision"])
        self.topic("two", aliases=["collision"])
        for command in (("memory-recall.sh", "collision"),
                        ("backlinks.py", "collision", "--base", self.base),
                        ("slugify.py", "--resolve", "collision", "--base", self.base)):
            self.assertNotEqual(self.run_cli(*command).returncode, 0)

    def test_typed_topics_require_explicit_status_but_legacy_remains_readable(self):
        path = self.topics / "claim.md"
        missing = self.topic_text("claim").replace('status: "active"\n', "")
        result = self.lint(path, missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing-status", result.stderr)
        legacy = missing.replace('note-kind: "atomic"\n', "")
        self.assertEqual(self.lint(path, legacy).returncode, 0)
        path.write_text(legacy)
        result = self.run_cli("memory-recall.sh", "claim")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_atomic_and_structure_status_must_be_active(self):
        for kind in ("atomic", "structure"):
            for status in ("merged", "superseded", "closed", "", None):
                with self.subTest(kind=kind, status=status):
                    text = self.topic_text("claim", kind=kind, status=status)
                    result = self.lint(self.topics / "claim.md", text)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("invalid-status", result.stderr)
            self.assertEqual(self.lint(self.topics / "claim.md", self.topic_text("claim", kind=kind)).returncode, 0)

    def test_redirect_requires_explicit_merged_or_superseded_status(self):
        self.topic("target")
        for status in ("active", "merged", "superseded"):
            text = self.topic_text("old", kind="redirect", status=status, **{"redirects-to": "target"},
                                   links=["target"], body="Merged into [[target]] for the same claim.")
            result = self.lint(self.topics / "old.md", text)
            self.assertEqual(result.returncode, 2 if status == "active" else 0, result.stderr)

    def test_optional_tags_and_supersedes_validate_list_shape_slugs_and_duplicates(self):
        for field in ("tags", "supersedes"):
            for value in ("not-a-list", [17], ["Bad Slug"], ["../outside"], ["repeat", "repeat"]):
                with self.subTest(field=field, value=value):
                    result = self.lint(self.topics / "claim.md", self.topic_text("claim", **{field: value}))
                    self.assertEqual(result.returncode, 2)
                    self.assertRegex(result.stderr, rf"(?:invalid|duplicate)-{field}")
            result = self.lint(self.topics / "claim.md", self.topic_text("claim", **{field: ["valid-slug"]}))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_ordinary_reads_skip_unused_factual_bodies_but_inventory_reports_them(self):
        self.topic("healthy")
        self.session("discussion-file", "We selected [[healthy]].", "sdk-session")
        evidence = self.sessions / "unused.md"
        evidence.write_bytes(b"---\ntype: session\nrecord-kind: factual-evidence\n---\n" + b"\xff" * 2_000_000)
        commands = [("memory-recall.sh", "healthy"),
                    ("backlinks.py", "healthy", "--base", self.base, "--json"),
                    ("slugify.py", "--resolve", "healthy", "--base", self.base),
                    ("memory-audit.py", "--base", self.base, "--json")]
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["unreadable"][0]["path"], "docs/sessions/unused.md")


class FactualValidationCacheTests(unittest.TestCase):
    setUp = fixtures.TopicGraphTests.setUp

    def factual_source(self, identities=("session-one", "session-two")):
        identifier = "2026-10-10--evidence-" + "a" * 32
        path = self.sessions / (identifier + ".md")
        records = [{"kind": "prompt", "sessionID": identity, "text": "Evidence."} for identity in identities]
        path.write_text(f"---\nid: {identifier}\nbatch-id: {identifier}\ntype: session\n"
                        "record-kind: factual-evidence\ndate: 2026-10-10\nstatus: closed\n"
                        "provenance: captured_signals\n---\n```json\n" + json.dumps(records) + "\n```\n")
        return path

    def summary(self, slug, identity, source, kind="semantic-summary"):
        path = self.sessions / (slug + ".md")
        path.write_text(f"---\nid: {slug}\ntype: session\nrecord-kind: {kind}\nsession-id: {identity}\n"
                        f"sources: [{source.stem}]\ndate: 2026-10-10\ntitle: Summary\nstatus: open\n"
                        "provenance: captured_signals\n---\nReviewed discussion.\n")
        return path

    def test_shared_batch_read_and_parsed_once_with_exact_identity_membership(self):
        source = self.factual_source()
        first = self.summary("first-file", "session-one", source)
        second = self.summary("second-file", "session-two", source)
        foreign = self.summary("foreign-file", "session-foreign", source)
        lint = _session_notes.note_lint
        with patch.object(lint, "read", wraps=lint.read) as reads, \
                patch.object(lint, "factual_records", wraps=lint.factual_records) as parses:
            selected = _session_notes.preferred_paths([source, first, second, foreign], self.base)
        self.assertEqual(selected, [first, second])
        self.assertEqual([Path(call.args[0]) for call in reads.call_args_list], [source])
        self.assertEqual(parses.call_count, 1)

    def test_invalid_batch_result_is_shared_across_summary_and_presentation_checks(self):
        source = self.factual_source()
        source.write_text(source.read_text().replace('"kind": "prompt"', '"kind": "unsupported"'))
        summary = self.summary("summary", "session-one", source)
        presentation = self.summary("presentation", "session-one", source, "session-presentation")
        lint = _session_notes.note_lint
        with patch.object(lint, "read", wraps=lint.read) as reads, \
                patch.object(lint, "factual_records", wraps=lint.factual_records) as parses:
            selected = _session_notes.preferred_paths([source, summary, presentation], self.base)
        self.assertEqual(selected, [])
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(parses.call_count, 1)

    def test_cache_is_fresh_on_every_selection_call(self):
        source = self.factual_source()
        summary = self.summary("summary", "session-one", source)
        self.assertEqual(_session_notes.preferred_paths([summary], self.base), [summary])
        source.write_text(source.read_text().replace("session-one", "session-foreign"))
        self.assertEqual(_session_notes.preferred_paths([summary], self.base), [])
        self.factual_source()
        self.assertEqual(_session_notes.preferred_paths([summary], self.base), [summary])
        source.write_text(source.read_text().replace("status: closed", "status: open"))
        self.assertEqual(_session_notes.preferred_paths([summary], self.base), [])

    def test_index_reuses_selected_views_for_health_and_recent_sessions(self):
        source = self.factual_source()
        self.summary("first-file", "session-one", source)
        self.summary("second-file", "session-two", source)
        graph = TopicGraph(self.base, self.project, include_evidence=False)
        reader = load_script("_memory_read.py")
        lint = _session_notes.note_lint
        with patch.object(lint, "read", wraps=lint.read) as reads, patch("sys.stdout", io.StringIO()):
            reader.topic_index(graph)
        self.assertEqual([Path(call.args[0]) for call in reads.call_args_list], [source])


if __name__ == "__main__":
    unittest.main()
