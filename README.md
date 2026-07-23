# opencode-session-chronicle

OpenCode plugin that gives a project a **chronological session memory**: an append-only journal of dated entries under `<docs-root>/sessions/` plus distilled topic notes under `<docs-root>/topics/`, written *for the agent to re-read*. The plugin covers the full loop:

- **Passive capture** — meaningful tool activity (file writes/edits, non-trivial bash, user prompts) is mirrored into a draft buffer, at zero token cost.
- **Retrieval injection** — on every user prompt, the top-k relevant note bodies are BM25-ranked and injected as a synthetic message part; on the first message of a session, a compact topic/session index is injected for orientation.
- **Write-path guard** — edits to closed (immutable) session entries are blocked, and content carrying secret-like patterns (tokens, keys, non-loopback IPs) is rejected before it can enter a note that would be re-injected forever.
- **Crystallisation triggers** — an idle-time nudge when buffered signals have no open journal entry, and a compaction handoff so an auto-compacted session does not forget its uncrystallised buffer.
- **Explicit recall tools** — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`.

All business logic lives in dependency-free Python/Bash scripts under `scripts/` (originally built and battle-tested as Claude Code hooks). `index.ts` is a thin adapter that maps OpenCode plugin hooks onto their original stdin JSON contract — the scripts run unmodified on both harnesses.

## Requirements

- OpenCode ≥ 1.18 (plugin API with `chat.message`, `tool.execute.*`, `experimental.session.compacting`)
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
```

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
.claude/docs/.drafts/
```

## Where memory lives (`docs-root`)

All paths are rooted at `<project>/<docs-root>`:

| Path | Content |
|---|---|
| `<docs-root>/sessions/*.md` | append-only session journal (one entry per session, `status: open\|closed`) |
| `<docs-root>/topics/*.md` | distilled topic notes, materialised when a subject recurs |
| `<docs-root>/.drafts/*.draft.jsonl` | uncommitted capture buffer (auto-pruned after 7 days) |

`docs-root` defaults to `.claude/docs` and is overridable via a `docs-root:` field in the project `CLAUDE.md` YAML frontmatter — resolved identically by the TS adapter and every script, so the plugin works out of the box on projects that already carry a Claude Code chronicle.

## Hook mapping

| Concern | Claude Code original | OpenCode hook |
|---|---|---|
| Capture file/bash signals | `PostToolUse` → `capture-signals.py` | `tool.execute.after` |
| Capture user prompts | `UserPromptSubmit` → `capture-signals.py` | `chat.message` |
| Retrieval injection (BM25) | `UserPromptSubmit` → `retrieve-inject.py` stdout | `chat.message` → synthetic text part |
| Session-start topic index | `SessionStart` → `topic-index.sh` stdout | `chat.message` (first message per session) → synthetic text part |
| Append-only + secret guard | `PreToolUse` → `note-lint.py` exit 2 | `tool.execute.before` → `throw` (blocks the call) |
| Note schema validation | `PostToolUse` → `note-lint.py` exit 2 | `tool.execute.after` → appended to tool output |
| Crystallisation nudge | `Stop` → `checkpoint-nudge.py` exit 2 | `session.idle` event → injected on the next message |
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
| `MEMORY_DRAFT_NUDGE_MIN` | `3` | buffered signals required before the idle nudge fires |
| `MEMORY_HEALTH_STALE_MAX` / `MEMORY_HEALTH_DANGLING_MAX` | `5` / `10` | thresholds for the index health line |

## Pairing with the crystallisation skill

The plugin handles capture, guard, retrieval, and nudging. The *crystallisation prose* — how to UPSERT the day's entry, wikilink subjects, materialise recurring topics — lives in the companion `session-chronicle` skill (an Agent Skills `SKILL.md`). OpenCode discovers skills natively from `.claude/skills/` or `.opencode/skills/`; deploy the skill alongside the plugin so the model knows the workflow when the nudge asks it to crystallise.

Maintenance scripts the skill invokes (`slugify.py`, `sync-topics-field.py`, `memory-audit.py --materialization-candidates`) ship in `scripts/` and remain directly runnable.

## Design notes

- **No MCP server.** The recall tools are plugin-registered custom tools (`tool:` key) — same UX for the model, no extra process, no MCP wiring.
- **Injection is part mutation, not a return value.** OpenCode hooks inject context by pushing a synthetic text part into `chat.message`'s `output.parts`; event handlers (e.g. `session.idle`) return nothing, so the idle nudge is staged and delivered on the next message.
- **Fail-open everywhere.** Every subprocess call is wrapped; a plugin bug degrades to "no memory this turn", never to a broken session — same contract as the original hooks (`never exit non-zero`).
- **`apply_patch` is not captured.** Its args carry `patchText`, not a file path; write/edit cover the overwhelming majority of signals. Known limitation.
- **Nudge wording mentions `/update-status` and `/session-chronicle`.** Those are Claude Code slash commands; on OpenCode read them as "run the update-status / session-chronicle workflow". Kept verbatim to leave the scripts byte-identical across harnesses.

## Development

```bash
bun install
bun run typecheck
```

## License

MIT
