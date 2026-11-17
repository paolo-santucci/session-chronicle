import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import _memory_markers as markers
import _memory_read

SCRIPTS = Path(__file__).resolve().parent
LEAF = SCRIPTS / "_memory_markers.py"
FRESH_LOADER = """
import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
specification = spec_from_file_location("leaf_under_test", sys.argv[1])
module = module_from_spec(specification)
specification.loader.exec_module(module)
print(json.dumps({
    "fcntl": "fcntl" in sys.modules,
    "project_modules": sorted(
        name for name in ("_capture", "_checkpoint", "_portable", "_docsroot") if name in sys.modules
    ),
}))
"""


class EmptyGraph:
    base = "."
    topics = {}
    names = set()

    def session_views(self):
        return []

    def session_links(self):
        return {}


class StripInjectedTests(unittest.TestCase):
    def test_text_without_marker_is_returned_unchanged(self):
        text = "  no markers here \n"
        self.assertEqual(markers.strip_injected(text), text)

    def test_earliest_marker_wins_and_survivor_is_rstripped(self):
        text = "0123456789" + markers.RETRIEVAL_HEADING + "x" * 30 + markers.UNTRUSTED_START
        self.assertEqual(markers.strip_injected(text), "0123456789")

    def test_marker_at_start_or_after_whitespace_yields_empty(self):
        self.assertEqual(markers.strip_injected(markers.UNTRUSTED_START + "body"), "")
        self.assertEqual(markers.strip_injected("  \n" + markers.RETRIEVAL_HEADING), "")

    def test_strip_is_idempotent(self):
        text = "Refactor the parser\n\n" + markers.RETRIEVAL_HEADING + "\n### [session] body"
        once = markers.strip_injected(text)
        self.assertEqual(markers.strip_injected(once), once)

    def test_strip_is_total(self):
        self.assertEqual(markers.strip_injected(""), "")
        self.assertEqual(markers.strip_injected("#"), "#")
        self.assertEqual(len(markers.strip_injected("x" * 2_000_000 + markers.UNTRUSTED_START)), 2_000_000)
        self.assertEqual(markers.strip_injected("a\ud800" + markers.UNTRUSTED_START), "a\ud800")


class SharedHeadingTests(unittest.TestCase):
    def test_prefix_matches_both_renderer_headings(self):
        for heading in (markers.RETRIEVAL_HEADING, markers.INDEX_HEADING):
            self.assertTrue(heading.startswith(markers.PROJECT_MEMORY_PREFIX), heading)

    def test_each_heading_alone_strips_to_empty(self):
        for text in (markers.PROJECT_MEMORY_PREFIX, markers.RETRIEVAL_HEADING, markers.INDEX_HEADING):
            self.assertEqual(markers.strip_injected(text), "")


class SessionStartIndexTests(unittest.TestCase):
    def render(self):
        output = io.StringIO()
        with redirect_stdout(output):
            _memory_read.topic_index(EmptyGraph())
        return output.getvalue()

    def test_rendered_index_heading_is_the_shared_constant(self):
        self.assertEqual(self.render().splitlines()[0], markers.INDEX_HEADING)

    def test_index_heading_comes_from_the_leaf_not_a_literal(self):
        with patch.object(_memory_read, "INDEX_HEADING", "## patched heading"):
            self.assertEqual(self.render().splitlines()[0], "## patched heading")

    def test_memory_read_holds_no_injected_marker_literals(self):
        source = Path(_memory_read.__file__).read_text(encoding="utf-8")
        for literal in (markers.PROJECT_MEMORY_PREFIX, markers.UNTRUSTED_START.splitlines()[0]):
            self.assertNotIn(literal, source)


class EnvelopeTests(unittest.TestCase):
    def test_escape_replaces_both_delimiters(self):
        self.assertEqual(markers.escape("<a>"), "&lt;a&gt;")
        self.assertEqual(markers.escape("a>b"), "a&gt;b")
        self.assertEqual(markers.escape("ab"), "ab")

    def test_envelope_len_counts_escaping_and_delimiters(self):
        for text in ("<a>", "a>b", "ab"):
            with self.subTest(text=text):
                self.assertEqual(markers.envelope_len(text),
                                 len(markers.escape(text)) + markers.UNTRUSTED_OVERHEAD)
        self.assertEqual(markers.UNTRUSTED_OVERHEAD,
                         len(markers.UNTRUSTED_START) + len(markers.UNTRUSTED_END))


class LeafSurfaceTests(unittest.TestCase):
    def test_leaf_imports_no_project_module_and_no_fcntl(self):
        result = subprocess.run([sys.executable, "-B", "-c", FRESH_LOADER, str(LEAF)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        self.assertFalse(outcome["fcntl"])
        self.assertEqual(outcome["project_modules"], [])


if __name__ == "__main__":
    unittest.main()
