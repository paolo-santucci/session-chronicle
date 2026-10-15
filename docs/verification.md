---
date: 2026-10-15
status: fixture-verified-native-blocked
---

# Verification evidence

This file separates static/fixture verification from native runtime qualification.
Commands run in the Chronicle checkout unless stated otherwise. Sibling references
are read-only; temporary fixtures must not use the live project journal.

## Rechecked pre-refactor baseline

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

## Portable implementation

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
the previously excluded legacy bootstrap bundle remains outside this commit.

## Native qualification

| Harness | Installed executable at inventory | Reference target | Native conformance |
|---|---|---|---|
| OpenCode | 2.0.29 | 2.0.26 | Not run; portable bundle not installed |
| Claude Code | 2.1.220 | 2.1.299 | Not run; incompatible with newer reference contracts |
| Codex CLI | Absent | 0.162.1 | Blocked |
| Pi | Absent | 1.2.0 | Blocked |

No authentication/model-backed execution was attempted, no live harness settings
were changed and no qualification attestations were manufactured. Interactive,
headless, trust and permission behavior remain native gates even where fixtures
pass. Linux fixture evidence does not establish macOS or WSL qualification.

## UAT planning reproductions

An in-memory probe imported real UAT `Artifacts`, `apply_package_artifacts` and
`compatibility_report` using its `.venv/bin/python -B`. With a minimal external
plugin, the observed results were:

```text
package capability: unsupported
required blockers: [{'capability': 'chronicle.capture', 'status': 'unsupported'}]
copied bytes: b'{{harness}}'
custom binding: Unknown portable binding: tool:memory_find
config collision: Plugin artifact collision: opencode.json
```

This establishes specific composition limitations, not deployment success. See
`uat-integration-request.md` for source references and acceptance criteria.
