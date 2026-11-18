---
domain: memory-tools
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Memory Tools

## Overview

Five agent-facing tools — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`, `memory_session_context` — expose the project's session journal and topic graph for programmatic recall, structural health checks, and session-target resolution (`README.md:29`, `README.md:207-211`). Four are read-only; `memory_session_context` checkpoints pending evidence before resolving a target and therefore requires mutation permission (`README.md:211`).

## Current behaviour

- **Ranked search (`memory_find`).** Takes `query` and optional `includeEvidence`; searches semantic session summaries and topics, and includes factual records only when `includeEvidence: true` (`README.md:207`). Result text is delimited as untrusted reference data, not instructions (`README.md:215`).
- **Known-subject recall (`memory_recall`).** Takes `slug` and optional `scope` (`all`, `topic`, `sessions`); prints the canonical topic note plus supporting session-note IDs (filename stems) including source provenance; aliases and redirects resolve to the canonical idea (`README.md:208`, `SKILL.md:203`). The shell wrapper only forwards arguments to the shared recall core (`skill/session-chronicle/scripts/memory-recall.sh:4`).
- **Backlink listing (`memory_backlinks`).** Takes `slug`; returns supporting session-note IDs gathered from wikilinks and provenance, resolving aliases and redirects, and states explicitly that these are note IDs, not SDK session IDs (`README.md:209`, `SKILL.md:204`). The script form is `skill/session-chronicle/scripts/backlinks.py <slug> [--base .] [--count] [--json]` (`skill/session-chronicle/scripts/backlinks.py:11-16`).
- **Backlink output shapes.** Default prints one session-note ID per line; `--count` prints the integer count; `--json` prints an object with the requested `slug`, resolved `canonical_slug`, `count` and `sessions` (`skill/session-chronicle/scripts/backlinks.py:21-26`).
- **Graph audit (`memory_audit`).** Takes a `mode` in `orphans`, `dups`, `dangling`, `stale`, `candidates`, `quality` and returns a JSON health report; `quality` findings are structural and require semantic review (`README.md:210`, `skill/session-chronicle/scripts/memory-audit.py:53-81`).
- **Audit mode meanings.** `orphans` = topics with no inbound body link, source topic or supporting session; `dups` = topics whose slug/alias collide after naive plural stemming; `dangling` = unresolved session links with occurrence counts, ordered by count then name; `materialization_candidates` = dangling links at or above the threshold; `stale` = topics whose `updated` date is older than the day limit; `quality` = graph quality findings plus a review notice (`skill/session-chronicle/scripts/memory-audit.py:11-46`, `:61-81`).
- **Audit rejects inconsistent graphs.** Every mode except a quality-only run first fails on resolution-code findings with `Invalid topic graph: …` and exits 2 (`skill/session-chronicle/scripts/memory-audit.py:57-60`, `:105-107`).
- **Session targeting (`memory_session_context`).** Called with `{}`; takes session identity only from trusted SDK context, checkpoints evidence, then resolves the current session's presentation, semantic summary, target path and factual batch IDs (`README.md:211-213`, `SKILL.md:58-64`, `skill/session-chronicle/scripts/session-context.py:51-69`).
- **Session targeting rejections.** A closed matching summary, duplicate summaries or presentations, an occupied deterministic target, missing/malformed `record-kind` or `session-id` frontmatter, a session note escaping the `sessions/` directory by symlink, and invalid factual-batch metadata each abort with a specific message before any write (`skill/session-chronicle/scripts/session-context.py:17-47`).
- **Workspace containment.** `project_root` must exist, and the resolved docs-root and its `sessions/` directory must both stay inside `project_root` (`skill/session-chronicle/scripts/session-context.py:57-62`).
- **Project-relative replies.** All returned paths are project-relative; `presentation` and `semantic_summary` may be `null`; `sources` holds factual batch IDs (`README.md:213`, `skill/session-chronicle/scripts/session-context.py:66-69`).

## Public contracts

- `memory_find(query, includeEvidence?) -> ranked text` (`README.md:207`).
- `memory_recall(slug, scope?: "all"|"topic"|"sessions") -> canonical topic note + session-note IDs` (`README.md:208`).
- `memory_backlinks(slug) -> session-note IDs` (`README.md:209`); script contract `skill/session-chronicle/scripts/backlinks.py <slug> [--base DIR] [--count] [--json]` with exit code 2 on `ValueError`/`OSError` after printing the message to stderr (`skill/session-chronicle/scripts/backlinks.py:11-16`, `:30-34`).
- `memory_audit(mode) -> JSON report` (`README.md:210`); script contract `skill/session-chronicle/scripts/memory-audit.py [--orphans|--dups|--dangling|--materialization-candidates|--stale|--quality|--json] [--base DIR] [--threshold N] [--days D]` (`skill/session-chronicle/scripts/memory-audit.py:86-92`).
- Audit JSON envelope keys: `orphans`, `dups`, `dangling`, `broken_topic_edges`, `materialization_candidates`, `stale`, `quality`, `semantic_review_required`, `review_notice`; keys prefixed `_` (`_threshold`, `_stale_days`) are echoed for machine use only and omitted from the human-readable rendering (`skill/session-chronicle/scripts/memory-audit.py:54`, `:62-81`, `:94-99`).
- `memory_session_context({}) -> {session_id, presentation, semantic_summary, target, sources}` (`README.md:213`, `SKILL.md:60-62`); the script reads that JSON object on stdin (`skill/session-chronicle/scripts/session-context.py:74`).
- Target filename contract: a new summary target is `sessions/session--<sha256(ID)>--summary.md`, computed by the summary-name helper (`README.md:271`, `skill/session-chronicle/scripts/session-context.py:45`).
- Read-path error envelope: `{"error": {"code": "session_context_failed", "message": "<reason>; resolve the data or checkpoint failure before retrying"}}` on stdout with exit code 1 (`skill/session-chronicle/scripts/session-context.py:73-80`).
- Audit/backlink failure surface: human-readable message on stderr, exit code 2 (`skill/session-chronicle/scripts/backlinks.py:32-34`, `skill/session-chronicle/scripts/memory-audit.py:103-107`).

## Enumerated providers / limits

- **Audit modes:** `orphans`, `dups`, `dangling`, `materialization-candidates`, `stale`, `quality`, plus `json` as an output switch — declared as CLI flags in one loop (`skill/session-chronicle/scripts/memory-audit.py:87-88`) and mirrored as the `mode` enum (`README.md:210`).
- **Recall scopes:** `all`, `topic`, `sessions`; `all` is the default (`SKILL.md:203`).
- **Backlink output selectors:** default list, `--count`, `--json` (`skill/session-chronicle/scripts/backlinks.py:14-15`).
- **Record kinds recognised by session targeting:** `factual-evidence` (with batch-id / record findings validation), `semantic-summary`, `session-presentation` (`skill/session-chronicle/scripts/session-context.py:24`, `:31`, `:21`).
- **Materialisation threshold:** default `2` (`--threshold`) — a subject earns a topic note after recurring across at least two distinct sessions (`skill/session-chronicle/scripts/memory-audit.py:90`, `SKILL.md:93`, `:231`).
- **Staleness window:** default `90` days (`--days`), compared against the topic's `updated` date; unparsable dates are skipped (`skill/session-chronicle/scripts/memory-audit.py:91`, `:75-80`).
- **Base directory:** `--base` defaults to `.` in both scripts (`skill/session-chronicle/scripts/backlinks.py:13`, `skill/session-chronicle/scripts/memory-audit.py:89`), while the skill instructs `--base ${docs-root}` (`SKILL.md:201`, `:204`).
- **Index health thresholds (consumed by the orientation line, not these scripts):** `MEMORY_HEALTH_STALE_MAX` 5, `MEMORY_HEALTH_DANGLING_MAX` 10 (`README.md:230`, `SKILL.md:148`).
- **Retrieval budgets reported for the read path:** `MEMORY_INJECT_BUDGET_CHARS` 6000, `MEMORY_INJECT_TOPK` 3, `MEMORY_INJECT_MAX_SCAN` 60 (`README.md:225-227`).

## Cross-domain dependencies

- Shared recall/ranking core `_memory_read.py` (operation `recall`, plus `find`/`retrieve` worker operations) — invoked by proxy from `memory-recall.sh` (`skill/session-chronicle/scripts/memory-recall.sh:4`, `SKILL.md:161-190`).
- Topic graph module `_topic_graph.py`: `TopicGraph`, `REVIEW_NOTICE`, `RESOLUTION_CODES`, `body_links`, `string_list`, `valid_slug` (`skill/session-chronicle/scripts/backlinks.py:7`, `skill/session-chronicle/scripts/memory-audit.py:8`).
- Factual checkpoint module `_checkpoint.py`: `checkpoint(base)` run before and after target resolution (`skill/session-chronicle/scripts/session-context.py:8`, `:64`).
- Docs-root resolution module `_docsroot.py`: `resolve_base` (`skill/session-chronicle/scripts/session-context.py:9`, `:60`).
- Session-note access module `_session_notes.py`: `load_note`, `note_lint`, `summary_findings` (`skill/session-chronicle/scripts/session-context.py:10`).
- Note lint/schema module `note-lint.py`: `fm_get`, `is_batch_id`, `factual_records`, `record_findings`, `require_unambiguous_identity`, `summary_findings`, `summary_name` (`skill/session-chronicle/scripts/session-context.py:10`, `:24-45`).
- Harness adapters that register the five tools and map `mode`/`scope` arguments to these scripts (`README.md:192`, `:207-211`, `SKILL.md:155`).

## Gaps

- `memory_recall`'s parameter parser and output format live in `_memory_read.py`, outside this slice; only the wrapper (`exec python3 … recall "$@"`) and the prose-documented `--topic|--sessions|--all` flags are visible, so the accepted flags and reply shape are unverified (`skill/session-chronicle/scripts/memory-recall.sh:4`, `SKILL.md:203`).
- `memory_find` has no in-scope implementation: the tool boundary is in the OpenCode adapter and the core `find` operation, so its ranking inputs, budget interaction and error shape cannot be confirmed here (`README.md:207`, `SKILL.md:167`).
- `--json` is counted separately from the audit mode tuple, so running `memory-audit.py --json` with no mode runs **all** modes; whether `--json` is a pure formatter or silently implies "all" is unstated (`skill/session-chronicle/scripts/memory-audit.py:55-56`, `:87-88`).
- A quality-only run skips the graph-validity rejection (`any(modes[:-1])` is false), so an invalid graph returns findings instead of exit 2 — deliberate leniency or an oversight (`skill/session-chronicle/scripts/memory-audit.py:57-60`).
- `dangling_sessions` counts link occurrences per session-links entry, while the module docstring promises recurrence by "distinct session identity, not file count"; whether duplicates inside one session are collapsed depends on `_topic_graph.session_links`, which is out of scope (`skill/session-chronicle/scripts/memory-audit.py:2`, `:18-24`).
- `summary_name`, `factual_records` and `record_findings` semantics — and therefore the exact filename and batch-validation rules behind `skill/session-chronicle/scripts/session-context.py` errors — are enforced in `note-lint.py`; the `session--<sha256(ID)>--summary.md` shape is evidenced only by README prose (`skill/session-chronicle/scripts/session-context.py:24-45`, `README.md:271`).
- `memory_session_context` is listed as requiring mutation permission because it checkpoints (`README.md:211`), yet its contract is otherwise read-only; whether callers must treat it as a write tool is ambiguous.
- The set of quality codes that count as resolution errors, and the review-notice text, are declared in `_topic_graph.py` (`RESOLUTION_CODES`, `REVIEW_NOTICE`) and cannot be enumerated from this slice (`skill/session-chronicle/scripts/memory-audit.py:8`, `:58`, `:54`).
- Both CLIs default `--base` to `.` while documentation always passes the docs-root; a caller that omits it resolves relative to the working directory without warning (`skill/session-chronicle/scripts/backlinks.py:13`, `skill/session-chronicle/scripts/memory-audit.py:89`, `SKILL.md:201`).
