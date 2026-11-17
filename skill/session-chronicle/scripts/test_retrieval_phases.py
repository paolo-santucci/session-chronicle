"""P1/P2 retrieval: query guard, per-call header memo, hoisted base path, exclusion in ranking.

Every test drives ``retrieve-inject.py`` in-process through its pure seams and patches the
four I/O seams (``resolve_base``, ``glob.glob``, ``read_frontmatter``, ``read``) by module
attribute, so a call count is real filesystem work and not a proxy for it.
"""
import glob
import importlib.util
import json
import os
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from _topic_graph import read_frontmatter

SCRIPTS = Path(__file__).parent


def load_retrieval():
    specification = importlib.util.spec_from_file_location("retrieve_inject", SCRIPTS / "retrieve-inject.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class RetrievalPhaseTests(unittest.TestCase):
    def setUp(self):
        self.retrieval = load_retrieval()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.base = self.project / "docs"
        self.topics = self.base / "topics"
        self.sessions = self.base / "sessions"
        self.topics.mkdir(parents=True)
        self.sessions.mkdir()

    def topic(self, slug, body, title=None, modified=None):
        path = self.topics / (slug + ".md")
        path.write_text("---\ntype: topic\nnote-kind: atomic\ntitle: %s\nstatus: active\n---\n\n%s\n"
                        % (title or slug, body), encoding="utf-8")
        if modified is not None:
            os.utime(path, (modified, modified))
        return path

    def session(self, slug, body, title=None, modified=None):
        path = self.sessions / (slug + ".md")
        path.write_text("---\ntype: session\ntitle: %s\n---\n\n%s\n" % (title or slug, body), encoding="utf-8")
        if modified is not None:
            os.utime(path, (modified, modified))
        return path

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file() and not path.is_symlink()}

    def stems(self, candidates):
        return [candidate["slug"] for candidate in candidates]

    # --- the query guard (FR-07, FR-08, EC-01) -----------------------------

    def test_stopword_only_prompts_have_no_query_terms(self):
        for prompt in ("ok", "sì", "vai", "the"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.retrieval.query_terms(prompt), set())
        self.assertTrue(self.retrieval.query_terms("octopus"))

    def test_synonyms_expand_a_term_to_its_target(self):
        self.assertIn("kubernetes", self.retrieval.query_terms("k8s"))
        self.assertIn("k8s", self.retrieval.query_terms("kubernetes"))

    def test_a_stopword_prompt_touches_no_filesystem(self):
        for index in range(60):
            self.session("session-%02d" % index, "Octopus migration %d." % index, modified=1000 + index)
        for index in range(40):
            self.topic("topic-%02d" % index, "Octopus distilled %d." % index, modified=2000 + index)
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch.object(self.retrieval, name, MagicMock(wraps=getattr(self.retrieval, name))))
                     for name in ("resolve_base", "read_frontmatter", "read")]
            mocks.append(stack.enter_context(patch.object(self.retrieval.glob, "glob", MagicMock(wraps=glob.glob))))
            self.assertIsNone(self.retrieval.retrieve(str(self.project), "ok"))
        for mock in mocks:
            self.assertEqual(mock.call_count, 0, mock)

    def test_a_real_query_still_validates_the_docs_root_after_the_early_return(self):
        (self.project / "AGENTS.md").write_text("---\ndocs-root: ../outside\n---\n", encoding="utf-8")
        with patch.object(self.retrieval, "resolve_base", MagicMock(wraps=self.retrieval.resolve_base)) as resolve_base:
            self.assertIsNone(self.retrieval.retrieve(str(self.project), "ok"))
            self.assertEqual(resolve_base.call_count, 0)
            with self.assertRaises(ValueError):
                self.retrieval.retrieve(str(self.project), "octopus")
            self.assertEqual(resolve_base.call_count, 1)

    def test_a_missing_docs_root_is_still_validated_for_a_real_query(self):
        bare = self.project / "bare"
        bare.mkdir()
        with patch.object(self.retrieval, "resolve_base", MagicMock(wraps=self.retrieval.resolve_base)) as resolve_base:
            self.assertIsNone(self.retrieval.retrieve(str(bare), "ok"))
            self.assertEqual(resolve_base.call_count, 0)
            self.assertIsNone(self.retrieval.retrieve(str(bare), "octopus"))
            self.assertEqual(resolve_base.call_count, 1)

    def test_a_single_token_prompt_runs_full_retrieval(self):
        self.topic("octopus", "Octopus distilled knowledge.")
        ranked = self.retrieval.ranked_candidates(str(self.project), "octopus")
        self.assertEqual(self.stems(ranked), ["octopus"])
        self.assertTrue(self.retrieval.retrieve(str(self.project), "octopus"))

    # --- memoised headers and the hoisted base path (FR-09, FR-11, NFR-02, NFR-03) ---

    def test_frontmatter_is_opened_once_per_candidate_path(self):
        for index in range(5):
            self.session("session-%d" % index, "Octopus migration notes.", modified=1000 + index)
        opens = Counter()

        def counted(path):
            opens[str(path)] += 1
            return read_frontmatter(path)

        with patch.object(self.retrieval, "MAX_SCAN", 2), \
                patch.object(self.retrieval, "read_frontmatter", counted):
            for _ in range(5):
                opens.clear()
                self.retrieval.ranked_candidates(str(self.project), "octopus")
                self.assertLessEqual(max(opens.values()), 1)
                self.assertLessEqual(sum(opens.values()), 5)

    def test_the_header_memo_does_not_outlive_the_call_or_write_anything(self):
        path = self.session("octopus-note", "Octopus migration notes.", title="Old title")
        before = self.snapshot()
        self.assertIn("Old title", self.retrieval.retrieve(str(self.project), "octopus"))
        path.write_text("---\ntype: session\ntitle: New title\n---\n\nOctopus migration notes.\n", encoding="utf-8")
        second = self.retrieval.retrieve(str(self.project), "octopus")
        self.assertIn("New title", second)
        self.assertNotIn("Old title", second)
        after = self.snapshot()
        self.assertEqual(set(after), set(before))
        self.assertEqual([name for name in after if name.startswith("docs/") and name.endswith((".json", ".cache"))], [])

    def test_the_base_is_resolved_once_per_call_and_never_per_candidate(self):
        for index in range(400):
            self.session("session-%03d" % index, "Octopus migration %d." % index, modified=1000 + index)
        calls, real = [], os.path.realpath

        def recording(value, *arguments, **keywords):
            calls.append(os.fspath(value))
            return real(value, *arguments, **keywords)

        base = str(self.base)
        with patch.object(self.retrieval, "resolve_base", return_value=base), \
                patch("os.path.realpath", recording):
            self.retrieval.ranked_candidates(str(self.project), "octopus")
        self.assertEqual(calls, [base])

    def test_a_symlink_escaping_the_base_is_rejected_before_it_is_read(self):
        self.topic("octopus", "Octopus distilled knowledge.", modified=1000)
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "escape.md"
            outside.write_text("---\ntype: topic\ntitle: Escape\nstatus: active\n---\n\nOctopus escape hatch.\n",
                               encoding="utf-8")
            (self.topics / "escape.md").symlink_to(outside)
            reads, original = [], self.retrieval.read_frontmatter

            def counted(path):
                reads.append(str(path))
                return original(path)

            with patch.object(self.retrieval, "read_frontmatter", counted):
                with self.assertRaises(ValueError):
                    self.retrieval.retrieve(str(self.project), "octopus")
        self.assertEqual([name for name in reads if Path(name).name == "escape.md"], [])
        self.assertTrue(all(Path(path).resolve().is_relative_to(self.base.resolve()) for path in reads))

    # --- exclusion inside ranking (FR-21, EC-03) ---------------------------

    def test_exclusion_replaces_a_hit_instead_of_shrinking_the_result(self):
        for index in range(5):
            self.topic("claim-%d" % index, "octopus " * (5 - index) + "filler " * (index + 1))
        with patch.object(self.retrieval, "TOP_K", 5):
            ranked = self.retrieval.ranked_candidates(str(self.project), "octopus")
        self.assertEqual(len(ranked), 5)
        excluded = ranked[0]
        with patch.object(self.retrieval, "TOP_K", 3):
            kept = self.retrieval.ranked_candidates(str(self.project), "octopus",
                                                    exclude=("topic:" + excluded["slug"],))
        self.assertEqual(len(kept), 3)
        self.assertEqual(self.stems(kept), self.stems(ranked[1:4]))
        self.assertNotIn(excluded["slug"], self.stems(kept))

    # --- bounded scan and pinned ordering (FR-32, NFR-13) ------------------

    def test_topics_take_the_scan_slots_and_body_reads_stay_capped(self):
        for index in range(3):
            self.topic("topic-%d" % index, "Octopus distilled knowledge.", modified=1000 + index)
        calls, original = [], self.retrieval.read

        def counted(path):
            calls.append(str(path))
            return original(path)

        with patch.object(self.retrieval, "MAX_SCAN", 2), patch.object(self.retrieval, "read", counted):
            self.assertTrue(self.retrieval.ranked_candidates(str(self.project), "octopus"))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(Path(path).parent.resolve() == self.topics.resolve() for path in calls))

    def test_newer_sessions_never_crowd_a_topic_out_of_the_scan_window(self):
        self.topic("octopus-topic", "Octopus distilled knowledge.", modified=1000)
        for index in range(10):
            self.session("2026-01-%02d--session" % (index + 1), "Unrelated body %d." % index, modified=2000 + index)
        with patch.object(self.retrieval, "MAX_SCAN", 3):
            ranked = self.retrieval.ranked_candidates(str(self.project), "octopus")
        self.assertIn("octopus-topic", self.stems(ranked))

    # --- candidate bodies that cannot be read (EC-05, EC-07) ----------------

    def test_an_undecodable_body_is_skipped_and_retrieval_still_answers(self):
        broken = self.topics / "broken.md"
        broken.write_bytes(b"---\ntype: topic\ntitle: Broken\nstatus: active\n---\n\xff\xfe octopus\n")
        os.utime(broken, (1000, 1000))
        self.topic("octopus", "Octopus distilled knowledge.", modified=2000)
        self.assertEqual(self.stems(self.retrieval.ranked_candidates(str(self.project), "octopus")),
                         ["octopus"])
        self.assertIn("octopus", self.retrieval.retrieve(str(self.project), "octopus"))

    def test_an_unreadable_body_is_skipped_and_retrieval_still_answers(self):
        self.topic("unreadable", "Octopus unreadable body.", modified=1000)
        self.topic("octopus", "Octopus distilled knowledge.", modified=2000)
        original = self.retrieval.read

        def partial(path):
            if Path(path).name == "unreadable.md":
                raise OSError("body cannot be opened")
            return original(path)

        with patch.object(self.retrieval, "read", partial):
            ranked = self.retrieval.ranked_candidates(str(self.project), "octopus")
        self.assertEqual(self.stems(ranked), ["octopus"])

    def test_an_unreadable_header_still_raises(self):
        (self.topics / "octopus.md").write_text("---\ntype: topic\ntitle: Octopus\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.retrieval.ranked_candidates(str(self.project), "octopus")

    # --- one identity extraction for the partition and for P3 (FR-31, FR-34) ---

    def factual_source(self, identity):
        identifier = "2026-10-10--evidence-" + "a" * 32
        records = [{"kind": "prompt", "sessionID": identity, "text": "Evidence."}]
        (self.sessions / (identifier + ".md")).write_text(
            "---\nid: %s\nbatch-id: %s\ntype: session\nrecord-kind: factual-evidence\n"
            "date: 2026-10-10\nstatus: closed\nprovenance: captured_signals\n---\n"
            "```json\n%s\n```\n" % (identifier, identifier, json.dumps(records)), encoding="utf-8")
        return identifier

    def view(self, slug, identity, sources, kind="semantic-summary"):
        path = self.sessions / (slug + ".md")
        path.write_text("---\nid: %s\ntype: session\nrecord-kind: %s\nsession-id: %s\n"
                        "sources: %s\ndate: 2026-10-10\ntitle: %s\nstatus: open\n"
                        "provenance: captured_signals\n---\nOctopus review.\n"
                        % (slug, kind, identity, json.dumps(sources), slug), encoding="utf-8")
        return path

    def test_a_quoted_session_id_is_read_once_so_a_summary_suppresses_its_presentation(self):
        # `session-id: 'a''b'` is a header on which a full frontmatter parse and the shared
        # accessor disagree; the batch records the identity as the shared accessor reads it.
        batch = self.factual_source("a''b")
        self.view("summary-quoted", "'a''b'", [batch])
        self.view("presentation-quoted", "'a''b'", [batch], "session-presentation")
        result = self.retrieval.retrieve_matches(str(self.project), "octopus")
        self.assertEqual(result["slugs"], ["session:summary-quoted"])

    def test_only_summary_and_presentation_kinds_are_suppressed_by_an_identity(self):
        batch = self.factual_source("session-one")
        self.view("summary-one", "session-one", [batch])
        (self.sessions / "plain-session.md").write_text(
            "---\ntype: session\nsession-id: session-one\ntitle: Plain\n---\nOctopus plain body.\n",
            encoding="utf-8")
        result = self.retrieval.retrieve_matches(str(self.project), "octopus")
        self.assertEqual(set(result["slugs"]), {"session:summary-one", "session:plain-session"})

    # --- read-only invariant (FR-09, FR-40) --------------------------------

    def test_no_module_level_cache_is_introduced(self):
        collections = {name for name, value in vars(self.retrieval).items()
                       if not name.startswith("__") and isinstance(value, (dict, list, set))}
        self.assertEqual(collections, {"SYNONYMS", "STOP", "TYPE_BOOST"})


if __name__ == "__main__":
    unittest.main()
