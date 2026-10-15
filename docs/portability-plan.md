---
date: 2026-10-15
status: fixture-verified-native-blocked
---

# Portable Chronicle milestones

Owner: this repository. Targets: OpenCode, Claude Code, Codex CLI, Pi only.
UAT and work-tools are read-only references. No deployment or publication is part
of this implementation. The detailed planning record is
`../.opencode/plan/session-chronicle-portable-uat.md`; this file is the durable
repository-local milestone ledger.

## Baseline and ownership

The starting working tree includes uncommitted atomic-topic and V2 work; it is not
equivalent to HEAD `2d532d6888e7c44b48463eabd3ce96efbaaa86e5`. Preserve it and the
project's historical memory. Before implementation, rerun results were: 119 Python
memory tests, 22 repository tests, 12 Bun adapter tests, and typecheck passed.

Chronicle owns persistence, capture selection, identity, retrieval, schemas,
semantic workflows and native adapters. UAT owns resolution, compilation,
configuration composition/ownership, deployment transactions and qualification.
One shared core, native event translation at the edge, no orchestration daemon.

## Milestones

| Milestone | Acceptance | State |
|---|---|---|
| M0 inventory | Existing workflows/test coverage and four-target matrix recorded; runtime/API and actual UAT gaps identified | Complete |
| M1 neutral contract | Versioned context/operations; qualified session identity; explicit legacy policy; capability gates | Implemented; schema/tests |
| M2 shared core | Regression coverage; worktree isolation; primary-only capture; durable replay/recovery; guarded mutations | Implemented; 119 existing + 60 portable tests pass; review fixes approved |
| M3 neutral workflows | Enrichment/bootstrap/refactor retain their full gates; physical resources; real schema validation | 17 workflow/scanner/schema tests pass |
| M4 package/adapters | Exact version, actual UAT manifest, reproducible package, four native translation layers | Implemented and fixture-tested; full native parity blocked by declared contracts |
| M5 UAT inspection | Real loading/resolution/rendering; coexistence and refusal cases; state-preservation checks in fixtures | 14 package + 20 real UAT tests pass; successful sync remains blocked |
| M6 native qualification | Exact artifact/runtime, interactive/headless positive and negative probes | Blocked |
| M7 delivery | README, status, precise integration requests and exact verification evidence | Documented; 325 tests pass, deployment blocked |

## Contract decisions

- Trusted adapter context supplies harness, native session ID, workspace and actor
  role. Model tool arguments cannot set these. Session identity is separate from a
  UAT execution/task/turn ID. Unknown provenance is not primary-session evidence.
- Canonical new identity: `chronicle:v1:<harness>:<base64url(native-id)>`, UTF-8,
  unpadded. The core retains original identity metadata. Existing bare identities
  remain legacy/unknown-harness; immutable evidence is never silently rewritten.
- Native operations become `prompt.submit`, `files.write`, `files.edit`,
  `files.patch`, or `process.exec`. Only existing selective payloads are retained;
  file bodies, tool output and full transcripts do not become journal content.
- Capture requires a stable native event identity. Replay prevention must cover
  draft, pending and published evidence under the same worktree writer lock.
  Identical text from different events is not a duplicate.
- All state remains under validated docs-root. Overlap with replaceable harness
  configuration is rejected. Explicit continuation links do not resume a native
  session or infer missing historical ownership.
- `memory_session_context` checkpoints and is therefore mutating. Other memory
  queries remain read operations. Retrieved content is untrusted reference data.
- Native write hooks protect the operations they intercept, not arbitrary shell,
  external processes or the filesystem. Missing required guards block qualification.
- Explicit semantic workflows preserve their stop conditions and require actual
  permitted tools; prompt instructions and frontmatter are not permission grants.

## Evidence and blocking dependencies

See [capability matrix](capability-matrix.md) and
[toolkit requests](uat-integration-request.md). UAT's external-plugin qualification
dead end, custom-tool policy mapping and configuration composition are real code
limitations, not missing Chronicle manifest keys. Required guarantees stay required.

Runtime probes: OpenCode 2.0.29 installed (UAT reference 2.0.26), Claude Code
2.1.220 installed (reference 2.1.299), Codex and Pi absent. No authentication or
model-backed workflow probe was performed. Installation/activation requires a
separate explicit request; static and fixture tests cannot qualify native behavior.

Spec gap: no `docs/canon/spec/INDEX.md` exists. Implementation documentation is
grounded in source, tests and cited runtime contracts rather than an absent canon.

## Remaining work after this implementation

- Establish original-user prompt provenance before activating prompt capture on
  any target. Preserve the core capture policy while native contracts are missing.
- Provide trusted Claude/Codex custom-tool discovery/transport; resolve Codex
  actor/result/event attribution and Pi actor/stable prompt-event attribution.
- Compose UAT-owned configuration and explicit memory-tool policy; then qualify
  implemented capabilities on exact native builds. Known unsupported requirements
  remain unsupported even if the toolkit's external-plugin allowlist is fixed.
- Qualify successful sync/removal/rollback and live semantic workflows in authorized
  disposable projects. Current refusal-preservation tests do not prove successful sync.
- Expose explicit continuation through a trusted native entrypoint if required;
  the validated core API does not by itself create a discovered native workflow.
- Define trusted mapping for generated maintenance-helper copies; exact-path
  filtering deliberately retains ambiguous commands rather than guessing ownership.

## Repository and package name

At the user's request, the GitHub repository, local checkout directory and npm
package are named `session-chronicle`. The portable plugin ID already used this
name. The remote is `git@github.com:paolo-santucci/session-chronicle.git`.
The installer writes the new ownership name and recognizes existing legacy
ownership markers. Historical journal content retains its original names.
