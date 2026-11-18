---
domain: capture
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Passive Capture

## Overview

Zero-token, heuristic capture of meaningful session activity — user prompts, file writes/edits and significant shell commands — into an uncommitted daily draft buffer that the checkpoint path later seals and publishes as factual evidence without a model. Two entry points exist: a harness hook (`skill/session-chronicle/scripts/capture-signals.py`) and a portable capability-envelope writer (`skill/session-chronicle/scripts/_capture.py`).

## Current behaviour

- Captures user prompt text after stripping injected memory blocks (retrieval headings, untrusted wrappers, index headings) via the shared `strip_injected` predicate; prompts consisting only of injected content are dropped (`_capture.py:52`, `capture-signals.py:43`).
- Drops the skill's own slash command: prompts whose text begins with `/session-chronicle` are never captured (`_capture.py:53`, `capture-signals.py:79`).
- Captures file write/edit/patch activity as `{kind: file, op, path}` for the five `files.*` operations (`_capture.py:54-59`) and for the `Write`/`Edit` tools on the hook path (`capture-signals.py:47-49`); file signals pass through unfiltered by marker logic (proven by `test_capture_injected_filter.py:189-195`).
- Ignores activity inside chronicle storage: the envelope writer skips writes under `.drafts`, `pending`, `sessions`, `topics` and `continuations` (`_capture.py:56-58`); the hook skips `.drafts`, `sessions` and `topics` (`capture-signals.py:74-78`).
- Captures shell commands as `{kind: bash, cmd}`, dropping empty commands and noise commands whose first token is `ls`, `cat`, `pwd`, `echo` or `cd` (`_capture.py:14,60-66`, `capture-signals.py:54-56`).
- Refuses to capture its own maintenance commands: environment assignments are unwrapped, `python`/`python3`/`bash` launchers (and `-B`) are unwrapped, the target script must live in the scripts directory and appear on a fixed allowlist; multi-line commands and commands containing shell operators are never treated as maintenance (`_capture.py:19-44`).
- Redacts secret-like values heuristically in prompt text, file paths and commands, exactly once — a second pass must not produce `[REDACTED][REDACTED]` (`_capture.py:52,59,66`; `test_capture_injected_filter.py:105-113`).
- Rejects a whole event whose provenance already contains secret-like values, raising `ValueError` instead of writing (`_capture.py:120-121`).
- Two independent kill switches disable *future* capture per channel — `SESSION_CHRONICLE_CAPTURE_PROMPTS` and `SESSION_CHRONICLE_CAPTURE_BASH`, default enabled, disabled by `0`/`false`/`no`/`off`; already-buffered data is retained and no pruning occurs (`_capture.py:15,50,60`, `capture-signals.py:41,51`).
- Appends each admitted signal to `<docs-root>/.drafts/<YYYY-MM-DD>.draft.jsonl` inside a shared writer lock using atomic full-file replacement plus an fsync of the parent directory (`_capture.py:122-128`, `capture-signals.py:88-99`).
- Envelope path is replay-safe: an event is matched on `(session_id, event_id)` across every stored draft, pending buffer and published batch; an identical re-delivery returns `duplicate` and re-syncs the file, a reuse of the same identity with a different payload raises `ReplayConflict` (`_capture.py:96-110,123-124`).
- Hook path instead collapses only *consecutive* duplicates, keyed by the SHA-256 of the sorted signal record, stored as `_h` on the record (`capture-signals.py:90-97`).
- Skips the event when the hook reports `stop_hook_active`, and ignores any hook event other than `PostToolUse` or `UserPromptSubmit` (`capture-signals.py:63-66`).
- Refuses to touch malformed evidence: an unparseable draft line, an unexpected record kind, or an invalid published factual batch aborts before any write; the wrapper never truncates or repairs buffers (`_capture.py:77-78,85-87`, `capture-signals.py` docstring `:18-20`).
- Never writes to stdout on the hook path (any stdout on `UserPromptSubmit` would enter context); failures print one stderr line and exit non-zero (`capture-signals.py:9-10,102-108`; `test_capture_injected_filter.py:128-140`).
- Captured prompt text is stored in full with no size cap or truncation (`test_capture_injected_filter.py:142-147`).

## Public contracts

- `select_signal(arguments, project, base) -> dict | None` — maps capability arguments to a signal, or `None` for "capture policy declines" (`_capture.py:47`).
- `capture(context, arguments, base) -> dict` — returns `{"status": "captured"|"duplicate"|"skipped", ...}`; skipped carries `{"reason": "capture_policy"}` and no text, digest or dedup key (`_capture.py:113-129`, `test_capture_injected_filter.py:86-103`).
- `is_maintenance_command(command, cwd) -> bool`, `stored_records(base) -> Iterator[(path, record)]`, `replayed(base, candidate) -> bool`, `class ReplayConflict(ValueError)` (`_capture.py:19,69,92,96`).
- `build_signal(data) -> dict | None` and a CLI reading one JSON hook payload from stdin, emitting nothing on stdout, exiting `0` on success and `1` on capture failure (`capture-signals.py:39,60-108`).
- Capability envelope consumed by the writer (shipped shape, from the tests): `{"schema_version": 1, "operation": "capture", "context": {"harness", "session_id", "workspace", "role"}, "arguments": {"operation", "event_id", "text"|"path"|"command"[,"workdir"], "status", "origin"}}`; the reply is wrapped as `{"ok": true, "result": ...}` by the portable dispatcher (`test_capture_injected_filter.py:65-71`).
- Draft record schema, envelope path: `{kind, text|op+path|cmd, identity, session_id, event_id, operation, origin, status, ts}` (`_capture.py:52,59,66,117-125`). Hook path: `{kind, ..., sessionID, eventID, _h, ts}` (`capture-signals.py:86-98`).
- Buffer file format: JSONL named `YYYY-MM-DD.draft.jsonl` under `<docs-root>/.drafts/`; readers additionally consume `.drafts/pending/*.jsonl` and published `sessions/*.md` batches marked `record-kind: factual-evidence` or carrying a batch-id stem (`_capture.py:69-89,126`).
- Hook integration surface: reads `hook_event_name`, `prompt`, `tool_name`, `tool_input`, `cwd`, `sessionID`, `eventID`, `stop_hook_active`; honours `PROJECT_ROOT` (`capture-signals.py:60-89`).

## Enumerated providers / limits

- **Capture channels**: `prompt` (operations `prompt.submit`), file (`files.write`, `files.edit`, `files.patch`), `bash` (`process.exec`) — the operation set is declared as `OPERATIONS` at `_capture.py:16`, and `prompt`/`file`/`bash` are the only kinds accepted on read (`_capture.py:77`).
- **Signal kinds**: `prompt`, `file`, `bash` (`_capture.py:16,77`).
- **Disabled values**: `("0", "false", "no", "off")`, case-insensitive (`_capture.py:15`; re-inlined at `capture-signals.py:41,51`).
- **Noise commands**: `ls`, `cat`, `pwd`, `echo`, `cd` (`_capture.py:14`, `capture-signals.py:31`).
- **Skipped storage folders**: envelope writer `.drafts`, `pending`, `sessions`, `topics`, `continuations` (`_capture.py:57`); hook `.drafts`, `sessions`, `topics` (`capture-signals.py:77`).
- **Maintenance allowlist** (script basenames in the scripts dir): `checkpoint.py`, `capture-signals.py`, `note-lint.py`, `sync-topics-field.py`, `topic-index.sh`, `retrieve-inject.py`, `memory-recall.sh`, `memory-audit.py`, `backlinks.py`, `slugify.py`, `_docsroot.py`, `session-context.py`, `_session_notes.py`, `topic-maintenance.py`, `topic-patch-lint.py`, `_memory_read.py`, `chronicle.py`, `chronicle-doctor.py` (`_capture.py:38-44`).
- **Interpreter unwrapping**: `python`, `python3`, `bash`, with a single leading `-B` stripped for Python (`_capture.py:30-34`).
- **Draft naming / timestamps**: `<local date>.draft.jsonl`; `ts` is local timezone ISO-8601 truncated to seconds (`_capture.py:125-126`, `capture-signals.py:98`).
- **Size limits**: none — prompt text is unbounded, no truncation or cap on record size (`test_capture_injected_filter.py:142-147`); no retention/pruning of unpublished evidence (`capture-signals.py:13`).

## Cross-domain dependencies

- Sealing and publication of draft buffers into immutable factual batches (`_capture.py:9` imports `_checkpoint`; `capture-signals.py:2-7` names `checkpoint.py` as the sealer/publisher) — the `checkpoint` domain.
- Injected-memory marker stripping, shared leaf predicate and marker constants (`_capture.py:10`, `capture-signals.py:29`; asserted for `_capture.py`, `capture-signals.py`, `_portable.py` and `retrieve-inject.py` at `test_capture_injected_filter.py:38,199-214`) — memory-markers / retrieval-injection.
- Session-note linting and identity: `note_lint.record_session_id`, `split_fm`, `fm_get`, `is_batch_id`, `record_findings`, `factual_records`, `secret_findings`, `require_unambiguous_identity` (`_capture.py:11,79-99,120`) — session-notes / note-lint.
- Storage layout and regular-file validation: `storage_layout`, `regular_file` (`_capture.py:12,70,73,82`) — storage-paths.
- Docs-root resolution from `AGENTS.md` frontmatter `docs-root` (`capture-signals.py:26,73`; test fixture `test_capture_injected_filter.py:54`) — docs-root configuration.
- Adapter/envelope dispatch and harness identity, which decides which writer runs and wraps the reply as `{"ok": ...}` (`_capture.py:117` consumes `context["identity"]`, `context["qualified_id"]`; exercised through `_portable.response` at `test_capture_injected_filter.py:71`) — portable capability envelope.
- Session identity and role (`context.harness`, `session_id`, `role`) supplied by the adapter (`test_capture_injected_filter.py:66-68`) — session context.

## Gaps

- `OPERATIONS` is declared at `_capture.py:16` but never referenced inside this slice; the enforcement point (likely the portable dispatcher) is out of scope. Which operations the capability actually admits is unverified here.
- `select_signal` falls through to the shell branch for any operation that is neither `prompt.submit` nor `files.*`, and reads `arguments["command"]` unguarded (`_capture.py:60-66`). If `OPERATIONS` is not enforced upstream, an unknown operation raises `KeyError` rather than skipping.
- Two writers with divergent policy: file-folder skips differ (`pending`/`continuations` only in the envelope writer, `_capture.py:57` vs `capture-signals.py:77`), and dedup differs (identity replay vs consecutive-hash, `_capture.py:96-110` vs `capture-signals.py:90-97`). Which writer is canonical per harness — and whether the divergence is intended — is not decidable from these files.
- Record schema diverges between writers (`session_id`/`event_id` vs `sessionID`/`eventID`, plus a hook-only `_h` at `capture-signals.py:86-97`). Where hook records are normalised for readers that require unambiguous identity (`_capture.py:99`) lives in `_session_notes`, outside this scope.
- `stored_records` calls `require_unambiguous_identity` on every stored record (`_capture.py:99`), so any pre-identity historical buffer makes all ingestion raise. Whether such legacy buffers exist in the supported corpus is unknown.
- Harness gating is declared in product context but only implied here (hook event names vs capability envelope). The set of harnesses routed to each writer, and any declared-unsupported harness, is not enumerated in these files — record as a limit whose detail lives in the adapter layer.
- `DISABLED` is duplicated as an inline literal in `capture-signals.py:41,51` instead of importing `_capture.DISABLED` (`_capture.py:15`). Behaviourally identical today; flagged as drift risk, not a defect.
- `stop_hook_active` short-circuits capture entirely (`capture-signals.py:65-66`); the intent (avoid recursion during a stop hook) is inferable but not documented in scope — whether activity during that window is knowingly lost is a human decision.
