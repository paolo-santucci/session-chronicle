# opencode-session-chronicle

OpenCode plugin that gives a project a **chronological session memory**: an append-only journal of dated entries under `<docs-root>/sessions/` plus distilled topic notes under `<docs-root>/topics/`, written *for the agent to re-read*. The plugin covers the full loop:

- **Passive capture** — meaningful tool activity (file writes/edits, non-trivial bash, user prompts) is mirrored into a draft buffer, at zero token cost.
- **Retrieval injection** — on every user prompt, the top-k relevant note bodies are BM25-ranked and injected as a synthetic message part; on the first message of a session, a compact topic/session index is injected for orientation.
- **Write-path guard** — edits to closed (immutable) session entries are blocked, and content carrying secret-like patterns (tokens, keys, non-loopback IPs) is rejected before it can enter a note that would be re-injected forever.
- **Crystallisation triggers** — a deterministic idle-time checkpoint: when buffered signals accumulate, the plugin invokes `/session-chronicle` directly (not a model-initiated request), plus a compaction handoff so an auto-compacted session does not forget its uncrystallised buffer.
- **Explicit recall tools** — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`.

All business logic lives in dependency-free Python/Bash scripts under `skill/session-chronicle/scripts/` (originally built and battle-tested as Claude Code hooks). That directory is the single copy: the skill ships it, and `index.ts` — a thin adapter mapping OpenCode plugin hooks onto the scripts' original stdin JSON contract — shells out to the same files. The scripts run unmodified on both harnesses.

## Requirements

- OpenCode ≥ 1.18 (plugin API with `chat.message`, `tool.execute.*`, `experimental.session.compacting`, and the SDK session client for `client.session.command`)
- `python3` (stdlib only) and `bash` on `PATH`
- `git` (only for the fallback "you committed today" nudge)
- `bun` for the local (git clone) install path — not needed once installed via npm

Verified end-to-end on OpenCode 1.18.4: prompt capture into the draft buffer, BM25 retrieval injection, and a model-initiated `memory_recall` tool call in a single `opencode run`.

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
| `<docs-root>/sessions/*.md` | append-only session journal (one entry per session, `status: open\|closed`) |
| `<docs-root>/topics/*.md` | distilled topic notes, materialised when a subject recurs |
| `<docs-root>/.drafts/*.draft.jsonl` | uncommitted capture buffer (auto-pruned after 7 days) |

`docs-root` defaults to `docs` and is overridable via a `docs-root:` field in the project instruction file's YAML frontmatter. `AGENTS.md` is read first and `CLAUDE.md` second, so a project that already carries a Claude Code chronicle keeps working without an edit. Resolution lives in one place — `skill/session-chronicle/scripts/_docsroot.py`, which the TS adapter and the Bash scripts also defer to.

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
| Crystallisation trigger | `Stop` → `checkpoint-nudge.py` exit 2 | `session.idle` → `client.session.command` invokes `/session-chronicle` |
| Compaction handoff | — (no Claude Code equivalent) | `experimental.session.compacting` → `output.context` |

Subagent (child) sessions are detected via the SDK (`parentID`) and skipped for injection and nudges — memory is a primary-session concern.

## Tools

| Tool | Args | Does |
|---|---|---|
| `memory_find` | `query` | BM25 search over sessions + topics, returns top note bodies |
| `memory_recall` | `slug`, `scope?` (`all\|topic\|sessions`) | topic note body + backlinking session ids in one call |
| `memory_backlinks` | `slug` | session entries wikilinking the slug (alias-aware) |
| `memory_audit` | `mode` (`orphans\|dups\|dangling\|stale\|candidates`) | memory health report, JSON |

Restrict them like any tool if needed:

```json
{ "permission": { "memory_*": "allow" } }
```

## Tunables (environment)

| Variable | Default | Meaning |
|---|---|---|
| `MEMORY_INJECT_BUDGET_CHARS` | `6000` | retrieval injection budget (~1500 tokens) |
| `MEMORY_INJECT_TOPK` | `3` | max notes injected per prompt |
| `MEMORY_INJECT_MAX_SCAN` | `60` | newest-first file scan cap (latency bound) |
| `MEMORY_DRAFT_NUDGE_MIN` | `3` | buffered signals required before the idle checkpoint fires |
| `SESSION_CHRONICLE_MODEL` | *(unset)* | full model id (e.g. `opencode-go/gpt-5.6`) the deterministic checkpoint is pinned to; unset → the session's own model runs it |
| `SESSION_CHRONICLE_CHECKPOINT_COOLDOWN_MS` | `300000` | min ms between deterministic checkpoint dispatches per session (loop guard) |
| `MEMORY_HEALTH_STALE_MAX` / `MEMORY_HEALTH_DANGLING_MAX` | `5` / `10` | thresholds for the index health line |

## The bundled skills

The plugin alone covers the full **read path** (capture, retrieval injection, guards, `memory_*` tools). The workflow prose the model must be able to *load* ships as two [Agent Skills](https://opencode.ai/docs/skills/) packages under `skill/`:

| Skill | Role | When it runs |
|---|---|---|
| `session-chronicle` | **Write path.** How to crystallise the draft into a well-formed entry: UPSERT on the day's `open` entry, frontmatter schema, midnight-rollover rule, `[[slug]]` wikilinks, lazy topic materialisation, draft truncation. Owns the note templates and the maintenance scripts. | Every checkpoint, for the life of the project. |
| `session-chronicle-bootstrap` | **Backfill.** Seeds the journal and the first topic notes from a project's pre-existing history (specs, plans, decisions, STATUS, git log). | Exactly once per project, on explicit request. |

Install both into the same discovery location (`.opencode/skills/`, `~/.config/opencode/skills/`) — the recipe above does it with one `cp -r`. The bootstrap deliberately keeps **no** copy of the note templates or `slugify.py`: it reads them from `session-chronicle`, so there is exactly one schema in the bundle. Installing the bootstrap alone leaves it inert; it stops with a message rather than improvising a note shape.

Each skill ships a matching one-line command shim under `command/`, so `/session-chronicle` and `/session-chronicle-bootstrap` work as slash commands. They are not optional decoration: the deterministic idle trigger invokes `/session-chronicle` verbatim, so without the shim the plugin points at a command that does not exist.

Without `session-chronicle` the plugin still works, but the deterministic trigger invokes a command whose workflow is missing — the model will improvise and iterate against the `note-lint` schema validator instead of following the canonical steps.

## Design notes

- **No MCP server.** The recall tools are plugin-registered custom tools (`tool:` key) — same UX for the model, no extra process, no MCP wiring.
- **The idle trigger is a command dispatch, not an injection.** `chat.message` injects context by pushing a synthetic text part into `output.parts`; but `session.idle` cannot inject, so it calls `client.session.command` directly to run `/session-chronicle` — the SDK client, not a hook return value, is what lets an idle session resume. A per-session cooldown plus draft truncation on crystallisation self-limit the loop.
- **Fail-open everywhere.** Every subprocess call is wrapped; a plugin bug degrades to "no memory this turn", never to a broken session — same contract as the original hooks (`never exit non-zero`).
- **`apply_patch` is not captured.** Its args carry `patchText`, not a file path; write/edit cover the overwhelming majority of signals. Known limitation.
- **The bundle names only what it ships.** The idle nudge points at `/session-chronicle`, which is in `command/`. Nothing here references a command, skill or file from any other library: a published plugin must work in a workspace that has only this plugin. The chronicle derives its entry from the draft buffer and the git log, both of which the plugin itself captures.

## Development

```bash
bun install
bun run typecheck
```

## License

MIT
