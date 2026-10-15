---
name: session-chronicle-bootstrap
description: >-
  Use ONLY when the user explicitly asks to initialise / backfill the session-memory
  system in a project. Concrete trigger phrases: "bootstrap session memory", "backfill
  the chronicle", "initialise session memory from past plans", "seed the session
  journal", "inizializza la memoria di sessione", "popola la cronologia dallo storico",
  "fai il backfill della memoria". Run-ONCE per project: reads prior specs/plans/decisions
  /STATUS/git, synthesises an initial chronology + first topic notes. Idempotent — refuses
  if sessions/ is already populated unless the user passes --force. NOT for routine
  checkpoints (that is the session-chronicle plugin, which runs continuously) — NEVER
  invoke proactively or as part of another workflow.
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(python3 .opencode/skills/session-chronicle-bootstrap/scripts/*.py *), Bash(python3 .opencode/skills/session-chronicle/scripts/*.py *)
version: 2.1.0
---

# Session Chronicle Bootstrap

One-shot seeding of the chronological journal and the first topic notes from a project's existing history. After this runs once it is never needed again: ongoing capture belongs to the `session-chronicle` plugin, which runs continuously and needs no help.

This skill is the **backfill**; the plugin is the **runtime**. They ship together and share one note schema.

`${docs-root}` defaults to `docs` unless the target `AGENTS.md` declares a `docs-root:` override in its frontmatter.

Bootstrap, explicit enrichment and topic refactoring use an LLM for semantic prose.
The plugin's automatic factual checkpoint path stays LLM-free.

## Scope

**Owns:**
- The one-time backfill of `${docs-root}/sessions/` and `${docs-root}/topics/` from history.
- `scripts/scan-history.py` — the read-only history manifest that feeds the backfill.
- A bootstrap report under `${docs-root}/reports/`.

**Does not own:**
- The note schema. That belongs to the `session-chronicle` skill; this one reads its templates rather than keeping a second copy that could drift.
- Ongoing capture, retrieval, and the write-path guards — all owned by the plugin.
- `STATUS.yaml`, source code, or anything outside `${docs-root}`.

**Requires:** the sibling `session-chronicle` skill installed in the same discovery root — they are installed together by this package's `cp -r`. It supplies `references/session-note-template.md`, `references/topic-note-template.md`, `scripts/slugify.py` and `scripts/memory-audit.py`. If it is absent, stop and tell the user to install the bundled skill before backfilling.

## Operating principles

1. **Run once, idempotent.** Refuse if `${docs-root}/sessions/` already has entries, unless the user passed `--force`. Even with `--force`, never overwrite an existing session entry — only add missing ones.
2. **Never invent history.** Every synthesised entry/topic is grounded in a real source (a spec/plan/decision path, a STATUS summary, or a commit). Provenance is mandatory.
3. **Cluster, don't transcribe.** One session entry per coherent unit of past work (a plan/spec, or a dated group of commits) — not one per commit.
4. **Write history, never wire runtime.** This skill produces files. It does not install, configure, or verify the plugin.
5. **One schema, one source.** Read the templates from `session-chronicle`; never fork them. A divergent shape here would produce a journal the plugin's note linter rejects.

## Workflow

### Step 1 — Pre-flight
- Require guarded `write`/`edit` tools for historical session entries. On a patch-only host, stop before any session or topic writes; the typed-topic patch subset does not permit session backfill.
- Confirm the sibling skill is present: `.opencode/skills/session-chronicle/SKILL.md` exists. If not, stop with `session-chronicle skill not installed — install the bundled skill first (see the package README)`.
- Run the scan: `python3 .opencode/skills/session-chronicle-bootstrap/scripts/scan-history.py --project $PWD`.
- If `sessions_populated` is `true` and the user did **not** pass `--force`: stop with `already bootstrapped — pass --force to add only missing entries`.

### Step 2 — Synthesise the chronology
From the manifest `items` (ordered by date), cluster coherent units of past work and write **one closed session entry per cluster** under `${docs-root}/sessions/<date>--<theme-slug>.md`, using `.opencode/skills/session-chronicle/references/session-note-template.md`:
- `date:` from the source item; `status: closed`; `commits:`/`plans:` = provenance for that cluster.
- Remove the template's `record-kind: semantic-summary` and `sources: []` fields for historical backfill without factual batches. These remain generic session notes, compatible with legacy validation; their provenance is the concrete `commits:`/`plans:` above. Do not invent factual batch IDs to satisfy the enrichment schema.
- Body: terse "Cosa è stato fatto" + "Decisioni e perché" reconstructed from the source doc/summary; wikilink every subject as `[[topic-slug]]` (slugs via `.opencode/skills/session-chronicle/scripts/slugify.py`).
- Prose in English; slugs/tags English.

### Step 3 — Seed the first topic notes
Read the sibling chronicle's `references/atomic-topic-contract.md` and
`references/zettelkasten-method.md`. Run
`python3 .opencode/skills/session-chronicle/scripts/memory-audit.py --materialization-candidates --threshold 2 --base ${docs-root} --json`
over the freshly-written entries. For each candidate, resolve the canonical slug
(`slugify.py --resolve`) and inspect whether it represents one idea or a broad subject.
Follow redirects to the terminal canonical atomic/structure note before UPSERT;
reject ambiguous names, missing targets or cycles rather than rewriting a redirect.
Create focused notes from the shared atomic template, or an annotated map of existing
ideas from `topic-structure-template.md`. A stem match never authorizes a merge.
Each new typed note needs concrete existing project-relative source paths, source
citations beside its central claim and explained body links matching `links`.
Preserve necessary qualifications; a short note can still contain several ideas.
UPSERT only the same idea, preserve stable addresses and creation dates, and leave
unchanged notes untouched. Historical sources do not establish current implementation
without further evidence. For comprehensive maintenance of an existing collection,
use the separate explicit `/session-chronicle-refactor` workflow rather than backfill.
Defer splits/merges of existing notes to that explicit workflow; bootstrap does not
own its snapshots or refactoring reports.

### Step 4 — Report
Write `${docs-root}/reports/session-chronicle-bootstrap-<YYYY-MM-DD>.md` (with `date:` frontmatter): entries created, topics seeded, and dangling/dubious candidates left for manual review.

### Step 5 — Confirm
Reply with exactly one line:

```
session-chronicle-bootstrap: <n> sessions, <m> topics seeded; report at <path>
```

Nothing else.

## Quality bar
- Re-running without `--force` on a populated project is a no-op that says so.
- Every seeded entry/topic carries real provenance; nothing invented.
- No existing session entry is ever overwritten.
- Notes conform to the `session-chronicle` templates, which are the schema its `note-lint.py` enforces — a backfilled journal must pass the same validator as a live one.

## Anti-patterns
- Do not invoke proactively or from another workflow — this is a deliberate one-shot.
- Do not write one session entry per commit — cluster.
- Do not invent decisions or work not present in the sources.
- Do not copy the note templates or `slugify.py` into this skill — a second copy is a second schema.
- Do not touch plugins, `opencode.json`, or anything outside `${docs-root}`.
- Do not duplicate a topic concept — UPSERT via `slugify.py --resolve`.
- Do not output anything after the single confirmation line.

## Escalation
- If history is too sparse to synthesise a meaningful chronology (e.g. no specs/plans and a shallow git log), say so and create only an index entry rather than fabricating detail.
