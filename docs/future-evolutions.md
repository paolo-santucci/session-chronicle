# Deferred options for the retrieval read path

Status: **deferred by decision.** None of the three options below is built. This
file records them, the figures that justify leaving them unbuilt, and the
condition under which each one comes back.

Plan task: TASK-10 of `docs/plans/sp-20261116-retrieval-integrity-performance-plan.md`.
Spec refs: FR-38, NFR-15. Open questions: OQ-01, OQ-16, OQ-27.

**Every figure in this file is a pre-change measurement**, recorded by the
operator during the assessment
(`docs/specs/sp-20261116-retrieval-integrity-performance-assessment/`) before
the retrieval rework landed. Nothing here was re-measured for this file, and
no figure here is a post-change measurement.

The post-change baseline measured for this feature lives in
`docs/reports/sp-20261116-retrieval-perf-baseline.md`, and none of its figures
are quoted here, because it measures a different fixture and is not a
before/after pair for any option below.

Three cautions about how to read them:

- The ≈95 ms end-to-end figure contains the ≈21 ms interpreter + imports
  figure. Adding them double-counts.
- The 60–100 ms interpreter-start figure and the ≈95 ms end-to-end figure were
  recorded at different moments, on different harnesses. They do not decompose
  one another, so the difference between them is not a saving.
- The corpus and the machine behind the assessment figures were never pinned
  down. Read them as order of magnitude, not as a budget.

Each section below carries the same four things: what the option is, the
pre-change figures recorded for it, the gain to expect if it is built, and the
condition that reopens the decision.

OQ-01 asks that the assessment's beyond-scope findings be recorded here rather
than turned into requirements. Two of them are open defects rather than
options, and carry no figure, no gain and no reopen trigger: the
five-versus-three capture-folder drift between `_capture.select_signal` and
`capture-signals.build_signal`, and the stale `.opencode_OLD/` copies of the
script and test trees.

## Precompiled on-disk index

**The option.** One JSON file under `docs/` holding path, kind, title, slug,
topics, mtime, sources, token count and claims, written by maintenance and
never by the read path. Retrieval still writes nothing, so FR-40 holds. The
read path opens that one file instead of globbing the corpus and opening every
note.

**Measured, pre-change (recorded in the assessment).**

| Cost centre | Recorded value |
|---|---|
| File reads per prompt, 60 sessions + 40 topics | ~200 |
| `realpath` calls per prompt | ~100 |
| Retrieval, end to end | ≈95 ms |
| Interpreter + imports | ≈21 ms |
| Note-body I/O | <1 ms |

Reading the ranked bodies costs <1 ms. The cost sits in the ~200 reads that
decide which bodies get ranked, and in the ~100 `realpath` calls that follow
the glob. Both are per-prompt, per-candidate work, and an index collapses both
into a single file open.

**Current top lever (OQ-16).** `_docsroot.validated_base` performs ~140–150
`Path.resolve()` calls per invocation: 7 memory paths plus 35
memory-by-managed pairs, each resolving twice. The assessment ranks it above
the per-file `resolve()` this feature removed, and it is smaller than any
option in this file. An index does not remove it either. The index would cache
the note list; the resolution cost would still be paid for every path the index
names. Fix the hotspot, measure the result, and only then decide whether an
index earns its write path.

**Expected gain:** the read path opens one file instead of ~200, the
"200 reads to 1" reduction the operator's note prices at ~1 day of work. The
per-prompt cost stops scaling with the corpus. The ~100 `realpath` calls do
not disappear; they move into the index writer.

**Reopen when:** the recorded ~200 reads per prompt grow with the corpus (the
figure comes from 60 sessions + 40 topics, and a corpus three times that size
triples the read count), or the end-to-end figure stays above the NFR-06
envelope after the OQ-16 hotspot is fixed and measured, or notes start changing
more often than a maintenance run can rebuild the index.

## Observability and debug channel

**The option.** One JSON line per retrieval on stderr, behind an environment
switch: elapsed milliseconds, files read, candidates, injected slugs, injected
characters, and the reason the result stopped where it did. The worker client
drains the child's stderr and discards it, so a line written there today
reaches no reader; the option gives it one without touching the stdout
protocol.

**Measured, pre-change (recorded in the assessment).**

| Cost centre | Recorded value |
|---|---|
| Retrieval, end to end | ≈95 ms |
| Interpreter + imports | ≈21 ms |
| Provenance validation | ≈40 ms |
| Note-body I/O | <1 ms |
| Worker call timeout | 30 s |

That table is the argument for the option. The four cost centres sit inside one
≈95 ms total, and today the total cannot be split by code that runs on every
prompt. stdout is the protocol: one `print(json.dumps(...))`, parsed by a
single `JSON.parse`. A stray print from any imported module turns a reply into
a `worker_protocol` failure, and the child's stderr is drained and discarded
before anyone sees it. The cost centres above were read by hand, one run at a
time.

The 30 s worker timeout carries the same blind spot. A hung worker is a hung
prompt, and nothing today says which phase it hung in.

OQ-27 records the same gap from the test side: the latency ceilings could not
be asserted from the baselines, because no harness measured in-process
retrieval time. The performance harness added for this feature measures two
fixed shapes. A debug channel measures every retrieval, in production, through
the same code path the model sees.

**Expected gain:** about ~1 h of work and no latency change. It makes the
≈95 ms attributable per prompt: which cost centre, how many candidates, how
many characters. It also produces the usage metric nothing else produces:
which notes are never injected, which candidates lose to a higher-scored note,
and which prompts match nothing at all.

**Reopen when:** before either of the other two options is scheduled, since
neither can show what it removed without a channel that runs on every prompt;
or when the end-to-end figure misses the NFR-06 envelope and the miss needs an
explanation rather than a guess; or when someone asks why a note they expected
was not injected.

## In-process TypeScript/Rust read path

**The option.** Move the read path out of the Python worker and into the
adapter's own process, in TypeScript or in a small Rust helper. No process
spawn per prompt. Python stays for maintenance, audit and refactor, where
latency does not matter.

**Measured, pre-change (recorded in the assessment).**

| Cost centre | Recorded value |
|---|---|
| Interpreter start, per worker call | 60–100 ms |
| Interpreter + imports | ≈21 ms |
| Retrieval, end to end | ≈95 ms |
| Worker call timeout | 30 s |
| Worker calls per prompt | 3 (checkpoint, index, find) |

The three worker calls are sequential, and each one is a cold process, so the
start-up cost is paid before the prompt is submitted.

**Expected gain:** ~5–15 ms in-process against 60–100 ms of interpreter start,
at 3–5 days of effort. The 30 s worker timeout leaves the prompt path
entirely, and the adapter stops waiting on a subprocess that can be slow,
absent or wedged.

**Reopen when:** the in-process path can be the read path rather than a second
one, with selection semantics, the budget authority and the provenance line
living in exactly one implementation, and the Python path retired instead of
shadowed. Two implementations of the selection rules is the drift the
assessment already found between the doctor and retrieval, and the pinned tests
cover the Python side only. The other trigger is a deployment that needs the
subprocess boundary the adapter has today: one process per event, with no
shared state between them.
