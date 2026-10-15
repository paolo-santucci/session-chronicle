---
date: 2026-10-15
status: requested-not-implemented-in-toolkit
---

# UAT contracts required by Session Chronicle

Reference: UAT `4d3c145f099c6dedad3373ef9fc469936ce9c651`, version 0.1.0.
All paths below are relative to that checkout. Chronicle remains independently
owned. These are toolkit requests, not extra keys invented for `plugin.yaml`.
UAT's accepted `docs/design.md` describes the desired ownership; its actual loader,
renderer and policy implementation establish what can work today.

## 1. External adapters must be qualifiable — blocking all targets

**Code:** `uat/adapters/common.py:245-252`, `uat/packages.py:56-62`,
`uat/deployment.py:34-46`.

**Reproduce:** select a schema-valid external `session-chronicle` plugin requiring
a custom feature capability and supply an adapter implementation with that
capability marked `unverified`. Render with the real adapter and apply its files.
The renderer first labels every plugin outside its built-in allowlist and its
required capabilities `unsupported`. Package artifacts cannot promote the label;
even exact-fingerprint evidence cannot qualify `unsupported`.

**Observed in-memory planning probe:** required `chronicle.capture` stayed
`unsupported`, and appeared in the compatibility blockers, although its adapter
declared `unverified`. File copying succeeded independently.

**Request:** distinguish absent implementations from present but unverified package
adapters. Preserve exact-artifact native qualification; no hardcoded Chronicle
allowlist exception, package self-certification, or omission of requirements.

**Acceptance:** local and pinned-archive packages can render unverified capability
implementations; absent adapters remain unsupported; fabricated/obsolete/mismatched
evidence is rejected; real evidence can qualify the exact implemented capability.

## 2. Custom memory operations need explicit policy mappings — blocking

**Code:** `uat/schemas/definition.json:21-32`,
`uat/adapters/common.py:11-41,144-157`, `uat/adapters/render.py:41-57,107-117`,
`uat/resources/native_hook.py:97-118`, `uat/resources/pi.ts:152-179`,
`uat/resources/opencode.ts:56-63`, `uat/telemetry.py:23-27,167-168`.

**Reproduce:** bind `{{tool:memory_find}}`, declare a policy capability outside the
built-in enum, or execute a memory tool through a deny-unknown native guard.
Binding/schema/guard resolution cannot represent the package-owned operation.
The first probe actually returned `Unknown portable binding: tool:memory_find`.

**Request:** collision-checked package operation registration connecting logical
operation, native tool ID, resource extraction, side effects and policy. The five
tools are `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`, and
`memory_session_context`. The last checkpoints and needs mutation authorization;
its identity/workspace must not be taken from its empty model input schema.

**Acceptance:** explicit least-privilege grants/denies/asks work for all five tools,
including nested/delegated invocations. Truly unknown tools remain denied or
coverage-unknown. Telemetry receives documented metadata only; it must not record
query text, note bodies, journal payloads or arbitrary tool input/output. Missing
observations are unknown, never zero. Do not alias all custom tools to `process.exec`.

## 3. Native hook/plugin composition — blocking command-hook targets

**Code:** `uat/adapters/render.py:86-104,122-133`,
`uat/packages.py:48-53`, `uat/schemas/definition.json:57-63`.

**Reproduce:** map Chronicle configuration to `.claude/settings.json` or
`.codex/hooks.json`; UAT already emits those paths, so copying fails with
`Plugin artifact collision`. Mapping only a hook script elsewhere copies bytes
but never registers the handler. The equivalent `opencode.json` collision was
reproduced in memory. A file containing `{{harness}}` was copied literally.

**Request:** structured, deterministic contributions with named ownership, ordering,
failure/deny aggregation, activation and removal. Preserve UAT status, statistics
and policy hooks. Plugin activation prose is not configuration merging.

**Acceptance:** combined hooks load once; no success overrides a deny; changes
invalidate fingerprints; package removal removes only its owned contributions;
interactive and headless failures have explicit outcomes. No generated settings
overwrite or textual merge hack. Native plugin/tool names remain adapter-owned.

**Original-input case:** work-tools `plugins/status-inject.ts:18-46` mutates the
prompt that the old Chronicle `index.ts:233-264` captures. An earlier status handler
can therefore enter evidence as user input. Expose/retain original user-input
provenance; preferred ordering or stripping status-shaped user text is not proof.

## 4. Trusted per-call provenance, separate from statistics runs — blocking

**Code:** `uat/resources/opencode.ts:17-35,48-54`, native hook/runner/extension
bridges; compare `docs/implementation-contract.md` statistics attribution contract.

**Reproduce:** installation directory A, active native session in worktree B;
concurrent primary and child runs; equal native IDs from different harnesses.
Static installation-root status/telemetry and current-session memory cannot safely
share a guessed directory. Codex/Pi surfaces lacking actor/event identity cannot
attribute Chronicle journal data merely because the statistics bridge has a run ID.

**Request:** a documented versioned context containing trusted harness, native
session identity, current workspace, known actor/parent classification and stable
event identity, with lifecycle ownership. Task/run/turn IDs remain distinct.

**Acceptance:** concurrent sessions/worktrees never cross-write; child/unknown
ownership never becomes primary evidence; missing provenance blocks required
operations; tool arguments cannot select the session; no last-active-session file,
transcript-based inference, guessed environment flag or other-project fallback.
Explicit continuation connects records without impersonating native resume.

## 5. Dependency installation and activation integrity

**Code:** `uat/qualification.py:39-53`, package `requires` resolution and adapter
activation strings. `requires` resolves definitions, not runtime libraries.

**Reproduce:** render a TS adapter and package manifest, then install dependencies
under its managed plugin directory. Activation's discovered-file inventory now
contains files absent from the rendered fingerprint. Loading the raw Chronicle
checkout can also traverse ignored files/symlinks because resource discovery is
recursive (`uat/definitions.py:116-125`).

**Request:** explicit prerequisite/version/lock provenance and supported dependency
locations/inventory rules. Inspection must not install anything. Host-provided
runtime modules should be reused where their actual contract supports it.

**Acceptance:** allowlisted physical local package and identical pinned archive,
relocation tests, no sibling checkout paths, acyclic explicit skill selection,
and separate rendered/installed/activated/qualified statuses. No automatic package
manager run hidden inside rendering. Do not bundle duplicate runtime instances.

## 6. Persistent memory must not overlap replacement surfaces

**Code:** `uat/deployment.py:19-24,122-134,160-186,246-252`.

**Reproduce:** declare `docs-root: .opencode/skills/knowledge`, seed sessions,
topics and `.drafts/pending`, then prepare normal replacement. That directory is
inside UAT's wholesale skill replacement surface. Default `docs/` is outside it,
but that alone does not prove arbitrary custom roots safe.

**Request:** persistent-root registration/preflight or an equivalent verified
non-overlap check before mutation. Chronicle rejects configuration-overlapping
roots locally; UAT must not delete existing state before Chronicle can start.

**Acceptance:** successful sync, removal, rollback and failed-sync recovery retain
sessions/topics/pending/drafts byte-for-byte, native session state and authored
AGENTS frontmatter/prose. Overlap and ambiguous ownership fail before mutation;
no automatic relocation or historical rewrite. Work-tools and UAT must not alternate
ownership of the same deployment surfaces.

## Evidence boundaries

Fixture package/load/render tests belong in this repository. Native qualification
requires exact builds, authorized activation, authentication where needed, positive
and negative permission probes, and complete UAT statistics evidence. Chronicle
does not emit duplicate lifecycle statistics or forward journal content to
`uat.telemetry.record_event`. Required unsupported guarantees keep deployment blocked.
