# OpenCode adapter + worker client — pre-implementation assessment

**Files reviewed:** `adapters/opencode/index.ts` (257 lines), `adapters/shared/worker-client.ts` (136), plus call paths `skill/session-chronicle/scripts/_portable.py`, `retrieve-inject.py`, `index.test.ts`, `plugin.yaml`, `docs/miglioramenti-session-chronicle.md`, `docs/runtime-contracts.md`, `docs/competitive-comparison.md`.
**Method:** static read-only review (no diff: this is a pre-implementation baseline; `shell`/`git` denied in this session).
**Limitation:** no `node_modules` in the checkout, so `@opencode/plugin` 2.0.26 type declarations are unavailable. Host instantiation semantics below are inferred from this repo's pinned docs, not verified against the package — flagged explicitly where it matters.

## Summary

Both files are disciplined, fail-closed transports with unusually good boundary hygiene (`safeCode`, strict `record`/`identifier`, untrusted delimiters, no payload reflection). The dedup feature fits the existing structure, but three properties of the current code will silently corrupt it if copied naively: `indexed` is marked **before** injection is confirmed, `replyText()` JSON-stringifies structured results straight into the prompt, and the worker has exactly one stdout channel carrying the whole protocol. The dominant design risk is not storage scope — it is mark-vs-confirm ordering plus a clear/retrieve race.

## Focus answers

**1. `indexed` scope.** Declared inside `setup` (`index.ts:88`), so the lifetime is one `setup` invocation = one host plugin instance; it is not module-scope and not persisted. It survives across sessions within that instance (that is its purpose), dies on server restart, and is shared by every worktree the instance serves — keyed only by session id, which is safe only if the host never reuses ids across directories. Whether the host calls `setup` once per process or once per session **cannot be verified here** (no types); the spec must add a runtime probe rather than assume `Map` persistence.

**2. `prompt` handler ordering.** `prompt` is read once at `index.ts:119`, `find` is queried with that local (`:138`), and only at `:142-145` is `promptRecord.text +=` applied in place. So the pre-injection text is already captured — the new `retrieve` needs no new plumbing, **provided** it consumes the local and not `event.prompt.text` re-read after any await. The hazard is across invocations: the mutation is in-place on the host's object (asserted by `index.test.ts:108`), so a second dispatch of the same submission reads post-injection text.

**3. Compaction payload.** `{sessionID, agent, model, system: Array<{type:"text",text}>, messages, options, tools}` per the fixture at `index.test.ts:82-92`; the handler mutates `system` (`:193-198`) so it runs before the request is consumed. `event.sessionID` is a plain string and is the only identity source that does not require an await. Today the handler checkpoints and pushes one advisory text; it clears nothing (`:199-200` documents the deliberate omission of continuation).

**4. worker-client accounting.** One `python3` process per call (`:80`), 30 s wall clock (`:6`, `:89-92`), 1 MiB stdout cap enforced per chunk (`:5`, `:93-99`), stderr drained and discarded (`:100-101`). The whole reply is one `print(json.dumps(...))` (`chronicle.py:18`) parsed by a single `JSON.parse(stdout)` (`:122`) — **stdout is the protocol, not a channel**. A structured `{text, slugs}` reply is a size non-issue (≤ ~6 KB + wrapper against 1 MiB) but it changes nothing about error signalling: any stray `print` from any imported module makes the reply unparseable and the operation fail as `worker_protocol`. A debug channel therefore exists only via stderr (currently discarded) or a file — the `CHRONICLE_DEBUG` line proposed at `docs/miglioramenti-session-chronicle.md:142-151` has no landing zone today.

**5. Failure mid-session.** A failed `retrieve` degrades safely *if* the set is updated only from a successful reply; the suppression risk is one-directional: slugs recorded for notes the model never saw. That happens today in embryo — `indexed.add` at `:132` precedes the injection attempt at `:142-145`, so a session whose `prompt.text` is not a string, or whose injection is dropped, is marked permanently. Copying that ordering into dedup produces silent, session-long suppression.

## Findings

### Critical

**C1. Compaction clear races an in-flight retrieve → lost update re-populates the set.**
`index.ts:187-201` vs `:129-141`. `compaction` awaits `checkpoint` (`:191`) before it could clear; `prompt` awaits `retrieve` (`:130`/`:138`). Sequence: prompt computes exclusions → compaction clears → prompt records returned slugs into the now-empty set → the post-compaction session suppresses notes it never saw. Fix: give each session an epoch, and clear synchronously before any await.
```ts
// in prompt:    const epoch = state(context.session_id).epoch   // captured before the await
//               after the await: if (state(context.session_id).epoch !== epoch) return
// in compaction: const s = state(String(event.sessionID)); s.epoch++; s.injected.clear()  // first line, no await
```

**C2. Dedup must be marked only after the injection actually lands.**
`index.ts:129-136` marks `indexed` before `:142-145` mutates the prompt. Fix: compute `const injectable = typeof promptRecord.text === "string"` before the worker calls, and record slugs only inside `:144`'s branch:
```ts
if (typeof promptRecord.text === "string") {
  promptRecord.text += `\n\n${additions.join("\n\n")}`
  for (const slug of returnedSlugs) state(context.session_id).injected.add(slug)
}
```

**C3. Slugs must be derived after both budget truncations, or notes get recorded as injected while truncated away.**
`retrieve-inject.py:183-192` budgets per block, then `_portable.py:141` re-wraps with `untrusted(result, MEMORY_INJECT_BUDGET_CHARS)` whose truncation at `:118-122` cuts the rendered string at a character boundary — a whole trailing note can disappear while the slug list still claims it. Fix: make `retrieve()` return `(blocks, slugs)` where `slugs` contains only blocks appended to `out`, and have the core apply the budget to blocks (drop the last block, never slice mid-string) before rendering and before reporting slugs.

**C4. `replyText()` turns a structured reply into raw JSON inside the prompt.**
`index.ts:33-36`: `JSON.stringify(reply.result)` for any non-string. A `{text, slugs}` result routed through the existing `additions.push(replyText(found))` path injects `{"text":"...","slugs":[...]}` literally. Fix: dedicated renderer, and never reuse `replyText` for `retrieve`:
```ts
function retrievalResult(reply: WorkerReply): { text: string; slugs: string[] } {
  if (!reply.ok) return { text: "", slugs: [] }
  const r = reply.result as { text?: unknown; slugs?: unknown }
  const text = typeof r?.text === "string" ? r.text : ""
  const slugs = Array.isArray(r?.slugs) ? r.slugs.filter((s): s is string => typeof s === "string" && SLUG.test(s)) : []
  return { text, slugs }
}
```

### Important

**I1. Unbounded, un-namespaced state.** `index.ts:88` has no eviction; a dedup `Map` adds a set per session on a long-lived server, and headless `opencode run` mints a new session per invocation. Fix: one `Map<string, {indexed: boolean; injected: Set<string>; epoch: number}>` with a cap (LRU, e.g. 256) and eviction on compaction; document process-scope as an explicit spec decision rather than durable dedup.

**I2. Second dispatch of the same submission double-injects and poisons the query.** `:144` mutates in place with no marker; `messageID` is already parsed at `:124`. Fix: store `lastMessageID` per session and return early on repeat; optionally strip a leading `## Project memory — auto-retrieved` block from the incoming text before using it as a query.

**I3. Compaction clear is gated behind identity resolution.** `:189-190` returns early when `trusted()` fails, leaving state populated. Fix: clear from `String(event.sessionID)` before the trust/role gate; keep `checkpoint` behind the gate.

**I4. Prompt latency is now three sequential spawns.** `checkpoint` (`:118`), `index` (`:130`), `find` (`:138`), each a cold Python process (measured ~60–100 ms import alone at `docs/miglioramenti:32`) with a 30 s ceiling each, all blocking prompt submission. Adding `retrieve` must not become a fourth. Fix: call `retrieve` first, and move `checkpoint` after injection (idle and compaction already checkpoint); state a p95 budget in the spec.

**I5. Observability is structurally impossible on the current channel.** stdout is protocol-only; stderr is discarded by design (`worker-client.ts:100`). Fix: `CHRONICLE_DEBUG` → capture stderr into a bounded buffer (≤4 KiB, keep draining to avoid pipe deadlock at 64 KiB) surfaced only via `console.error`/file, never model-facing; keep the error-message redaction rule.

**I6. Slug keys collide across namespaces.** `retrieve-inject.py:188` derives `slug` from the basename and topics/sessions are separate directories; dedup by bare slug can suppress a different note. Fix: key `kind + "/" + slug`, and validate each stored slug with `SLUG` before insertion.

**I7. The test mock hides duplicate hook registration.** `index.test.ts:37-40` stores callbacks in a `Map` keyed by name, so a second `compaction` registration would overwrite the first, while production may run both. Fix: accumulate arrays in the mock and assert single registration.

**I8. Compaction handler size.** `:187-201` will grow past a readable unit once it clears state, checkpoints, and builds two messages; extract `clearSession(event.sessionID)` and `compactionNotice(saved)`.

### Suggestion

**S1.** `retrieve()` returning a formatted string is the structural blocker for slug reporting; return structured blocks and keep rendering in `main()` (`retrieve-inject.py:194-210`) so the CLI contract at `test_topic_patch.py:244` stays intact.
**S2.** `Buffer.byteLength(stdout)` per chunk (`worker-client.ts:95`) is O(n²) on a 1 MiB cap; track a running counter.
**S3.** `worker-client.ts:102` settles without killing the child on `error`; kill in the settle path.
**S4.** `setup` awaits `recover` (`index.ts:90`) up to 30 s before returning, blocking server start.
**S5.** `retrieve-inject.py:120-121` returns `None` both for "no tokens" and "no candidates"; dedup introduces a third empty case ("all excluded"), which the silence-breaking change needs to distinguish.

## What was done well

- Fail-closed by default: `parseReply` rejects malformed envelopes without executing them, and non-zero exit discards an `ok` payload (`worker-client.ts:103-110`).
- Diagnostics are pre-sanitised (`safeCode` at `index.ts:73-75`) and user-facing strings are static, so worker internals and paths never reach the model.
- The `index` marker is at least placed after `index.ok`, and every other state transition (capture, guard) is explicitly ordered around observed success — the codebase already reasons in mark-after-success terms, which C2 only needs to extend.

## Verdict

**REQUEST CHANGES on the design, before implementation.** No defect exists in the shipped code from this feature (it is unimplemented), but C1–C4 are silent-corruption shapes that will not fail loudly and must be resolved in the spec. Re-review after the spec lands: a single pass over `index.ts` + `worker-client.ts` + `_portable.py` + `retrieve-inject.py` is well under the 500-line budget.

## Spec Inputs

**Components and files affected**

| File | Change |
|---|---|
| `adapters/opencode/index.ts` | session state map, `retrieve` call, mark-after-inject, compaction clear + epoch, renderer |
| `adapters/shared/worker-client.ts` | optional structured `meta`/`result` typing, slug validation, opt-in stderr debug |
| `skill/session-chronicle/scripts/_portable.py` | `OPERATIONS_API:22`, new `retrieve` branch in `read_operation:132-141`, `fields()` optional lists, block-level budget |
| `skill/session-chronicle/scripts/retrieve-inject.py` | structured return + exclusion filter before the `TOP_K` slice (`:183`) |
| `index.test.ts` | repeat-prompt, compaction-clear, exclusion, protocol-failure tests |
| `plugin.yaml` | only if a new Python module appears (four adapter file maps: `:22-61`, `:62-101`, `:102-137`, `:226-265`) |
| `docs/runtime-contracts.md`, `adapters/opencode/README.md` | state lifetime and dedup semantics |

**Patterns to follow / anti-patterns to avoid**
Follow: strict `record`/`identifier`/`stringField` validation at every event boundary; `safeCode` for logged error codes; `untrusted()` delimiters on all injected text; `fields()`-declared argument lists; `lifecycleFailure(operation, reply)` for non-fatal worker errors.
Avoid: `replyText`'s `JSON.stringify` fallback for anything model-facing (`index.ts:35`); marking state before confirming the effect (C2); in-place prompt mutation without an idempotency key; unbounded per-session maps with a single lifecycle for index and dedup; stderr for anything that must be seen (it is discarded).

**Integration constraints**
- `WorkerReply.result` is `object | string` (`worker-client.ts:17-19`) and `parseReply:125` accepts any object without shape checks — extend the union deliberately and validate `slugs` in the client, not at the call site.
- `_portable.fields()` **rejects unknown keys** (`:42-44`), and `trusted_context` pins context to `harness, session_id, workspace, role` (`:61`) — dedup state cannot ride in the envelope; it must be adapter-local. New ops must be listed in `OPERATIONS_API` **and** in `read_operation` plus the codex/claude allowed-argument maps (`adapters/codex/hook.py:195`, `adapters/claude-code/hook.py:220`).
- Exclusion must be applied to `scored` **before** `scored[:TOP_K]` and before per-block budgeting, otherwise excluding k notes empties the result instead of backfilling.
- `find`'s budget is applied twice (`retrieve-inject.py:43` at import, `_portable.py:141` per call); the new op needs one authoritative budget point.
- Adapter-side dedup is OpenCode-only: `adapters/codex/hook.py` and `adapters/claude-code/hook.py` are one process per event, so a file-backed store would be required for parity — and it must live outside `docs/` to avoid the write-boundary/guard rules (the design note's `.drafts/injected-<session>.json` would be rejected by the guard tests at `index.test.ts:397`).
- Hook disposables are ignored (`index.ts:110-201`); only the idle subscription is aborted on cleanup, so state cleanup cannot rely on disposal.

**Tech debt that blocks or complicates the feature**
1. `retrieve()` returns a rendered string — no structured picks, so slugs cannot be reported without refactoring three call sites (`_portable.py:139`, `retrieve-inject.py:207`, `test_topic_patch.py:270`).
2. One process per call ⇒ no worker-side session state; durability requires a file, and the file path is itself a write-boundary decision.
3. stderr discarded + single-channel stdout ⇒ no debug/metrics channel for the dedup set (blocks the §P3 observability prerequisite).
4. `indexed` never cleared ⇒ the pattern the feature would extend is already leaky.
5. Double budget accounting ⇒ slug/report divergence risk (C3).
6. Host lifecycle unverified in-checkout (no `@opencode/plugin` types) ⇒ `Map` persistence across sessions is an assumption to probe, not a fact.
7. `STATUS.yaml` points at `docs/specs/sp-20261116-retrieval-integrity-performance-spec.md`, which does not exist yet — the assessment directory is empty.

**Test coverage baseline**
- `bun test` (`package.json:45`): `index.test.ts` (14 tests) drives the adapter through a mocked plugin; `tests/pi.adapter.test.ts` covers the Pi adapter.
- `tsc --noEmit` (`package.json:46`) is the only type gate; it cannot check the unchecked `as unknown as Input` cast at `index.ts:111` or the compaction payload shape.
- Python: `tests/test_portable_core.py` (envelope/dispatch, `find`, budget), `test_portable_package.py`, `test_native_hooks.py`, `test_uat_package.py`, `test_install_local.py`, `test_neutral_workflows.py`, `test_lint_agents.py`, plus the skill-script suites (`test_memory_contracts`, `test_topic_graph`, `test_topic_patch`, `test_write_boundaries`, `test_session_context`, `test_chronicle_doctor`, `test_checkpoint`, `test_topic_review`).
- **Gaps:** no test invokes `prompt` twice for one session; no test asserts compaction clears state; no test for `worker_protocol`/`worker_timeout`/the 1 MiB cap (only `worker_unavailable` at `index.test.ts:219`); no assertion that a previously injected slug is absent from the next injection. These four are the minimum additions before build.
