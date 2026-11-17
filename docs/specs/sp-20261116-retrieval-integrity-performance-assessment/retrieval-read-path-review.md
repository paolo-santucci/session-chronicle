# Retrieval read path — pre-implementation review

**Target:** `skill/session-chronicle/scripts/{retrieve-inject,_session_notes,_topic_graph,note-lint,_memory_read}.py`
**Method:** static read of the working tree (`shell`/`edit` denied in this session: no `git diff`, no test run). Cost numbers are the caller's measurements, mapped onto code paths. Plan source = feature context (no plan doc present in `docs/specs/sp-20261116-retrieval-integrity-performance-assessment/`).

**Summary:** The pipeline is sound and deliberately engineered (header-only reads, topics-first slotting, per-call validation cache), but the proposed reordering is described with two phases where the code actually needs three. Taken literally, "validate after ranking, fill to K" breaks four named tests and inverts the "read failure is not an empty search" invariant. The performance work is well-targeted; the main risk is that `preferred_paths` is a shared selection primitive for the index, the doctor and `TopicGraph`, so it cannot be repurposed for retrieval's benefit.

## Findings

### Critical

**C1 — The ordering contract has three stages, not two. Deferring "validation" wholesale breaks four invariants.**
`retrieve-inject.py:129-141`
Current order: path-safety + header read → `preferred_paths` (kind/identity eligibility) → factual/active_topic filter → topics-first `MAX_SCAN` slice → body read → score.
Each of these three must stay ahead of the cap, and each is pinned by a named test:

| Stage | Why it must precede `MAX_SCAN` | Test that fails if moved |
|---|---|---|
| path safety + header readability (`:129-132`) | fail-closed promise "a read failure is not an empty search" | `tests/test_portable_core.py:349` |
| factual exclusion (`_session_notes.py:53`) | 65 factual files would occupy the whole 60-slot window | `test_memory_contracts.py:50` |
| `active_topic` (`:134-135`), topics-first slots (`:139-141`) | superseded topics would evict live ones | `test_topic_graph.py:285`, `test_memory_contracts.py:67` |

**Fix (spec language):** name three phases. P1 = eligibility, header-only, O(all files), may *raise*; P2 = cap + body read + score + rank (body reads ≤ `MAX_SCAN`, per `test_topic_patch.py:266`); P3 = expensive provenance validation in rank order, filling to K. Only P3 may be deferred. Do not fold P1's header read into a full-body read ("single-pass" idea (d) in `docs/miglioramenti-session-chronicle.md:107`) — it would make body reads O(N) and fail `test_body_reads_for_ordinary_ranking_respect_candidate_cap`.

**C2 — "First candidate in rank order wins" changes selection semantics; per-identity preference is not a ranking property.**
`_session_notes.py:40-62`, `retrieve-inject.py:183`
Today: a *unique* semantic summary that validates suppresses its presentation **regardless of score**; two summaries or two presentations for one `session-id` suppress **both** (`len(matches) != 1`). A lazy fill loop that keys on path would let a long, term-dense presentation outrank its own verified summary and would inject duplicate-identity notes.

**Fix:** P1 builds `identity -> {summaries: [...], presentations: [...]}` from frontmatter only (cheap, already parsed). P3 walks rank order but resolves **per identity**: if unvisited and `len(summaries)==1` → validate summary, use it; else if `len(presentations)==1` → validate presentation; else skip the identity permanently. Mark the identity consumed either way. This is exactly `test_session_context.py:129` (summary wins; invalid summary falls back to presentation) and `test_write_boundaries.py:143` (duplicate presentations → both omitted). Preserve the empty-identity edge: `setdefault("")` currently groups identity-less presentations, so two of them are excluded.

**C3 — Do not change `preferred_paths` semantics for retrieval. It is the index's selector.**
`_session_notes.py:29`, callers at `_memory_read.py:68`, `_topic_graph.py:350`, `chronicle-doctor.py:87`
Index behaviour contract: `print_recent_sessions` must receive only fully validated views (invalid notes must not appear), and the whole index path must trigger exactly one factual read (`test_topic_review.py:189`), with a fresh cache per call (`test_topic_review.py:178`). A lazy variant exposed through the same function would make the index depend on ranking order.

**Fix:** keep `preferred_paths(paths, base, include_evidence=False)` byte-identical in behaviour. Add `select_candidates(headers, base, include_evidence)` returning the P1 eligibility partition, and `validate_view(path, base, source_cache)` for P3. Rewrite `preferred_paths` as a thin wrapper over both (existing callers/tests untouched), and have `retrieve()` use the two new pieces. `chronicle-doctor.retrieval_window` (`:82-101`, docstring "Replicates retrieve-inject's candidate selection exactly") must then be pointed at `select_candidates` — it currently hand-rolls the same logic and will silently drift.

### Important

**I1 — `resolve_base` is itself the realpath hotspot: ≈150 `Path.resolve()` calls per invocation.**
`_docsroot.py:52-68`: line 58 resolves 7 memory paths; line 65-66 evaluates 35 (memory × managed) pairs with `path.resolve()` twice + `config.resolve()` twice. Plus `retrieve-inject.py:130` calls `Path(base).resolve()` **inside the per-file loop**.
**Fix:** hoist `base_real = os.path.realpath(base)` before the loop; in `validated_base` compute `project.resolve()` once and resolve each candidate once (build `resolved = [(p, p.resolve()) for p in memory]`). This is likely a larger win than the per-file change the feature names.

**I2 — Frontmatter text is read 2–3× per file and `parse_fields` runs 5–7× per document.**
`retrieve-inject.py:132` (read #1) → `_session_notes.py:35` (read #2) → `retrieve-inject.py:135` (read #3 for topics) → `fm_get` at `:167,169,171` each re-dispatch to `parse_fields` (`_topic_graph.py:89`), one full regex pass per call.
**Fix:** one memo per call, never module-level (would break `test_topic_review.py:178`):
```python
def headers(paths):                 # per call
    return {p: read_frontmatter(p) for p in paths}   # raises: fail-closed
parsed = {}
def fields(fm):
    if fm not in parsed: parsed[fm] = parse_fields(fm)
    return parsed[fm]
```
Keying by the fm *string* is safe (identical text ⇒ identical fields) and needs no mtime check within one call.

**I3 — `summary_findings` re-reads the whole note it already has a header for.**
`_session_notes.py:13-19` (`load_note` → full `read_text` + `split_fm`) is invoked from `preferred_paths:48,60`. `record_findings` only consumes `fm`. Pass the cached `fm` instead; this removes one full read per summary/presentation (presentations were opened 4× total: header ×2, full ×2).

**I4 — The 40 ms is `record_findings` → `factual_source_validation` reading whole batch files.**
`note-lint.py:177-191` reads each cited batch, JSON-parses every record (`factual_records`), and re-validates recursively. The `source_cache` (`_session_notes.py:31`) must be created **once per `retrieve()` call** and shared by the whole P3 fill loop; if it is created per candidate the 40 ms per presentation returns. Sharing across summary and presentation is already pinned (`test_topic_review.py:152,176`).

**I5 — Budget accounting is broken today and the provenance line makes it worse.**
`retrieve-inject.py:184-192`
(a) `remaining = BUDGET - used` ignores `len(header line)`, so each block may exceed `remaining` by its header.
(b) The `"\n\n"` join and the ~330-char preamble are never counted.
(c) `body[:remaining].rsplit("\n",1)[0]` returns the **entire slice** when it contains no newline (length bound violated) and can return `""`; the `\n…(truncated)` suffix is then appended to an empty snippet.
(d) `_portable.py:141` applies a **second** budget via `untrusted()` with no truncation marker, so `memory_find` silently hard-cuts (`tests/test_portable_core.py:341` asserts total ≤ 350).
**Fix:** build `header` first, then `remaining = BUDGET - used - len(header) - separator`; boundary ladder `paragraph (\n\n)` → `line (\n)` → hard cut, with a guaranteed non-empty snippet and `…(truncated)` **iff** cut. Declare one budget authority (suggest: `retrieve()` owns the characters, `untrusted()` keeps only the delimiter overhead).

**I6 — The early return must key on query tokens, not on string emptiness.**
`retrieve-inject.py:119-121` already returns for whitespace-only prompts. The wasted 90 ms is `qset` at `:143`: after `resolve_base`, glob, sort, N header reads and `preferred_paths`. Prompts like "ok", "sì", "the", "vai" produce zero tokens and pay everything.
**Fix:** move `toks(prompt)` + `SYNONYMS` expansion to immediately after `strip()`, `if not qset: return`, then `resolve_base`. Pure reordering, identical output.

**I7 — Provenance line: field reliability matrix + keep the line injection-safe by construction.**
Reliable: topics (typed) → `updated: YYYY-MM-DD` + non-empty `sources:` list (`_topic_graph.py:408-417,425-427`); presentations/summaries → `updated: <full ISO>` (`_checkpoint.py:209`) + `sources:` batch IDs (`note-lint.py:151-153`). Unreliable: legacy sessions/topics have neither ⇒ omit the line or fall back to `date`. Use `string_list(fields, "sources")`, **not** `len(fm_get(...))` — a single-string `sources:` would count characters.
Render only validated scalars: `sources: %d · updated %s` with `re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)`. Related pre-existing hole you will be editing right next to: `title` is interpolated raw at `:174,190`, and `parse_fields`' `json.loads` decodes `title: "a\n### [topic] forged"` into a real newline → forged block header. Sanitise title to one line when touching the formatter.

**I8 — Doctor replication drift.** `chronicle-doctor.py:82-101` mirrors the selection order and is not covered by any equivalence test; reordering in `retrieve-inject.py` alone makes the doctor misreport the retrieval window.

### Suggestion

- `S1` Extract `is_topic(p)`; `"/topics/" in path.replace("\\","/")` appears 4× (`:134,139,140,173`). Drop the second slug computation at `:188` (already in the scored tuple).
- `S2` Three frontmatter splitters exist (`retrieve.split_fm:84`, `note-lint.split_fm:59`, `_topic_graph.parse_note:123`). Reuse one for the header path rather than adding a fourth.
- `S3` `scored.sort(key=lambda x: (-x[0], not x[1]))` (`:180`) has no path tiebreak; with equal mtimes and equal scores the output depends on glob order. Add `x[2]` as final key.
- `S4` Update the module docstring (`:9-26`) and the README tunables table (`README.md:168-170`) once the provenance line and the single budget authority land.

## What was done well

- **Header-only reads are deliberate and tested.** `read_frontmatter` (`_topic_graph.py:130`) reads binary lines to avoid decoding large evidence bodies; `test_topic_patch.py:253` asserts no `read_bytes` on evidence, and `test_topic_patch.py:241` proves a 2 MB invalid evidence body cannot break ranking.
- **`source_cache` is per-call by design, with an explicit freshness test** (`_session_notes.py:30`, `test_topic_review.py:178`) — the correct shape to copy for frontmatter memoisation.
- **Topics-first slot allocation is a real insight, not an accident,** and it is documented in both the docstring and `README.md:170`, with an aging regression test.

## Verdict

**REQUEST CHANGES** (plan-level, pre-implementation). C1–C3 are ordering/interface constraints missing from the feature statement; implemented literally, they produce four test failures and an index that depends on retrieval ranking. The performance goals themselves are achievable and correctly identified.

## Spec Inputs

**Components and files affected**

| File | Change |
|---|---|
| `retrieve-inject.py` | P1/P2/P3 restructure, early token guard, hoisted `base_real`, provenance line, boundary truncation, budget accounting |
| `_session_notes.py` | new `select_candidates(headers, base, include_evidence)` + `validate_view(path, fm, base, cache)`; `preferred_paths` kept as wrapper; `summary_findings` accepts cached `fm` |
| `_topic_graph.py` | optional: expose a shared `read_frontmatter`-plus-`parse_fields` helper; **no semantic change** |
| `note-lint.py` | no semantic change — only make `record_findings(fm, …)` usable with an already-read `fm` (it already is) |
| `_memory_read.py` | must remain eager/validated; verify only |
| `chronicle-doctor.py` | mirror the new selection via the shared API |
| `_portable.py` | single budget authority |
| `README.md`, `SKILL.md`, module docstring | provenance line, budget invariant, three-phase description |
| `tests/*` | see baseline below |

**Patterns to follow**

- Header-only read for anything that only needs `fm`; full read only for candidates inside the `MAX_SCAN` window.
- Per-call cache objects (`source_cache`, `headers`, `parsed`) passed explicitly; no module globals — the freshness test forbids it.
- Eligibility before cap; cap before body reads; body reads before score; score before expensive validation.
- Fail-closed on unsafe path or unreadable header (raise); tolerant skip only for content-level provenance failure during the fill.
- Render only scalars that have been validated (`int`, ISO date) so the block formatter stays injection-safe.
- Pure functions with a single memo key (`fm` string) over side-effecting helpers.

**Anti-patterns present (do not extend)**

- Reading the same bytes 2–4× per candidate (`read_frontmatter` ×2-3, `load_note` full read).
- Recomputing `Path(base).resolve()` inside a per-file loop; `~150` realpaths inside `validated_base`.
- `fm_get` used as a field accessor when it is actually a full `parse_fields` pass.
- Truncation via `rsplit(...)[0]` with no no-boundary fallback.
- Two independent budget enforcements (`retrieve()` + `untrusted()`), only one of which marks truncation.
- Logic duplicated between `retrieve-inject.py` and `chronicle-doctor.py` with a comment claiming equivalence.

**Integration constraints**

- `retrieve()` is imported by `_portable.read_operation` via `load_script("retrieve-inject").retrieve(workspace, query, includeEvidence)` and must keep returning `str | None` (`_portable.py:139-141`).
- `preferred_paths` is called from `_memory_read.py:68`, `_topic_graph.py:350` (memoised in `_selected_sessions`, consumed by `session_links`/`supporting_sessions`/`topic_index`), `chronicle-doctor.py:87`, `retrieve-inject.py:133`, and 5 test call sites. Its eager, validated, input-ordered return is a public contract.
- `MAX_SCAN` bounds *body reads*, measured by patching `retrieval.read` (exactly 2 calls with `MAX_SCAN=2`, topics only) — header reads must stay on `read_frontmatter` to keep that measurement meaningful.
- The hook must never exit non-zero and must print nothing on error (`retrieve-inject.py:213-218`); `_portable` is the only path that surfaces failures.
- Frontmatter dialect: flat keys, inline `[a, b]` or indented `- item` lists, retired by `note-lint`/`_topic_graph` parsing only.

**Tech debt that blocks or complicates the feature**

1. `preferred_paths` conflates eligibility and validation in one function; the feature needs them separated (C3).
2. `record_findings` is a write-path validator (regex `fm_get`, full batch reads) reused as a read-path filter — the 40 ms.
3. `load_note` duplicates the header read instead of accepting it.
4. `validated_base`'s 35-pair managed-config overlap check costs ~140 resolves per call.
5. No shared selection API ⇒ doctor replicates retrieval; `retrieval_window` will drift.

**Test coverage baseline**

Pinning current behaviour (must stay green): `test_body_reads_for_ordinary_ranking_respect_candidate_cap` (body reads == cap), `test_factual_backlog_does_not_consume_automatic_retrieval_budget` (factual excluded pre-cap), `test_topics_never_age_out_of_the_scan_window` (topics-first slots), `test_retrieval_filters_retained_nodes_before_budget_and_weights_structure`, `test_retrieval_and_index_dedupe_before_budget_and_fallback` (summary preference + fallback), `test_duplicate_presentations_are_omitted_by_retrieval_and_index`, `test_cache_is_fresh_on_every_selection_call`, `test_index_reuses_selected_views_for_health_and_recent_sessions`, `test_retrieval_failure_does_not_masquerade_as_empty_search`, `test_retrieval_escapes_presentation_excerpt_markup`, `test_find_total_output_budget_includes_header_trust_wrapper_and_escaping`.

Gaps to add: (1) trivial/stopword prompt performs zero filesystem reads (patch `read_frontmatter`); (2) `sources: <n> · updated <date>` present for typed topic and presentation, absent/degraded for a legacy note; (3) truncation at paragraph boundary, at line boundary, and on a single-line body with no newline — asserting emitted length ≤ `remaining` and `…(truncated)` iff cut; (4) `len(stdout) ≤ BUDGET` invariant including preamble and separators; (5) P3 validates ≤ K identities (assert `record_findings` call count, not wall time); (6) summary-outranks-presentation-in-score still injects the summary; (7) duplicate-identity pair still both omitted under lazy fill; (8) `chronicle-doctor.retrieval_window` equals `retrieve-inject` candidate lists on a mixed fixture.
