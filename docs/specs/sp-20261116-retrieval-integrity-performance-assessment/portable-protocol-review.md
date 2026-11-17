# Portable protocol review — `retrieve` operation (`{text, slugs}`)

**Report target:** `docs/specs/sp-20261116-retrieval-integrity-performance-assessment/portable-protocol-review.md`
**Scope:** `skill/session-chronicle/scripts/{_portable.py, chronicle.py, session-context.py, retrieve-inject.py, _storage_paths.py, _docsroot.py, _topic_graph.py, _memory_read.py}`, plus `schemas/envelope.schema.json`, `adapters/{opencode,pi,claude-code,codex}`, `adapters/shared/worker-client.ts`, `tests/test_portable_core.py`, `skill/session-chronicle/scripts/test_write_boundaries.py`.
**Type:** pre-implementation assessment (no diff exists yet; whole-module static read). `git diff` unavailable — shell denied to this agent.

## Summary

The protocol is a clean single-envelope, single-response worker with a strict whitelist validator (`fields`/`text`), one fail-closed error funnel, and a centralized untrusted-text wrapper. A `{text, slugs}` reply fits the existing v1 contract **without** a version bump, because `schema_version` governs envelope shape while the operation set is an additive enum; the exact constants are `OPERATIONS_API` (`_portable.py:22`) and the mirrored enum in `schemas/envelope.schema.json:11`. The real risks are not architectural but three sharp traps: `untrusted()` is a string renderer so `slugs` must be proven safe rather than wrapped, `valid_slug()` rejects every session-note stem, and exclusion must be applied inside ranking rather than after it.

## Findings

### Critical (must resolve before implementation — constraints, not shipped defects)

**C1 — `slugs` would bypass `untrusted()` by construction; `text` must be the only wrapped field**
`skill/session-chronicle/scripts/_portable.py:113–122`, precedent `:217`, `:148`, `:152`.
No operation currently returns a dict whose payload is untrusted note content; `context`/`continuation`/`recover` return trusted metadata only, and untrusted parts are pre-wrapped strings (`continuation_context` wraps the whole list). A `{text, slugs}` reply therefore introduces a new shape class. If `text` is returned raw it loses both escaping and budget; if `slugs` is passed through `untrusted()` it becomes `"&lt;…&gt;"`-decorated text the adapter cannot compare against its exclude set.
Fix — wrap exactly one field, at the same call site that already owns the budget:
```python
matches = load_script("retrieve-inject").retrieve_matches(context["workspace"], arguments["query"],
                                                         arguments.get("exclude", []), False)
budget = max(0, int(os.environ.get("MEMORY_INJECT_BUDGET_CHARS", "6000")))
return {"text": untrusted(matches["text"], budget) if matches["text"] else "",
        "slugs": matches["slugs"]}
```
Reason `slugs` is safe outside the wrapper **only** if they are constrained at the source (see C2) — never interpolated free text.

**C2 — `valid_slug()` cannot validate emitted slugs or returned `exclude` entries; it rejects every session stem**
`_portable.py:20` (imports `valid_slug`), `_topic_graph.py:18–19` (`^[a-z0-9]+(?:-[a-z0-9]+)*$`), `_checkpoint.py:127–131` (`2026-10-15--<readable>-<digest>`), `note-lint.py:247–248` (`session--<64hex>--summary`).
`valid_slug` forbids consecutive hyphens, so all session-note slugs fail it. An implementer reaching for the already-imported helper either crashes on every session hit or silently returns an empty `slugs` list — the feature degrades to "no dedup" with no error.
Fix — add one predicate used for **both** directions, in `_portable.py`:
```python
NOTE_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,199}")
def note_slug(value, name):
    if not isinstance(value, str) or not NOTE_SLUG.fullmatch(value) or ".." in value:
        raise CoreError("invalid_request", name + " must be a note-file slug")
    return value
```
It excludes `<`, `>`, `/`, `\`, NUL and `.`-traversal by construction, which is what makes C1's unwrapped `slugs` defensible. Add a test asserting a session stem (`…--…`) round-trips.

**C3 — Extending `find` to return `{text, slugs}` silently breaks the public `memory_find` contract**
`adapters/opencode/index.ts:33–36` (`replyText` → `JSON.stringify(reply.result)`), `:227` (`use("find", …)`), `index.test.ts:127–146` (asserts `content.includes("<chronicle-untrusted>")`, `length <= 240`, and `"(no matching memory notes)"` on miss), `README.md:150`.
Any non-string `find` result reaches the model as a JSON blob and fails three existing assertions.
Fix — `find` stays byte-identical; `retrieve` is a separate operation and a separate adapter call site that reads `.text` directly, never via `replyText`.

### Important

**I1 — `exclude` must filter inside ranking, not after selection**
`retrieve-inject.py:164–192`. `scored[:TOP_K]` is taken at `:183` and the block budget is consumed in the same loop; filtering afterwards yields fewer than `TOP_K` hits and under-spends the budget while lower-ranked candidates sit unused. Topics-first fairness at `:139–141` must also survive: exclude after `preferred_paths`/`active_topic` filtering and after sort, before the `TOP_K` slice and before `used` accounting.

**I2 — `retrieve()` cannot yield slugs; it must be split, not modified**
`retrieve-inject.py:118–200`. The slug is computed at `:170` and `:188` and discarded into a formatted block string; the `None` return at `:120/:127/:145/:161/:177` carries the "no match" signal used by `_portable.py:141` (`if result else ""`). Extract a `retrieve_matches(proj, prompt, exclude=(), include_evidence=False) -> {"text": str, "slugs": [...]}`, keep `retrieve()` as a thin `or ""`-style wrapper for `main()` at `:203–210`, and leave `find`'s call site untouched. Do not let `retrieve_matches` return `None`.

**I3 — Two independent reads of `MEMORY_INJECT_BUDGET_CHARS` create a budget mismatch**
`retrieve-inject.py:43` (module-level `BUDGET`) vs `_portable.py:141` (re-read per call). `untrusted()` subtracts wrapper overhead (`:118`) before truncating, so inner text is always up to ~80 chars longer than the outer envelope allows. `test_find_total_output_budget_includes_header_trust_wrapper_and_escaping` (`tests/test_portable_core.py:341–347`) passes only because it measures the outer string. For `retrieve` the outer budget should be the single authority and the inner fill should receive the already-reduced number.

**I4 — Truncation can split an HTML entity and can empty `text` while `slugs` stays populated**
`_portable.py:116–122`. Escape expands `<` → `&lt;`, then `rendered[:available]` may cut mid-entity (`&l`), and `if not available: return ""` (`:119–120`) returns an empty wrapper while slugs remain non-empty. The adapter would then mark notes as "injected" for zero injected characters.
Fix — truncate on the raw string *before* escaping, or strip a trailing partial entity; and for `retrieve` decide explicitly that `text == ""` ⇒ `slugs == []` (adapter must not record non-injected slugs).

**I5 — Operation registration lives in six places; missing any one fails closed at runtime**
`_portable.py:22` (`OPERATIONS_API`); `schemas/envelope.schema.json:11` (enum) and `:30–33` (per-op argument conditional); `adapters/pi/index.ts:8` (`Operation` union — already missing `"recover"`); `adapters/claude-code/hook.py:220–221` and `adapters/codex/hook.py:195–196` (`allowed` arg maps, reject with `Blocked("native_context_transport_required")`); `tests/test_native_hooks.py:205–206` (diagnostic fixtures). `fields()` raises `invalid_request` for the unexpected `exclude` key (`_portable.py:42–44`) if the schema/allowlist is not updated in lockstep.

**I6 — No version bump needed, but old workers are still deployed — the adapter needs a fallback**
`_portable.py:222–226` rejects unknown operations with `invalid_request`; `schemas/envelope.schema.json:10` pins `schema_version` `const 1`. Widening the `operation` enum is additive within v1, so no bump is required. However `STATUS.yaml:142` records 0.1.0 still deployed in `opencode-work-tools`, which will answer an unknown `retrieve` with `invalid_request`. The adapter must degrade to `find` (no dedup) on `invalid_request` / `worker_protocol` rather than lose injection entirely.

**I7 — Read path is read-only by convention only; dedup state must stay adapter-side**
`_portable.py:132–164` (`read_operation`), `:205–217` (`continuation_context`), `_storage_paths.py:28–44` (`storage_layout` only `lstat`/`glob`/`exists` — no writes), `_topic_graph.py` (no write calls). Write primitives (`writer_lock`, `publish`, `ensure_directory`) live in `_checkpoint.py`/`_capture.py` and are reached only from `capture`/`checkpoint`/`continuation`. Nothing *prevents* `read_operation` from importing them. `tests/test_portable_core.py:118–130` asserts `find` under `role: "unknown"` leaves `self.base` nonexistent — any worker-side session store would break it. Encode the invariant as a test: `snapshot()` equality around `retrieve`, plus the unknown-role read case.

**I8 — Adapter dedup map must be per-session and bounded**
`adapters/opencode/index.ts:88` — `const indexed = new Set<string>()` is process-lifetime and never pruned; copying that shape for slugs leaks memory across every session in a long-lived plugin process. Use `Map<session_id, Set<slug>>` and delete the entry in the compaction hook (`:187–201`), matching the plan's "cleared on compaction". Cap the per-session set (`MEMORY_INJECT_TOPK` × ~50) and evict oldest.

### Suggestion

**S1 — Naming collision.** `retrieve` (operation) vs `retrieve-inject.py` (module) vs the SKILL docs' "retrieval" (the whole read path, `SKILL.md:147`). Keep the requested name but state in the spec that the operation is "ranked note discovery for adapter dedup", and cross-reference `retrieve-inject.py` in the schema description so the two are not conflated.

**S2 — `fields()` does not name the offending key** (`_portable.py:42–44`). For a new operation with an optional `exclude`, the generic message costs debugging round-trips. Optional: include the symmetric difference in the message.

**S3 — `exclude` has no size/duplicate bound.** Add `len(exclude) <= 200` and dedupe before matching; unbounded input makes the exclude-set intersection cost O(n) per candidate.

**S4 — Doc surfaces to update with the feature:** `README.md:150`, `docs/capability-matrix.md:28`, `skill/session-chronicle/SKILL.md:147`, and the duplicated `skills/session-chronicle/` mirror.

## What was done well

- `response()` (`_portable.py:260–272`) is a single fail-closed funnel: `CoreError` codes, `ReplayConflict`, `AmbiguousIdentity`, then a catch-all that deliberately maps to fixed strings so no payload, path or traceback can reach a model. Any new operation inherits that posture for free — asserted by `test_guard_validator_exception_fails_closed` (`tests/test_portable_core.py:377–381`).
- The trust wrapper is centralized and tested from both directions: delimiter forgery (`:329–339`) and total-envelope budget (`:341–347`). The budget test measures the *whole* string including header and escaping, which is the right invariant and the one the new reply must keep.
- `fields()` rejects unknown keys at the envelope, argument and schema layers consistently (`additionalProperties: false` throughout `envelope.schema.json`), so a new `exclude` argument cannot be silently ignored — it fails loudly in every layer that is updated, and it is exactly why I5's six-site checklist matters.

## Verdict

**APPROVE WITH NOTES.** The existing module is sound and no defect requiring a fix was found in shipped code. The three Critical items are design constraints that must be encoded in the spec before implementation: `text`-only wrapping with structurally-proven `slugs`, a slug predicate that is not `valid_slug`, and leaving `find` untouched. No protocol version bump is required; the exact constant to extend is `OPERATIONS_API` in `skill/session-chronicle/scripts/_portable.py:22`, mirrored by the `operation` enum at `schemas/envelope.schema.json:11`.

## Spec Inputs

**Components and files affected**
- `skill/session-chronicle/scripts/_portable.py` — `OPERATIONS_API:22`; new `retrieve` branch in `read_operation:132–164`; new `note_slug()` predicate; `fields` call with `("query",)` required and `("exclude", "includeEvidence")` optional.
- `skill/session-chronicle/scripts/retrieve-inject.py` — split `retrieve:118–200` into `retrieve_matches(...)` (returns `{"text", "slugs"}`, exclusion before `scored[:TOP_K]` and before the `used` budget loop) plus a text-only wrapper for `main():203–210`. `find` behaviour unchanged.
- `skill/session-chronicle/scripts/_storage_paths.py` — unchanged; `storage_layout()` is already read-only and remains the read-path precondition (`_portable.py:133`, `:206`).
- `schemas/envelope.schema.json` — `operation` enum `:11`; new `if/then` arguments branch modelled on `find:30–33`; `exclude` as `{"type":"array","maxItems":200,"uniqueItems":true,"items":{"type":"string","pattern":"^[a-z0-9][a-z0-9-]{0,199}$"}}`.
- `adapters/opencode/index.ts` — new injection call site beside `:138–141`; per-session slug map replacing the `indexed`-style closure at `:88`; clear-on-compaction in `:187–201`; new tool registration block if a public tool is added; `find` tool at `:224–228` untouched.
- `adapters/shared/worker-client.ts` — no change needed (`result: object | string` at `:18`, `parseReply:120–132` already accepts objects).
- `adapters/{pi,claude-code,codex}` — `Operation` union (`pi/index.ts:8`), `allowed` maps (`claude-code/hook.py:220`, `codex/hook.py:195`), `DIAGNOSTIC_OPERATIONS` (`:13` in both hooks) only if those adapters adopt dedup.
- Tests: `tests/test_portable_core.py`, `index.test.ts`, `tests/test_native_hooks.py`, `skill/session-chronicle/scripts/test_write_boundaries.py`.
- Docs: `README.md:150`, `docs/capability-matrix.md:28`, `skill/session-chronicle/SKILL.md:147`, `skills/session-chronicle/SKILL.md:200`.

**Patterns to follow**
- Validate every argument through `fields()` + a per-field predicate before touching storage; optional keys are declared, never inferred (`_portable.py:42–51`, `:134–141`).
- Wrap untrusted note content exactly once, at the point of leaving the worker, with the budget as a total-envelope bound (`:113–122`, tested `:341–347`).
- Return empty-string/`""`-equivalent only when the underlying read genuinely found nothing; a read *failure* must raise, never masquerade as empty (`test_retrieval_failure_does_not_masquerade_as_empty_search:349–353`).
- Structured replies are allowed for trusted metadata (`context:242–251`, `continuation:181`, `recover:77`); untrusted content inside them is always a pre-wrapped string, never a raw field.

**Anti-patterns to avoid**
- Passing a dict to `untrusted()` for a reply the adapter must parse — it becomes escaped JSON text, destroying slug equality (contrast `backlinks:164`, correct for a display-only op, wrong for a machine-readable one).
- Reusing `valid_slug()` for note slugs or for `exclude` (C2).
- Adding `retrieve` fields to the `find` branch or to `memory_find`'s `input` schema (C3).
- Applying `exclude` after `TOP_K`/budget selection (I1).
- Holding dedup state, a cache, or any per-session counter in the Python worker — it breaks statelessness and the `role: "unknown"` no-mutation guarantee (`tests/test_portable_core.py:118–130`).
- Growing a process-lifetime adapter `Set` without pruning (I8).

**Integration constraints**
- Envelope: `{schema_version: 1, operation, context, arguments}` with `additionalProperties: false` at every level; unknown operation or unknown argument ⇒ `invalid_request` (`_portable.py:42–44`, `:225–226`). No `schema_version` bump; additive enum widening only.
- Reply: `{ok: true, result}` or `{ok: false, error: {code, message}}`; `result` may be `string | object` (`worker-client.ts:18`). Response ceiling 1,048,576 bytes and 30 s timeout (`worker-client.ts:5–6`) — `slugs` add bytes outside the text budget; with `TOP_K` capped at 3 and slugs ≤ 200 chars each this stays trivial, but note it.
- Role gate: `retrieve` is a read op, so it must run under `role: "delegated"` and `role: "unknown"` (`:231–236` only restricts capture/checkpoint/context/continuation). Add it to the read-op list in `tests/test_portable_core.py:120–127`.
- Budget env var `MEMORY_INJECT_BUDGET_CHARS` (default 6000) is currently read in two places (`retrieve-inject.py:43`, `_portable.py:141`); `MEMORY_INJECT_TOPK` (default 3) and `MEMORY_INJECT_MAX_SCAN` (default 60) are read at `retrieve-inject.py:44–45` only.
- Adapter compatibility: deployed 0.1.0 workers answer unknown operations with `invalid_request`; fall back to `find` (I6).
- `adapter.slugs` must be the note file stem exactly as `retrieve-inject.py:170/:188` computes it (`os.path.splitext(os.path.basename(f))[0]`); no TopicGraph canonicalisation, because that would emit a slug for a note that was not injected.

**Tech debt that blocks or complicates the feature**
- `adapters/pi/index.ts:8` `Operation` union already omits `"recover"` — the registration checklist is demonstrably incomplete today; treat six-site registration as a review gate.
- Duplicated skill tree `skill/session-chronicle/` vs `skills/session-chronicle/` (same content, `SKILL.md:147` vs `:200`) — doc updates must land twice or drift.
- `.opencode_OLD/` contains stale copies of the same scripts; grep hits there are noise and must be excluded from any "update all call sites" sweep.
- Two budget sinks (I3) predate the feature and will produce a subtly different truncation point for `retrieve` than for `find` unless unified.
- `STATUS.yaml:142` deployment drift means the adapter fallback (I6) is a hard requirement, not a nicety.

**Test coverage baseline**
- `tests/test_portable_core.py` (real subprocess against `chronicle.py`) covers: read ops delimited by the wrapper (`:329–339`), total budget incl. header/escaping (`:341–347`), read-failure ≠ empty (`:349–353`), unknown-role reads allowed without mutation (`:118–130`), delegated reads (`:110–116`), argument rejection (`:500`), no-match ⇒ `""` (`:778`). Extend with: `retrieve` result is a dict with exactly `{text, slugs}`; `text` starts with `<chronicle-untrusted>` and contains exactly one closing marker; `snapshot()` unchanged around `retrieve`; session-stem slug round-trip through `exclude`; `exclude` of the top hit still returns `TOP_K` candidates; invalid `exclude` (non-list, NUL, `../`, `x/y`, `..`, >200 items) ⇒ `invalid_request`; budget underflow ⇒ `text == ""` and `slugs == []`.
- `index.test.ts:127–146` is the `memory_find` regression guard (`<chronicle-untrusted>`, `length <= 240`, `"(no matching memory notes)"`) — must pass unchanged. Add an adapter test: two prompts where the first injects a note and the second does not repeat it; compaction clears the set; `retrieve` returning `invalid_request` falls back to `find`.
- `skill/session-chronicle/scripts/test_write_boundaries.py:143–154` and `tests/test_portable_core.py:100–130` are the read-only guards to extend; `tests/test_native_hooks.py:204–216` is the per-adapter diagnostic allowlist test.
- Parity a new operation needs, minimum: registered in `OPERATIONS_API` + schema enum + argument conditional; accepted for all three roles; delimited/escaper-correct; budget-bounded; failure is an error not an empty result; adapter allowlists and `Operation` unions updated; docs and capability matrix updated.
