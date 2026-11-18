---
domain: session-journal
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Session Journal

## Overview

Chronological memory of work sessions: captured activity is sealed into immutable factual
evidence notes without consulting a model, a derived per-session "presentation" is kept up to
date from that evidence, and an optional, explicitly requested semantic summary can be written
on top (`skill/session-chronicle/scripts/_checkpoint.py`, `skill/session-chronicle/scripts/_session_notes.py`).
Continuations link distinct sessions, and are declared as a contract while their native
entrypoints remain pending (`schemas/continuation.schema.json`).

## Current behaviour

- **Seals captured activity into immutable evidence notes.** A checkpoint consumes daily draft
  batches and publishes one note per batch under `sessions/`, titled "Captured activity (not a
  semantic summary)", status `closed`, `record-kind: factual-evidence`
  (`skill/session-chronicle/scripts/_checkpoint.py:62-91,323-349`).
- **States that captured evidence is not success.** The published note declares captured inputs
  untrusted and says tool hooks record activity, not success, completion, verified outcomes or
  decisions, and that `closed` means the batch is immutable, not that the work is finished
  (`skill/session-chronicle/scripts/_checkpoint.py:78-81`).
- **Sanitises before publication.** Payloads and excerpts are rewritten through the note-lint
  redaction patterns into `[REDACTED-<kind>]` placeholders (safelisted IPs kept verbatim), and
  backticks, angle brackets and `[[`/`]]` are escaped so captured text cannot become a link or
  markup; a note still tripping secret findings is refused
  (`skill/session-chronicle/scripts/_checkpoint.py:55-72,87-88,134-139`).
- **Maintains exactly one presentation per session.** Each session identity gets a
  `record-kind: session-presentation` note named `<date>--<slug>-<sha256[:12]>.md`, created or
  upserted in place; two distinct identities that slugify alike still keep two presentations
  (`skill/session-chronicle/scripts/_checkpoint.py:127-132,173-183,265-271`;
  `skill/session-chronicle/scripts/test_checkpoint.py:101-110`).
- **Shows only recent, bounded activity.** The body lists the last 12 observed prompts, file
  operations and commands, ordered by record timestamp rather than batch name
  (`skill/session-chronicle/scripts/_checkpoint.py:155-170,233-236`).
- **Derives a fallback title, then upgrades it.** Title is "Session activity: <first 6 words>"
  once a prompt exists, otherwise `Session <slug>`; later checkpoints replace it while it still
  holds a fallback value (`skill/session-chronicle/scripts/_checkpoint.py:142-148,229-230`).
- **Refuses to adopt ambiguous sessions.** More than one existing presentation for an identity,
  or a target that is a symlink, occupied by a different note or already closed, aborts the
  checkpoint instead of guessing
  (`skill/session-chronicle/scripts/_checkpoint.py:176-181,219-220,243-253`).
- **Retries and failures are safe.** Re-running over published batches publishes nothing and
  byte-identical notes are accepted; conflicting content aborts with evidence retained, and a
  malformed batch raises while staying in `.drafts/pending/` with the CLI exiting non-zero
  (`skill/session-chronicle/scripts/_checkpoint.py:274-282`, `checkpoint.py:12-16`;
  `skill/session-chronicle/scripts/test_checkpoint.py:30-36,229-236,238-249`).
- **Serialises writers across processes.** Checkpoints take an exclusive POSIX lock on
  `.drafts/.writer.lock`, fsync data and directories, and publish via temp file plus hard link
  or atomic replace (`skill/session-chronicle/scripts/_checkpoint.py:40-51,274-321`).
- **Reports the current session's enrichment target.** `session-context` checkpoints first, then
  returns the presentation, semantic summary (if any), target path and the factual batch sources
  mentioning the session; a closed matching view, missing `session-id`, symlink escape from
  `sessions/` or duplicate views raise a repair error instead of a target
  (`skill/session-chronicle/scripts/session-context.py:16-47,51-69`).
- **Selects what a session index shows.** Factual evidence is excluded unless explicitly
  included, inactive topics are dropped, a valid unique semantic summary suppresses its
  presentation, an identity with duplicate views contributes nothing, and input order is kept
  (`skill/session-chronicle/scripts/_session_notes.py:69-149`;
  `skill/session-chronicle/scripts/test_session_notes_selection.py:154-183`).
- **Validates a summary against the batches it cites.** A summary needs a filename-matching `id`,
  `date`, `title`, `session-id`, `open`/`closed` status, a non-empty body and resolvable
  provenance, otherwise it is not presented
  (`skill/session-chronicle/scripts/_session_notes.py:20-37,97-105`).
- **Keeps legacy notes readable; lists recent sessions.** A note with no frontmatter stays
  selectable and legacy data is read in place without migration
  (`skill/session-chronicle/scripts/_session_notes.py:40-50`; `docs/legacy-data.md:8-26`), and a
  helper prints the newest eight notes by `started`, `date`, filename
  (`skill/session-chronicle/scripts/_session_notes.py:152-160`).

**Model-free vs model-assisted.** Everything above except the semantic summary is deterministic
and runs without a model: the checkpoint CLI is documented as persisting "pending evidence
without a model" (`skill/session-chronicle/scripts/checkpoint.py:2`), and presentation bodies
state they are derived, bounded excerpts from immutable evidence
(`skill/session-chronicle/scripts/_checkpoint.py:234-236`). A `semantic-summary` exists only when
someone writes it at the target returned by `session-context`, citing batch IDs that match the
exact session ID (`skill/session-chronicle/references/session-note-template.md:17-26`); no code
path writes one automatically.

## Public contracts

- **Session view selection (shared API).** `select_candidates(headers, base, include_evidence=False)`
  → `{"eligible": [paths], "identities": {id: {"summaries": [], "presentations": []}}}`; pure, no
  file I/O. `validate_view(path, fm, base, source_cache)` → bool. `preferred_paths(paths, base,
  include_evidence=False)` → ordered list. `summary_findings(path, base, source_cache=None, *,
  fm=None)`. Plus `usable_fields`, `record_kind_of`, `identity_of`, `load_note`
  (`skill/session-chronicle/scripts/_session_notes.py:20-149`).
- **Checkpoint entry point.** `checkpoint(base)` → list of published factual-note paths; CLI
  wrapper `checkpoint.py` prints it as JSON and exits 1 on failure
  (`skill/session-chronicle/scripts/_checkpoint.py:323-349`, `skill/session-chronicle/scripts/checkpoint.py:11-16`).
- **Session-context request/response (stdin JSON / stdout JSON).** Input
  `{project_root, session_id}`; output `{session_id, presentation, semantic_summary, target,
  sources}` with project-relative POSIX paths or `null`; failures return
  `{"error": {"code": "session_context_failed", "message": ...}}` with exit code 1
  (`skill/session-chronicle/scripts/session-context.py:67-79`).
- **Factual evidence note format and naming.** Frontmatter `id`, `type: session`, `record-kind:
  factual-evidence`, `batch-id`, `date`, `title`, `status: closed`, `provenance:
  captured_signals`, `topics: []`, `commits: []`, `plans: []`; body `## Observed Evidence` plus a
  fenced JSON array of `prompt`/`file`/`bash` records (`_checkpoint.py:64-65,74-82`). Published
  batches are `sessions/<YYYY-MM-DD>--evidence-<32 hex>.md`, drafted as
  `.drafts/<YYYY-MM-DD>.draft.jsonl`, in flight as `.drafts/pending/<date>--evidence-<hex>.jsonl`
  (`_checkpoint.py:330-343`).
- **Presentation note format.** Frontmatter `id`, `type: session`, `record-kind:
  session-presentation`, `provenance: captured_signals`, `date`, `started`, `updated`,
  `session-id`, `title`, `sources`, `topics: []`, `commits: []`, `plans: []`, `status: open`;
  body `## Observed activity` (`skill/session-chronicle/scripts/_checkpoint.py:202-237`).
- **Semantic summary note format.** Template with `record-kind: semantic-summary`, `sources`,
  `status: open`, and sections "What has been done", "Decisions and why", "Open threads"; new
  filenames are `session--<sha256(ID)>--summary.md`; `id`, `session-id`, `started`, `date` and
  target are preserved on update, and closed summaries cannot be reopened
  (`skill/session-chronicle/references/session-note-template.md:1-26`).
- **Continuation record (present, native entrypoint pending).** JSON Schema
  `urn:chronicle:continuation:v1`: `{schema_version: 1, from, to, sources[], reason}`, no
  additional properties, `from`/`to` referencing `identity.schema.json`, `sources` a non-empty
  unique array of factual batch IDs, filename being the SHA-256 of the exact UTF-8 bytes
  including the final LF (`schemas/continuation.schema.json:1-19`). Semantics are declared as
  additive: a continuation never renames identities, merges native sessions, changes the session
  count, reopens a closed summary, or simulates native resume (`docs/legacy-data.md:41-47`).
  Storage is `continuations/` under the validated docs-root (`docs/legacy-data.md:49-52`).

## Enumerated providers / limits

- **Record kinds (closed set):** `factual-evidence`; `semantic-summary`, `session-presentation`
  (`skill/session-chronicle/scripts/_session_notes.py:12-13`).
- **View statuses (closed set):** `open`, `closed` (`skill/session-chronicle/scripts/_session_notes.py:35`).
- **Evidence record kinds (closed set):** `prompt`, `file`, `bash`
  (`skill/session-chronicle/scripts/_checkpoint.py:65,104`).
- **Harness IDs (exactly these):** `opencode`, `claude-code`, `codex`, `pi` — used in the
  canonical identity `chronicle:v1:<harness>:<base64url(native-session-id)>`
  (`docs/legacy-data.md:28-34`).
- **Declared limits:** excerpt length 180 characters (`_checkpoint.py:134`); last 12 activity
  items per presentation (`_checkpoint.py:170`); title from 6 words, max 80 characters
  (`_checkpoint.py:145-147`); session slug max 40 characters plus 12-hex digest
  (`_checkpoint.py:127-132`); recent-session listing capped at 8 (`_session_notes.py:158`);
  required factual frontmatter fields `id`, `type`, `date`, `title`, `status` plus non-empty body
  (`_checkpoint.py:84-86`); lock file opened `0o600` with `O_NOFOLLOW` and single-link check
  (`_checkpoint.py:45-49`); temp prefixes `.checkpoint-` and `.presentation-`
  (`_checkpoint.py:283,310`); continuation `schema_version` const 1, `sources` minItems 1 and
  unique, `reason` minLength 1 and non-null (`schemas/continuation.schema.json:10-18`).

## Cross-domain dependencies

- **Capture / signal ingestion:** consumes `.drafts/*.draft.jsonl` batches produced by the
  capture hooks, where self-generated events are filtered
  (`skill/session-chronicle/scripts/_checkpoint.py:330-338`;
  `skill/session-chronicle/scripts/test_checkpoint.py:198-205`).
- **Note contract and linting (`note-lint.py`):** record validation, redaction patterns, secret
  findings, identity/batch-ID recognition and summary naming are delegated to the note-lint
  module (`_checkpoint.py:15,55-59,68`; `session-context.py:24-45`).
- **Topics and storage layout:** candidate selection drops inactive topics through the topic
  graph (`_session_notes.py:5,84`), while the writer lock, `sessions/`, `.drafts/pending/` and
  file-type guards come from the storage-paths and docs-root modules
  (`_checkpoint.py:16,42-51`; `session-context.py:60-62`).
- **Retrieval / session index:** `preferred_paths` is the index's eager selector, and consumers
  such as `chronicle-doctor` depend on its signature (`_session_notes.py:108-114`;
  `test_session_notes_selection.py:3-6`).
- **Identity schema:** continuation endpoints reference `identity.schema.json`, and qualified
  identities follow the versioned format (`schemas/continuation.schema.json:11-12`;
  `docs/legacy-data.md:28-34`).
- **Shared portable core and native tool entrypoints:** a `continuation` operation and
  `continuations/` storage exist in the portable core, outside the reviewed paths
  (`_portable.py:23,202-216`); the summary template instructs using the target returned by
  `memory_session_context({})`, the model-facing wrapper of `session-context`
  (`references/session-note-template.md:17`).

## Gaps

- **Continuation writer is only referenced, not reviewed.** The schema and semantics are in
  scope, but the operation that writes and validates these records lives in `_portable.py:202-237`,
  outside the reviewed paths, and no in-scope reader surfaces continuations in the
  `session-context` response (`session-context.py:67-69`). Native entrypoints are stated as
  pending: is the contract shipped or declaration-only?
- **`preferred_paths` silently drops unreadable notes.** `OSError`, `UnicodeError` and
  `ValueError` per path are swallowed so the index survives a missing file
  (`_session_notes.py:118-122`), so "not a view" and "corrupt view" are indistinguishable.
- **Legacy notes bypass validation entirely.** An empty header stays selectable with no field
  checks (`_session_notes.py:40-50`; `test_session_notes_selection.py:100-106`), so a genuinely
  empty file is presented as a session. Intended compatibility or a hole?
- **Fallback-title upgrade is a value comparison.** The title is rewritten only when it equals
  `activity_title([], session_id)` (`_checkpoint.py:229-230`); a human-authored title matching
  that exact string would be overwritten. Confirm the intended rule.
- **Presentation body may go stale.** `presentation_text` returns the existing note unchanged
  when the source list is unchanged (`_checkpoint.py:224-226`), so activity in an already-known
  batch is not re-rendered. Is that intended immutability of the derived body?
- **POSIX-only durability is a hard constraint.** The module claims durability on "local POSIX
  filesystems" and uses `fcntl`, `os.link` and directory fsync (`_checkpoint.py:1,4,19-51,283-291`);
  network or non-POSIX behaviour is undefined here.
- **Identity and naming rules are out of review scope.** `require_unambiguous_identity`,
  `is_batch_id`, `summary_name`, `REDACT_PATTERNS`/`SAFE_IPS` live in `note-lint.py`
  (`_checkpoint.py:15,55-59`; `session-context.py:24-45`), so bare-versus-qualified ID rules,
  safelisted IPs and the `session--<sha256(ID)>--summary.md` hash input
  (`session-note-template.md:17`) cannot be confirmed here.
