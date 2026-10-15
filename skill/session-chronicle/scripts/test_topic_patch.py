import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_topic_graph as fixtures
from _topic_graph import TopicGraph, parse_note, proposed_graph_findings


class TopicPatchTests(unittest.TestCase):
    setUp = fixtures.TopicGraphTests.setUp
    topic_text = fixtures.TopicGraphTests.topic_text
    topic = fixtures.TopicGraphTests.topic
    session = fixtures.TopicGraphTests.session
    run_cli = fixtures.TopicGraphTests.run_cli
    lint = fixtures.TopicGraphTests.lint

    def add(self, slug, text):
        return f"*** Add File: docs/topics/{slug}.md\n" + "\n".join("+" + line for line in text.splitlines())

    def update(self, slug, old, new, marker=False):
        lines = [f"*** Update File: docs/topics/{slug}.md", "@@"]
        lines += ["-" + line for line in old.splitlines()]
        lines += ["+" + line for line in new.splitlines()]
        if marker:
            lines.append("*** End of File")
        return "\n".join(lines)

    def preflight(self, *operations, env=None, cwd=None):
        text = "*** Begin Patch\n" + "\n".join(operations) + "\n*** End Patch\n"
        before = self.snapshot()
        result = self.run_cli("topic-patch-lint.py", payload={"cwd": str(cwd or self.project),
                              "sessionID": "trusted-session", "patchText": text}, env=env)
        self.assertEqual(self.snapshot(), before, "preflight must not mutate the project")
        return result

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_complete_add_and_update_are_accepted_without_writes(self):
        result = self.preflight(self.add("claim", self.topic_text("claim")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        path = self.topic("claim", body="Original statement.\n")
        result = self.preflight(self.update("claim", path.read_text(), self.topic_text("claim", body="Revised statement.\n")))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_batch_supports_cross_linked_children_and_updated_hub(self):
        hub = self.topic("hub", body="Broad discussion.\n")
        revised = self.topic_text("hub", kind="structure", links=["child-one", "child-two"],
                                 body="This hub separates [[child-one]] and [[child-two]].\n")
        operations = [self.update("hub", hub.read_text(), revised)]
        for slug in ("child-one", "child-two"):
            operations.append(self.add(slug, self.topic_text(slug, sources=["docs/topics/hub.md"])))
        result = self.preflight(*operations)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sources_may_reference_another_new_topic_in_same_batch(self):
        hub = self.topic_text("hub", kind="structure", links=["child"], body="Start with [[child]].")
        child = self.topic_text("child", sources=["docs/topics/hub.md"])
        result = self.preflight(self.add("child", child), self.add("hub", hub))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_final_newline_requires_end_marker_and_exact_original(self):
        path = self.topic("claim", body="Original without LF.")
        new = self.topic_text("claim", body="Revised text.\n")
        rejected = self.preflight(self.update("claim", path.read_text(), new))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("requires *** End of File", rejected.stderr)
        accepted = self.preflight(self.update("claim", path.read_text(), new, marker=True))
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_stale_or_partial_original_cannot_pass(self):
        path = self.topic("claim", body="Original statement.\n\n")
        new = self.topic_text("claim", body="New statement.\n")
        for old in (path.read_text().rstrip() + "\n", path.read_text().replace("Original", "Stale"), "Original statement.\n"):
            with self.subTest(old=old):
                result = self.preflight(self.update("claim", old, new))
                self.assertEqual(result.returncode, 2)
                self.assertIn("Stale or partial original", result.stderr)

    def test_context_partial_multiple_hunks_and_interleaved_changes_rejected(self):
        path = self.topic("claim", body="Original.\n")
        unsupported = ["@@\n Original.\n+Changed.", "@@ heading\n-Original.\n+Changed.",
                       "@@\n-Original.\n+Changed.\n@@\n+More.", "@@\n-Original.\n+Changed.\n-Another."]
        for body in unsupported:
            result = self.preflight(f"*** Update File: docs/topics/{path.name}\n{body}")
            self.assertEqual(result.returncode, 2)
            self.assertIn("complete", result.stderr)

    def test_only_topic_add_update_operations_allowed(self):
        valid = self.add("claim", self.topic_text("claim"))
        operations = ["*** Delete File: docs/topics/claim.md", "*** Move to: docs/topics/other.md",
                      "*** Add File: docs/sessions/forged.md\n+---", "*** Add File: docs/.drafts/raw.md\n+data",
                      "*** Add File: source.py\n+code"]
        for operation in operations:
            with self.subTest(operation=operation):
                result = self.preflight(valid, operation)
                self.assertEqual(result.returncode, 2)

    def test_duplicate_and_existing_add_paths_rejected(self):
        operation = self.add("claim", self.topic_text("claim"))
        result = self.preflight(operation, operation.replace("docs/topics/claim.md", str(self.topics / "claim.md")))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Duplicate", result.stderr)
        self.topic("claim")
        result = self.preflight(operation)
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)

    def test_paths_reject_traversal_and_symlink_targets_or_parents(self):
        target = self.topic("claim", body="Original.\n")
        (self.topics / "alias.md").symlink_to(target)
        operation = self.add("new", self.topic_text("new"))
        traversal = operation.replace("docs/topics/new.md", "docs/topics/../topics/new.md")
        self.assertEqual(self.preflight(traversal).returncode, 2)
        linked = self.update("alias", target.read_text(), self.topic_text("alias"))
        self.assertIn("symbolic links", self.preflight(linked).stderr)
        real_topics = self.base / "original-topics"
        self.topics.rename(real_topics)
        self.topics.symlink_to(real_topics, target_is_directory=True)
        result = self.preflight(operation)
        self.assertEqual(result.returncode, 2)
        self.assertIn("symbolic links", result.stderr)

    def test_secrets_forged_record_kinds_and_kind_downgrade_rejected(self):
        proposed = [self.topic_text("claim", body="Token ghp_" + "x" * 30),
                    self.topic_text("claim", **{"record-kind": "factual-evidence"}),
                    self.topic_text("claim", **{"session-id": "foreign"}),
                    self.topic_text("claim", type="session"),
                    self.topic_text("claim").replace('note-kind: "atomic"\n', "")]
        for text in proposed:
            result = self.preflight(self.add("claim", text))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("x" * 30, result.stderr)
        path = self.topic("claim", body="Original.\n")
        text = path.read_text().replace('note-kind: "atomic"\n', "")
        self.assertEqual(self.preflight(self.update("claim", path.read_text(), text)).returncode, 2)

    def test_existing_session_disguised_by_topic_path_is_not_mutable(self):
        path = self.topics / "claim.md"
        path.write_text("---\ntype: session\nstatus: closed\n---\nHistory.\n")
        result = self.preflight(self.update("claim", path.read_text(), self.topic_text("claim")))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a session", result.stderr)

    def test_independent_repair_allows_unrelated_errors_and_unreadable_records(self):
        broken = self.topic("broken-one", sources=["missing-one.md"], body="Original.\n")
        self.topic("broken-two", sources=["missing-two.md"])
        (self.sessions / "unreadable.md").write_bytes(b"\xff")
        repaired = self.topic_text("broken-one", body="Repaired.\n")
        self.assertEqual(self.lint(broken, repaired).returncode, 0)
        result = self.preflight(self.update("broken-one", broken.read_text(), repaired))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_inbound_break_and_unchanged_errors_on_proposed_notes_rejected(self):
        target = self.topic("target", aliases=["alternate"], body="Target.\n")
        self.topic("inbound", links=["alternate"], body="Depends on [[alternate]].")
        self.topic("unrelated", sources=["missing.md"])
        proposed = self.topic_text("target", body="Target.\n")
        result = self.preflight(self.update("target", target.read_text(), proposed))
        self.assertEqual(result.returncode, 2)
        self.assertIn("inbound broken-topic-edge", result.stderr)
        broken = self.topics / "unrelated.md"
        self.assertEqual(self.lint(broken, broken.read_text()).returncode, 2)

    def test_newly_broken_legacy_inbound_edge_is_not_silenced_as_advisory(self):
        target = self.topic("target", aliases=["alternate"], body="Target.\n")
        (self.topics / "legacy.md").write_text("---\ntype: topic\n---\nSee [[alternate]].")
        result = self.lint(target, self.topic_text("target", body="Target.\n"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("broken-topic-edge", result.stderr)

    def test_shared_graph_validator_detects_kind_downgrade(self):
        path = self.topic("claim")
        text = path.read_text().replace('note-kind: "atomic"\n', "")
        findings = proposed_graph_findings({path: text}, self.base, self.project)
        self.assertIn("kind-downgrade", {item["code"] for item in findings})

    def test_template_comments_quotes_and_quoted_list_commas(self):
        (self.project / "source, detail.md").write_text("Source with a comma.")
        text = self.topic_text("claim", title="A # literal title", sources=["source, detail.md#section"])
        text = text.replace('note-kind: "atomic"', 'note-kind: atomic # optional note kind')
        text = text.replace('sources: ["source, detail.md#section"]', "sources: ['source, detail.md#section'] # provenance")
        text = text.replace("links: []", "links: [] # no outgoing edges")
        text = text.replace('title: "A # literal title"', 'title: "A # literal title" # commentary')
        self.assertEqual(parse_note(text)[0]["title"], "A # literal title")
        result = self.preflight(self.add("claim", text))
        self.assertEqual(result.returncode, 0, result.stderr)
        block = text.replace("sources: ['source, detail.md#section'] # provenance",
                             "sources: # provenance\n  # a source\n  - 'source, detail.md#section' # evidence")
        self.assertEqual(self.preflight(self.add("claim", block)).returncode, 0)
        path = self.topics / "claim.md"
        path.write_text(block)
        result = self.run_cli("note-lint.py", payload={"hook_event_name": "PostToolUse", "tool_name": "Write",
                              "tool_input": {"file_path": str(path)}})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_or_unsupported_frontmatter_is_a_finding(self):
        original = self.topic_text("claim")
        changes = ['title: "unterminated', 'title: &anchor claim', 'title: |', "title: 'value' extra"]
        for replacement in changes:
            text = original.replace('title: "claim"', replacement)
            findings = proposed_graph_findings({self.topics / "claim.md": text}, self.base, self.project)
            self.assertIn("invalid-frontmatter", {item["code"] for item in findings})

    def test_project_root_preferred_and_relative_paths_follow_native_cwd(self):
        result = self.preflight(self.add("claim", self.topic_text("claim")).replace("docs/topics/claim.md", "topics/claim.md"),
                                cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_capture_filter_only_matches_the_installed_helper(self):
        module = load_script("capture-signals.py")
        helper = (fixtures.SCRIPTS / "topic-patch-lint.py").resolve()
        self.assertTrue(module.is_maintenance_command(f'python3 "{helper}"', self.project))
        self.assertFalse(module.is_maintenance_command("python3 topic-patch-lint.py", self.project))
        self.assertFalse(module.is_maintenance_command(f'python3 "{helper}" && other', self.project))


def load_script(name):
    specification = importlib.util.spec_from_file_location(name.replace("-", "_"), fixtures.SCRIPTS / name)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class RoutineReadTests(unittest.TestCase):
    setUp = fixtures.TopicGraphTests.setUp
    topic_text = fixtures.TopicGraphTests.topic_text
    topic = fixtures.TopicGraphTests.topic
    run_cli = fixtures.TopicGraphTests.run_cli

    def unused_evidence(self):
        path = self.sessions / "unused.md"
        path.write_bytes(b"---\ntype: session\nrecord-kind: factual-evidence # source only\n---\n" + b"\xff" * 2_000_000)
        return path

    def test_unused_invalid_evidence_body_does_not_break_ranking_or_index(self):
        self.unused_evidence()
        self.topic("octopus", body="Octopus supported knowledge.")
        result = self.run_cli("retrieve-inject.py", payload={"prompt": "octopus"})
        self.assertIn("(octopus)", result.stdout)
        index = self.run_cli("topic-index.sh")
        self.assertIn("- octopus", index.stdout)
        self.assertNotIn("unused", index.stdout)
        full = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
        self.assertEqual(full.returncode, 1)
        self.assertIn("docs/sessions/unused.md", full.stdout)

    def test_lightweight_graph_does_not_read_or_hash_evidence_bodies(self):
        evidence = self.unused_evidence()
        original = Path.read_bytes

        def checked_read(path):
            self.assertNotEqual(path, evidence, "routine graph must not read evidence bytes")
            return original(path)

        with patch.object(Path, "read_bytes", checked_read):
            graph = TopicGraph(self.base, self.project, include_evidence=False)
        self.assertEqual(graph.records[evidence]["body"], "")
        self.assertIsNone(graph.records[evidence]["sha256"])

    def test_body_reads_for_ordinary_ranking_respect_candidate_cap(self):
        self.unused_evidence()
        for index in range(10):
            self.topic(f"claim-{index}", body="Octopus knowledge.")
        retrieval = load_script("retrieve-inject.py")
        calls = []
        original = retrieval.read

        def tracked_read(path):
            calls.append(path)
            return original(path)

        with patch.dict(os.environ, self.environment), patch.object(retrieval, "MAX_SCAN", 2), \
                patch.object(retrieval, "read", tracked_read), patch("sys.stdin", io.StringIO('{"prompt":"octopus"}')), \
                patch("sys.stdout", io.StringIO()):
            retrieval.main()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(Path(path).parent == self.topics for path in calls))


if __name__ == "__main__":
    unittest.main()
