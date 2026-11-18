---
domain: runtime-architecture
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Runtime Architecture

## Overview

One versioned process protocol and one on-disk memory layout, shared unchanged by every harness adapter. A workspace's memory root (`<docs-root>`) is resolved from project frontmatter, pinned inside the project, and written only through a single locked, durably published storage layout; adapters converse with the shared Python core by piping exactly one JSON envelope in and receiving exactly one JSON response out (`skill/session-chronicle/scripts/chronicle.py`, `skill/session-chronicle/scripts/_portable.py`, `skill/session-chronicle/scripts/_docsroot.py`).

## Current behaviour

- **Resolves `<docs-root>` from the instruction file.** Reads `docs-root:` from the YAML frontmatter of `AGENTS.md` first and `CLAUDE.md` second; falls back to `docs` when neither declares one (`skill/session-chronicle/scripts/_docsroot.py:22`, `:43-49`, `:27-40`).
- **Rejects unsafe roots instead of degrading.** A declaration that is absolute, contains `..`, resolves outside the project, or overlaps a managed harness config directory (`.opencode`, `.claude`, `.codex`, `.pi`, `.agents`) raises `ValueError`; it never silently falls back to `docs` (`skill/session-chronicle/scripts/_docsroot.py:52-68`, `README.md:98`).
- **Diagnoses misplaced memory.** Reports the resolved root as unsound when it holds no notes but `sessions/*.md` or `topics/*.md` exist in another top-level project directory or its `docs/` child, and names the file to repair (`skill/session-chronicle/scripts/_docsroot.py:75-98`, `:101-133`).
- **Refuses aliased storage before writing.** Any symlinked component of the root or of its memory folders, any non-regular file, any non-directory, or a file whose hard-link count exceeds 1 (one extra `.checkpoint-*` inode-sharing temporary is tolerated) aborts as an error (`skill/session-chronicle/scripts/_storage_paths.py:8-44`).
- **Serialises publication behind one exclusive lock.** A checkpoint opens `<docs-root>/.drafts/.writer.lock` with `O_CREAT|O_WRONLY|O_APPEND|O_NOFOLLOW` at mode `0600`, rejects it unless the descriptor is a regular file with exactly one hard link, blocks on `fcntl.flock(LOCK_EX)`, and re-validates the whole storage layout *after* the lock is held (`skill/session-chronicle/scripts/_checkpoint.py:41-52`).
- **Seals drafts into UUID-named pending batches.** Under that lock, each non-empty `????-??-??.draft.jsonl` is fsynced, renamed to `.drafts/pending/<date>--evidence-<uuid4 hex>.jsonl`, and both directories are fsynced; a draft is never truncated, and a malformed buffer is left byte-identical for repair (`skill/session-chronicle/scripts/_checkpoint.py:323-338`, `:110-115`).
- **Validates an entire run before writing anything.** Every pending batch is rendered, identity grouping is checked across drafts, pending batches and existing evidence notes, and every presentation destination is checked for symlinks, identity collisions and closed status before the first byte is published — so a corrupt batch stops the run with its evidence still in `pending/` and no partial notes (`skill/session-chronicle/scripts/_checkpoint.py:257-262`, `:339-341`, `:352-362`).
- **Publishes evidence by hard link, derived views by atomic rename.** An immutable evidence note is written to a `.checkpoint-*` temporary, fsynced, `os.link`-ed into its final name (a destination that already exists must be byte-identical or the run aborts with `Checkpoint publication conflict`), the directory is fsynced, then the temporary is unlinked; a mutable session presentation is written to `.presentation-*` and moved in with `os.replace` plus a directory fsync (`skill/session-chronicle/scripts/_checkpoint.py:274-292`, `:305-320`).
- **Removes a batch only once its notes are durable.** After the evidence note and its presentations are published, the pending batch is unlinked and the pending directory fsynced; the run returns the list of published note paths (`skill/session-chronicle/scripts/_checkpoint.py:342-349`).
- **Leaves crash residue inert.** A `.checkpoint-*` temporary that shares the published inode is tolerated by the storage guard and removed by the next successful publication, and `.presentation-*` temporaries are unlinked in a `finally` (`skill/session-chronicle/scripts/_checkpoint.py:295-302`, `:318-320`, `skill/session-chronicle/scripts/_storage_paths.py:15-25`).
- **Names derived notes readably but keys them by identity.** A presentation lands at `sessions/<YYYY-MM-DD>--<first 40 chars of the normalized id>-<sha256 first 12 hex>.md`, carries the id as `session-id` frontmatter, and is never rewritten once `status: closed` (`skill/session-chronicle/scripts/_checkpoint.py:127-131`, `:173-182`, `:219-220`).
- **Keeps memory files immutable once named.** A continuation record's filename is the SHA-256 of its exact UTF-8 JSON bytes; reading verifies the digest and rejects any mismatch (`skill/session-chronicle/scripts/_portable.py:210-215`, `:243-249`, `schemas/continuation.schema.json:5`).
- **Reads one envelope and writes one response, and writes no bytecode.** `chronicle.py` parses exactly one JSON document from stdin, prints one JSON response to stdout, and exits 0 on success or 1 on failure with `sys.dont_write_bytecode` set (`skill/session-chronicle/scripts/chronicle.py:6`, `:11-19`).
- **Serves every operation from one in-process core.** Sub-scripts are loaded by path and cached, so one process call is one implementation (`skill/session-chronicle/scripts/_portable.py:34-39`).
- **Gates memory mutation on trusted role.** Capture and checkpoint return `{"status":"skipped","reason":"delegated_session"}` for delegated sessions; `context` and `continuation` refuse them with `primary_required`; an `unknown` role is refused with `unknown_provenance` before any memory write (`skill/session-chronicle/scripts/_portable.py:269-274`).
- **Admits only completed, user-originated capture events.** Everything else returns `{"status":"skipped","reason":"unadmitted_event"}` (`skill/session-chronicle/scripts/_portable.py:275-279`).
- **Answers retrieval without touching memory.** `retrieve` resolves and answers before any docs-root resolution, so a stopword or empty query can never fail on a broken root (EC-01) (`skill/session-chronicle/scripts/_portable.py:265-267`).
- **Wraps all recalled text as untrusted.** Note bodies returned by `find`, `retrieve`, `recall`, `backlinks`, `audit`, `index` and `context` are delimited by untrusted markers, and stored text is escaped (`skill/session-chronicle/scripts/_portable.py:132-139`, `:166-199`).
- **Fails closed with fixed error codes.** Unexpected exceptions are never reflected: only `validation_failed`/`operation_failed` with a generic message reach the caller, with no payload, path, credential or traceback (`skill/session-chronicle/scripts/_portable.py:298-310`).

## Public contracts

- **Process protocol (stable entrypoint).** `chronicle.py` on stdin: `{"schema_version":1,"operation":<op>,"context":{...},"arguments":{...}}`; on stdout: `{"ok":true,"result":…}` or `{"ok":false,"error":{"code","message"}}`; unknown/absent JSON yields `invalid_json`. `result` is an object or a string (`skill/session-chronicle/scripts/chronicle.py:11-19`, `schemas/envelope.schema.json:6-13`, `schemas/response.schema.json:4-11`).
- **Envelope schema `urn:chronicle:envelope:v1`.** `additionalProperties:false` at every level; `schema_version` is the integer 1; the operation-specific `arguments` shapes are declared per operation (`schemas/envelope.schema.json`).
- **Trusted context (adapters supply, models cannot).** Normal operations require `{harness, session_id, workspace, role}`; `recover` instead requires only `{harness, workspace}` and may not carry identity or arguments (`schemas/envelope.schema.json:63-79`, `skill/session-chronicle/scripts/_portable.py:60-67`).
- **Workspace is validated, never defaulted.** Must be an absolute, existing directory without parent traversal; no cwd or environment fallback (`skill/session-chronicle/scripts/_portable.py:53-57`, `schemas/envelope.schema.json:5`).
- **Qualified session identity.** `chronicle:v1:<harness>:<URL-safe base64 of the UTF-8 session_id, paddings stripped>`; parsing re-derives the canonical form and rejects non-canonical input; bare legacy identifiers are never assigned a harness (`skill/session-chronicle/scripts/_identity.py:12-37`, `schemas/identity.schema.json:5`).
- **On-disk layout under `<docs-root>`** (`README.md:89-96`, mirrored by `skill/session-chronicle/scripts/_storage_paths.py:5`, `:40-44`):
  - `sessions/*.md` — one mutable `record-kind: session-presentation` per captured session, optional semantic summaries, immutable factual-evidence batches;
  - `topics/*.md` — atomic ideas, annotated structure notes, retained redirects;
  - `.drafts/*.draft.jsonl` — durable uncommitted capture buffers, never age-pruned;
  - `.drafts/pending/*.jsonl` — sealed batches awaiting publication or acknowledgement;
  - `continuations/*.json` — sourced links between distinct qualified sessions;
  - `reports/session-chronicle-refactor-<run-id>/` — refactoring reports and original-topic snapshots, excluded from retrieval;
  - `.drafts/.writer.lock` — the single-writer advisory lock file.
- **Publication contract visible to readers.** `sessions/<batch-id>.md` (factual evidence) appears atomically and is never modified afterwards; `sessions/<date>--<id>-<digest>.md` (presentation) is replaced atomically and stops changing at `status: closed`; a file still in `.drafts/pending/` means "not yet published", and a `.checkpoint-*`/`.presentation-*` file is never a note (`skill/session-chronicle/scripts/_checkpoint.py:274-320`, `:342-349`).
- **Continuation record (`urn:chronicle:continuation:v1`).** `{schema_version:1, from:<identity>, to:<identity>, sources:[<evidence batch id>…], reason}`; both endpoints must differ and each must be substantiated by a valid factual source's original identity metadata; the record may not contain secret-like values (`schemas/continuation.schema.json`, `skill/session-chronicle/scripts/_portable.py:219-237`).
- **Operation result shapes** (dispatch return values, `skill/session-chronicle/scripts/_portable.py:255-295`): `capture` → capture receipt; `checkpoint` → `{published, session_id}`; `context` → session-context result plus `identity`, `enrichment_allowed`, `continuations`; `retrieve` → `{text, slugs}`; `find`/`index`/`recall`/`audit`/`backlinks` → untrusted-rendered text or object; `continuation` → `{continuation_id, from, to}`; `recover` → `{published}`.
- **Diagnostic entrypoint.** `python3 _docsroot.py --check <project>` prints a one-line orphan warning and nothing when the resolution is sound; the bare form prints the resolved root relative to the project (`skill/session-chronicle/scripts/_docsroot.py:136-150`).

## Enumerated providers / limits

- **Operations (12)**: `capture`, `checkpoint`, `context`, `find`, `recall`, `backlinks`, `audit`, `index`, `guard`, `continuation`, `recover`, `retrieve` (`schemas/envelope.schema.json:11`, `skill/session-chronicle/scripts/_portable.py:23`).
- **Harnesses (4)**: `opencode`, `claude-code`, `codex`, `pi` (`skill/session-chronicle/scripts/_identity.py:5`).
- **Context roles (3)**: `primary`, `delegated`, `unknown` (`skill/session-chronicle/scripts/_portable.py:65`).
- **Capture operations (5)**: `prompt.submit`, `files.write`, `files.edit`, `files.patch`, `process.exec`; statuses `completed`/`error`; origins `user`/`synthetic`/`unknown` (`schemas/envelope.schema.json:87-90`).
- **Guard shapes**: kinds `replace`, `edit`, `patch` × phases `pre`, `post` (`schemas/envelope.schema.json:103`).
- **Audit modes (6)**: `orphans`, `dups`, `dangling`, `stale`, `candidates`, `quality` (`skill/session-chronicle/scripts/_portable.py:24`).
- **Recall scopes (3)**: `all`, `topic`, `sessions` (`schemas/envelope.schema.json:36`).
- **Instruction files (2, ordered)**: `AGENTS.md` then `CLAUDE.md` (`skill/session-chronicle/scripts/_docsroot.py:22`).
- **Managed config directories (5)**: `.opencode`, `.claude`, `.codex`, `.pi`, `.agents` (`skill/session-chronicle/scripts/_docsroot.py:62`).
- **Memory folders (6)**: `.drafts`, `.drafts/pending`, `pending`, `sessions`, `topics`, `continuations` (`skill/session-chronicle/scripts/_storage_paths.py:5`).
- **Exclusion cap**: at most 200 unique `exclude` references of form `session:<stem>`/`topic:<stem>` (`skill/session-chronicle/scripts/_portable.py:25`, `:118-123`, `schemas/envelope.schema.json:57`).
- **Injection budget**: `MEMORY_INJECT_BUDGET_CHARS`, default 6000, floored at 0, applied in one place only — the renderer (`skill/session-chronicle/scripts/_portable.py:127-139`).
- **Audit thresholds**: candidate threshold 2 and window 90 days, hardcoded at the dispatch site (`skill/session-chronicle/scripts/_portable.py:183`).
- **Identifier shapes**: topic slug `^[a-z0-9]+(?:-[a-z0-9]+)*$`; exclude stem `[a-z0-9][a-z0-9-]{0,190}`; evidence batch id `^\d{4}-\d{2}-\d{2}--evidence-[a-f0-9]{32}$` (`schemas/envelope.schema.json:58`, `:82`, `:49`).
- **Schema version**: integer 1 only — envelope, identity, continuation, and the `chronicle:v1:` identity prefix (`skill/session-chronicle/scripts/_portable.py:257-258`).
- **Hard-link budget**: exactly 1 link per memory file, plus at most 1 for a same-directory `.checkpoint-*` publication temporary (`skill/session-chronicle/scripts/_storage_paths.py:15-25`).
- **Lock and temporary conventions**: lock file `<docs-root>/.drafts/.writer.lock`, mode `0600`, single link, exclusive `flock`; publication temporaries are `.checkpoint-*` for immutable notes and `.presentation-*` for mutable ones, created in the destination directory (`skill/session-chronicle/scripts/_checkpoint.py:283`, `:310`, `:45`).
- **Naming caps**: drafts match `????-??-??.draft.jsonl`; a batch id is `<YYYY-MM-DD>--evidence-<32 hex>`; a presentation stem spends 40 characters on the readable id fragment plus 12 hex of a SHA-256 digest (`skill/session-chronicle/scripts/_checkpoint.py:330`, `:335`, `:127-131`).
- **Derived-view bounds**: excerpts are truncated to 180 characters and only the last 12 observed items are rendered into a presentation (`skill/session-chronicle/scripts/_checkpoint.py:134-139`, `:170`).
- **Declared platform prerequisites**: Python 3.11+ and `bash` on `PATH`; a local POSIX filesystem with `flock`, hard links, atomic rename and directory `fsync`, with cooperating writers; Linux fixture tests do not certify macOS or WSL (`README.md:45-46`).

## Cross-domain dependencies

- Delegates capture admission and replay-conflict detection to the capture subsystem (`skill/session-chronicle/scripts/_portable.py:12`, `:279`).
- Delegates evidence publication and lock acquisition to the checkpoint subsystem (`skill/session-chronicle/scripts/_portable.py:13`, `:77`, `:208-215`, `:283`).
- Delegates write-path guarding to the write-guard subsystem, which owns protected-target rules (`skill/session-chronicle/scripts/_portable.py:15`, `:290-292`).
- Delegates ranking and block rendering to the retrieval subsystem, and untrusted-text escaping to the memory-markers subsystem (`skill/session-chronicle/scripts/_portable.py:16-17`, `:152-156`, `:173-175`).
- Delegates topic resolution, backlink counts and topic index rendering to the topic-memory subsystem (`skill/session-chronicle/scripts/_portable.py:18`, `:21`, `:184-199`).
- Delegates session context/index resolution and note/structure validation to the session-journal and note-lint subsystems (`skill/session-chronicle/scripts/_portable.py:19`, `:284-285`).
- Native adapters under `adapters/<harness>/` translate host events into this envelope; the shared Python core is packaged under `core/` and is not reimplemented per harness (`README.md:31-36`).

## Gaps

1. Top-level `<docs-root>/pending/` is validated as memory storage (`skill/session-chronicle/scripts/_storage_paths.py:5`, `:41`) and included in the docs-root containment check (`skill/session-chronicle/scripts/_docsroot.py:59`, `:63`), but `checkpoint()` publishes only through `<docs-root>/.drafts/pending/` (`skill/session-chronicle/scripts/_checkpoint.py:326-339`) and the documented layout lists only the `.drafts` form (`README.md:95`) — is the top-level directory a legacy pipeline or an unbuilt one?
2. `reports/` is documented as excluded from retrieval (`README.md:93`) but is absent from both the validated directory set (`skill/session-chronicle/scripts/_docsroot.py:59-64`, `skill/session-chronicle/scripts/_storage_paths.py:5`), so a symlinked or escaping `reports/` is not rejected — deliberate (report output is throwaway) or an uncovered hole?
3. Continuations are fully specified in the core and schema but `README.md:96` marks native entrypoints "pending" — the core API exists today while no adapter is declared to call it; shipped surface or declared-but-pending contract?
4. `context` synthesises three extra fields on top of the session-context result — `identity`, `enrichment_allowed` (derived from `sources` being non-empty), `continuations` (`skill/session-chronicle/scripts/_portable.py:284-288`); whether `enrichment_allowed` is a contract or a convenience is not stated anywhere in scope.
5. `schemas/envelope.schema.json:5` states unknown roles "may read and guard unrelated source writes", but dispatch only enforces the read/mutate split for capture/checkpoint/context/continuation (`skill/session-chronicle/scripts/_portable.py:269-274`); guard's own role handling lives in `skill/session-chronicle/scripts/_guards.py`, outside the assigned paths, so the enforcement point is unverified.
6. `skill/session-chronicle/scripts/_portable.py:307-309` collapses *all* non-`ValueError` exceptions to `operation_failed`, including the `OSError`s that `publish`/`sync_directory`/`flock` can raise (`skill/session-chronicle/scripts/_checkpoint.py:283-292`, `:45-51`) — indistinguishable from a genuine bug for the caller; is that intentional opacity or a lost signal?
7. `checkpoint()` seals only drafts matching `????-??-??.draft.jsonl` (`skill/session-chronicle/scripts/_checkpoint.py:330`); a draft file with any other name is silently never published — rename hygiene enforced elsewhere, or data that can go permanently uncollected?
