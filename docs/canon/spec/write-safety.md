---
domain: write-safety
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Write safety

## Overview

The write-path guard: every supported direct native mutation into the memory store is checked before it lands and re-validated after it lands, so that closed history stays closed, provenance stays truthful, secrets do not enter long-lived notes, and no writer can silently corrupt a record it does not own (`skill/session-chronicle/scripts/note-lint.py`, `skill/session-chronicle/scripts/_guards.py`).

## Current behaviour

- **Blocks edits to closed session entries.** A session note whose frontmatter says `status: closed` cannot be edited by an agent; the write is refused and the caller is told to create a new session entry instead (`note-lint.py:353-356`; `test_write_boundaries.py:89-102`).
- **Requires a trusted session identity for semantic summaries.** A summary is accepted only when its `session-id` equals the trusted runtime session ID, its `id` equals its filename stem, it lives directly inside `sessions/` and is not a symlink, it carries `date`, `title`, `status: open|closed` and a non-empty body, and no other summary claims the same `session-id` (`note-lint.py:251-283`; `test_write_boundaries.py:52-80`).
- **Keeps summary identity immutable.** Once a summary exists, an edit may not change its `record-kind` or `session-id`; a valid but non-canonical existing summary stays writable at its own path, while a *new* summary must use the deterministic target name `session--<sha256(identity)>--summary.md` (`note-lint.py:247-248`, `note-lint.py:271-278`, `note-lint.py:329-332`; `test_write_boundaries.py:61-63`, `test_write_boundaries.py:66-79`).
- **Refuses agent authorship of writer-owned records.** `factual-evidence` files may only be created by the checkpoint writer and are immutable once written; `session-presentation` files are generated only by the checkpoint writer, so neither creation nor later edit is permitted (`note-lint.py:337-340`, `note-lint.py:346-352`; `test_write_boundaries.py:82-87`; `test_memory_contracts.py:137-165`).
- **Reserves the draft/pending/continuation folders.** `.drafts/`, `pending/` and `continuations/` are writer-owned; any mutation there is refused with "drafts, pending evidence and continuation records are writer-owned" (`note-lint.py:100-103`, `note-lint.py:302-303`).
- **Rejects secret-like patterns in the proposed content.** The guard reports which pattern kinds matched and asks the caller to re-submit with `[REDACTED-<KIND>]` placeholders, because notes are re-injected into context on every retrieval (`note-lint.py:29-48`, `note-lint.py:341-345`).
- **Enforces the note schema after the write.** Post-write validation requires a `---` fenced frontmatter block, a non-empty body, `id`/`type`/`date`/`title`/`status` on session notes with `status` restricted to `open|closed`, `id` matching the filename for view records, and `id`/`type`/`title` on topic notes (`note-lint.py:359-402`).
- **Requires concrete provenance on topic notes.** `derived_from_sessions` and `derived_from_plan` must carry a non-empty `sources:` list; `stated_by_user` may omit it; any other provenance value must also supply `sources:` — a bare template default cannot pass (`note-lint.py:384-396`; `test_memory_contracts.py:186-189`).
- **Refuses provenance laundering on typed topics.** A topic edit that drops `note-kind` to escape structural validation is blocked, and any note declaring `note-kind` is run through the topic structural validator before acceptance (`note-lint.py:323-328`).
- **Fails a whole factual batch rather than publish ambiguous identity.** If any pending record carries a non-string or conflicting `session_id`/`sessionID`, the checkpoint raises and no session file is written while the pending batch is left byte-identical (`test_write_boundaries.py:115-126`).
- **Refuses to overwrite an existing note with a generated presentation.** A presentation collision aborts with an error, leaves the existing note's bytes untouched and does not publish the batch's evidence (`test_write_boundaries.py:128-141`, `test_write_boundaries.py:156-170`).
- **Constrains cooperating writers by path shape and snapshot.** Guarded mutations reject parent traversal, refuse symbolic-link components and hard-linked or non-regular targets, reject an unknown runtime role, and require an unambiguous exact original (or `replace_all`) for an edit (`_guards.py:34-47`, `_guards.py:57-59`, `_guards.py:75-79`).
- **Serialises and CAS-checks semantic replaces.** An atomic semantic replacement requires the primary role and a complete replacement, takes the writer lock, rejects a stale snapshot hash, and requires the new content to be a `semantic-summary` (`_guards.py:84-96`).
- **Fails closed on its own errors.** A validator exception exits 2 with "validator failed; mutation cannot be approved"; only "not a memory note" exits 0 (`note-lint.py:422-431`, `note-lint.py:304-305`, `note-lint.py:17`).
- **Treats an escaping `docs-root` as a hard stop.** An absolute, traversing or externally symlinked `docs-root` is rejected and guarded writes fail rather than falling back to `docs` (`test_write_boundaries.py:32-50`; `README.md:102`).

## Public contracts

- **Hook protocol.** stdin JSON with `hook_event_name` (`PreToolUse`|`PostToolUse`), `tool_name` (`Write`|`Edit`), `sessionID`, `tool_input{file_path, content, old_string, new_string, replace_all}`; exit `2` on violation with the message on stderr, exit `0` when allowed or when the path is not a memory note (`note-lint.py:405-431`).
- **`note_lint.validate_change(proj, identity, arguments)`** — validates a neutral replace/edit snapshot (`kind`, `path`, `phase`, `content`, `old_text`, `new_text`, `replace_all`); callers own the actual write (`note-lint.py:291-292`).
- **`note_lint.classify(path, base)` → `"protected" | "session" | "topic" | None`** (`note-lint.py:98-108`).
- **`note_lint.secret_findings(content)` → list of `"<KIND> x<N>"`**; `[REDACTED-*]` placeholders are not themselves patterns (`note-lint.py:40-48`; `test_memory_contracts.py:244`).
- **Schema helpers** used by other modules: `split_fm`, `fm_get`, `fm_has`, `record_findings`, `factual_records`, `record_session_id`, `summary_name` (`note-lint.py:59-244`, `note-lint.py:247-248`).
- **`_guards.guard(context, arguments, base)` → `{"allowed": True, "atomic": False, "sha256"|"snapshots"}`** or raise; `context` carries `workspace`, `role`, `qualified_id`; `arguments` carries `kind` (`replace|edit|patch`), `path`, `patch`, `phase` (`_guards.py:54-81`).
- **`_guards.guarded_semantic_replace(context, arguments, base, expected_sha256)` → `{"sha256": …}`**, atomic only for cooperating writers (`_guards.py:84-97`).
- **`_guards.memory_target` / `protected_mutation` / `local_target` / `fingerprint`** — the mutation-scope predicates and the sha256 snapshot primitive (`_guards.py:11-51`).
- **File formats produced or consumed.** Factual batch IDs must match `\d{4}-\d{2}-\d{2}--evidence-[a-f0-9]{32}` with a real ISO date (`note-lint.py:111-118`); a factual source is a note carrying exactly one ```` ```json ```` fenced array of non-empty records whose `kind` is `prompt|file|bash` (`note-lint.py:232-244`); summaries are named `session--<sha256(session-id)>--summary.md` (`note-lint.py:247-248`); the reference template ships `record-kind: semantic-summary` with `sources: []` (`test_memory_contracts.py:191-195`).
- **Error conventions.** `ValueError` / `CoreError("unknown_provenance", …)` for refusals, and validator findings joined as `"<code>: <message>"` (`_guards.py:57-59`, `_guards.py:69-71`, `note-lint.py:328`, `note-lint.py:336`).

## Enumerated providers / limits

**Secret-like patterns** (`note-lint.py:29-36`), each a closed set member:

- `GITHUB-TOKEN` — `gh[pousr]_` followed by ≥20 alphanumerics (`note-lint.py:30`).
- `API-KEY` — `sk-` followed by ≥20 of `[A-Za-z0-9_-]` (`note-lint.py:31`).
- `AWS-KEY` — `AKIA` followed by exactly 16 uppercase alphanumerics (`note-lint.py:32`).
- `SLACK-TOKEN` — `xox[bp]-` followed by ≥10 of `[A-Za-z0-9-]` (`note-lint.py:33`).
- `PRIVATE-KEY` — a `-----BEGIN <KIND> PRIVATE KEY-----` header (`note-lint.py:34`).
- `IP-ADDRESS` — any dotted-quad IPv4, exempting `SAFE_IPS = {"127.0.0.1", "0.0.0.0"}` (`note-lint.py:35-37`, `note-lint.py:44-45`).

**Record kinds** — `factual-evidence | semantic-summary | session-presentation`; anything else is rejected (`note-lint.py:149-150`).

**Status** — `open | closed` only (`note-lint.py:269-270`, `note-lint.py:370-372`).

**Provenance for factual and presentation records** — must be exactly `captured_signals` (`note-lint.py:145`, `note-lint.py:169`). **Topic provenance branches** — `derived_from_sessions`, `derived_from_plan` (require sources), `stated_by_user` (sources optional), anything else must still supply sources (`note-lint.py:390-396`).

**Protected roots** — `sessions/`, `topics/`, `.drafts/`, `pending/`, `continuations/` (`_guards.py:13`, `note-lint.py:100`, `note-lint.py:296`).

**Declared limits:**

- **The guard is deliberately partial, and that is a product promise.** It covers supported direct native mutations only; it does **not** protect arbitrary shell or external filesystem writes (`README.md:27`). The same limit is restated where the design explains it: arbitrary shell commands that modify memory cannot reliably be classified (`README.md:365`), native patch syntax support belongs to each adapter and preflight is not a transaction with native execution (`README.md:368`), and a post-write diagnostic cannot undo a completed native operation (`README.md:363`).
- **Redaction is heuristic, not comprehensive** — arbitrary passwords, credential bodies, personal information, file paths and unknown token formats may remain (`README.md:240`).
- **Hook scope** — only `Write` and `Edit` tool events are inspected; every other tool name returns without validation (`note-lint.py:407-408`).
- **Path shape** — no `..` components, no symlink components on a memory path, and the target must be a regular file with `st_nlink == 1`; otherwise the mutation is refused (`_guards.py:36-46`). A lexical memory target must also resolve inside the project and not be a symlink (`note-lint.py:296-300`).
- **Identity gate** — `context["role"] == "unknown"` cannot perform a protected mutation (`_guards.py:57-59`); a semantic transaction additionally requires `role == "primary"` and `kind == "replace"` (`_guards.py:86-87`).
- **Patch grammar** — targets are recognised by `*** Add File:` / `*** Update File:` / `*** Delete File:` / `*** Move to:`; a patch with no classifiable targets raises, and patch validation runs in `pre` phase only (`_guards.py:28-30`, `_guards.py:66-67`).
- **Edit ambiguity** — the old text must occur exactly once unless `replace_all` is set (`_guards.py:77-79`).
- **Evidence cardinality** — exactly one JSON evidence array per factual source, and it must be non-empty (`note-lint.py:235-239`).
- **`docs-root` boundary** — absolute paths, parent traversal and symlinks escaping the project are rejected; guarded writes fail closed instead of falling back (`test_write_boundaries.py:32-50`).
- **Exit codes** — `0` allowed/out of scope, `2` refused; unexpected validator failure also exits `2` (`note-lint.py:17`, `note-lint.py:427-431`).

## Cross-domain dependencies

- **Capture / checkpoint writer** — the guard's counterpart owns creation of `factual-evidence` and `session-presentation` records, and enforces batch-identity and collision behaviour the guard's tests assert (`test_write_boundaries.py:82-87`, `test_write_boundaries.py:115-141`).
- **Storage paths / docs-root resolution** — `resolve_base` supplies the memory root the guard classifies against, and the layout contract (`sessions/`, `topics/`, `.drafts/`, `pending/`, `continuations/`) is shared (`note-lint.py:24`, `note-lint.py:98-108`, `docs/legacy-data.md:51-53`).
- **Identity** — `parse_identity` / `canonical_identity` qualify a session identity, and an unqualified legacy ID that collides with the reserved `chronicle:` namespace must fail explicitly rather than be adopted (`note-lint.py:25`, `note-lint.py:194-221`, `docs/legacy-data.md:23-26`, `docs/legacy-data.md:28-34`).
- **Topic memory / topic graph** — structural topic validation (`parse_note`, `proposed_topic_findings`, `proposed_graph_findings`) gates typed topics and complete-topic patches (`note-lint.py:27`, `note-lint.py:323-328`, `_guards.py:63-71`).
- **Topic patch lint** — `load_script("topic-patch-lint")` reconstructs proposed notes for guarded patch preflight (`_guards.py:62-68`).
- **Portable core** — `CoreError` and `load_script` define the refusal type and script loading used by the guard (`_guards.py:57-59`, `_guards.py:61-64`); `_portable` is the only in-tree importer of `guard` (`_portable.py:15`).
- **Writer lock / presentation update** — atomic semantic replace depends on `writer_lock` and `update_presentation` (`_guards.py:7`, `_guards.py:88-96`).
- **Retrieval** — duplicate presentations are omitted by retrieval and the startup index, which is the read-side consequence of the guard's no-duplicate rule (`test_write_boundaries.py:143-154`).

## Gaps

- **Patch coverage depends on adapters outside scope.** `_guards.guard` validates `kind == "patch"`, but whether every native patch tool routes through it — and which patch syntaxes survive — is stated as adapter-owned (`README.md:368`) and not visible in these paths.
- **`_guards.py` has one in-scope importer.** An in-tree search finds `guard` imported only by `_portable.py:15`; nothing in these paths shows the hook path calling it, so how `_guards` and `note-lint.py` compose at runtime (which one runs first for an edit) is unclassified.
- **Role enumeration is incomplete.** Only `"unknown"`, `"primary"` and the `children` mention in `README.md:199` are visible; the full set of role strings and which of them may write memory is not declared in these paths.
- **Two provenance regimes look asymmetric.** Session records must use `captured_signals` exactly (`note-lint.py:145`, `note-lint.py:169`), while topic notes accept *any* provenance value provided `sources:` is non-empty (`note-lint.py:395-396`); whether an unrecognised topic provenance is intended to pass is unstated.
- **Secret-scan patterns may drift from the capture-time redactor.** The guard refuses but never rewrites content (`note-lint.py:341-345`), while capture-side redaction rewrites before persist (`test_memory_contracts.py:231-244`). Whether both use one shared pattern definition is not visible in these paths.
- **`sync-topics-field.py` is a second writer into `sessions/`.** Tests pin that it blocks immutable and invalid notes without mutating bytes (`test_write_boundaries.py:89-106`), but its own guard implementation is outside scope, so the division of responsibility with `note-lint.py` is unverified.
- **Unprotected roots.** `reports/` (described as excluded from retrieval in `README.md:91`) is absent from `memory_target`'s protected set (`_guards.py:13`); whether agent writes to `reports/` need guarding is unclassified.
- **Hardlink detection cost and edge cases.** `memory_target` scans every protected root with `rglob("*")` whenever the target has `st_nlink > 1` (`_guards.py:16-21`); the behaviour for a hardlink created *after* validation, or for a link whose sibling lives outside the roots, is not covered by an in-scope test.
- **"Exactly one JSON block" may be over-strict.** A factual source containing any second fenced `json` block fails as malformed (`note-lint.py:234-236`); whether that is intended for notes that quote JSON in prose is undecided in these paths.
- **The negative boundary is documentary, not tested.** The partial-protection promise lives in `README.md:27` prose and the design notes; no in-scope test asserts that a shell or external write is *not* guarded, so the statement's scope rests on documentation rather than on executed evidence.
