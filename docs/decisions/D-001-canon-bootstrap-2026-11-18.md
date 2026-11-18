---
id: D-001
title: Canon bootstrap — initial spec slices for session-chronicle
date: 2026-11-18
status: active
domain: process
---

### Canon bootstrap — initial spec slices for session-chronicle

- **Date:** 2026-11-18
- **Domain:** process
- **Status:** active
- **Context:** Project had no `docs/canon/spec/` slices. Cold-start was required before any `spec-changelog` write, because delta validation needs an existing slice to compare an `old:` against. Project brief (from the Phase 0.5 brainstorm): initial canon for `session-chronicle` 0.2.1, a four-harness (OpenCode, Claude Code, Codex CLI, Pi) project-memory system. Product-first shape — capability slices are the spine, with two subordinate architecture/data-model slices (`runtime-architecture`, `harness-adapters`). Gated capabilities are first-class: every slice states its own declared limits, and a dedicated `capability-gates` domain holds the cross-harness matrix of installed/activated/operational states, gate owners and permissible claims. Deliberate non-capabilities appear as declared limits, never silent absences. Scope is today's truth only, including contracts declared but not yet natively wired (continuations stay, marked pending). Excluded: roadmap ambition, competitor comparison, archived plans, refactor reports and verification logs. Deployment is in canon: one slice covers bundle contents, the standalone installer and the Chronicle/UAT ownership boundary.
- **Options considered:**
  1. Bootstrap from code with human review per slice — chosen.
  2. Hand-author each slice from scratch — rejected: too slow for eleven domains and discards the implementation as evidence.
  3. Skip canon and rely on `spec-changelog` from empty — rejected: no `old:` anchor exists, so delta validation cannot be strict.
  4. Fold the taxonomy to nine or ten slices — rejected by the operator in favour of full granularity, keeping the tool API and the operator health surface as their own slices.
- **Decision:** Run `canon-bootstrap` with a hybrid taxonomy (code-proposed, human-curated) and a per-domain human review gate before any promote. Eleven domains approved, all eleven promoted.
- **Rationale:** Cold-start was a hard prerequisite for later spec deltas. Drafts were held in `_draft/` and promoted only on explicit per-domain approval, so no unreviewed text ever became canon. Slices were kept lean and self-contained because a canon consumer reads at most a few slices per task, which means each one has to stand alone.
- **Owner:** project owner
- **Metrics to watch:** slices approved vs skipped (11/0 this run); gap count per slice (6–10; a high count signals either genuine ambiguity or an over-narrow read set); unresolved cross-domain refs (6, all external actors rather than missing domains, so no taxonomy gap was indicated).
- **Revisit date:** 2027-02-16 — bootstrap date plus 90 days, aligning with the first `canon-verify` staleness threshold.
- **Outcome:** TBD — fill in at revisit.

#### Bootstrap details

- Bootstrap date: 2026-11-18
- Domains approved (11): `capability-gates`, `capture`, `diagnostics`, `harness-adapters`, `memory-tools`, `packaging-deployment`, `retrieval`, `runtime-architecture`, `session-journal`, `topic-memory`, `write-safety`
- Domains skipped: none
- Cross-domain refs: 65 resolved internal edges, 6 unresolved external actors (UAT toolkit, `status-inject`, `agent-statistics`, native hosts, Codex broker). The unresolved set is external-actor scope, not missing taxonomy — no refinement is implied.
- Revision during the run: `runtime-architecture` was re-extracted once, because the durability protocol it must specify lives in `_checkpoint.py` and that path was missing from the initial read set. The corrected draft is code-verified and its lock-file gap closed.
- State file: `docs/canon/spec/_bootstrap-state.yaml`
- INDEX: `docs/canon/spec/INDEX.md`

#### Notable findings recorded in the canon

These are facts the bootstrap surfaced and deliberately preserved as canon rather than fixed, because the canon describes what is:

- Per-session retrieval repeat suppression is implemented only in the OpenCode adapter; the Claude Code and Codex hooks keep no cross-prompt state.
- Pi lifecycle checkpoints cannot succeed, because Pi always presents role `unknown` and the core refuses checkpointing for that role.
- Codex patches are guarded but never journaled: `apply_patch` is refused as an unsupported capture shape.
- A summary note without a valid `sources` list is dropped whole, while the README states it renders `sources: none`.
- The two-distinct-session topic materialisation threshold exists only in reference prose; no code enforces or reports it.
- The write-path guard's partial-protection boundary (supported direct native mutations guarded, arbitrary shell writes not) is documented but not pinned by any test.
- Three documents carry three unrelated frontmatter status vocabularies with no stated external meaning.
