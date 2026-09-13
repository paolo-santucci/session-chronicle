# opencode-session-chronicle

OpenCode plugin that gives a project a **chronological session memory**: an append-only journal of dated entries under `<docs-root>/sessions/` plus distilled topic notes under `<docs-root>/topics/`, written *for the agent to re-read*. The plugin covers the full loop:

- **Passive capture** — meaningful tool activity (file writes/edits, non-trivial bash, user prompts) is mirrored into a draft buffer, at zero token cost.
- **Retrieval injection** — on every user prompt, the top-k relevant session/topic bodies are BM25-ranked and injected as a synthetic message part. Retrieval and the session-start index prefer a semantic summary over its presentation for the same `session-id`; deduplication and factual-evidence exclusion happen before the retrieval candidate budget.
- **Write-path guard** — edits to closed (immutable) session entries are blocked, and content carrying secret-like patterns (tokens, keys, non-loopback IPs) is rejected before it can enter a note that would be re-injected forever.
- **Factual checkpoints**: captured evidence is persisted without an LLM at plugin startup, after primary-session prompts, on primary-session idle, and before compaction. Optional manual `/session-chronicle` enrichment adds a separate semantic summary.
- **Explicit recall tools** — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`.

All business logic lives in dependency-free Python/Bash scripts under `skill/session-chronicle/scripts/` (originally built and battle-tested as Claude Code hooks). That directory is the single copy: the skill ships it, and `index.ts` — a thin adapter mapping OpenCode plugin hooks onto the scripts' original stdin JSON contract — shells out to the same files. The scripts run unmodified on both harnesses.

## Requirements

- OpenCode ≥ 1.18 (plugin API with `chat.message`, `tool.execute.*`, `experimental.session.compacting`, and `session.idle`)
- Python 3.9+ (`python3`, stdlib only) and `bash` on `PATH`
- A local POSIX filesystem supporting `flock`, hard links, atomic rename, and directory `fsync` (Linux/macOS; not Windows)
- `bun` for the local (git clone) install path — not needed once installed via npm

Earlier end-to-end verification on OpenCode 1.18.4 covered capture, retrieval, and recall. The factual-checkpoint path has automated script and hook-adapter tests; interactive/headless lifecycle delivery still needs runtime verification.

## Install

> ⚠ **The plugin loader only picks up flat `*.ts`/`*.js` files directly inside `plugins/` — a cloned directory there is silently ignored** (verified empirically on OpenCode 1.18.4). Install via a one-line re-export shim.

**Project-local (recommended while unpublished):**

```bash
git clone https://github.com/<you>/opencode-session-chronicle .opencode/session-chronicle
cd .opencode/session-chronicle && bun install && cd -
mkdir -p .opencode/plugins
echo 'export { SessionChronicle } from "../session-chronicle/index.ts"' \
  > .opencode/plugins/session-chronicle.ts
mkdir -p .opencode/skills .opencode/commands
cp -r .opencode/session-chronicle/skill/* .opencode/skills/
cp -r .opencode/session-chronicle/command/* .opencode/commands/
```

The last two steps install the bundled **skills** and their **slash commands** (see below): `session-chronicle` (the crystallisation workflow) and `session-chronicle-bootstrap` (the one-shot backfill). Install both skills — the bootstrap reads the chronicle's note templates. Skill and command names must be unique across all discovery locations, so make sure neither name is already present from another source.

The `bun install` matters: the loader resolves `@opencode-ai/plugin` automatically only for files inside `plugins/`; the cloned module needs its own `node_modules`, or its whole import graph fails silently (ESM semantics — the shim never executes either).

**Global:** same recipe under `~/.config/opencode/` (`session-chronicle/` + `plugins/session-chronicle.ts`).

**Via npm (once published):**

```json
// opencode.json
{ "plugin": ["opencode-session-chronicle"] }
```

OpenCode installs npm plugins with Bun at startup (cached in `~/.cache/opencode/node_modules/`), dependencies included — no shim needed on this path.

Add the draft buffer to the target project's `.gitignore`:

```
docs/.drafts/
```

## Where memory lives (`docs-root`)

All paths are rooted at `<project>/<docs-root>`:

| Path | Content |
|---|---|
| `<docs-root>/sessions/*.md` | one mutable `record-kind: session-presentation` per captured session, optional semantic summaries, and immutable factual-evidence batches |
| `<docs-root>/topics/*.md` | distilled topic notes, materialised when a subject recurs |
| `<docs-root>/.drafts/*.draft.jsonl` | durable, uncommitted capture buffers; never age-pruned |
| `<docs-root>/.drafts/pending/*.jsonl` | sealed batches awaiting publication or acknowledgement |

`docs-root` defaults to `docs` and is overridable via a `docs-root:` field in the project instruction file's YAML frontmatter. `AGENTS.md` is read first and `CLAUDE.md` second, so a project that already carries a Claude Code chronicle keeps working without an edit. Capture, persistence, and other scripts use `skill/session-chronicle/scripts/_docsroot.py`; the TS adapter mirrors this lookup for displayed paths and recall arguments.

> ⚠ **`docs-root` is the system's single point of failure, and it fails quietly.** Every consumer reads "the notes directory does not exist" as "there are no notes yet". Resolve it wrong — by rewriting the instruction file without its frontmatter, say — and retrieval goes silent, `capture-signals.py` starts filling a draft buffer nobody reads, and `note-lint.py` stops recognising notes as notes, which disables the append-only and secret guards on exactly the files they protect. To make that state visible, the session-start index prints a diagnosis instead of nothing when the resolved root is empty but a chronicle exists elsewhere in the project. Check it by hand at any time:
>
> ```bash
> python3 .opencode/skills/session-chronicle/scripts/_docsroot.py --check .
> ```
>
> Silence means the resolution is sound.

## Hook mapping

| Concern | Claude Code original | OpenCode hook |
|---|---|---|
| Capture file/bash signals | `PostToolUse` → `capture-signals.py` | `tool.execute.after` |
| Capture user prompts | `UserPromptSubmit` → `capture-signals.py` | `chat.message` |
| Retrieval injection (BM25) | `UserPromptSubmit` → `retrieve-inject.py` stdout | `chat.message` → synthetic text part |
| Session-start topic index | `SessionStart` → `topic-index.sh` stdout | `chat.message` (first message per session) → synthetic text part |
| Append-only + secret guard | `PreToolUse` → `note-lint.py` exit 2 | `tool.execute.before` → `throw` (blocks the call) |
| Note schema validation | `PostToolUse` → `note-lint.py` exit 2 | `tool.execute.after` → appended to tool output |
| Factual checkpoint | `checkpoint.py` can be called explicitly | startup, `chat.message`, `session.idle` → `checkpoint.py` |
| Compaction checkpoint | — (no Claude Code equivalent) | `experimental.session.compacting` → persistence, then `output.context` |

Subagent (child) sessions are detected via the SDK (`parentID`) and skipped for capture, injection, idle, and compaction checkpoints. Startup recovery is project-wide. If the SDK lookup fails, child detection is best-effort.

## Tools

| Tool | Args | Does |
|---|---|---|
| `memory_find` | `query`, `includeEvidence?` | BM25 search over semantic sessions + topics; explicitly set `includeEvidence: true` to include factual records |
| `memory_recall` | `slug`, `scope?` (`all\|topic\|sessions`) | topic note body + backlinking session ids in one call |
| `memory_backlinks` | `slug` | session entries wikilinking the slug (alias-aware) |
| `memory_audit` | `mode` (`orphans\|dups\|dangling\|stale\|candidates`) | memory health report, JSON |
| `memory_session_context` | `{}` | obtains trusted SDK `context.sessionID`, checkpoints via `session-context.py`, and resolves the current semantic-summary target and sources |

`memory_session_context` returns `{session_id, presentation, semantic_summary, target, sources}`: paths are project-relative, `presentation` and `semantic_summary` may be `null`, and `sources` contains factual batch IDs. Session identity comes only from SDK context, never model arguments. A closed summary or duplicate summaries cause an error.

Restrict them like any tool if needed:

```json
{ "permission": { "memory_*": "allow" } }
```

## Tunables (environment)

| Variable | Default | Meaning |
|---|---|---|
| `MEMORY_INJECT_BUDGET_CHARS` | `6000` | retrieval injection budget (~1500 tokens) |
| `MEMORY_INJECT_TOPK` | `3` | max notes injected per prompt |
| `MEMORY_INJECT_MAX_SCAN` | `60` | newest-first eligible candidate cap; automatic retrieval excludes factual records before counting. File discovery/header classification are not bounded by this cap. |
| `SESSION_CHRONICLE_CAPTURE_PROMPTS` | `1` | set to `0`, `false`, `no`, or `off` to disable future prompt capture independently |
| `SESSION_CHRONICLE_CAPTURE_BASH` | `1` | set to `0`, `false`, `no`, or `off` to disable future Bash command capture independently |
| `MEMORY_HEALTH_STALE_MAX` / `MEMORY_HEALTH_DANGLING_MAX` | `5` / `10` | thresholds for the index health line |

## Privacy controls

**Captured evidence becomes durable files under `<docs-root>/sessions/` and may be committed, shared, or explicitly read by a model.** Ignoring `.drafts/` does not ignore published evidence. Exclusion from automatic retrieval is not a storage or confidentiality guarantee.

Set `SESSION_CHRONICLE_CAPTURE_PROMPTS=0` and/or `SESSION_CHRONICLE_CAPTURE_BASH=0` in the environment before starting OpenCode to opt out of those capture channels. File-operation capture remains enabled. These controls only affect future capture: existing drafts and pending batches still publish during recovery, and existing notes are not deleted. Review storage/sharing policy and existing records before enabling capture for sensitive projects.

Known GitHub/API/AWS/Slack token patterns, private-key headers, and non-loopback IPv4 addresses are redacted heuristically before durable capture and before presentation excerpts are bounded. This is **not comprehensive redaction**: arbitrary passwords, credentials, private-key bodies, personal information, file paths, and unknown token formats may remain. Prefer disabling the relevant capture channel when its inputs may be sensitive.

## The bundled skills

The plugin alone covers capture, deterministic factual persistence, retrieval, guards, and recall. Optional semantic workflows ship as two [Agent Skills](https://opencode.ai/docs/skills/) packages under `skill/`:

| Skill | Role | When it runs |
|---|---|---|
| `session-chronicle` | **Optional enrichment (1.6.0).** Uses trusted tool targeting to write one separate semantic summary per session ID, with source batch IDs, wikilinks, and topic materialisation. Never edits presentations, evidence, pending batches, or drafts. | Explicit `/session-chronicle` invocation or explicit enrichment request. |
| `session-chronicle-bootstrap` | **Backfill.** Seeds the journal and the first topic notes from a project's pre-existing history (specs, plans, decisions, STATUS, git log). | Exactly once per project, on explicit request. |

Install both into the same discovery location (`.opencode/skills/`, `~/.config/opencode/skills/`) — the recipe above does it with one `cp -r`. The bootstrap deliberately keeps **no** copy of the note templates or `slugify.py`: it reads them from `session-chronicle`, so there is exactly one schema in the bundle. Installing the bootstrap alone leaves it inert; it stops with a message rather than improvising a note shape.

Each skill ships a matching command shim under `command/`. Commands and skills are optional for factual persistence; install them for manual enrichment and backfill.

The installed SDK declares `SessionCommandData.body.model` optional, but types alone do not guarantee model inheritance or background execution semantics. The plugin does not dispatch commands or select a model. Manual enrichment uses normal OpenCode command/model selection and permissions; failure or refusal leaves factual records intact.

Enrichment requires `memory_session_context({})`. If the tool is unavailable, denied, fails, or returns empty sources, the agent stops without writes; guessed IDs and model-supplied direct-script fallbacks are forbidden. Mixed batches contribute only records whose `session_id`/`sessionID` matches the exact returned ID, and summaries cite only batch IDs actually used. No matching records means no writes.

Only the returned matching open semantic summary may be updated, or the returned new target created. Existing summaries keep their target across midnight; new targets use `session--<sha256(ID)>--summary.md`. `id` equals the target stem, `session-id` is the exact tool ID, and `id`, `session-id`, `started`, `date`, and target remain stable on updates. Presentations and immutable evidence remain separately stored; enrichment never replaces either.

An end-of-session signal alone never triggers enrichment. Only an explicit enrichment request that also asks for closure closes the current summary; a closed summary cannot be reopened or replaced. Duplicate summaries cause a stop, not automatic repair or unrelated closes. These are workflow instructions; skill `allowed-tools` metadata grants no runtime permissions.

## Design notes

- **No MCP server.** The recall tools are plugin-registered custom tools (`tool:` key) — same UX for the model, no extra process, no MCP wiring.
- **Single writer and durable publication.** Capture and checkpoint processes share a project-local advisory `flock`. Under that lock, non-empty daily drafts (including old dates) are atomically renamed to UUID-named pending batches. A batch ID remains stable across retries. Every batch is published as immutable factual evidence and updates the one derived presentation for each unambiguous captured `sessionID`. Presentation filenames use a readable normalized ID fragment plus a hash; `session-id`, not title or filename, is the identity. A fully written, synced temporary note is hard-linked into its final name without overwriting history, then the sessions directory is synced. Only then is that specific pending batch removed and its directory synced. Appends wait for the lock and go into a new draft; no draft is truncated. Duplicate dispatches with no new evidence are no-ops.
- **Factual, not semantic.** Notes reuse the session schema and lint helpers. `record-kind: factual-evidence` has `batch-id` and `provenance: captured_signals`; it is immutable and may contain several sessions. `record-kind: session-presentation` is the updatable, derived view for one stable `session-id`; its deterministic title uses bounded safe words from the first prompt and upgrades a no-prompt fallback when a prompt later arrives. Titles can collide, so `session-id` remains the identity. Captured inputs are quoted as untrusted JSON; no outcomes, commits, decisions, or topics are inferred from commands or edits. Source session/event IDs are retained when provided.
- **Kind-specific validation.** Factual notes require a valid dated batch ID matching `id`/`date`, `type: session`, closed status, and `captured_signals` provenance. Semantic summaries and session presentations require non-empty `sources:` referencing existing valid factual batch IDs; presentations also require `session-id`. Generic legacy session notes without `record-kind` remain valid. Historical batches without a captured session ID are retained as factual evidence and are not migrated into a presentation.
- **Failure visibility.** Capture/checkpoint errors are logged without raw evidence; pending batches remain retryable. Model responses are never awaited. File-lint policy violations still block guarded edits.
- **Recovery limits.** Guarantees cover successfully synced capture on a cooperating local filesystem, not events lost before capture, external draft edits, non-cooperating writers, network filesystems, or disk corruption. There is no SDK shutdown hook used here; the next startup, primary prompt, idle, compaction, or explicit `PROJECT_ROOT=/project python3 <installed-scripts>/checkpoint.py` retries pending evidence. A malformed batch or publication conflict stops the checkpoint and requires operator repair; evidence is not silently discarded. A process killed during publication can leave an ignored `.checkpoint-*` temporary file. Large backlogs are processed synchronously and are not size-bounded.
- **Filtering and privacy limits.** Direct writes to drafts, sessions, and topics, synthetic prompt parts, explicit chronicle prompts, and recognized direct maintenance invocations are excluded. Maintenance scripts must resolve into the executing capture script's installed directory; unrelated `tests/checkpoint.py` and commands merely mentioning that name are retained. Shell wrappers, interpreter options, and compound commands are conservatively retained rather than guessed. Arbitrary shell commands that modify memory cannot be reliably identified. Capture only collapses consecutive duplicates within a draft; durable SDK replay deduplication remains a follow-up. Older draft data may already contain secrets.
- **`apply_patch` is not captured.** Its args carry `patchText`, not a file path; write/edit cover the overwhelming majority of signals. Known limitation.
- **No mandatory semantic workflow.** Factual persistence needs neither a command shim nor an agent skill. Restart OpenCode after updating the plugin and installed skill/command copies.

## Development

```bash
bun install
bun run typecheck
bun test
python3 -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py' -v
```

## License

MIT
