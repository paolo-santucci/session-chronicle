import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import _checkpoint as store
from _topic_graph import TopicGraph

SCRIPTS = Path(__file__).parent


class TopicGraphTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.base = self.project / "docs"
        self.topics = self.base / "topics"
        self.sessions = self.base / "sessions"
        self.topics.mkdir(parents=True)
        self.sessions.mkdir()
        (self.project / "source.md").write_text("An independently recorded source.")
        self.environment = {**os.environ, "PROJECT_ROOT": str(self.project)}

    def run_cli(self, script, *arguments, payload=None, env=None):
        interpreter = "bash" if script.endswith(".sh") else "python3"
        return subprocess.run([interpreter, str(SCRIPTS / script), *map(str, arguments)],
                              input=json.dumps(payload) if payload is not None else None,
                              text=True, capture_output=True, timeout=20,
                              env={**self.environment, **(env or {})})

    def topic_text(self, slug, kind="atomic", body="A specific supported statement.", **fields):
        metadata = dict(id=slug, type="topic", title=slug, created="2026-10-10", updated="2026-10-10",
                        status="active", provenance="derived_from_sessions", sources=["source.md"], links=[], aliases=[])
        metadata["note-kind"] = kind
        metadata.update(fields)
        return "---\n" + "".join(f"{key}: {json.dumps(value)}\n" for key, value in metadata.items()) + "---\n" + body

    def topic(self, slug, **kwargs):
        path = self.topics / (slug + ".md")
        path.write_text(self.topic_text(slug, **kwargs))
        return path

    def session(self, slug, body, identity=None):
        path = self.sessions / (slug + ".md")
        path.write_text("---\ntype: session\n" + (f"session-id: {identity}\n" if identity else "") + "---\n" + body)
        return path

    def graph(self):
        return TopicGraph(self.base, self.project)

    def lint(self, path, text):
        return self.run_cli("note-lint.py", payload={"hook_event_name": "PreToolUse", "tool_name": "Write",
                                                    "tool_input": {"file_path": str(path), "content": text}})

    def test_typed_write_validates_before_mutation_but_legacy_is_compatible(self):
        path = self.topics / "claim.md"
        invalid = self.topic_text("wrong")
        result = self.lint(path, invalid)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("invalid-id", result.stderr)
        self.assertFalse(path.exists())
        self.assertEqual(self.lint(path, self.topic_text("claim")).returncode, 0)
        legacy = "---\nid: claim\ntype: topic\ntitle: Claim\nprovenance: stated_by_user\n---\nLegacy text."
        self.assertEqual(self.lint(path, legacy).returncode, 0)

    def test_legacy_quality_is_advisory_and_does_not_mutate(self):
        path = self.topics / "old.md"
        path.write_text("---\ntype: topic\n---\nOriginal knowledge.")
        before = path.read_bytes()
        findings = self.graph().quality()
        self.assertIn("legacy-kind", {item["code"] for item in findings})
        self.assertTrue(all(item["severity"] == "warning" for item in findings))
        self.assertEqual(path.read_bytes(), before)

    def test_sources_reject_absolute_traversal_missing_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("Outside.")
            (self.project / "escape.md").symlink_to(target)
            for source in (str(target), "../source.md", "missing.md", "escape.md"):
                with self.subTest(source=source):
                    result = self.lint(self.topics / "claim.md", self.topic_text("claim", sources=[source]))
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("invalid-source", result.stderr)
        self.assertEqual(self.lint(self.topics / "claim.md", self.topic_text("claim", sources=["source.md#not-checked"])).returncode, 0)

    def test_fenced_examples_and_quotes_are_not_topic_edges(self):
        self.topic("claim", body="Supported claim.\n```md\n[[fake]]\n```\n> [[quoted]]\n`[[inline]]`\n~~~\n[[other]]\n~~~")
        self.assertEqual(self.graph().quality(), [])

    def test_topic_links_must_exist_and_match_metadata(self):
        result = self.lint(self.topics / "claim.md", self.topic_text("claim", body="See [[missing]]."))
        self.assertIn("links-mismatch", result.stderr)
        self.assertIn("broken-topic-edge", result.stderr)

    def test_audit_separates_intentional_session_refs_from_broken_topic_edges(self):
        self.session("discussion", "Consider [[future]].")
        self.topic("claim", links=["missing"], body="Depends on [[missing]].")
        result = self.run_cli("memory-audit.py", "--dangling", "--base", self.base, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["dangling"], {"future": 1})
        self.assertEqual(parsed["broken_topic_edges"][0]["code"], "broken-topic-edge")

    def test_alias_collision_with_canonical_name_blocks_proposed_write(self):
        self.topic("claim")
        result = self.lint(self.topics / "other.md", self.topic_text("other", aliases=["claim"]))
        self.assertEqual(result.returncode, 2)
        self.assertIn("alias-collision", result.stderr)

    def test_typed_write_cannot_remove_kind_to_bypass_validation(self):
        path = self.topic("claim")
        proposed = path.read_text().replace('note-kind: "atomic"\n', "")
        result = self.lint(path, proposed)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot drop note-kind", result.stderr)

    def test_prewrite_rejects_duplicate_fields_invalid_lists_and_dates(self):
        original = self.topic_text("claim")
        changes = [original.replace('id: "claim"', 'id: "claim"\nid: "claim"'),
                   original.replace('created: "2026-10-10"', 'created: "20261010"'),
                   self.topic_text("claim", aliases=[17]), self.topic_text("claim", links="[]")]
        for text in changes:
            with self.subTest(text=text):
                self.assertEqual(self.lint(self.topics / "claim.md", text).returncode, 2)

    def test_alias_and_redirect_resolve_and_recall_canonical(self):
        self.topic("claim", aliases=["alternate"])
        self.topic("old", kind="redirect", status="merged", **{"redirects-to": "claim"},
                   links=["claim"], body="Merged into [[claim]] because the claim is identical.")
        self.session("discussion", "We chose [[old]].")
        for name in ("claim", "alternate", "old"):
            result = self.run_cli("backlinks.py", name, "--base", self.base, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["sessions"], ["discussion"])
            recall = self.run_cli("memory-recall.sh", name, "--topic")
            self.assertEqual(recall.returncode, 0, recall.stderr)
            self.assertIn("## [topic] claim", recall.stdout)

    def test_redirect_cycles_and_missing_targets_fail_usefully(self):
        self.topic("one", kind="redirect", status="merged", **{"redirects-to": "two"},
                   links=["two"], body="Moved to [[two]].")
        self.topic("two", kind="redirect", status="superseded", **{"redirects-to": "one"},
                   links=["one"], body="Moved to [[one]].")
        self.assertIn("redirect-cycle", {item["code"] for item in self.graph().quality()})
        result = self.run_cli("memory-recall.sh", "one")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cycle", result.stderr)
        (self.topics / "two.md").unlink()
        self.assertIn("redirect-target", {item["code"] for item in self.graph().quality()})

    def test_child_recovers_broad_topic_sources_and_hub_remains_a_hub(self):
        self.session("original", "Discussion without child wikilinks.")
        self.topic("hub", kind="structure", sources=["docs/sessions/original.md"],
                   links=["child"], body="The original discussion separates into [[child]].")
        self.topic("child", sources=["docs/topics/hub.md"])
        self.assertEqual(self.graph().supporting_sessions("child"), ["original"])
        result = self.run_cli("memory-recall.sh", "hub", "--topic")
        self.assertIn("## [topic] hub", result.stdout)
        self.assertIn("[[child]]", result.stdout)
        child = self.run_cli("memory-recall.sh", "child", "--sessions")
        self.assertIn("original", child.stdout)

    def test_source_cycles_are_exposed_and_block_new_graph(self):
        self.topic("one", sources=["docs/topics/two.md"])
        self.topic("two", sources=["docs/topics/one.md"])
        self.assertEqual({item["slug"] for item in self.graph().quality() if item["code"] == "provenance-cycle"}, {"one", "two"})
        result = self.run_cli("topic-maintenance.py", "validate", "--project", self.project)
        self.assertEqual(result.returncode, 1)

    def test_recurrence_counts_identity_and_excludes_evidence_and_quotes(self):
        self.session("view-one", "[[candidate]]\n```\n[[fake]]\n```\n> [[quoted]]", "same-session")
        self.session("view-two", "[[candidate]]", "same-session")
        evidence = self.session("evidence", "[[fake]] [[candidate]]")
        evidence.write_text(evidence.read_text().replace("type: session", "type: session\nrecord-kind: factual-evidence"))
        result = self.run_cli("memory-audit.py", "--materialization-candidates", "--dangling", "--base", self.base, "--json")
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["dangling"], {"candidate": 1})
        self.assertEqual(parsed["materialization_candidates"], [])
        self.session("legacy", "[[candidate]]")
        result = self.run_cli("memory-audit.py", "--materialization-candidates", "--base", self.base, "--json")
        self.assertEqual(json.loads(result.stdout)["materialization_candidates"], ["candidate"])

    def test_valid_semantic_view_wins_over_presentation_for_recurrence(self):
        draft = self.base / ".drafts"
        draft.mkdir()
        (draft / "2026-10-10.draft.jsonl").write_text(json.dumps({"kind": "prompt", "text": "[[captured]]",
                                                                "sessionID": "session-one"}) + "\n")
        batch = Path(store.checkpoint(self.base)[0])
        path = self.sessions / "summary.md"
        path.write_text("---\nid: summary\ntype: session\nrecord-kind: semantic-summary\nsession-id: session-one\n"
                        "date: 2026-10-10\ntitle: Summary\nstatus: open\nsources: [" + batch.stem + "]\n---\n[[chosen]]")
        self.assertEqual(self.graph().session_links(), {"session-one": {"chosen"}})

    def test_word_limit_warns_without_truncating_or_blocking(self):
        path = self.topic("long", body="word " * 400)
        result = self.lint(path, path.read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = self.graph().quality()
        self.assertEqual([(item["code"], item["severity"]) for item in findings], [("review-length", "warning")])
        with patch.dict(os.environ, {"MEMORY_TOPIC_REVIEW_WORDS": "500"}):
            self.assertEqual(self.graph().quality(), [])
        self.assertEqual(path.read_text().count("word"), 400)

    def test_orphans_include_topic_inbound_and_provenance(self):
        self.session("original", "No explicit links.")
        self.topic("child")
        self.topic("hub", kind="structure", links=["child"], body="See [[child]].", sources=["docs/sessions/original.md"])
        result = self.run_cli("memory-audit.py", "--orphans", "--base", self.base, "--json")
        self.assertEqual(json.loads(result.stdout)["orphans"], [])

    def test_inventory_is_full_deterministic_and_excludes_drafts(self):
        for index in range(65):
            self.topic(f"claim-{index}")
        self.session("legacy", "Legacy session.")
        draft = self.base / ".drafts"
        draft.mkdir()
        (draft / "ignore.md").write_text("draft")
        first = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
        second = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["coverage"], {"discovered": 66, "readable": 66, "unreadable": 0, "topics": 65, "sessions": 1})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in result["records"]))

    def test_inventory_lists_unreadable_files_and_nonzero(self):
        (self.topics / "invalid.md").write_bytes(b"\xff")
        result = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
        self.assertNotEqual(result.returncode, 0)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["unreadable"][0]["path"], "docs/topics/invalid.md")

    def test_symlink_notes_and_directories_never_escape_inventory_or_write_guard(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external)
            target = outside / "claim.md"
            target.write_text(self.topic_text("claim"))
            path = self.topics / "claim.md"
            path.symlink_to(target)
            (self.sessions / "external").symlink_to(outside, target_is_directory=True)
            result = self.run_cli("topic-maintenance.py", "inventory", "--project", self.project)
            parsed = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(parsed["unreadable"]), 2)
            self.assertEqual(parsed["records"], [])
            self.assertEqual(self.lint(path, self.topic_text("claim")).returncode, 2)

    def test_slugify_never_silently_selects_ambiguous_alias_or_stem(self):
        self.topic("widget", aliases=["shared"])
        self.topic("widgets", aliases=["shared"])
        result = self.run_cli("slugify.py", "--resolve", "shared", "--base", self.base)
        self.assertEqual(result.returncode, 2)
        self.assertIn("multiple owners", result.stderr)
        self.topic("widgets")
        result = self.run_cli("slugify.py", "--resolve", "widgetes", "--base", self.base)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Ambiguous stem", result.stderr)

    def test_quality_output_and_validate_warnings_are_not_errors(self):
        self.topic("long", body="word " * 400)
        result = self.run_cli("memory-audit.py", "--quality", "--base", self.base, "--json")
        parsed = json.loads(result.stdout)
        self.assertTrue(parsed["semantic_review_required"])
        self.assertIn("cannot prove atomicity or factual truth", parsed["review_notice"])
        self.assertEqual(set(parsed["quality"][0]), {"slug", "code", "severity", "message"})
        validation = self.run_cli("topic-maintenance.py", "validate", "--project", self.project)
        self.assertEqual(validation.returncode, 0)

    def test_source_support_does_not_inflate_recurrence(self):
        self.session("original", "Source discussion with [[future]].", "session-one")
        for index in range(4):
            self.topic(f"child-{index}", sources=["docs/sessions/original.md"])
        result = self.run_cli("memory-audit.py", "--dangling", "--materialization-candidates",
                              "--base", self.base, "--json")
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["dangling"], {"future": 1})
        self.assertEqual(parsed["materialization_candidates"], [])

    def test_retrieval_filters_retained_nodes_before_budget_and_weights_structure(self):
        for slug, kind in (("atomic", "atomic"), ("structure", "structure")):
            path = self.topic(slug, kind=kind, title="Shared", body="Octopus specific knowledge.")
            os.utime(path, (1, 1))
        for index in range(65):
            self.topic(f"old-{index}", status="superseded", body="Octopus retained text.")
        result = self.run_cli("retrieve-inject.py", payload={"prompt": "octopus"},
                              env={"MEMORY_INJECT_MAX_SCAN": "2", "MEMORY_INJECT_TOPK": "1"})
        self.assertIn("(atomic)", result.stdout)
        self.assertNotIn("retained", result.stdout)

    def test_index_is_bounded_filters_retained_and_advertises_recall(self):
        for index in range(45):
            self.topic(f"claim-{index}")
        self.topic("old", status="superseded")
        result = self.run_cli("topic-index.sh")
        entries = [line for line in result.stdout.splitlines() if line.startswith("- ")]
        self.assertEqual(len(entries), 40)
        self.assertIn("5 omitted", result.stdout)
        self.assertIn("memory_recall", result.stdout)
        result = self.run_cli("topic-index.sh", env={"MEMORY_INDEX_MAX_TOPICS": "2"})
        self.assertIn("43 omitted", result.stdout)

    def test_invalid_slug_rejected_but_forward_reference_can_recall(self):
        self.session("legacy", "Future [[forward]].")
        for script in ("backlinks.py", "memory-recall.sh"):
            result = self.run_cli(script, "../source")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid topic slug", result.stderr)
        result = self.run_cli("memory-recall.sh", "forward")
        self.assertEqual(result.returncode, 0)
        self.assertIn("legacy", result.stdout)
        self.topic("index")
        result = self.run_cli("memory-recall.sh", "index", "--topic")
        self.assertIn("## [topic] index", result.stdout)

    def test_maintenance_capture_exclusion_requires_exact_installed_path(self):
        specification = importlib.util.spec_from_file_location("capture_signals", SCRIPTS / "capture-signals.py")
        capture = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(capture)
        script = (SCRIPTS / "topic-maintenance.py").resolve()
        self.assertTrue(capture.is_maintenance_command(f'python3 "{script}" inventory --project .', self.project))
        self.assertFalse(capture.is_maintenance_command("python3 topic-maintenance.py inventory --project .", self.project))
        self.assertFalse(capture.is_maintenance_command(f'python3 "{script}" inventory --project . && other', self.project))


if __name__ == "__main__":
    unittest.main()
