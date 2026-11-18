---
domain: topic-memory
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Topic Memory

## Overview

Durable, project-shared knowledge stored as one Markdown note per idea under `<docs-root>/topics/`, with three note kinds (atomic, structure, redirect), stable slug addresses that survive splitting and merging, and an explicit refactoring workflow that reviews, splits, merges and repairs the collection (`skill/session-chronicle/scripts/_topic_graph.py`, `skill/session-chronicle-refactor/SKILL.md`).

## Current behaviour

- Every topic file is `<docs-root>/topics/<slug>.md` with `type: topic`; the filename stem must equal the frontmatter `id` and be a kebab-case slug (`skill/session-chronicle/scripts/_topic_graph.py:410-413`, `skill/session-chronicle/references/topic-note-template.md:3,7`).
- Topics carry exactly one of three note kinds — `atomic`, `structure`, `redirect` — and unknown or missing kinds are reported as findings (`skill/session-chronicle/scripts/_topic_graph.py:406-409`).
- An atomic note explains one independently reusable claim, concept, argument, decision-with-rationale or mechanism; the context, qualifications, evidence and example needed for that idea stay together, and another idea splits off only when it could be revised or disputed independently (`skill/session-chronicle/references/atomic-topic-contract.md:10-26`).
- Authoring is checked against five questions (single question answered, every paragraph supporting it, intelligible without the origin conversation, no part deserving its own title, relation to existing ideas) (`skill/session-chronicle/references/atomic-topic-contract.md:21-26`).
- A structure note has one navigation purpose: it states its scope in a sentence and gives annotated links to existing notes rather than duplicating their explanations (`skill/session-chronicle/references/atomic-topic-contract.md:104-107`, `skill/session-chronicle/references/topic-structure-template.md:2-20`).
- Split/merge decisions are steered by worked examples: a short note answering several independently changeable questions becomes a structure note plus children, while one indivisible observation-limitation-conclusion argument stays whole (`skill/session-chronicle/references/atomicity-examples.md:7-46`).
- Splitting a broad topic creates sourced atomic children first and keeps the old broad slug as a structure note; merging equivalent notes consolidates evidence in a survivor and leaves the other address as a redirect, never mapping a broad subject onto one arbitrary child (`skill/session-chronicle/references/atomic-topic-contract.md:113-130`).
- Bodies cite the supporting source and section beside the central claim with ordinary Markdown source links; topic `[[slug]]` links are reserved for conceptual connections with a stated relationship (`skill/session-chronicle/references/atomic-topic-contract.md:64-69`, `:93-102`).
- Lifecycle status is one of `active`, `merged`, `superseded`; atomic and structure notes must be `active`, redirects must be `merged` or `superseded` (`skill/session-chronicle/scripts/_topic_graph.py:424-430`, `:457-460`).
- A redirect note keeps an old address alive by declaring `redirects-to: <existing-slug>`, must link its target in the body, and must add explanatory prose beyond that link (`skill/session-chronicle/scripts/_topic_graph.py:457-464`, `skill/session-chronicle/references/topic-redirect-template.md:3-19`).
- Addressing is redirect-aware: an exact slug or alias wins first, then the redirect chain is followed to a terminal non-redirect note, and only afterwards are stem near-duplicates considered; cycles and dangling targets are errors (`skill/session-chronicle/scripts/_topic_graph.py:289-307`, `skill/session-chronicle/scripts/slugify.py:50-61`).
- Notes may declare `aliases` that identify the same idea; an alias owned by more than one note is reported as `alias-collision` (`skill/session-chronicle/scripts/_topic_graph.py:280-287`).
- Frontmatter `links` must list exactly the body `[[slug]]` wikilinks found outside fenced code, indented blocks, block quotes and inline code (`skill/session-chronicle/scripts/_topic_graph.py:447-449`, `:149-169`).
- `sources` must be a non-empty list of existing project-relative files (optional `#fragment`); absolute paths, `..` traversal, symlink escapes and missing files are rejected (`skill/session-chronicle/scripts/_topic_graph.py:431-438`, `:177-186`).
- Topic-to-topic `sources` edges form a provenance graph; a cycle is reported as `provenance-cycle` ("cannot establish independent provenance") (`skill/session-chronicle/scripts/_topic_graph.py:321-349`).
- Bodies are word-counted and flagged with a `review-length` warning above a configurable threshold (default 300 body words); the warning never blocks or truncates (`skill/session-chronicle/scripts/_topic_graph.py:471-474`).
- A note whose body has no prose outside code/evidence is rejected as `empty-body` (`skill/session-chronicle/scripts/_topic_graph.py:469-470`).
- Legacy topics without `note-kind` remain readable and are flagged `legacy-kind`; a typed topic cannot be downgraded back to untyped (`skill/session-chronicle/scripts/_topic_graph.py:406-407`, `:495-500`).
- Typed topics may not carry session/evidence identity fields (`record-kind`, `batch-id`, `session-id`) (`skill/session-chronicle/scripts/_topic_graph.py:403-404`).
- The validator emits an explicit disclaimer that structure checks cannot prove atomicity or factual truth (`skill/session-chronicle/scripts/_topic_graph.py:13`, `skill/session-chronicle/scripts/topic-maintenance.py:41`).
- A read-only `inventory`/`validate` command emits JSON with findings, per-note SHA-256, coverage counts (discovered/readable/unreadable/topics/sessions) and exits non-zero on unreadable records or validation errors (`skill/session-chronicle/scripts/topic-maintenance.py:12-46`).
- Topic writes made through the native patch tool are preflight-validated: only `Add File` with complete `+` content, or `Update File` with exactly one bare `@@` listing every original line then every replacement line (`skill/session-chronicle/scripts/topic-patch-lint.py:20-24`, `:70-114`).
- Preflight rejects partial/context/multi-hunk edits, stale originals, CR/NUL content, path traversal, symlinked targets/parents, hard-linked targets (`st_nlink != 1`), non-topic targets and any note lacking a valid `note-kind` (`skill/session-chronicle/scripts/topic-patch-lint.py:49-67`, `:104-113`, `:125-128`).
- Preflight rejects secret-like content in a proposed topic, requiring `[REDACTED-*]` placeholders instead (`skill/session-chronicle/scripts/topic-patch-lint.py:129-132`).
- Slug resolution dedupes a new title against the existing corpus: exact slug match, then alias match, then a conservative English plural-stem near-duplicate, else a fresh slug; the match type is reported on stderr as `match: exact|alias|stem|new` (`skill/session-chronicle/scripts/slugify.py:43-61`, `:64-71`).
- An ambiguous stem match (multiple surviving candidates) fails with an error rather than guessing (`skill/session-chronicle/scripts/slugify.py:56-58`).
- Slug text is normalised by NFKD decomposition, dropping combining marks, lowercasing, collapsing every non-`[a-z0-9]` run to a hyphen and trimming edge hyphens; there is no transliteration, so non-Latin script is removed rather than romanised (`skill/session-chronicle/scripts/slugify.py:20-24`).
- A title may be re-worded while the slug stays put; renames happen for address reasons only, and `created` is preserved while `updated` moves only on real content or metadata change (`skill/session-chronicle/references/atomic-topic-contract.md:46-48`).
- Stem near-duplicate folding is deliberately conservative: only English plural suffixes (`ies`, `es`, `s`) fold, and only while the stem stays at least 4 characters, preferring a missed merge over a wrong one (`skill/session-chronicle/scripts/slugify.py:27-40`).
- The mutable-note `topics:` frontmatter field is synchronised from a note's body wikilinks, rewritten under a writer lock, and skipped for immutable notes (closed status, factual-evidence, generated presentation) (`skill/session-chronicle/scripts/sync-topics-field.py:13-33`, `:41-51`).
- Startup orientation is available as a bounded, read-only topic index that never blocks session startup (`skill/session-chronicle/scripts/topic-index.sh:1-5`).
- A separate opt-in refactor workflow reviews the whole corpus and applies `keep | refine | split | merge | create | defer` transformations, retaining the old broad slug as a structure note on split and as a redirect on merge, with originals snapshotted under a run directory (`skill/session-chronicle-refactor/SKILL.md:99-121`, `:123-166`).
- Refactoring supports no-argument apply, `--dry-run` (no workflow file writes) and `--resume <report-path>` with hash-checked resumption; unknown arguments are rejected (`skill/session-chronicle-refactor/SKILL.md:26-33`, `:58-67`).
- Refactoring never edits session files, factual evidence, presentations, drafts, pending batches, source code or STATUS, and never edits historical session links to mask a refactor (`skill/session-chronicle-refactor/SKILL.md:22-25`, `:157-160`).
- Corpus discovery walks `topics/` and `sessions/`, skips `.drafts`, refuses symlinked directories, and treats unreadable or project-escaping notes as findings rather than reading them (`skill/session-chronicle/scripts/_topic_graph.py:222-278`).
- Frontmatter parsing is intentionally minimal: flat fields and flat lists only; duplicate fields, nested structures and unsupported YAML syntax become `:parse-errors` entries rather than crashes (`skill/session-chronicle/scripts/_topic_graph.py:95-133`).

## Public contracts

- `TopicGraph(base, project=None, proposed=None, *, include_evidence=True)` — read-only topic+session graph; exposes `topics`, `records`, `names`, `unreadable`, `findings`, `quality()`, `require_resolvable()`, `resolve(name)`, `source_topics(slug)`, `source_path(source)`, `supporting_sessions(name)`, `session_links()` (`skill/session-chronicle/scripts/_topic_graph.py:204-390`).
- `resolve(name) -> slug`: accepts an existing slug or alias (kebab-case only), follows `redirects-to` chains, raises on invalid slug, ambiguity, cycle or missing target (`skill/session-chronicle/scripts/_topic_graph.py:289-307`).
- `topic_findings(slug, note, graph) -> [finding]`, each finding shaped `{slug, code, severity, message}`; severities are `error` for typed notes and `warning` for legacy ones (`skill/session-chronicle/scripts/_topic_graph.py:393-475`).
- `proposed_graph_findings(proposed, base, project)` / `proposed_topic_findings(path, text, base, project)` — diff against the unmodified baseline; a write is rejected only for new/introduced errors, plus a newly broken inbound edge is escalated to `error` (`skill/session-chronicle/scripts/_topic_graph.py:478-501`).
- Frontmatter contract for `topics/<slug>.md`: `id, type: topic, note-kind, title, aliases, tags, created, updated, provenance, sources, status, [redirects-to], [supersedes], links` (`skill/session-chronicle/references/topic-note-template.md`, `skill/session-chronicle/references/topic-structure-template.md`, `skill/session-chronicle/references/topic-redirect-template.md`).
- Redirect contract: `status` in `merged|superseded`, `redirects-to` an existing slug, body links the target plus explanatory prose, old uniquely-owned aliases may stay on the redirect (`skill/session-chronicle/scripts/_topic_graph.py:457-464`, `skill/session-chronicle/references/topic-redirect-template.md:13-20`).
- Finding code vocabulary: `alias-collision, duplicate-id, redirect-cycle, redirect-target, topic-path, unreadable-topic` are resolution-blocking (`skill/session-chronicle/scripts/_topic_graph.py:15-16`); the full set additionally includes `invalid-frontmatter, topic-record-mixing, legacy-kind, invalid-kind, invalid-id, invalid-type, missing-title, missing-provenance, invalid-created, invalid-updated, missing-status, invalid-status, missing-sources, invalid-source, invalid-<list-field>, duplicate-<list-field>, links-mismatch, broken-topic-edge, redirect-status, redirect-context, empty-body, review-length, provenance-cycle, kind-downgrade` (`skill/session-chronicle/scripts/_topic_graph.py:401-501`).
- CLI: `topic-maintenance.py {inventory|validate} --project <dir>` prints one JSON object with `findings`, `semantic_review_required`, `review_notice`, and for `inventory` also `records`, `unreadable`, `coverage` (`skill/session-chronicle/scripts/topic-maintenance.py:34-46`).
- CLI: `slugify.py "<Title>"` prints just the slug; `slugify.py --resolve "<Title>" --base <dir>` prints the resolved slug on stdout and `match: exact|alias|stem|new` on stderr; exit 2 on invalid graph or ambiguity (`skill/session-chronicle/scripts/slugify.py:64-80`).
- CLI: `sync-topics-field.py <session-file>` rewrites `topics: [slug, ...]` from sorted unique body wikilinks and prints the new line (`skill/session-chronicle/scripts/sync-topics-field.py:36-51`).
- Hook contract: `topic-patch-lint.py` reads `{cwd, sessionID, patchText}` on stdin, is silent on success, and prints an actionable rejection to stderr with exit 2; it validates a snapshot, not the later write (`skill/session-chronicle/scripts/topic-patch-lint.py:1-7`, `:139-159`).
- Refactor runs publish `<docs-root>/reports/session-chronicle-refactor-<run-id>/report.md` plus `inventory.json` and `original-topics/` snapshots, with required identity, coverage ledger, change map, before/after hashes and outcome (`skill/session-chronicle-refactor/references/report-template.md:1-78`, `skill/session-chronicle-refactor/SKILL.md:52-56`, `:186-191`).

## Enumerated providers / limits

- **Note kinds**: `atomic`, `structure`, `redirect` (`skill/session-chronicle/scripts/_topic_graph.py:408`, `skill/session-chronicle/references/atomic-topic-contract.md:37-41`).
- **Statuses**: `active`, `merged`, `superseded` (`skill/session-chronicle/scripts/_topic_graph.py:429`).
- **Slug resolution match types**: `exact`, `alias`, `stem`, `new` (`skill/session-chronicle/scripts/slugify.py:44`, `:70`).
- **Refactor actions**: `keep`, `refine`, `split`, `merge`, `create`, `defer` (`skill/session-chronicle-refactor/SKILL.md:102`).
- **Refactor coverage states**: `reviewed`, `represented-by-view`, `observed-input-only`, `unreadable`, `pending` (`skill/session-chronicle-refactor/references/report-template.md:31`).
- **Refactor outcomes**: `complete`, `complete with unresolved findings`, `partial`, `dry-run` (`skill/session-chronicle-refactor/SKILL.md:194-196`, `skill/session-chronicle-refactor/references/report-template.md:5,19`).
- **Refactor modes**: no argument (apply), `--dry-run`, `--resume <report-path>` (`skill/session-chronicle-refactor/SKILL.md:26-31`).
- **Review threshold**: `MEMORY_TOPIC_REVIEW_WORDS`, default `300` body words, minimum effective value `1`; warning only (`skill/session-chronicle/scripts/_topic_graph.py:472-474`).
- **Slug grammar**: `[a-z0-9]+(-[a-z0-9]+)*`; note-reference stems capped at 191 characters (`skill/session-chronicle/scripts/_topic_graph.py:11-12`).
- **Materialisation threshold**: routine materialisation uses **two distinct sessions** as its default recurrence threshold; explicit refactoring may extract an idea supported by a single source (`skill/session-chronicle/references/atomic-topic-contract.md:131-135`, `skill/session-chronicle/references/zettelkasten-method.md:69-70`).
- **Patch subset**: LF-only UTF-8, no NUL, no `..`, no symlinks, single hard link, `.md` directly in `topics/`, at least one operation, at least one `+` line (`skill/session-chronicle/scripts/topic-patch-lint.py:28-34`, `:49-67`, `:101-113`, `:134-135`).
- **Wiki-link capture for `topics:` field**: `\[\[([a-z0-9][a-z0-9-]*)\]\]` (`skill/session-chronicle/scripts/sync-topics-field.py:44`).

## Cross-domain dependencies

- Docs-root resolution and project identity via `_docsroot.resolve_base` and `PROJECT_ROOT` / `AGENTS.md`|`CLAUDE.md` discovery (`skill/session-chronicle/scripts/_topic_graph.py:9`, `:189-197`; `skill/session-chronicle/scripts/topic-maintenance.py:8`, `skill/session-chronicle/scripts/topic-patch-lint.py:16`).
- Session notes and evidence records: discovery of `sessions/`, `record-kind: factual-evidence` suppression, preferred session views, note classification and secret scanning (`skill/session-chronicle/scripts/_topic_graph.py:222-278`, `:351-390`; `skill/session-chronicle/scripts/topic-patch-lint.py:17`, `:129`; `skill/session-chronicle/scripts/sync-topics-field.py:10`).
- Checkpoint write safety: `writer_lock` and `update_presentation` guard the `topics:` field rewrite (`skill/session-chronicle/scripts/sync-topics-field.py:8`, `:41-50`).
- Memory quality audit: refactoring reruns `skill/session-chronicle/scripts/memory-audit.py --quality` from the sibling skill (`skill/session-chronicle-refactor/SKILL.md:170-171`).
- Retrieval / startup orientation: `skill/session-chronicle/scripts/topic-index.sh` delegates to `skill/session-chronicle/scripts/_memory_read.py index`, and the refactor workflow uses recall/backlinks to verify old addresses (`skill/session-chronicle/scripts/topic-index.sh:3-4`, `skill/session-chronicle-refactor/SKILL.md:180-182`).
- Guarded native write path: the plugin's patch preflight must reconstruct and validate complete typed topics before the native patch executes (`skill/session-chronicle-refactor/SKILL.md:140-155`).
- Session-chronicle sibling skill as a hard dependency for the shared contract and templates (`skill/session-chronicle-refactor/SKILL.md:38-45`).

## Gaps

- The two-distinct-session materialisation threshold appears only in reference prose (`skill/session-chronicle/references/atomic-topic-contract.md:131-135`, `skill/session-chronicle/references/zettelkasten-method.md:69-70`); no in-scope script measures session recurrence, so whether any code enforces or reports it is unverified.
- `slugify()` strips everything outside `[a-z0-9]` after NFKD, so a wholly non-Latin title (e.g. CJK/Cyrillic) yields an empty slug with no guard (`skill/session-chronicle/scripts/slugify.py:20-24`); intended behaviour for non-English titles is undocumented.
- `skill/session-chronicle/scripts/sync-topics-field.py:44` harvests `[[...]]` from the whole body including code fences and block quotes, while `_topic_graph.body_links` excludes them (`skill/session-chronicle/scripts/_topic_graph.py:149-169`); a note with an example wikilink would get a `topics:` value the topic contract says to exclude.
- `legacy-kind` is a warning, yet the patch preflight refuses any note without a valid `note-kind` (`skill/session-chronicle/scripts/topic-patch-lint.py:125-126`); whether legacy notes are expected to be migrated before any guarded edit is unstated in the in-scope paths.
- `slugify.resolve` calls `require_resolvable()`, so any `alias-collision`, `duplicate-id` or broken redirect anywhere in the corpus blocks all new slug resolution (`skill/session-chronicle/scripts/slugify.py:51-52`, `skill/session-chronicle/scripts/_topic_graph.py:316-319`); whether that global blast radius is intended is unclear.
- `MEMORY_TOPIC_REVIEW_WORDS` is parsed with bare `int()` (`skill/session-chronicle/scripts/_topic_graph.py:472`), so a non-numeric value aborts the whole validation run instead of falling back to the default; deliberate or incidental is undetermined.
- `proposed_graph_findings` computes "changed" slugs as `Path(path).stem` of proposed files (`skill/session-chronicle/scripts/_topic_graph.py:486`); behaviour for a rename/merge that alters one note and leaves the affected redirect untouched is not documented.
- `skill/session-chronicle/scripts/topic-index.sh` behaviour is delegated to the out-of-scope `skill/session-chronicle/scripts/_memory_read.py index`; its actual index content and bounds could not be verified here.
- Whether a redirect may itself be the target of another redirect is allowed by the chain walker (`skill/session-chronicle/scripts/_topic_graph.py:293-307`) but not described in `skill/session-chronicle/references/atomic-topic-contract.md` or the redirect template; the canonical form (single hop vs. chains) is undecided.
