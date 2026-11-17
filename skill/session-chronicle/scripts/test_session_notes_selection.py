"""The shared selection API: purity, identity partition, validation and the index contract.

`select_candidates` is phase 1 of retrieval (eligibility over headers the caller already
read); `validate_view` is phase 3 (deferred provenance validation); `preferred_paths` is the
index's eager selector and must keep its pre-change output exactly.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _session_notes
from _session_notes import preferred_paths, select_candidates, summary_findings, validate_view


FACTUAL_HEADER = "type: session\nrecord-kind: factual-evidence\nid: evidence\n"
SEMANTIC_HEADER = "type: session\nrecord-kind: semantic-summary\nsession-id: session-one\n"
PRESENTATION_HEADER = "type: session\nrecord-kind: session-presentation\nsession-id: session-one\n"
ANONYMOUS_PRESENTATION_HEADER = "type: session\nrecord-kind: session-presentation\n"
TOPIC_HEADER = "type: topic\ntitle: Octopus\nnote-kind: atomic\nstatus: active\n"
SUPERSEDED_TOPIC_HEADER = "type: topic\ntitle: Retired\nnote-kind: atomic\nstatus: superseded\n"
MISSING_BATCH = "2026-10-10--evidence-" + "b" * 32


def no_note_reads():
    """Fail loudly if selection touches the filesystem instead of the given headers."""
    return patch.object(_session_notes, "read_frontmatter",
                        side_effect=AssertionError("selection must not read notes"))


class SelectionFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name) / "docs"
        (self.base / "sessions").mkdir(parents=True)
        (self.base / "topics").mkdir()

    def factual_source(self, identities=("session-one",)):
        identifier = "2026-10-10--evidence-" + "a" * 32
        path = self.base / "sessions" / (identifier + ".md")
        records = [{"kind": "prompt", "sessionID": identity, "text": "Evidence."} for identity in identities]
        path.write_text(f"---\nid: {identifier}\nbatch-id: {identifier}\ntype: session\n"
                        "record-kind: factual-evidence\ndate: 2026-10-10\nstatus: closed\n"
                        "provenance: captured_signals\n---\n```json\n" + json.dumps(records) + "\n```\n")
        return path

    def view(self, slug, identity, sources, kind="semantic-summary"):
        path = self.base / "sessions" / (slug + ".md")
        path.write_text(f"---\nid: {slug}\ntype: session\nrecord-kind: {kind}\n"
                        f"session-id: {identity}\nsources: {json.dumps(sources)}\n"
                        "date: 2026-10-10\ntitle: Summary\nstatus: open\n"
                        "provenance: captured_signals\n---\nReviewed discussion.\n")
        return path

    def topic(self, slug, **fields):
        path = self.base / "topics" / (slug + ".md")
        declared = "".join(f"{key}: {value}\n" for key, value in fields.items())
        path.write_text(f"---\ntype: topic\ntitle: {slug}\n{declared}---\nTopic prose.\n")
        return path


class SelectCandidatesTests(SelectionFixture):
    def test_factual_backlog_is_partitioned_without_reading_any_note(self):
        headers = [(Path(f"/nowhere/docs/sessions/factual-{index:02d}.md"), FACTUAL_HEADER)
                   for index in range(65)]
        headers.append((Path("/nowhere/docs/sessions/semantic.md"), SEMANTIC_HEADER))
        headers.append((Path("/nowhere/docs/topics/octopus.md"), TOPIC_HEADER))
        # The paths do not exist, so any read would fail even without the patch below.
        with no_note_reads():
            selected = select_candidates(headers, self.base)
            with_evidence = select_candidates(headers, self.base, include_evidence=True)
        self.assertEqual(selected["eligible"], [headers[65][0], headers[66][0]])
        self.assertEqual(with_evidence["eligible"], [path for path, _ in headers])
        self.assertEqual(len(with_evidence["eligible"]), 67)

    def test_identity_partition_groups_summaries_and_presentations(self):
        headers = [
            (Path("summary.md"), SEMANTIC_HEADER),
            (Path("first-presentation.md"), PRESENTATION_HEADER),
            (Path("second-presentation.md"), PRESENTATION_HEADER),
            (Path("anonymous-presentation.md"), ANONYMOUS_PRESENTATION_HEADER),
            (Path("retired-topic.md"), SUPERSEDED_TOPIC_HEADER),
        ]
        selected = select_candidates(headers, self.base)
        self.assertEqual(selected["identities"]["session-one"]["summaries"], [headers[0][0]])
        self.assertEqual(selected["identities"]["session-one"]["presentations"],
                         [headers[1][0], headers[2][0]])
        self.assertEqual(len(selected["identities"]["session-one"]["presentations"]), 2)
        self.assertEqual(selected["identities"][""]["presentations"], [headers[3][0]])
        self.assertNotIn(headers[4][0], selected["eligible"])

    def test_malformed_header_yields_no_candidate_and_no_exception(self):
        for text in ("garbage without a colon", "---\n", "\x00 not frontmatter"):
            with self.subTest(text=text):
                self.assertEqual(select_candidates([(Path("broken.md"), text)], self.base),
                                 {"eligible": [], "identities": {}})

    def test_header_without_frontmatter_stays_a_legacy_candidate(self):
        # A note that was never given frontmatter read as "" and stays selectable, as before.
        headers = [(Path("legacy.md"), "")]
        with no_note_reads():
            selected = select_candidates(headers, self.base)
        self.assertEqual(selected["eligible"], [Path("legacy.md")])
        self.assertEqual(selected["identities"], {})


class ValidateViewTests(SelectionFixture):
    def test_summary_and_presentation_share_one_per_call_cache(self):
        batch = self.factual_source(("session-one", "session-two"))
        summary = self.view("summary", "session-one", [MISSING_BATCH])
        presentation = self.view("presentation", "session-two", [batch.stem], "session-presentation")
        summary_fm = _session_notes.read_frontmatter(summary)
        presentation_fm = _session_notes.read_frontmatter(presentation)
        lint = _session_notes.note_lint
        cache = {}
        with patch.object(lint, "read", wraps=lint.read) as reads, \
                patch.object(_session_notes, "load_note",
                             side_effect=AssertionError("validation must not re-read notes")):
            self.assertFalse(validate_view(summary, summary_fm, self.base, cache))
            self.assertTrue(validate_view(presentation, presentation_fm, self.base, cache))
            self.assertFalse(validate_view(summary, summary_fm, self.base, cache))
            self.assertEqual(reads.call_count, 2)
            self.assertEqual([Path(call.args[0]) for call in reads.call_args_list],
                             [self.base / "sessions" / (MISSING_BATCH + ".md"), batch])
            # A fresh cache per call: the cache never outlives the call that made it.
            self.assertFalse(validate_view(summary, summary_fm, self.base, {}))
            self.assertEqual(reads.call_count, 3)

    def test_ordinary_notes_validate_without_provenance_work(self):
        lint = _session_notes.note_lint
        with patch.object(lint, "read", side_effect=AssertionError("ordinary notes need no batch read")):
            self.assertTrue(validate_view(self.base / "sessions" / "plain.md",
                                          "type: session\ntitle: Plain\n", self.base, {}))


class SummaryFindingsTests(SelectionFixture):
    def test_summary_findings_reuses_an_already_read_header(self):
        batch = self.factual_source()
        healthy = self.view("healthy", "session-one", [batch.stem])
        foreign = self.view("foreign", "session-two", [batch.stem])
        for path in (healthy, foreign):
            with self.subTest(path=path.name):
                read_fm, _ = _session_notes.load_note(path)
                expected = summary_findings(path, self.base)
                with patch.object(_session_notes, "load_note",
                                  side_effect=AssertionError("summary_findings must not re-read the note")):
                    self.assertEqual(summary_findings(path, self.base, fm=read_fm), expected)
        self.assertEqual(summary_findings(healthy, self.base), [])


class PreferredPathsContractTests(SelectionFixture):
    def test_mixed_fixture_keeps_membership_and_order(self):
        batch = self.factual_source(("session-one", "session-two", "session-four"))
        one_summary = self.view("one-summary", "session-one", [batch.stem])
        one_presentation = self.view("one-presentation", "session-one", [batch.stem], "session-presentation")
        two_presentation = self.view("two-presentation", "session-two", [batch.stem], "session-presentation")
        four_summary = self.view("four-summary", "session-four", [MISSING_BATCH])
        four_presentation = self.view("four-presentation", "session-four", [batch.stem], "session-presentation")
        legacy = self.base / "sessions" / "2020-01-01--legacy.md"
        legacy.write_text("Legacy note without frontmatter.\n")
        active_topic = self.topic("octopus", **{"note-kind": "atomic", "status": "active"})
        legacy_topic = self.topic("old-idea")
        unreadable = self.base / "sessions" / "ghost.md"  # never written
        paths = [one_presentation, legacy, one_summary, batch, legacy_topic,
                 four_presentation, four_summary, active_topic, two_presentation, unreadable]
        # Recorded pre-change output: the summary suppresses its presentation regardless of
        # order, an unvalidatable summary falls back to its presentation, factual evidence is
        # opt-in, and the survivor order is the input order.
        self.assertEqual(preferred_paths(paths, self.base),
                         [legacy, one_summary, legacy_topic, four_presentation,
                          active_topic, two_presentation])
        self.assertEqual(preferred_paths(paths, self.base, include_evidence=True),
                         [legacy, one_summary, batch, legacy_topic, four_presentation,
                          active_topic, two_presentation])

    def test_duplicate_identities_and_per_path_read_errors_are_omitted(self):
        batch = self.factual_source(("session-one", "session-two"))
        first = self.view("first", "session-one", [batch.stem], "session-presentation")
        second = self.view("second", "session-one", [batch.stem], "session-presentation")
        missing = self.base / "sessions" / "missing.md"
        self.assertEqual(preferred_paths([missing, first, second], self.base), [])


if __name__ == "__main__":
    unittest.main()
