---
date: 2026-10-15
status: acceptance-matrix
---

# Workflow acceptance and qualification

This is the acceptance matrix established before restructuring. **No target is
operationally qualified.** `core` means an outcome shared by every adapter, not
proof that an adapter delivers the required native events. `blocked` is a known
missing runtime/UAT contract. Verification results belong in `verification.md`.

| Workflow | OpenCode | Claude Code | Codex CLI | Pi | Required acceptance |
|---|---|---|---|---|---|
| Selective prompts | Blocked: original-user provenance | Blocked: origin discriminator | Blocked: event ID/origin | Blocked: event ID/role | Core policy/opt-out tested; native gaps never produce invented user evidence |
| File/process signals | Implemented, fixture-tested | Implemented, fixture-tested | Blocked: success/attribution | Blocked: role | Paths/command inputs only; failed operations excluded |
| Primary-only capture | SDK parent check | Native actor check | Blocked where origin unknown | Blocked where role unknown | Delegated and unknown calls never become primary evidence |
| Trusted identity | SDK session/location | Native hook identity | Native hook identity | Session manager/cwd | Model IDs rejected; missing workspace fails; no fallback project |
| Qualified identities | Core | Core | Core | Core | Same native ID on different harnesses stays distinct |
| Draft/checkpoint durability | Core | Core | Core | Core | Lock, fsync, no-clobber evidence; acknowledgement after publication |
| Replayed delivery | Native stable IDs + core | Stable IDs required | Stable IDs required | Stable IDs required | Duplicate event across restart/rotation/publication captured once |
| Concurrent writers | Core | Core | Core | Core | Same worktree serialized; different worktrees isolated |
| Crash recovery | Core | Core | Core | Core | Pending replay; conflicting/malformed batches retained and reported |
| Presentations/evidence | Core | Core | Core | Core | Immutable evidence; one derived presentation per identity |
| Session-start index | Implemented, fixture-tested | Implemented, fixture-tested | Read-only hook orientation | Automatic injection blocked | Bounded index; status integration retained |
| BM25 prompt retrieval | Implemented, fixture-tested | Implemented, fixture-tested | Implemented, fixture-tested | Explicit read tools only | Ranking, deduplication, source exclusion, configured budgets preserved |
| Compaction/handoff | Native hook | PreCompact/context | PreCompact/context | Extension hook | Persist before handoff; failures retain pending evidence |
| `memory_find` | Native tool, UAT policy blocked | Native discovery gap | Native discovery gap | Native tool, UAT policy blocked | Query/evidence switch; untrusted wrapper; explicit error vs no matches |
| `memory_recall` | Native tool, UAT policy blocked | Native discovery gap | Native discovery gap | Native tool, UAT policy blocked | Scope, aliases/redirects and supporting history |
| `memory_backlinks` | Native tool, UAT policy blocked | Native discovery gap | Native discovery gap | Native tool, UAT policy blocked | File-addressable note IDs, not substituted native session IDs |
| `memory_audit` | Native tool, UAT policy blocked | Native discovery gap | Native discovery gap | Native tool, UAT policy blocked | Six modes including quality; distinct-session recurrence |
| `memory_session_context` | Trusted native tool | Trusted tool-call transport gap | Trusted tool-call transport gap | Primary provenance gap | Empty arguments; checkpoint; exact source/target; no latest-session lookup |
| Enrichment | Neutral workflow + guarded tools | Required tools gate | Required tools gate | Required provenance gate | Explicit invocation, exact identity, sources, open target, explicit-only closure |
| Bootstrap | Neutral workflow | Neutral workflow | Guarded-write gate | Guarded-write gate | Populated-journal refusal; force additive only; sourced history |
| Topic refactoring | Neutral workflow | Native mutation gate | Native mutation gate | Native mutation gate | Complete review; dry-run; snapshots; resume hashes; retained addresses |
| Secret/history guard | Direct native tool guard | Native hook guard | Failure/coverage gap | tool_call guard | Positive valid write and negative protected-write probes |
| Shell/external protection | Limited | Limited | Limited | Limited | Record bypass coverage honestly; hooks are not universal immutability |
| Legacy reads | Core | Core | Core | Core | No inferred harness, byte-preserved history, existing pending recoverable |
| Cross-harness retrieval | Core | Core | Core | Core | Shared memory without native-session impersonation |
| Explicit continuation | Core API; native entrypoint pending | Core API; native entrypoint pending | Core API; native entrypoint pending | Core API; native entrypoint pending | Sourced link between distinct existing identities; no native-resume impersonation |
| Skill discovery | UAT rendering | UAT rendering | UAT rendering | UAT rendering | Explicit entrypoints; no redundant commands; selected dependencies |
| Permissions | UAT custom-tool gap | UAT custom-tool gap | UAT custom-tool gap | UAT custom-tool gap | Unknown tools remain denied; no shell workaround |
| Package loading/rendering | Real UAT test | Real UAT test | Real UAT test | Real UAT test | Actual schema, exact version, physical resources, byte-copy semantics |
| Sync/rollback preservation | Qualification blocked | Qualification blocked | Qualification blocked | Qualification blocked | Memory/pending/authored instructions survive; configuration overlap refused |
| Status/statistics coexistence | Composition tests | Composition gap | Composition gap | Policy/provenance gap | One lifecycle owner; no journal content in statistical metadata |
| Interactive/headless operation | Runtime version mismatch | Runtime version mismatch | Runtime absent | Runtime absent | Exact build/artifacts, trust flows, negative probes, verified workflow outcome |
| Activation failure | Explicit gate | Explicit gate | Explicit gate | Explicit gate | Missing required capabilities must not produce qualified status |

## Installed / activated / operational

These columns refer to the **portable 0.2.0 implementation**, not the pre-existing
OpenCode shim installed before this task.

| Target | Portable bundle installed | Activated | Operationally qualified |
|---|---|---|---|
| OpenCode | No | No | No |
| Claude Code | No | No | No |
| Codex CLI | No | No | No |
| Pi | No | No | No |

Linux is the fixture-test platform. macOS and WSL are unverified. A passing mock,
schema check, package render or subprocess exit does not change this table.

`plugin.yaml` declares known incomplete aggregate capabilities `unsupported`,
while implemented but not natively qualified capabilities remain `unverified`.
Fixing UAT's external-plugin allowlist alone would not resolve the native
provenance/tool-discovery gaps.
