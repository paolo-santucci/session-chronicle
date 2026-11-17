"""Documentation contracts for the shipped retrieval path.

The retrieval change reaches a reader through four documents only: the README,
the shared skill definition, the capability matrix and the verification record.
A sentence that drifts from the code there reads like behaviour that was never
shipped, so the contracts below are asserted against the documents themselves.
The verification record is checked against the performance report that produced
its figures, so the two cannot drift apart.

The counts asserted here are the ones the build produced (213 script tests,
283 repository tests, 48 adapter tests); a projection is not a baseline.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SKILL = ROOT / "skill/session-chronicle/SKILL.md"
MATRIX = ROOT / "docs/capability-matrix.md"
VERIFICATION = ROOT / "docs/verification.md"
PERF_REPORT = ROOT / "docs/reports/sp-20261116-retrieval-perf-baseline.md"

PROVENANCE_FORMAT = "sources: <n> · updated <YYYY-MM-DD>"
MEASURED_FIGURE = re.compile(r"\d+(?:\.\d+)?\s*ms")
ASSESSMENT_ONLY_FIGURES = ("≈ 95 ms", "≈ 21 ms", "≈ 40 ms", "< 1 ms", "30 s")


def read(path):
    return path.read_text(encoding="utf-8")


class ReadmeContractTests(unittest.TestCase):
    """The README states the retrieval contract an operator reads first."""

    def setUp(self):
        self.text = read(README)

    def test_provenance_line_format_is_stated(self):
        self.assertIn(PROVENANCE_FORMAT, self.text)

    def test_budget_tunables_and_the_single_budget_authority_are_named(self):
        for name in ("MEMORY_INJECT_BUDGET_CHARS", "MEMORY_INJECT_TOPK", "MEMORY_INJECT_MAX_SCAN"):
            self.assertIn(name, self.text)
        self.assertIn("single budget authority", self.text.lower())

    def test_dedup_contract_is_stated(self):
        self.assertIn("slugs", self.text)
        self.assertIn("exclude", self.text)
        self.assertRegex(self.text, r"(?i)suppress\w*[^.]*session")
        self.assertRegex(self.text, r"(?i)compaction")

    def test_dedup_contract_names_the_adapter_that_keeps_the_state(self):
        # The exclusion lives in the core; only the OpenCode adapter keeps the
        # per-session state that feeds it, so the README must say which is which.
        self.assertRegex(self.text, r"(?i)OpenCode adapter[^.]*already injected")
        self.assertRegex(self.text, r"(?i)Claude Code and\s+Codex[^.]*still call `find`")

    def test_the_doctor_exit_codes_are_the_ones_the_doctor_returns(self):
        # chronicle-doctor.py returns 0/1/2/3, and only under --strict.
        self.assertNotIn("4 not installed", self.text)
        self.assertRegex(self.text, r"(?i)always exits 0")
        self.assertRegex(self.text, r"(?i)--strict[^.]*exit code carries the\s+verdict")


class SkillContractTests(unittest.TestCase):
    """The shared skill definition documents the read path it ships with."""

    def setUp(self):
        self.text = read(SKILL)

    def test_retrieve_operation_and_its_reply_shape_are_documented(self):
        self.assertIn("`retrieve`", self.text)
        self.assertIn("`slugs`", self.text)
        self.assertIn("`{text, slugs}`", self.text)

    def test_note_references_use_the_kind_stem_form(self):
        self.assertIn("kind:stem", self.text)

    def test_the_find_fallback_is_documented(self):
        self.assertIn("`find`", self.text)
        self.assertRegex(self.text, r"(?i)falls back[^.]*`find`")

    def test_the_provenance_line_and_its_fallback_are_documented(self):
        self.assertIn(PROVENANCE_FORMAT, self.text)
        self.assertIn("sources: none", self.text)

    def test_the_single_budget_authority_is_documented(self):
        self.assertIn("MEMORY_INJECT_BUDGET_CHARS", self.text)
        self.assertRegex(self.text, r"(?i)budget[^.]*spent in one place")

    def test_the_dedup_contract_names_the_adapter_that_keeps_the_state(self):
        self.assertRegex(self.text, r"(?i)OpenCode[^.]*keeps that per-session state")
        self.assertRegex(self.text, r"(?i)Claude Code and\s+Codex[^.]*still call `find`")


class CapabilityMatrixContractTests(unittest.TestCase):
    """One row carries the retrieval capabilities an adapter can rely on."""

    def setUp(self):
        self.text = read(MATRIX)

    def test_the_retrieval_row_states_the_exact_shipped_clauses(self):
        # Word presence passes on negated claims ("no dedup; provenance TBD"), so the
        # shipped clauses are asserted verbatim and the negations are refused.
        rows = [line for line in self.text.splitlines() if line.strip().startswith("|")]
        retrieval = [row for row in rows if "BM25 prompt retrieval" in row]
        self.assertEqual(len(retrieval), 1, [row for row in rows if "retriev" in row.lower()])
        for clause in ("One budget authority",
                       "per-session dedup by injected slugs",
                       "provenance line per block",
                       "degradation to `find` when the worker rejects `retrieve`"):
            with self.subTest(clause=clause):
                self.assertIn(clause, retrieval[0])
        for negation in ("no dedup", "no provenance", "no degradation", "tbd"):
            with self.subTest(negation=negation):
                self.assertNotIn(negation, retrieval[0].lower())


class VerificationContractTests(unittest.TestCase):
    """The verification record states the counts and figures this build produced."""

    def setUp(self):
        self.text = read(VERIFICATION)

    def test_the_post_change_test_counts_are_recorded(self):
        # These are the counts the build's gate produced. The verification record is
        # the gate of record, so this assertion follows the document rather than
        # freezing a projection of it.
        lines = self.text.splitlines()
        self.assertTrue(
            any("213" in line and "script" in line.lower() for line in lines),
            "no script-suite line records 213 tests",
        )
        self.assertTrue(
            any("283" in line and ("repositor" in line.lower() or "tests" in line.lower()) for line in lines),
            "no repository-suite line records 283 tests",
        )

    def test_zero_collection_errors_is_recorded(self):
        self.assertIn("0 collection errors", self.text)

    def test_the_adapter_suite_is_part_of_the_baseline(self):
        self.assertRegex(self.text, r"(?m)^.*`bun test`.*48.*$")

    def measured_figures(self):
        """Every figure of the measured-latency table's "Measured now" column."""
        self.assertIn("### Measured latency", self.text)
        section = self.text.split("### Measured latency", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in section.splitlines() if line.strip().startswith("|")]
        measured = [row.strip().strip("|").rsplit("|", 1)[-1].strip() for row in rows]
        figures = MEASURED_FIGURE.findall("\n".join(measured))
        self.assertTrue(figures, "the measured-latency table records no figure")
        return figures

    def test_every_measured_figure_is_verbatim_in_the_perf_report(self):
        # The figures are not frozen here: the record and the report that produced
        # them must agree, so a re-measurement cannot leave one of them behind.
        report = read(PERF_REPORT)
        for figure in set(self.measured_figures()):
            with self.subTest(figure=figure):
                self.assertIn(figure, report)

    def test_the_perf_report_measured_table_holds_no_assessment_figure(self):
        # The report's measured table is the post-change data; an assessment-only
        # figure there would present a pre-change number as a measurement.
        report = read(PERF_REPORT)
        measured, marker, _ = report.partition("## 3.")
        self.assertTrue(marker, "the perf report has no section 3")
        rows = "\n".join(line for line in measured.splitlines() if line.strip().startswith("|"))
        self.assertTrue(rows.strip(), "the perf report has no measured table")
        for figure in ASSESSMENT_ONLY_FIGURES:
            with self.subTest(figure=figure):
                self.assertNotIn(figure, rows)

    def test_assessment_figures_are_labelled_and_kept_out_of_the_measured_section(self):
        measured, marker, assessment = self.text.partition("## Assessment-recorded")
        self.assertTrue(marker, "the verification record has no assessment-recorded section")
        for figure in ("≈ 95 ms", "≈ 21 ms", "≈ 40 ms"):
            self.assertNotIn(figure, measured)
            self.assertIn(figure, assessment)


if __name__ == "__main__":
    unittest.main()
