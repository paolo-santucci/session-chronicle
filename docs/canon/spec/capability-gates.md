---
domain: capability-gates
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Capability Gates

## Overview

The adjudication surface that separates what Chronicle implements in source, what is only fixture-verified, and what is natively qualified on each of the four supported harnesses — and names which actor (Chronicle or UAT) must act before a blocked gate can open (`docs/capability-matrix.md`, `docs/runtime-contracts.md`). Its user-visible result is the set of support claims an integrating project may repeat and the set it may not.

## Current behaviour

- **Asserts zero operational qualification.** "**No target is operationally qualified**"; `core` means an outcome shared by every adapter, not proof that an adapter delivers the required native events; `blocked` means a known missing runtime/UAT contract (`docs/capability-matrix.md:8-11`).
- **Reports installed / activated / operational as three independent axes.** For the portable 0.2.1 implementation — not the pre-existing OpenCode shim — all four targets read No/No/No (`docs/capability-matrix.md:52-60`).
- **Labels aggregate capabilities by evidence grade.** Known incomplete aggregate capabilities are declared `unsupported`; implemented-but-not-natively-qualified capabilities stay `unverified` (`docs/capability-matrix.md:65-66`).
- **Downgrades external-plugin capabilities in UAT.** The renderer labels any plugin outside its built-in allowlist and every required capability `unsupported`; package artifacts cannot promote that label and even exact-fingerprint evidence cannot qualify an `unsupported` (`docs/uat-integration-request.md:22-24`). The planning probe observed `chronicle.capture` staying `unsupported` and landing in compatibility blockers (`docs/verification.md:207-213`).
- **Distinguishes absent adapters from present-but-unverified adapters.** Absent implementations remain unsupported; present package adapters render as unverified until exact real evidence qualifies them (`docs/uat-integration-request.md:30-36`).
- **Blocks custom memory-operation policy mapping.** Binding, schema and deny-unknown guard resolution cannot represent the package-owned operation; the probe returned `Unknown portable binding: tool:memory_find` (`docs/uat-integration-request.md:45-48`). UAT must not alias all custom tools to `process.exec` (`:60`).
- **Composes Codex hooks but does not qualify them.** Structured contributions with named ownership, ordering, deny aggregation and removal are implemented; fixtures establish eight owned contributions, retained matchers, three-second shutdown limits and collision refusal, and explicitly do **not** establish native trust, execution, concurrency, denial coverage or workflow success (`docs/uat-integration-request.md:67-80`, `docs/verification.md:188-191`).
- **Records the original-input contamination case.** A status handler that mutates the prompt can enter evidence as user input; preferred ordering or stripping status-shaped text is not proof of provenance (`docs/uat-integration-request.md:82-85`).
- **Requires trusted per-call provenance.** Harness, native session identity, workspace, actor/parent classification and stable event identity must arrive as a versioned context, never from tool arguments, a last-active-session file, transcript inference or another project's directory (`docs/uat-integration-request.md:98-106`).
- **Keeps four lifecycle states separate.** Rendering, installation, activation and qualification are distinct; inspection must not install anything and rendering must not run a package manager (`docs/uat-integration-request.md:113-126`). README echoes this: "Source packaging and inspection rendering do not imply installation or activation" (`README.md:73`).
- **Runs overlap preflight before mutation.** Persistent roots are checked against UAT's replacement surfaces; overlap and ambiguous ownership fail before any write (`docs/uat-integration-request.md:131-139`).
- **Refuses to convert weak evidence into a support claim.** "A passing mock, schema check, package render or subprocess exit does not change this table"; Linux is the fixture-test platform, macOS and WSL unverified (`docs/capability-matrix.md:62-63`); "An unavailable native runtime remains blocked, never a passed test" (`docs/verification.md:135`).
- **Publishes the per-harness installed executable next to the reference target** (`docs/verification.md:159-164`), and states that not running a runtime is consistent with making no compatibility claim (`README.md:50-53`).
- **Declares enforcement limits rather than immutability.** Only explicitly intercepted native operations are guarded; arbitrary shell/Python/external writers are not universally intercepted and filesystem immutability must not be claimed (`docs/runtime-contracts.md:30-38`).
- **Leaves UAT's unknown-tool denies intact while integration is pending** (`docs/runtime-contracts.md:40-42`), and never claims completion from exit zero or a tool observation (`:65-66`).
- **Emits no duplicate lifecycle statistics** and forwards no journal payloads to `uat.telemetry` (`docs/runtime-contracts.md:59-65`, `docs/uat-integration-request.md:147-153`).

## Public contracts

- **Status-axis contract.** `installed`, `activated`, `operationally qualified` are independent columns; a Yes in one implies nothing about the others (`docs/capability-matrix.md:55-60`).
- **Workflow acceptance matrix** — 33 workflow rows × 4 harness cells + one required-acceptance column. This is the table an integrator cites or is contradicted by (`docs/capability-matrix.md:14-48`).
- **UAT integration contract** — six numbered requests, each with **Reproduce**, **Request/Implemented** and **Acceptance** text, with per-item status: §1 resolved in UAT, §2 blocking, §3 resolved for Codex package declarations, §4 blocking, §5 no status label, §6 resolved in UAT preflight (`docs/uat-integration-request.md:14-145`).
- **Enforcement coverage contract** — one row per surface with mechanism and required probe/limit, plus "required guarantees missing on an adapter block its operational qualification" (`docs/runtime-contracts.md:26-42`).
- **Identity and provenance policy** — native session identity is trusted only when obtained from runtime context; the neutral stdin protocol is a process boundary, not an authentication service, and an arbitrary OS process can fabricate JSON; legacy bare session IDs remain unknown-harness records; continuation is additive metadata, never resume impersonation (`docs/runtime-contracts.md:44-57`, `README.md:34-36`).
- **Evidence-boundary contract** — fixture tests belong in-repo; native qualification requires exact builds, authorized activation, authentication where needed, positive and negative permission probes, and complete UAT statistics evidence (`docs/uat-integration-request.md:147-153`).
- **Claim registry for integrators.**
  - *May claim*: source/fixture verification; package load/render for all four UAT targets; Codex hook composition fixtures; named limitations (`docs/verification.md:124-127,188-191`).
  - *May not claim*: four-harness operational certification (`README.md:7-10`); compatibility against the reference versions (`README.md:50-53`); filesystem immutability (`docs/runtime-contracts.md:35`); universal secret detection (`:36`); native resume or continuation impersonation (`:52-56`); statistics-run IDs as Chronicle session identity (`:63-65`).

## Enumerated providers / limits

**Targets — reference version vs installed executable vs conformance** (`docs/verification.md:159-164`; reference set also `README.md:50-51`):

| Harness | Reference target | Installed at inventory | Native conformance |
|---|---|---|---|
| OpenCode | 2.0.26 | 2.0.29 | Not run; portable bundle not installed |
| Claude Code | 2.1.299 | 2.1.220 | Not run; stated incompatible with newer reference contracts |
| Codex CLI | 0.163.0 | 0.163.0 reported by UAT in Ansel | Chronicle not activated; exact-artifact qualification pending |
| Pi | 1.2.0 | Absent | Blocked |

**Qualification ladder** (closed set): absent implementation → `unsupported` → `unverified` → qualified by exact-artifact evidence (`docs/capability-matrix.md:65-66`, `docs/uat-integration-request.md:30-36`).

**Capability set — 33 rows** (`docs/capability-matrix.md:14-48`), grouped by evidence grade:
- *`Core` on all four harnesses*: qualified identities, draft/checkpoint durability, concurrent writers, crash recovery, presentations/evidence, legacy reads, cross-harness retrieval (`:20-25,39-40`).
- *Implemented and fixture-tested* (not runtime-qualified): file/process signals and session-start index on OpenCode and Claude Code; BM25 prompt retrieval on OpenCode, Claude Code and Codex (`:17,26,27`).
- *Blocked with a named missing contract*: selective prompts (§16), primary-only capture (§18), replayed delivery (§22), compaction/handoff (§28), all five `memory_*` tools (§29-33), enrichment (§34), bootstrap (§35), topic refactoring (§36), secret/history guard (§37), permissions (§43), package loading/rendering (§44), sync/rollback preservation (§45), status/statistics coexistence (§46), interactive/headless operation (§47).
- *Universal non-guarantee*: shell/external protection is `Limited` on every harness (`:38`).

**Per-harness gates and blocking owner:**
- **OpenCode** — supports: native V2 session/tool hooks plus five registered memory tools, SDK parent check, trusted session location/parent (`README.md:192`). Blocked: original-user prompt provenance, UAT custom-tool policy, secret-guard coverage, permissions, headless/interactive qualification. Owner of unblocking action: **UAT** (§2 policy mappings, §4 provenance, plus runtime-version qualification).
- **Claude Code** — supports: native command-hook translation, native actor check, native hook guard, fixture-tested retrieval and index (`README.md:193`). Blocked: memory-tool native discovery, trusted tool-call transport for `memory_session_context`, hook composition, statistics composition, runtime version. Owner: **UAT**; the memory-tool discovery gap is explicitly listed as a UAT dependency (`README.md:193`).
- **Codex CLI** — supports: UAT-composed 0.163.0 command-hook translation; successful Bash/native tool IDs are translated and preserved (`README.md:194`, `docs/verification.md:193-199`). Blocked: primary-actor provenance (absence of child fields is ambiguous with internal/synthetic sessions), prompt/event ID uniqueness, patch shape, capture, trusted memory-tool transport, `memory_session_context`. Owner: **UAT** versioned broker operation carrying trusted harness/thread/turn/workspace/actor (`docs/uat-integration-request.md:155-168`) plus activation in Ansel, which no document assigns.
- **Pi** — supports: native extension/tool registration; read tools use session manager/cwd (`README.md:195`). Blocked: role/primary classification, stable prompt IDs, automatic index injection, capture and enrichment, `memory_session_context` primary provenance. Owner: partly **UAT** (§4 provenance), partly **not assigned** because the runtime is absent.

**Declared limits:**
- Fixture platform is Linux only; macOS and WSL are unverified (`docs/capability-matrix.md:62`).
- Host must provide `flock`, hard links, atomic rename and directory `fsync` with cooperating writers (`README.md:46`).
- Composed Codex contributions: eight owned, three-second shutdown limits (`docs/verification.md:188-191`).
- Five custom memory tools require explicit least-privilege grants, including nested/delegated invocations; telemetry is bounded categorical metadata only (`docs/uat-integration-request.md:51-60`).
- "UAT reference versions are not certification of Chronicle or compatibility ranges" (`docs/runtime-contracts.md:11`).

## Cross-domain dependencies

- `capture` — selective prompts, file/process signals and primary-only capture are the gated rows (`docs/capability-matrix.md:16-18`).
- `session-journal` — durability, replayed delivery, concurrent writers, crash recovery (`:21-24`).
- `retrieval` — BM25 prompt retrieval, session-start index, degradation to `find` (`:26-27`).
- `memory-tools` — the five `memory_*` tools and their policy/UAT mapping gap (`:29-33`, `docs/uat-integration-request.md:38-60`).
- `write-safety` — secret/history guard and shell/external protection rows (`:37-38`, `docs/runtime-contracts.md:30-38`).
- `topic-memory` — enrichment, bootstrap, topic refactoring gates (`:34-36`).
- `harness-adapters` — per-adapter native surface and integration boundary (`README.md:188-201`).
- `runtime-architecture` — `chronicle.py` operation protocol with trusted adapter context; single-writer/durable publication (`README.md:31-36,359-360`).
- External subsystems: the sibling **UAT toolkit** (policy, composition, qualification), the **work-tools** `status-inject` plugin (`docs/uat-integration-request.md:82-85`), and the package builder (`docs/verification.md:184`).

## Gaps

- **`plugin.yaml` capability declarations are unverified.** `docs/capability-matrix.md:65-66` asserts what the manifest declares; the manifest is outside this slice's read set, so the exact capability names and their `unsupported`/`unverified` values remain unconfirmed.
- **Version-mismatch semantics differ between harnesses without a rule.** OpenCode installed 2.0.29 against reference 2.0.26 and Claude Code installed 2.1.220 against reference 2.1.299 are both labelled "Runtime version mismatch" (`docs/capability-matrix.md:47`, `docs/verification.md:161-162`), but one is newer and one older than its reference. No document states whether an installed-only-newer build is a defect or merely an unverified range.
- **UAT request §5 carries no status label.** §1, §3 and §6 are marked resolved/implemented and §2/§4 blocked; dependency and activation integrity (`docs/uat-integration-request.md:108-126`) has neither marker, so whether it currently blocks integration is a human call.
- **The Codex activation owner in Ansel is unassigned.** `docs/verification.md:163` records "0.163.0 available in Ansel; Chronicle not activated" and `docs/uat-integration-request.md:165-166` says the app-server transport "deliberately disables hooks" with no production broker — no document names who activates or brokers it.
- **OpenCode "Composition tests" is not backed by a named test.** The matrix grades status/statistics coexistence for OpenCode as "Composition tests" (`docs/capability-matrix.md:46`), while the only recorded OpenCode composition evidence is an in-memory `opencode.json` collision probe (`docs/uat-integration-request.md:70-71`, `docs/verification.md:213`). Whether a real composition run exists is unresolved.
- **Secret/history guard coverage conflicts at the harness level.** The matrix assigns Codex a "Failure/coverage gap" but Pi a functional "tool_call guard" (`docs/capability-matrix.md:37`), while `docs/runtime-contracts.md:30-38` describes mechanisms per surface, not per harness. Which harness actually enforces which guard surface cannot be reconciled from these documents.
- **Three documents carry three unrelated status vocabularies** — `acceptance-matrix` (`docs/capability-matrix.md:3`), `source-evidence-not-runtime-certification` (`docs/runtime-contracts.md:3`) and `partially-implemented-custom-operation-api-blocked` (`docs/uat-integration-request.md:3`). No document states whether these labels are externally meaningful to an integrator or internal bookkeeping only.
- **`docs/verification.md` mixes method with dated run logs.** This slice used its gate declarations, native-qualification table and composition limits only; superseded run counts (`:84-152,171-216`) are verification logs, excluded from canon by policy, and no document says when such a log stops being authoritative.
