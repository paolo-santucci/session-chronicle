---
name: session-chronicle
description: >-
  MUST BE USED at every checkpoint to maintain the project's CHRONOLOGICAL session
  memory — an append-only journal under <docs-root>/sessions/. PROACTIVELY invoked
  after a logical group of work, after commits, and at end-of-session, and is called
  by the update-status skill as a hand-off right after STATUS.yaml is written. Also
  fires on explicit signals ("checkpoint", "save progress", "end of session", "that's
  it", "talk to you tomorrow"). Writes one entry per session (UPSERT), wikilinking the
  topics discussed so a subject can be reconstructed across time. NOT for STATUS.yaml
  (that is update-status) and NOT for source code.
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(bash .claude/skills/session-chronicle/scripts/*.sh), Bash(python3 .claude/skills/session-chronicle/scripts/*.py *)
version: 1.5.0
---

# Session Chronicle

Maintains the **chronological session memory** of the target project: an append-only journal of dated entries under `${docs-root}/sessions/`, one entry per working session, that records *what was done, what was decided and why, and what stayed open* — and wikilinks the topics touched so the discussion on any subject can later be reconstructed.

This memory exists **for Claude Code to re-read**, not primarily for the human. The companion read-path (the `UserPromptSubmit` hook, see *Hooks* below) injects relevant entries back into context automatically — that is what makes this memory worth writing.

`${docs-root}` defaults to `.claude/docs` unless the target `CLAUDE.md` declares a `docs-root:` override in its frontmatter. Session entries live in `${docs-root}/sessions/`.

## Scope

**Owns:**
- `${docs-root}/sessions/*.md` — the chronological journal (this skill is the only writer).
- `${docs-root}/topics/*.md` — atomic topic notes, materialised lazily when a subject recurs across ≥2 sessions (Step 5).
- The wikilinks (`[[topic-slug]]`) embedded in those entries.

**Does not own:**
- `STATUS.yaml` — that is `update-status`. This skill never touches it.
- `.claude/agent-memory/` — agent behavioural memory; different subject, different owner.
- Source code, tests, config.

## Operating principles

1. **Append-only chronology.** A `status: closed` entry is immutable history — never edit it. The current session has exactly one `status: open` entry; everything is appended there until the session closes. (Enforced by the `note-lint.py` PreToolUse hook.)
2. **One entry per session (UPSERT).** Multiple checkpoints in the same session coalesce into the same `open` entry — never fragment one session across many files.
3. **Spillover, not re-derivation.** Reuse the summaries `update-status` just wrote to `recently-completed` and the commit list; do not re-summarise the work from scratch.
4. **Link generously, materialise lazily.** Name every meaningful subject as `[[topic-slug]]` in the body even when no topic note exists yet — an unresolved link is a forward marker. A topic note is created only once the subject recurs across **≥2 sessions** (Step 5); never one note per mention.
5. **Provenance always.** Every entry records its `commits:` and any `plans:`/specs it touched. No invented work.
6. **Terse and atomic.** Optimise for cheap re-injection: short prose, no filler. The body is what gets re-read into context; every sentence pays rent.

## Language

Free-form prose (the three body sections) is written **in the language of the session** (so, for an Italian-conducted session, Italian) — this memory is for the consumer and the user, not a machine-only state file. **Slugs, tags, and the `type` enum are always English/kebab-case** for stable matching and linking. (This deliberately differs from `update-status`, which forces English in `STATUS.yaml`.)

## Workflow

### Step 1 — Resolve paths
Resolve `${docs-root}` from the target `CLAUDE.md` frontmatter (default `.claude/docs`). Ensure `${docs-root}/sessions/` exists (create if missing).

### Step 2 — Find or create the current session entry
The current session is identified by `status: open`, **not** by a `<today>` filename match — a session that crosses midnight keeps its original entry (whose filename carries the *start* date). But an `open` entry is the *current* session only if it is **recent**: closes are best-effort (Step 6 fires only on an explicit end-of-session signal), so a forgotten-to-close entry from days ago must NOT be adopted by an unrelated later session.

Glob **all** `${docs-root}/sessions/*.md`; read each one's `status:` and `date:`. An `open` entry is **adoptable** only if its `date:` is **today or yesterday** (the yesterday window covers a midnight crossing; an open entry older than that is a forgotten close, not the current session).

- **An adoptable `open` entry exists** → UPSERT into the most recent one, **regardless of whether its filename date equals today** (this is the day-rollover fix: never key the lookup on `<today>`, or a checkpoint past midnight would fork a second file and violate principle #2). Set any *other* `open` entries (stale or accidental duplicates) to `status: closed`.
- **`open` entries exist but all are older than yesterday** → they are forgotten closes: set each to `status: closed`, then create a fresh entry for today (next bullet).
- **No adoptable `open` entry** → start a new session: create `${docs-root}/sessions/<today>--<theme-slug>.md` from `references/session-note-template.md`, where `<today>` = `YYYY-MM-DD` and `<theme-slug>` is a short English kebab slug for the session's main theme. Set `status: open` and stamp `started:` (see Step 4).

### Step 3 — Update the body
**Consume the draft buffer first (v1.4.0).** If `${docs-root}/.drafts/<today>.draft.jsonl` exists and is non-empty, Read it: it is the raw tool-activity evidence passively captured by the `capture-signals.py` hook (file writes, significant bash commands, prompts). Use it to crystallise — nothing real missed, nothing invented; the buffer is *evidence*, never pasted verbatim into the entry. After the session entry is written, **truncate the draft** (Write it back empty): its signals are now crystallised, and a stale buffer would keep re-triggering the Stop nudge after the session closes.

Append/merge into the three sections, reusing the `recently-completed` summaries and commit list from the just-completed `update-status` run:
- **`## Cosa è stato fatto`** — what was done this session.
- **`## Decisioni e perché`** — each decision with its reason. This is the in-line decision log; it is read back by the retrieval hook.
- **`## Thread aperti`** — questions/work left open.

In every section, write subjects as `[[topic-slug]]` wikilinks. Keep prose terse.

### Step 4 — Update frontmatter
- `started:` — full ISO-8601 timestamp **with time and timezone** (e.g. `2026-06-14T23:30:00+02:00`), stamped **once** when the entry is created (Step 2) and never changed thereafter. This is what orders multiple sessions *within the same day* chronologically — the filename only carries the date. Get it with `date +%Y-%m-%dT%H:%M:%S%:z`.
- `updated:` — full ISO-8601 timestamp (same format), refreshed on **every** checkpoint. Besides recording last-touch, it breaks ties in Step 2's "more than one `open`" rule.
- `topics:` — keep in sync with the body `[[slug]]` links. Run `sync-topics-field.py <entry>` to set this deterministically instead of hand-editing.
- `commits:` — short SHAs from this session.
- `plans:` — paths of any spec/plan documents touched (else `[]`).
- `status:` — keep `open` for a mid-session checkpoint.

### Step 5 — Materialise recurring topics (v1.1.0)
A subject earns an atomic topic note once it recurs across **≥2 sessions** (threshold N, default 2).

1. List candidates: `memory-audit.py --materialization-candidates --threshold 2 --base ${docs-root} --json` → slugs that appear in ≥N distinct sessions but have no topic note yet.
2. For each candidate, resolve the canonical slug (dedup against existing notes + aliases): `slugify.py --resolve "<subject>" --base ${docs-root}`. The script prints the slug on stdout and the **match type** on stderr (`match: exact|alias|stem|new`). Act on the match type:
   - `exact` / `alias` → trustworthy: **UPSERT** into that note. Read it, enrich the distilled body, append the new session/plan path to `sources:`, bump `updated:`. Never duplicate.
   - `stem` → heuristic near-duplicate (e.g. `topic`/`topics`). It can be a **false positive** (distinct concepts that happen to share a stem). Do **not** UPSERT blindly: confirm the two are the same concept before merging. If yes, UPSERT and add the candidate to the existing note's `aliases:`. If not, treat as `new`.
   - `new` → create from `references/topic-note-template.md` with mandatory provenance (`sources:` = the sessions where it appears) and `links:` to related topics.
3. Topic-note bodies hold the **current distilled understanding** — not a log. History stays reconstructable from session backlinks (`backlinks.py <slug> --base ${docs-root}`).

Materialisation is **lazy and bounded**: never create a note on first mention; never auto-create one note per mention.

### Step 6 — Close on end-of-session
Only when the signal is an end-of-session one ("end of session", "that's it", "talk to you tomorrow", `SessionEnd`): set `status: closed`. After this, the entry is immutable.

### Step 7 — Confirm
Reply with exactly one line:

```
session-chronicle: <created|updated> sessions/<file> (status: <open|closed>, topics: <n>, materialised: <m>)
```

Nothing else.

## Hooks (registered per-target; not synced by sync-claude.sh)

This skill ships five hook scripts under `scripts/`. They are registered in the target's `.claude/settings.json` — see `references/hooks.settings.json` for the block to merge. `sync-claude.sh` does **not** touch settings, so registration is a one-time per-target step (automated later by the M3 `session-memory-bootstrap` skill).

- **`capture-signals.py`** (v1.4.0) — `PostToolUse` on `Write|Edit|Bash` + `UserPromptSubmit`. The **passive capture path**: mirrors meaningful tool activity (file writes, non-trivial bash, prompts) into `${docs-root}/.drafts/<today>.draft.jsonl`. Zero API calls, zero injected tokens (never writes stdout); noise-filtered, dedup by hash, drafts auto-pruned after 7 days. The draft is *evidence* consumed by Step 3, not memory — add `.drafts/` to the target's `.gitignore`.
- **`retrieve-inject.py`** — `UserPromptSubmit`. The **read-path**: lexically matches the prompt against sessions/ (and topics/), injects the top-k note *bodies* (frontmatter stripped, budgeted) into context. The budget is in **characters** (`MEMORY_INJECT_BUDGET_CHARS`, default 6000 ≈ ~1500 tokens), a cheap proxy for tokens. v1.4.0+ ranking: **BM25** body relevance (k1=1.5, b=0.75, flat IDF — saturates repeated terms, normalises note length; v1.5.0), internal synonym expansion (acronym ↔ spelt-out, never injected), recency-tiered scan capped at `MEMORY_INJECT_MAX_SCAN` (default 60 files, newest first — bounds latency as memory grows), and a `type:` boost that weights distilled topic notes above raw session logs. Read-only; always exits 0 (never blocks a prompt).
- **`topic-index.sh`** — `SessionStart`. Injects a compact orientation index (topic slugs + recent session titles). Not the content — orientation only. v1.5.0: appends a one-line **health check** (via `memory-audit.py --stale --dangling`) only when thresholds are exceeded (`MEMORY_HEALTH_STALE_MAX` default 5, `MEMORY_HEALTH_DANGLING_MAX` default 10, ~30 tokens) — this is what makes the audit actually run instead of relying on someone remembering to.
- **`note-lint.py`** — `PreToolUse` + `PostToolUse` on `Write|Edit`. PreToolUse blocks edits to `closed` session entries (append-only) and (v1.4.0) blocks content carrying secret-like patterns (GitHub/API/AWS/Slack tokens, private keys, non-loopback IPs) — notes are re-injected on every retrieval, so a leaked credential would resurface forever; Claude is asked to re-submit with `[REDACTED-*]` placeholders. PostToolUse validates frontmatter schema + provenance; `exit 2` reports violations back to Claude.
- **`checkpoint-nudge.py`** — `Stop`. v1.4.0, **active**: if no recent (today/yesterday) `open` entry is being journaled and today's draft buffer holds ≥3 signals (`MEMORY_DRAFT_NUDGE_MIN`), it asks to crystallise that concrete evidence; fallback (capture hook not registered): the original commit-today reminder. Self-limiting (honours `stop_hook_active`, goes quiet once a recent open entry exists).

### Maintenance scripts (on demand / periodically — M4)

Deterministic, read-mostly; the LLM only writes prose. Invoked by Step 5 and by audits.
- `memory-audit.py` — `--orphans` (topic notes with 0 backlinks), `--dups` (near-duplicate slugs/aliases), `--dangling` (links to non-existent topics), `--materialization-candidates [--threshold N]`, `--stale [--days D]`. `--json` for machine use. `--base ${docs-root}`.
- `memory-recall.sh <slug> [--topic|--sessions|--all]` (v1.5.0) — one-call recall of a **known** subject: prints the topic note body and the backlinking session ids in a single invocation (default `--all`). Use it instead of a `cat`+`grep` chain when you already know the slug; the read-path hook remains the way memory reaches you unprompted.
- `backlinks.py <slug> --base ${docs-root}` — sessions linking a slug (+ aliases); `--count` / `--json`.
- `slugify.py [--resolve "<title>" --base ${docs-root}]` — canonical slug + dedup resolution.
- `sync-topics-field.py <entry>` — realign a session's `topics:` to its body wikilinks.

## Quality bar
- Idempotent: a second checkpoint with no new work changes only `updated:`.
- Draft buffer consumed: after each crystallisation, `.drafts/<today>.draft.jsonl` is truncated.
- Exactly one `open` entry per day; closed entries never modified.
- Every body subject is a `[[slug]]`; `topics:` matches the body links.
- Prose terse and in English; slugs/tags English.
- `commits:`/`plans:` provenance present; no invented work.

## Anti-patterns
- Do not edit a `closed` session entry — create a new one. (The hook will block you.)
- Do not write `STATUS.yaml` — that is `update-status`. Hand-off only.
- Do not materialise a topic on first mention, or create more than one note per concept — UPSERT and dedup via `slugify.py --resolve`.
- Do not fragment one session across multiple files.
- Do not re-summarise work already summarised in `recently-completed` — reuse it.
- Do not inline long context into an entry; keep it atomic and link out.
- Do not treat the draft buffer as memory — it is uncommitted evidence: crystallise, then truncate. Never paste raw JSONL signals into a session entry.
- Do not write secrets into notes — the PreToolUse guard blocks them; use `[REDACTED-*]` placeholders.
- Do not output anything after the single confirmation line.

## Escalation
- If `${docs-root}/sessions/` grows large and `retrieve-inject.py`'s lexical match grows imprecise or slow, escalate to an FTS5 ranking index — **not** embeddings. Deferred until measured: at small N the pure-Python BM25 scan (recency-capped at `MEMORY_INJECT_MAX_SCAN`) is adequate.
- Recurring-subject topic notes are materialised in Step 5 (threshold N=2). To change N, pass `--threshold` to `memory-audit.py`.
