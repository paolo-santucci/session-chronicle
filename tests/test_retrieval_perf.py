"""Wall-clock latency harness for retrieval (NFR-04, NFR-06).

This module is the only place a wall-clock assertion is allowed: unit tests assert call
counts, not milliseconds, and the CLI acceptance suite asserts behaviour, not timing.

Two measurements, both on one inline corpus of 60 session notes and 40 topic notes:

- in-process: one warm-up call, then 10 timed `retrieve_matches()` calls, median <= 40 ms
  (NFR-04). The median is printed so `docs/reports/sp-20261116-retrieval-perf-baseline.md`
  can cite the number this run actually produced.
- subprocess: 20 invocations of `retrieve-inject.py` reading `{"prompt": "octopus"}` on
  stdin, median <= 150 ms and max <= 250 ms (NFR-06). Both numbers are printed.

The ceilings are deliberately generous and are the pre-change targets from the spec: they
exist to catch a regression of the right order of magnitude, not to police a few
milliseconds on a shared machine. Per OQ-06 no delta is claimed against the assessment
figures until the report records what this harness measured.

The corpus is built inline, in this module, on purpose: TASK-14 authors a CLI acceptance
suite in the same wave and a shared fixture helper would couple the two files.
"""
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skill/session-chronicle/scripts"
CLI = SCRIPTS / "retrieve-inject.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SESSION_COUNT = 60
TOPIC_COUNT = 40
IN_PROCESS_RUNS = 10
SUBPROCESS_RUNS = 20
IN_PROCESS_CEILING_MS = 40.0
SUBPROCESS_MEDIAN_CEILING_MS = 150.0
SUBPROCESS_MAX_CEILING_MS = 250.0
PROMPT = "octopus"

# Filler vocabulary: gives every note a body of realistic size without repeating one term.
FILLER = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
          "india", "juliet", "kilo", "lima", "mike", "november", "papa", "quebec")


def load_retrieval():
    """The production module, imported exactly as `test_retrieval_render.py` does."""
    specification = importlib.util.spec_from_file_location("retrieve_inject_perf", CLI)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def note_body(index):
    """Six deterministic paragraphs; the query term appears so every note can rank."""
    paragraphs = []
    for paragraph in range(6):
        words = [FILLER[(index * 5 + paragraph * 3 + offset) % len(FILLER)] for offset in range(35)]
        paragraphs.append(" ".join(words) + ".")
    paragraphs.insert(1, "Observed %s behaviour in run %d; the %s path stayed read-only."
                      % (PROMPT, index, PROMPT))
    return "\n\n".join(paragraphs) + "\n"


def write_note(path, frontmatter, body):
    path.write_text("---\n" + frontmatter + "---\n" + body, encoding="utf-8")


def build_corpus(project):
    """60 sessions + 40 topics below `project/docs`, plus the docs-root declaration."""
    base = project / "docs"
    sessions = base / "sessions"
    topics = base / "topics"
    sessions.mkdir(parents=True)
    topics.mkdir()
    (project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n", encoding="utf-8")
    for index in range(SESSION_COUNT):
        day = index % 28 + 1
        slug = "2026-10-%02d--session-%02d" % (day, index)
        frontmatter = ("type: session\ntitle: Session %02d %s review\ndate: 2026-10-%02d\n"
                       "status: closed\nsources: [AGENTS.md]\nupdated: 2026-10-%02d\n"
                       % (index, PROMPT, day, day))
        write_note(sessions / (slug + ".md"), frontmatter, note_body(index))
    for index in range(TOPIC_COUNT):
        day = index % 28 + 1
        frontmatter = ("type: topic\nnote-kind: atomic\ntitle: Topic %02d %s\ndate: 2026-10-%02d\n"
                       "status: active\nsources: [AGENTS.md]\nupdated: 2026-10-%02d\n"
                       % (index, PROMPT, day, day))
        write_note(topics / ("topic-%02d.md" % index), frontmatter, note_body(TOPIC_COUNT + index))
    return base


def elapsed_ms(call):
    """Run `call()` once and return (milliseconds, result) from a monotonic clock."""
    started = time.perf_counter()
    result = call()
    return (time.perf_counter() - started) * 1000.0, result


class CorpusTestCase(unittest.TestCase):
    """Builds the 60-session + 40-topic corpus inline; skips with a reason if it cannot."""

    def setUp(self):
        self.assertTrue(CLI.is_file(), "retrieval script is missing at %s" % CLI)
        try:
            temporary = tempfile.TemporaryDirectory(prefix="retrieval-perf-")
            self.addCleanup(temporary.cleanup)
            self.project = Path(temporary.name)
            build_corpus(self.project)
        except OSError as error:
            self.skipTest("cannot create the 60-session + 40-topic fixture: %s" % error)


class InProcessLatencyTests(CorpusTestCase):
    def test_in_process_retrieval_median_stays_within_ceiling(self):
        retrieval = load_retrieval()
        warm_up = retrieval.retrieve_matches(str(self.project), PROMPT)
        self.assertEqual(len(warm_up["slugs"]), retrieval.TOP_K,
                         "the fixture must produce a full result before timing it")

        durations, results = [], []
        for _ in range(IN_PROCESS_RUNS):
            milliseconds, result = elapsed_ms(
                lambda: retrieval.retrieve_matches(str(self.project), PROMPT))
            durations.append(milliseconds)
            results.append(result)

        median_ms = statistics.median(durations)
        print("retrieval-perf in-process: median %.2f ms over %d runs (min %.2f, max %.2f)"
              % (median_ms, IN_PROCESS_RUNS, min(durations), max(durations)))
        self.assertTrue(all(result["text"] for result in results),
                        "every timed run must emit text, not an empty result")
        self.assertLessEqual(
            median_ms, IN_PROCESS_CEILING_MS,
            "in-process retrieval median %.2f ms exceeds the %.0f ms ceiling (NFR-04)"
            % (median_ms, IN_PROCESS_CEILING_MS))


class SubprocessLatencyTests(CorpusTestCase):
    def run_cli(self, environment):
        started = time.perf_counter()
        completed = subprocess.run([sys.executable, "-B", str(CLI)],
                                   input=json.dumps({"prompt": PROMPT}), text=True,
                                   capture_output=True, env=environment, timeout=60)
        return (time.perf_counter() - started) * 1000.0, completed

    def test_subprocess_retrieval_median_and_max_stay_within_ceilings(self):
        environment = dict(os.environ, PROJECT_ROOT=str(self.project))
        durations, outputs = [], []
        for _ in range(SUBPROCESS_RUNS):
            milliseconds, completed = self.run_cli(environment)
            self.assertEqual(completed.returncode, 0,
                             "retrieve-inject.py must exit 0: %s" % completed.stderr)
            self.assertEqual(completed.stderr, "", completed.stderr)
            durations.append(milliseconds)
            outputs.append(completed.stdout)

        median_ms = statistics.median(durations)
        max_ms = max(durations)
        print("retrieval-perf subprocess: median %.2f ms, max %.2f ms over %d runs (min %.2f)"
              % (median_ms, max_ms, SUBPROCESS_RUNS, min(durations)))
        self.assertTrue(all(output.strip() for output in outputs),
                        "every invocation must write a rendered block to stdout")
        self.assertLessEqual(
            median_ms, SUBPROCESS_MEDIAN_CEILING_MS,
            "subprocess retrieval median %.2f ms exceeds the %.0f ms ceiling (NFR-06)"
            % (median_ms, SUBPROCESS_MEDIAN_CEILING_MS))
        self.assertLessEqual(
            max_ms, SUBPROCESS_MAX_CEILING_MS,
            "subprocess retrieval max %.2f ms exceeds the %.0f ms ceiling (NFR-06)"
            % (max_ms, SUBPROCESS_MAX_CEILING_MS))


if __name__ == "__main__":
    unittest.main()
