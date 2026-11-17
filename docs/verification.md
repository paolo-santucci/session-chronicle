---
date: 2026-11-17
status: fixture-verified-native-blocked
---

# Verification evidence

This file separates static/fixture verification from native runtime qualification.
Commands run in the Chronicle checkout unless stated otherwise. Sibling references
are read-only; temporary fixtures must not use the live project journal.

Sections are dated and labelled. The **post-change baseline** below is what the
current tree produces; the **assessment-recorded figures** are the operator's
pre-change numbers, kept for comparison and never presented as post-change
results; the **earlier recorded runs** further down are the historical evidence
of what was observed before this change and are superseded by the baseline above.

## Post-change baseline (measured now — 2026-11-17)

The retrieval-integrity change was verified with the commands below. Every count
in this section is **measured now**: it is what the command produced on the
machine and interpreter named here.

| Command | Observed result |
|---|---|
| `python3 -B -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py'` | 213 tests, 0 failures |
| `/var/home/paolo/distrobox/any-dev/universal-agentic-toolkit/.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'` | 283 tests, OK, 21 skipped; 0 collection errors |
| `bun test` | 48 pass, 0 failures across `index.test.ts` and `tests/pi.adapter.test.ts` |
| `bun run typecheck` | clean |
| `python3 -B -m unittest -v tests.test_retrieval_perf` | 2 tests, OK — in-process and subprocess latency measured |

These are the counts the build's gate produced. This table is the
gate of record for the retrieval-integrity change: a later gate run that produces
different numbers replaces the figures here rather than adding a second table.

What the counts cover:

- The 17 packaging tests in `tests/test_neutral_workflows.py` collect
  individually and are reported by name instead of collapsing into one
  collection error. Discovery reports 0 collection errors.
- The 21 skips in the repository suite are explained rather than silent: the
  UAT checkout is absent from this environment, so the UAT-gated packaging and
  loader tests skip, and the optional-dependency gate names PyYAML/jsonschema.
- The 11 pinned retrieval and selection tests and all ten
  `skill/session-chronicle/scripts/test_write_boundaries.py` cases pass with
  no assertion edits.
- The adapter suite belongs to the baseline rather than to a separate note:
  `bun test` runs `index.test.ts` and `tests/pi.adapter.test.ts` together.

### Measured latency (measured now)

| Path | Ceiling | Measured now |
|---|---|---|
| In-process retrieval, 10 timed runs after one warm-up (NFR-04) | ≤ 40 ms | median 12.20 ms (min 11.82 ms, max 19.79 ms) |
| Subprocess retrieval, 20 runs — median (NFR-06) | ≤ 150 ms | 34.97 ms (min 34.57 ms) |
| Subprocess retrieval, 20 runs — max (NFR-06) | ≤ 250 ms | 37.58 ms (min 34.57 ms) |

Source: `docs/reports/sp-20261116-retrieval-perf-baseline.md` §2. Environment:
Python 3.14.7 on Linux 7.3.3-300.fc45.x86_64, over a corpus of 60 session notes
and 40 topic notes. The in-process figure prices eligibility, ranking and
rendering; it does not include provenance validation, because the fixture's
sessions carry no `record-kind: semantic-summary`.

## Assessment-recorded figures (pre-change, not re-measured)

These figures were recorded by the operator during the assessment of the
retrieval path (`docs/specs/sp-20261116-retrieval-integrity-performance-assessment/`).
They describe the **pre-change** read path on an unspecified corpus and
machine. They are recorded here for comparison and are never presented as
post-change results.

| Cost centre | Recorded | What it is |
|---|---|---|
| Retrieval, end to end | ≈ 95 ms | one complete prompt-time retrieval |
| Interpreter + imports | ≈ 21 ms | Python start plus module import, before any work |
| Provenance validation | ≈ 40 ms | factual-source validation in the deferred phase |
| Note-body I/O | < 1 ms | reading the ranked bodies |
| Worker timeout | 30 s | the worker call budget, pre-change |

The comparison is descriptive, not like-for-like: the measured in-process figure
excludes interpreter start, and the fixture exercises no provenance validation,
so nothing here shows that the ≈ 40 ms validation cost is gone.

## Earlier recorded run — pre-refactor baseline (superseded)

Kept as evidence of what was observed before this change. The current counts
are the post-change baseline above.

| Command | Observed result |
|---|---|
| `python3 -B -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py'` | 119 passed |
| `python3 -B -m unittest discover -s tests -p 'test_*.py'` | 22 passed |
| `bun test` | 12 passed, 46 assertions |
| `bun run typecheck` | Passed |
| `python3 -B scripts/lint-agents.py` | 3 commands, 3 legacy skills; 0 errors/warnings |

The last command checks legacy definitions; actual neutral definitions require
UAT schema/loader checks. These baseline counts are not counts for the completed
portable implementation. Negative adapter tests intentionally log rejected lookup,
invalid docs-root and failed checkpoint diagnostics.

## Earlier recorded run — portable implementation, 2026-10-15 (superseded)

Final integration checks on 2026-10-15:

| Command | Observed result |
|---|---|
| `git diff --check` | Passed |
| `python3 -B scripts/lint-agents.py` | 3 commands, 3 legacy skills; 0 errors/warnings |
| `bun run typecheck` | Passed, including the actual Pi 1.2.0 SDK types |
| `bun test` | 22 passed, 68 assertions; no failures |
| `python3 -B -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py'` | 119 passed |
| `/var/home/paolo/distrobox/any-dev/universal-agentic-toolkit/.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'` | 184 passed; no skips |

**325 tests passed** across the final suites. The 184-test suite includes 60 neutral
core tests, 42 command-hook tests, 17 neutral workflow/scanner tests, 14 packaging
tests, 20 real UAT integration tests and 10 standalone-installer tests. Counts for
these subsets are not additional tests. Scoped installer and neutral-resource
tests were rerun after fixing integration failures before the full suite passed.

Development dependencies were installed with `bun install --ignore-scripts`;
`bun.lock` records Pi SDK 1.2.0 and typebox 1.3.27. This installs development types,
not a native Pi runtime or live harness configuration. Runtime package/archive
tests use the actual allowlisted source inventory, load/resolve/render all four
UAT targets, unpack a pinned local archive, verify literal artifact bytes and
expected unsupported-capability/synchronization refusals. No fabricated
qualification evidence or successful native sync is claimed.

Review found and resolved reserved legacy-ID ambiguity, compatibility append
durability, read aliases, continuation validation/recovery, overbroad guards,
transport bounds, and installer rollback/signal failure paths. Core re-review
approved those fixes. The installer suite tests preserved backups on rollback
failure; it does not establish crash-atomic multi-path installation.

An unavailable native runtime remains blocked, never a passed test. Fixture tests
use synthetic model assignments solely for rendering; no model was invoked.

### Commit snapshot and rename verification

After renaming the package to `session-chronicle`, the Git index was exported to
an isolated directory with `git checkout-index --all --prefix=<snapshot>/`.
`bun install --frozen-lockfile --ignore-scripts` succeeded there. Typecheck and
all three suites above passed again: 22 Bun, 119 memory and 184 repository tests.
The UAT suite used `UAT_ROOT=/var/home/paolo/distrobox/any-dev/universal-agentic-toolkit`
with the same absolute interpreter path. These are repeat checks, not additional
tests in the total. This verifies the committed source set without local-only
resources. The snapshot definition lint passed with 2 commands and 2 legacy skills;
the legacy bootstrap bundle was excluded from that initial implementation commit.

After the user authorized its inclusion and the legacy-file deletions, all suites
passed again (22 + 119 + 184 = 325), with typecheck and whitespace checks passing.
Definition lint now covers 3 commands and 3 legacy skills with no errors/warnings.

## Native qualification

Recorded on 2026-10-23. The retrieval change moves the shared core's read path
and leaves the native harness contracts below as they were.

| Harness | Installed executable at inventory | Reference target | Native conformance |
|---|---|---|---|
| OpenCode | 2.0.29 | 2.0.26 | Not run; portable bundle not installed |
| Claude Code | 2.1.220 | 2.1.299 | Not run; incompatible with newer reference contracts |
| Codex CLI | UAT reports 0.163.0 in Ansel | 0.163.0 | Chronicle not activated; exact-artifact qualification pending |
| Pi | Absent | 1.2.0 | Blocked |

No authentication/model-backed execution was attempted, no live harness settings
were changed and no qualification attestations were manufactured. Interactive,
headless, trust and permission behavior remain native gates even where fixtures
pass. Linux fixture evidence does not establish macOS or WSL qualification.

## Earlier recorded run — Codex 0.163.0 package revision, 2026-10-23 (superseded)

Checks run on 2026-10-23 after adding structured Codex hook contributions and
re-evaluating pinned producer semantics:

| Command | Observed result |
|---|---|
| `git diff --check` | Passed |
| `python3 -B scripts/lint-agents.py` | 3 commands, 3 skills; 0 errors/warnings |
| `bun run typecheck` | Passed |
| `bun test` | 22 passed, 68 assertions |
| `python3 -B -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py'` | 119 passed |
| `/var/home/paolo/distrobox/any-dev/universal-agentic-toolkit/.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'` | 186 passed |
| `python3 -B scripts/build-package.py --output … --archive …` | Version 0.2.1 stage and deterministic archive built |

**327 tests passed** across the full suites. The repository suite includes 44
native-hook tests and 20 real UAT package tests. Those focused subsets also passed
independently before the full run. UAT composition fixtures establish eight owned
Codex contributions, preserved settings/status/statistics groups, retained
matchers, three-second shutdown limits and artifact-bound inventory. They do not
establish native trust, execution, concurrency, denial coverage or workflow success.

Pinned 0.163.0 source proves that prompt hooks receive pending `TurnInput::UserInput`
before persistence/context injection and that PostToolUse follows successful tool
output. It also proves child fields are emitted only for thread-spawn children;
absence remains ambiguous with internal/synthetic sources. A turn ID is not proven
unique per pending prompt item. Tests therefore retain unknown actor/origin, exclude
child/unknown capture, preserve native tool IDs and refuse prompt-ID or single-path
patch inference. Capture and session-context remain unsupported.

## Earlier recorded run — UAT planning reproductions (superseded)

Recorded on 2026-10-23. An in-memory probe imported real UAT `Artifacts`,
`apply_package_artifacts` and `compatibility_report` using its `.venv/bin/python -B`.
With a minimal external plugin, the observed results were:

```text
package capability: unsupported
required blockers: [{'capability': 'chronicle.capture', 'status': 'unsupported'}]
copied bytes: b'{{harness}}'
custom binding: Unknown portable binding: tool:memory_find
config collision: Plugin artifact collision: opencode.json
```

This establishes specific composition limitations, not deployment success. See
`uat-integration-request.md` for source references and acceptance criteria.
