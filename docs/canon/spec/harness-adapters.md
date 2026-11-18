---
domain: harness-adapters
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Harness Adapters

## Overview

Four native adapters translate each target harness's hook/extension events onto one neutral JSON envelope executed by the shared Python worker, and stamp each request with a harness name, session ID, absolute workspace and trusted role (`adapters/opencode/index.ts`, `adapters/claude-code/hook.py`, `adapters/codex/hook.py`, `adapters/pi/index.ts`, `adapters/shared/worker-client.ts`).

## Current behaviour

- **Worker resolution is package-relative only.** Every adapter looks for `core/chronicle.py`, falling back to `skill/session-chronicle/scripts/chronicle.py`, and never searches the caller's cwd or PATH (`adapters/claude-code/hook.py:48-54`, `adapters/pi/index.ts:49-59`, `adapters/shared/worker-client.ts:38-75`).
- **One process per call.** Each operation spawns `python3 <worker>`, writes a single envelope to stdin, parses one JSON reply, discards stderr, and passes no shell (`adapters/claude-code/hook.py:57-75`, `adapters/shared/worker-client.ts:77-117`, `adapters/pi/index.ts:77-130`).
- **Identity comes from native fields only.** Session ID, workspace and role are read from native hook/extension input; environment variables, model-supplied `role`, `agent_type`, `model` and transcript paths never establish identity, and missing/relative values fail closed (`adapters/claude-code/hook.py:28-40`, `adapters/codex/hook.py:27-41`, `adapters/pi/index.ts:33-38`, `tests/test_native_hooks.py:79-86`).
- **Delegated and unknown actors are read-only for memory.** Capture and checkpoint are refused unless the actor is proven primary; reads and pre-execution guards still run (`adapters/claude-code/hook.py:125-148`, `adapters/codex/hook.py:109-128`, `tests/test_native_hooks.py:187-198`).

**OpenCode** (`@opencode/plugin` 2.0.26, `package.json:32`)

- At setup it calls `recover` with the setup workspace when that path is absolute, else logs `recover_blocked:workspace_unavailable`; recovery carries no session identity (`adapters/opencode/index.ts:212-219`).
- On `prompt`, for primary sessions: checkpoint, run `index` once per session (prepending an orientation banner), then one `retrieve` call whose `exclude` list is the session's previously injected note refs, falling back to `find` when the reply is `invalid_request`, `worker_protocol`, `worker_timeout` or `worker_unavailable`; results are appended to the prompt text only after the mutation lands (`adapters/opencode/index.ts:235-288`).
- Native prompt evidence is never captured: it logs `prompt_capture_blocked:missing_event_id` or `prompt_capture_blocked:origin_unavailable` while retrieval still uses the prompt text (`adapters/opencode/index.ts:254-262`, `adapters/opencode/README.md:9-14`).
- Before `write`/`edit`/`patch` execution it calls `guard` and refuses the tool on guard failure or unresolvable identity; after a completed call it re-runs `guard` as post-validation and appends a warning to the tool result when it fails (`adapters/opencode/index.ts:289-314`).
- Completed primary tool calls are captured as `files.write`, `files.edit`, `process.exec`, and one `files.patch` per absolute `output.applied[].target` with event ID `${callID}:patch:${index}` and `origin: "synthetic"` (`adapters/opencode/index.ts:163-184`, `:315-327`).
- Compaction clears that session's dedup history before any await, then checkpoints and appends a fixed system line (success or "checkpoint failed; pending evidence retained"); it never requests a continuation (`adapters/opencode/index.ts:329-347`).
- `session.idle` and `session.status` with `status.type == "idle"` checkpoint primary sessions through a long-lived event subscription (`adapters/opencode/index.ts:348-361`).
- It contributes five SDK tools — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`, `memory_session_context` — each resolved against the trusted session before dispatch (`adapters/opencode/index.ts:362-396`).

**Claude Code** (reference release 2.1.299; installed 2.1.220; `adapters/claude-code/README.md:5-16`)

- Registers `SessionStart`, `PreToolUse` (matcher `Write|Edit`), `PostToolUse` and `PostToolUseFailure` (matcher `Write|Edit|Bash`), `UserPromptSubmit`, `Stop`, `PreCompact`, `SessionEnd`; `PostCompact` is deliberately not registered (`adapters/claude-code/hooks.fragment.json:3-10`).
- `SessionStart` checkpoints a primary, then injects the `index` result as untrusted `additionalContext`; index runs even when the checkpoint fails (`adapters/claude-code/hook.py:173-176`).
- `UserPromptSubmit` attempts prompt capture (refused as `native_origin_unproven` even when a `prompt_id` exists), then independently calls `find` with the prompt and `includeEvidence: false` and injects the result (`adapters/claude-code/hook.py:182-186`, `tests/test_native_hooks.py:130-139`).
- `PreToolUse` preflights `replace`/`edit` guards; any contract or worker failure becomes `permissionDecision: deny` with exit 2, even for malformed stdin (`adapters/claude-code/hook.py:177-181`, `:206-213`).
- `PostToolUse` captures Write/Edit as `files.write`/`files.edit` and Bash as `process.exec` with the native `tool_use_id`, `status: "completed"`, `origin: "unknown"`; capture happens before post-write lint, so lint failure only adds a `systemMessage` (`adapters/claude-code/hook.py:187-194`, `tests/test_native_hooks.py:141-152`).
- `PostToolUseFailure` excludes the failed call entirely and reports a nonfatal diagnostic (`adapters/claude-code/hook.py:110-117`, `:188-189`).
- `Stop`, `PreCompact` and `SessionEnd` checkpoint a primary; for `PreCompact`/`SessionEnd` the diagnostic is re-raised to stderr with exit 1 (`adapters/claude-code/hook.py:195-200`).
- Role is `primary` unless `agent_id` is present, in which case `delegated`; `agent_type` is ignored (`adapters/claude-code/hook.py:35-40`, `tests/test_native_hooks.py:58-68`).

**Codex** (`codex-cli` 0.163.0, tag `rust-v0.163.0`, commit `8308618…`; `adapters/codex/README.md:5-6`)

- Registers `SessionStart`, `PreToolUse` (matcher `^apply_patch$`), `PostToolUse` (matcher `^(apply_patch|Bash)$`), `UserPromptSubmit`, `Stop`, `PreCompact`, `Interrupt`, `SessionEnd` (`adapters/codex/hooks.fragment.json:3-10`).
- `SessionStart` performs index orientation; the concurrent checkpoint attempt is refused because the actor is `unknown` (`adapters/codex/hook.py:153-156`, `tests/test_native_hooks.py:446-448`).
- `UserPromptSubmit` runs `find` from the prompt text; prompt capture always raises `native_prompt_event_id_unproven` because `turn_id` is not treated as a prompt event ID (`adapters/codex/hook.py:92-95`, `:162-166`).
- `PreToolUse` reconstructs a `patch` guard proposal from `apply_patch`'s `command` (never a synthesized path), denies with exit 2 (`adapters/codex/hook.py:80-87`, `:157-161`).
- `PostToolUse` preserves the native `tool_use_id` and completion status but captures nothing: Bash is refused `actor_not_primary`, `apply_patch` is refused `native_tool_capture_shape_unsupported` (`adapters/codex/hook.py:96-113`, `tests/test_native_hooks.py:160-186`).
- `Stop`/`PreCompact` checkpoint only proven primaries, which in practice never resolves from these events; `SessionEnd`/`Interrupt` are the only events where an absent `agent_id` proves primary, and they use a 2-second worker timeout inside the 3-second native limit (`adapters/codex/hook.py:34-41`, `:63`, `adapters/codex/hooks.fragment.json:9-10`).
- `PostCompact` is refused as `use_session_start_compact_for_context` (`adapters/codex/hook.py:175-177`).

**Pi** (`@earendil-works/pi-coding-agent` 1.2.0, `package.json:39`)

- Registers `session_start` → `index`, `session_before_compact` → awaited `checkpoint`, `tool_call` → `guard` for `write`/`edit` (Pi's `edits[]` array mapped per edit), and `message_end` for user messages, which only warns that prompt capture is unavailable (`adapters/pi/index.ts:194-208`).
- A guard reply that is an error, or that returns `allowed: false`/`block: true`, blocks the tool call with a fixed reason; unavailable guard blocks writes rather than allowing them (`adapters/pi/index.ts:158-163`, `tests/pi.adapter.test.ts:30-38`).
- Exposes `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit` as read-only tools; `memory_session_context` is registered but always returns `provenance_unavailable` (`adapters/pi/index.ts:176-192`).
- Context is always `{harness: "pi", role: "unknown"}` because Pi 1.2.0 documents no primary/delegated field, so capture, checkpoints and `memory_session_context` cannot succeed (`adapters/pi/index.ts:33-37`, `adapters/pi/README.md:17-27`).

## Public contracts

- **Worker envelope** `{"schema_version": 1, "operation": <name>, "context": {"harness", "session_id", "workspace", "role"}, "arguments": {…}}` on stdin, one JSON reply `{ok: true, result}` or `{ok: false, error: {code, message}}` on stdout (`adapters/claude-code/hook.py:43-45`, `adapters/shared/worker-client.ts:21-33`).
- **Harness identifiers** are exactly `opencode`, `claude-code`, `codex`, `pi` (`adapters/opencode/index.ts:228`, `adapters/claude-code/hook.py:12`, `adapters/codex/hook.py:12`, `adapters/pi/index.ts:37`).
- **Python adapter surface**: `hook_context(payload)`, `run_core(message)`, `capture_arguments(payload)`, `guard_arguments(payload, phase)`, `handle_hook(payload)`, `diagnostic_request(payload, operation, arguments)`, and the CLI `hook.py [--event E] [--diagnostic OP] [--arguments JSON]` reading one hook payload from stdin (`adapters/claude-code/hook.py:230-260`, `adapters/codex/hook.py:205-235`).
- **Hook output shapes**: `{"systemMessage": …}` for diagnostics, `hookSpecificOutput.additionalContext` for injected reads, `hookSpecificOutput.permissionDecision: "deny"` for pre-tool refusal (`adapters/claude-code/hook.py:151-159`, `:206-213`).
- **Pi surface**: `registerPiExtension(pi, run?)`, `createWorkerRunner({timeoutMs, maxStdoutBytes, resolveWorker, spawnWorker})`, default export `extension` (`adapters/pi/index.ts:77`, `:166`, `:211`).
- **OpenCode surface**: `createSessionChronicle(worker?)` returning a plugin, default export `SessionChronicle`, plus `createSessionStore(env?)`, `noteRef(value)`, `NOTE_REF`, and the `SessionStore` contract (`size`, `peek`, `touch`, `exclude`, `record`, `compact`) (`adapters/opencode/index.ts:12-90`, `:209`, `:402`).
- **Shared transport**: `ChronicleWorkerClient.call(operation, context, arguments)` and `.recover(workspace)`, with `ChronicleRole = "primary" | "delegated" | "unknown"` (`adapters/shared/worker-client.ts:8-63`).
- **Registration fragments** `adapters/<harness>/hooks.fragment.json` are settings-shaped and inert, containing only `type`/`command`/`timeout` handlers and a fixed `--event` (`adapters/claude-code/hooks.fragment.json`, `tests/test_native_hooks.py:375-386`).
- **Operations dispatched per adapter** — OpenCode: `recover`, `checkpoint`, `index`, `retrieve`, `find`, `guard`, `capture`, `recall`, `backlinks`, `audit`, `context`. Claude/Codex: `checkpoint`, `index`, `find`, `guard`, `capture` (Codex guard/capture only for `apply_patch`/Bash), plus operator-only `recall`/`backlinks`/`audit`/`retrieve`. Pi: `index`, `checkpoint`, `guard`, `find`, `recall`, `backlinks`, `audit` (`adapters/opencode/index.ts`, `adapters/claude-code/hook.py:169-203`, `adapters/pi/index.ts:166-209`).

## Enumerated providers / limits

- **Providers (native harnesses), closed set of four**: `opencode`, `claude-code`, `codex`, `pi` (`adapters/opencode/`, `adapters/claude-code/`, `adapters/codex/`, `adapters/pi/`).
- **Roles**: `primary`, `delegated`, `unknown` (`adapters/shared/worker-client.ts:8`). Claude maps absent `agent_id` → primary (`adapters/claude-code/hook.py:35-40`); Codex maps absent `agent_id` → unknown except `SessionEnd`/`Interrupt` → primary (`adapters/codex/hook.py:34-41`); Pi is always unknown (`adapters/pi/index.ts:37`); OpenCode uses `parentID` presence → delegated (`adapters/opencode/index.ts:228`).
- **Reference versions targeted**: `@opencode/plugin` 2.0.26 (`package.json:32`); `@earendil-works/pi-coding-agent` 1.2.0 (`package.json:39`); Claude Code release reference 2.1.299 with installed 2.1.220 and mods minimum 2.1.287 (`adapters/claude-code/README.md:5-15`); codex-cli 0.163.0 / `rust-v0.163.0` (`adapters/codex/README.md:5-6`).
- **OpenCode session store**: `MAX_SESSIONS = 256` with insertion-order eviction (`adapters/opencode/index.ts:13`, `:57-61`); `DEFAULT_MEMORY_INJECT_TOPK = 3` overridable via `MEMORY_INJECT_TOPK`; `REFS_PER_TOP_K = 50`; per-session ref cap `MAX_EXCLUDE_REFS = 200` (`adapters/opencode/index.ts:14-22`, `:40-43`).
- **Reference predicate**: `NOTE_REF = /^(?:session|topic):[a-z0-9][a-z0-9-]{0,190}$/`; slug predicate `^[a-z0-9]+(?:-[a-z0-9]+)*$` (`adapters/opencode/index.ts:10-12`, `adapters/pi/index.ts:19`).
- **Transport**: worker timeout 30 000 ms and stdout cap 1 048 576 bytes for OpenCode and Pi (`adapters/shared/worker-client.ts:5-6`, `adapters/pi/index.ts:78-79`); Python adapters use 20 s for every operation, with 2 s for Codex `checkpoint` (`adapters/claude-code/hook.py:61`, `adapters/codex/hook.py:63`).
- **Native registration timeouts**: Claude 30 s on every event (`adapters/claude-code/hooks.fragment.json`); Codex 30 s except `Interrupt`/`SessionEnd` at 3 s (`adapters/codex/hooks.fragment.json:9-10`).
- **Operator diagnostics**: `DIAGNOSTIC_OPERATIONS = ("index", "find", "recall", "backlinks", "audit", "retrieve")` on both Python adapters; diagnostics force role `unknown` and reject identity arguments (`adapters/claude-code/hook.py:13`, `:216-227`).
- **Audit modes (Pi tool)**: `orphans`, `dups`, `dangling`, `stale`, `candidates`, `quality` (`adapters/pi/index.ts:18`).
- **Unsupported operations per adapter** — Claude: prompt capture, `context`/semantic context, custom native tools, `PostCompact` handler. Codex: prompt capture, all tool capture (Bash lacks primary, `apply_patch` shape unsupported), `context`, `PostCompact` handler. Pi: prompt capture, `memory_session_context`, checkpoints (unknown role). OpenCode: prompt capture only (all other operations are wired).

## Cross-domain dependencies

- Executes the shared worker at `core/chronicle.py` / `skill/session-chronicle/scripts/chronicle.py` and depends on its operation roster (`checkpoint`, `index`, `retrieve`, `find`, `guard`, `capture`, `recover`, `context`, `recall`, `backlinks`, `audit`) (`adapters/claude-code/hook.py:48-54`, `adapters/shared/worker-client.ts:38-41`).
- Depends on retrieval/index semantics and its degradation codes (`invalid_request`, `worker_protocol`, `worker_timeout`, `worker_unavailable`) to fall back from `retrieve` to `find` (`adapters/opencode/index.ts:120-161`).
- Depends on the journal guard and protected-history policy, surfaced as denial or warning at `guard` sites (`adapters/claude-code/hook.py:177-194`, `adapters/pi/README.md:22-24`).
- Depends on journal capture semantics for `files.write`, `files.edit`, `files.patch`, `process.exec` and `prompt.submit` event shapes (`adapters/claude-code/hook.py:104-122`, `adapters/opencode/index.ts:163-184`).
- Depends on the envelope schema to validate hook requests, asserted byte-compatible in tests (`tests/test_native_hooks.py:228-271`, referencing `schemas/envelope.schema.json`).
- Reads the packaging manifest's `adapters.codex.hooks` contributions and capability names `chronicle.retrieval`, `chronicle.protected-history`, `chronicle.capture`, `chronicle.session-context`, none of which live under the adapter paths (`adapters/codex/README.md:10-17`, `:85-104`).
- Emits operator diagnostics consumed by packaging/qualification workflows, and requires an external broker for model-facing memory tools in Codex (`adapters/codex/README.md:85-104`).

## Gaps

- **Two worker-resolution preferences.** `worker-client.ts` (OpenCode) tries `skill/session-chronicle/scripts/chronicle.py` *before* `core/chronicle.py`, while Pi and both Python adapters prefer `core/chronicle.py` (`adapters/shared/worker-client.ts:38-41` vs `adapters/pi/index.ts:20-23`). Which bundle wins when both exist is undocumented.
- **Claude README diagnostic roster is stale.** Prose lists `index`/`find`/`recall`/`backlinks`/`audit` and omits `retrieve`, but the code and tests include `retrieve` (`adapters/claude-code/README.md:51` vs `adapters/claude-code/hook.py:13`, `tests/test_native_hooks.py:228-245`).
- **Codex patches are guarded but never journaled.** `PreToolUse` intercepts `apply_patch`, yet `PostToolUse` refuses `apply_patch` capture as `native_tool_capture_shape_unsupported`; whether patch bodies are intentionally unwritable or awaiting a shape contract is unstated (`adapters/codex/hook.py:85-105`, `adapters/codex/README.md:44-50`).
- **`stop_hook_active` is computed and never used.** Both Python adapters derive `active` in `main()` and pass it to `failure_output(event, code, stop_active=False)`, whose body ignores it; the documented "Stop never requests another turn" property is asserted only by tests (`adapters/claude-code/hook.py:206-213`, `:257`, `tests/test_native_hooks.py:295-299`).
- **Pi lifecycle checkpoints cannot succeed.** `session_start`/`session_before_compact` are issued with role `unknown`, so core refuses checkpoints; the code records this as a warning only, and README says the core "returns the unavailable result" — unclear whether this is the shipped behaviour or a pending Pi identity contract (`adapters/pi/index.ts:33-37`, `:171-174`, `adapters/pi/README.md:17-27`).
- **OpenCode dead role branch.** `execute.before`/`execute.after` test `context.role === "unknown"`, but `trusted()` only ever returns `primary` or `delegated`, so the branch is unreachable (`adapters/opencode/index.ts:224-229`, `:294`, `:308`).
- **Entry re-export paths differ.** `adapters/opencode/entry.ts` re-exports `./adapters/opencode/index.ts`, while `adapters/pi/entry.ts` re-exports `./index.ts`; the OpenCode form only resolves if the bundler relocates the file to the package root, which its README does not state (`adapters/opencode/entry.ts:1`, `adapters/pi/entry.ts:2-3`).
- **Per-session dedup exists only in OpenCode.** `injected` refs, the epoch guard and `exclude` lists have no counterpart in the hook or Pi adapters, so repeated retrieval across Claude/Codex/Pi prompts is not deduplicated; recorded as an intentional asymmetry in code comments, not in any adapter contract (`adapters/opencode/index.ts:45-90`, `adapters/claude-code/hook.py:182-186`).
