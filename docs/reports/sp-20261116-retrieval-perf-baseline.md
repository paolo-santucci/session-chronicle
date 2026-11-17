# Retrieval performance baseline — 60 sessions + 40 topics

Status: **complete — figures measured 2026-11-17, post-change.**
§2 records what one run of `tests/test_retrieval_perf.py` measured on the environment
recorded there. §3 records the assessment's pre-change figures and is labelled as such;
every delta in this report names which side it comes from and whether the two cover the
same scope. No cell in this report is a placeholder.

Plan task: TASK-13 of `docs/plans/sp-20261116-retrieval-integrity-performance-plan.md`.
Spec refs: NFR-04, NFR-06, OQ-06, OQ-27.

## 1. How the numbers are produced

```sh
cd /var/home/paolo/distrobox/any-dev/session-chronicle
python3 -B -m unittest -v tests.test_retrieval_perf
```

The harness builds the corpus inline on a temporary project (60 session notes + 40 atomic
topic notes below `docs/sessions/` and `docs/topics/`, `docs-root: docs` declared in
`AGENTS.md`), then prints two lines that are the only source for §2 (printed format):

```
retrieval-perf in-process: median … ms over 10 runs (min …, max …)
retrieval-perf subprocess: median … ms, max … ms over 20 runs (min …)
```

- **In-process (NFR-04):** one warm-up `retrieve_matches(project, "octopus")` call, then 10
  timed calls; the **median** must be ≤ 40 ms. Both the warm-up and every timed run must
  return a full `TOP_K` result, so a fixture that stops matching cannot look fast.
- **Subprocess (NFR-06):** 20 invocations of `python -B retrieve-inject.py` with
  `{"prompt": "octopus"}` on stdin and `PROJECT_ROOT` pointing at the fixture; the **median**
  must be ≤ 150 ms and the **max** ≤ 250 ms. Every invocation must exit 0 with empty stderr
  and non-empty stdout.

Fixture composition, so the numbers are read with the right caveats: the 60 session notes
are plain sessions (no `record-kind: semantic-summary`), so the P3 provenance-fill step
performs no identity validation on this corpus; with the default `MEMORY_INJECT_MAX_SCAN`
of 60 the scan window is 40 topic slots plus 20 session slots, and each note body is about
1.5 KB. The in-process figure therefore prices P0–P2 plus rendering over 100 headers and 60
bodies, and does **not** include the ≈40 ms provenance-validation cost the assessment
attributes to identity validation.

## 2. Measured now (this build, post-change)

One run of the command in §1 on 2026-11-17: `Ran 2 tests in 0.866s` — `OK`.

| Item | Value |
|---|---|
| Interpreter | `Python 3.14.7 (main, Aug 10 2026, 00:00:00) [GCC 16.1.1 20260515 (Red Hat 16.1.1-2)]` |
| Machine class / OS | `Linux 7.3.3-300.fc45.x86_64 x86_64` |
| Corpus | 60 session notes + 40 topic notes, built by `tests/test_retrieval_perf.py` |
| Command | `python3 -B -m unittest -v tests.test_retrieval_perf` |
| Runs | 10 in-process (after 1 warm-up) + 20 subprocess invocations |

| Metric | Ceiling | Measured | Result |
|---|---|---|---|
| In-process retrieval after 1 warm-up, 10 timed runs (NFR-04) | ≤ 40 ms | **median 12.20 ms** (min 11.82 ms, max 19.79 ms) | pass |
| Subprocess retrieval, 20 runs — median (NFR-06) | ≤ 150 ms | **34.97 ms** (min 34.57 ms) | pass |
| Subprocess retrieval, 20 runs — max (NFR-06) | ≤ 250 ms | **37.58 ms** (min 34.57 ms) | pass |

Verbatim harness output for the figures above:

```
retrieval-perf in-process: median 12.20 ms over 10 runs (min 11.82, max 19.79)
retrieval-perf subprocess: median 34.97 ms, max 37.58 ms over 20 runs (min 34.57)
```

## 3. Recorded in the assessment — **not** measured by this harness

These figures were recorded by the operator during the assessment
(`docs/specs/sp-20261116-retrieval-integrity-performance-assessment/`, summarised in
`docs/plans/sp-20261116-retrieval-integrity-performance-plan.md` §"Numbers"). They describe
the **pre-change** read path, on an unspecified corpus and machine, and must never be
presented as a post-change measurement or as a like-for-like comparison with §2.

| Cost centre (recorded) | Value | What it is |
|---|---|---|
| Retrieval, end to end | ≈ 95 ms | One complete prompt-time retrieval |
| Interpreter + imports | ≈ 21 ms | Python start plus module import, before any work |
| Provenance validation | ≈ 40 ms | `record_findings` → factual-source validation in P3 |
| Note-body I/O | < 1 ms | Reading the ranked bodies |

Adjacent assessment figures that bound the same path, recorded but outside this harness's
assertions: an end-to-end envelope of 150–250 ms, ~90 ms of per-prompt I/O, 60–100 ms of
interpreter start, "~200 reads and ~100 realpaths at 60 + 40 notes", and a 30 s worker
timeout.

## 4. Ceilings, re-baselining and the OQ-06 rule

- The ceilings in §2 are the spec's **pre-change targets** (NFR-04, NFR-06). They are
  deliberately generous: they catch a regression of the right order of magnitude, they do
  not police a few milliseconds on a shared or loaded machine. The 2026-11-17 run leaves
  them unchanged; a ceiling is re-baselined only after repeated clean runs, and the change
  is recorded here with the run it came from.
- **Measured figures are now recorded (§2), so deltas against the assessment may be
  stated — labelled "measured now vs recorded in the assessment", never as a controlled
  before/after.** §3 measured a different corpus on a different machine at a different
  moment, and this harness isolates no single cost centre, so the attribution below is
  descriptive, not causal.
- Any later sentence of the form "X ms → Y ms" must cite both a §3 figure labelled
  *recorded* and a §2 figure labelled *measured*, and must say whether the two cover the
  same scope.

Deltas — measured now vs recorded in the assessment:

| Path | Measured now (§2) | Recorded in the assessment (§3) | Reading |
|---|---|---|---|
| In-process retrieval | median 12.20 ms (min 11.82, max 19.79) | ≈ 95 ms end-to-end | **Not like-for-like.** The in-process figure excludes interpreter start and process setup, and this fixture performs no provenance validation; it prices P0–P2 plus rendering only. |
| Subprocess retrieval (total process wall time) | median 34.97 ms, max 37.58 ms (min 34.57) | ≈ 95 ms end-to-end | Same kind of total: both include interpreter start. The recorded ≈ 21 ms interpreter + imports is a component of this figure, not a competing total. |
| Interpreter + imports | not isolated (inside the subprocess totals above) | ≈ 21 ms | Recorded as a component; this harness measures whole-process time only and cannot confirm or refute the 21 ms on its own. |
| Provenance validation | **not exercised** | ≈ 40 ms | The fixture's sessions carry no `record-kind: semantic-summary`, so the P3 identity-validation branch never runs. No delta can be attributed to this cost centre, and the 12.20 ms in-process figure is not evidence that this ≈ 40 ms is gone. |
| Note-body I/O | not isolated | < 1 ms | Inside the measured totals; not separately measured here. |

- A failure of either harness test is read in the order the plan requires: a genuine
  regression, then a stale ceiling, then a fixture problem — and the fixture is the least
  likely of the three because both tests assert that the measured path returned real output.

## 5. Known limits of this baseline

- The harness measures this machine and this fixture only; there is no CI matrix and no
  repeated-run stability study beyond the 10 + 20 samples per run.
- The corpus is generated deterministically by the test module, so the numbers are
  comparable across runs of this repository but not directly comparable to the assessment's
  corpus, whose note shapes and sizes are not recorded.
- A skip is reported with an explicit reason (`cannot create the 60-session + 40-topic
  fixture: …`) rather than silently: a skipped latency harness leaves §2 stale rather than
  green, so a skip is reported to the caller and never read as a pass.
