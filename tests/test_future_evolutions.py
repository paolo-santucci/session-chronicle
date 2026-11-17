"""Doc assertions for docs/future-evolutions.md.

FR-38: the file records exactly three deferred options — a precompiled index,
an observability channel and an in-process read path — each with the measured
figures that justify deferring it, an expected gain and a reopen trigger.
NFR-15: no option is recorded without a number.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "future-evolutions.md"

H2 = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
FIGURE = re.compile(r"\d+ ?(ms|s|day|%)")
EXPECTED_GAIN = re.compile(r"^\*\*Expected gain:\*\*", re.MULTILINE)
REOPEN_WHEN = re.compile(r"^\*\*Reopen when:\*\*", re.MULTILINE)

OPTION_TITLES = {
    "precompiled index": (r"\bindex\b",),
    "observability channel": (r"observability", r"debug channel"),
    "in-process read path": (r"in-process", r"in process"),
}

ASSESSMENT_FIGURES = (
    "≈95 ms",
    "≈21 ms",
    "≈40 ms",
    "<1 ms",
    "30 s",
    "200 reads to 1",
    "~1 day",
    "~5–15 ms",
    "60–100 ms",
    "3–5 days",
    "~140–150",
)

POST_CHANGE_MEDIANS = ("12.20 ms", "34.97 ms", "37.58 ms")

NEGATION = re.compile(r"\b(not|never|no|nor)\b")


def split_sections(text):
    """Return [(title, body)] for every H2 section in the document."""
    heads = list(H2.finditer(text))
    sections = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        sections.append((head.group(1), text[head.end():end]))
    return sections


class FutureEvolutionsDocTests(unittest.TestCase):
    def read_doc(self):
        self.assertTrue(DOC.is_file(), f"{DOC} is missing")
        text = DOC.read_text(encoding="utf-8")
        self.assertTrue(text.strip(), f"{DOC} is empty")
        return text

    def test_document_exists(self):
        self.read_doc()

    def option_sections(self, text):
        """The H2 sections that name one of the three options, as [(option, title, body)].

        A section that names no option — a later "Known defects" heading, say — is
        not part of the option set and must not change what the option contract
        asserts.
        """
        found = []
        for title, body in split_sections(text):
            hits = [
                name
                for name, patterns in OPTION_TITLES.items()
                if any(re.search(pattern, title, re.IGNORECASE) for pattern in patterns)
            ]
            if hits:
                self.assertEqual(len(hits), 1, f"title {title!r} matches {hits}")
                found.append((hits[0], title, body))
        return found

    def test_exactly_three_option_sections(self):
        options = self.option_sections(self.read_doc())
        names = [name for name, _, _ in options]
        self.assertEqual(len(names), 3, names)
        self.assertEqual(sorted(names), sorted(OPTION_TITLES))

    def test_no_section_title_names_two_options(self):
        for title, _ in split_sections(self.read_doc()):
            hits = [
                name
                for name, patterns in OPTION_TITLES.items()
                if any(re.search(pattern, title, re.IGNORECASE) for pattern in patterns)
            ]
            with self.subTest(title=title):
                self.assertLessEqual(len(hits), 1, hits)

    def test_each_section_carries_a_measured_figure(self):
        for name, _title, body in self.option_sections(self.read_doc()):
            with self.subTest(option=name):
                self.assertRegex(body, FIGURE)

    def test_each_section_carries_an_expected_gain_and_a_reopen_trigger(self):
        for name, _title, body in self.option_sections(self.read_doc()):
            with self.subTest(option=name):
                self.assertRegex(body, EXPECTED_GAIN)
                self.assertRegex(body, REOPEN_WHEN)

    def test_figures_are_attributed_as_pre_change(self):
        text = self.read_doc()
        self.assertIn("pre-change", text)
        self.assertIn("assessment", text.lower())
        for name, _title, body in self.option_sections(text):
            with self.subTest(option=name):
                self.assertIn("pre-change", body)

    def test_assessment_figures_are_cited_verbatim(self):
        text = self.read_doc()
        for figure in ASSESSMENT_FIGURES:
            with self.subTest(figure=figure):
                self.assertIn(figure, text)

    def test_no_figure_is_presented_as_a_post_change_measurement(self):
        text = self.read_doc()
        for median in POST_CHANGE_MEDIANS:
            with self.subTest(median=median):
                self.assertNotIn(median, text)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if "post-change" in sentence.lower():
                with self.subTest(sentence=sentence.strip()):
                    self.assertRegex(sentence.lower(), NEGATION)


if __name__ == "__main__":
    unittest.main()
