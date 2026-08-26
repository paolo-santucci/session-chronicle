import { tool, type Plugin } from "@opencode-ai/plugin"
import { readFileSync } from "node:fs"
import { join } from "node:path"

const SCRIPTS = join(import.meta.dirname, "skill", "session-chronicle", "scripts")

const INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md"]

type ExecResult = { code: number; stdout: string; stderr: string }

async function exec(cmd: string[], env: Record<string, string>, stdin?: string): Promise<ExecResult> {
  try {
    const proc = Bun.spawn(cmd, {
      stdin: stdin === undefined ? "ignore" : Buffer.from(stdin),
      stdout: "pipe",
      stderr: "pipe",
      env: { ...process.env, ...env },
    })
    const [stdout, stderr, code] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ])
    return { code, stdout, stderr }
  } catch {
    return { code: 0, stdout: "", stderr: "" }
  }
}

function docsRoot(worktree: string): string {
  for (const name of INSTRUCTION_FILES) {
    try {
      const fm = readFileSync(join(worktree, name), "utf8").match(/^---\s*\n([\s\S]*?)\n---/)
      const m = fm?.[1]?.match(/^docs-root:\s*(.*)$/m)
      if (m) {
        const declared = m[1].trim().replace(/^["']|["']$/g, "").replace(/\/+$/, "")
        if (declared) return declared
      }
    } catch {}
  }
  return "docs"
}

const CC_TOOL: Record<string, string> = { write: "Write", edit: "Edit", bash: "Bash" }

function ccToolInput(toolName: string, args: any): Record<string, unknown> {
  if (toolName === "bash") return { command: args?.command ?? "" }
  return {
    file_path: args?.filePath ?? args?.file_path ?? "",
    content: args?.content ?? "",
    new_string: args?.newString ?? args?.new_string ?? "",
  }
}

/**
 * OpenCode port of the session-chronicle memory system.
 *
 * Write-path: passive signal capture (`tool.execute.after`, `chat.message`),
 * append-only + secret guard (`tool.execute.before`), idle crystallisation
 * nudge (`session.idle`), compaction handoff (`experimental.session.compacting`).
 * Read-path: session-start topic index and per-prompt BM25 retrieval injected
 * as synthetic message parts, plus `memory_*` tools for explicit recall.
 * All business logic stays in the original Python/Bash scripts under scripts/;
 * this module only adapts OpenCode hook shapes to their Claude-Code stdin contract.
 */
export const SessionChronicle: Plugin = async ({ worktree, client }) => {
  const env = { PROJECT_ROOT: worktree }
  const py = (script: string, args: string[] = [], stdin?: string) =>
    exec(["python3", join(SCRIPTS, script), ...args], env, stdin)
  const sh = (script: string, args: string[] = []) =>
    exec(["bash", join(SCRIPTS, script), ...args], env)
  const hookPayload = (data: Record<string, unknown>) => JSON.stringify({ cwd: worktree, ...data })
  const base = () => join(worktree, docsRoot(worktree))
  const today = () => new Date().toISOString().slice(0, 10)
  const draftFile = () => join(base(), ".drafts", `${today()}.draft.jsonl`)

  const greeted = new Set<string>()
  const pendingNudge = new Map<string, string>()
  const childSession = new Map<string, boolean>()

  async function isChildSession(sessionID: string): Promise<boolean> {
    const cached = childSession.get(sessionID)
    if (cached !== undefined) return cached
    let child = false
    try {
      const res: any = await client.session.get({ path: { id: sessionID } })
      child = Boolean(res?.data?.parentID)
    } catch {}
    childSession.set(sessionID, child)
    return child
  }

  function draftSignals(): number {
    try {
      return readFileSync(draftFile(), "utf8")
        .split("\n")
        .filter((l) => l.trim()).length
    } catch {
      return 0
    }
  }

  const lastDispatch = new Map<string, number>()
  const CHECKPOINT_COOLDOWN_MS = Number(process.env.SESSION_CHRONICLE_CHECKPOINT_COOLDOWN_MS || "300000")

  function checkpointModel(): string | undefined {
    const raw = process.env.SESSION_CHRONICLE_MODEL
    return raw && raw.trim() ? raw.trim() : undefined
  }

  function dispatchCheckpoint(sessionID: string): boolean {
    const now = Date.now()
    const last = lastDispatch.get(sessionID)
    if (last !== undefined && now - last < CHECKPOINT_COOLDOWN_MS) return false
    lastDispatch.set(sessionID, now)
    const model = checkpointModel()
    client.session
      .command({
        path: { id: sessionID },
        body: {
          command: "session-chronicle",
          arguments: "auto-checkpoint",
          ...(model ? { model } : {}),
        },
      })
      .catch(() => {})
    return true
  }

  return {
    "chat.message": async (input, output) => {
      if (!input.sessionID || (await isChildSession(input.sessionID))) return
      const prompt = output.parts
        .filter((p: any) => p.type === "text" && !p.synthetic)
        .map((p: any) => p.text ?? "")
        .join("\n")
        .trim()
      if (prompt)
        void py("capture-signals.py", [], hookPayload({ hook_event_name: "UserPromptSubmit", prompt }))

      const inject: string[] = []
      if (!greeted.has(input.sessionID)) {
        greeted.add(input.sessionID)
        inject.push(
          `[session-chronicle] This project keeps a chronological session journal under ${docsRoot(worktree)}/sessions/. ` +
            `You maintain it — run /session-chronicle at every checkpoint: after a logical group of work, after every commit, and at end-of-session.`,
        )
        const idx = await sh("topic-index.sh")
        if (idx.stdout.trim()) inject.push(idx.stdout.trim())
      }
      if (prompt) {
        const hit = await py("retrieve-inject.py", [], hookPayload({ prompt }))
        if (hit.stdout.trim()) inject.push(hit.stdout.trim())
      }
      const buffered = draftSignals()
      if (buffered > 0)
        inject.push(
          `[session-chronicle] ${buffered} uncrystallised signal(s) are buffered — run /session-chronicle at the next checkpoint, then truncate the draft.`,
        )
      const nudge = pendingNudge.get(input.sessionID)
      if (nudge) {
        pendingNudge.delete(input.sessionID)
        inject.push(nudge)
      }
      if (inject.length)
        output.parts.push({
          id: `prt_chronicle_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
          sessionID: input.sessionID,
          messageID: output.message.id,
          type: "text",
          text: inject.join("\n\n"),
          synthetic: true,
        } as (typeof output.parts)[number])
    },

    "tool.execute.before": async (input, output) => {
      const cc = CC_TOOL[input.tool]
      if (!cc || cc === "Bash") return
      const res = await py(
        "note-lint.py",
        [],
        hookPayload({
          hook_event_name: "PreToolUse",
          tool_name: cc,
          tool_input: ccToolInput(input.tool, output.args),
        }),
      )
      if (res.code === 2) throw new Error(res.stderr.trim())
    },

    "tool.execute.after": async (input, output) => {
      const cc = CC_TOOL[input.tool]
      if (!cc) return
      const shaped = hookPayload({
        hook_event_name: "PostToolUse",
        tool_name: cc,
        tool_input: ccToolInput(input.tool, input.args),
      })
      void py("capture-signals.py", [], shaped)
      if (cc === "Bash") return
      const res = await py("note-lint.py", [], shaped)
      if (res.code === 2) output.output += `\n\n[session-chronicle note-lint] ${res.stderr.trim()}`
    },

    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const sessionID = (event as any).properties?.sessionID
      if (!sessionID || (await isChildSession(sessionID))) return
      const res = await py("checkpoint-nudge.py", [], hookPayload({}))
      if (res.code !== 2 || !res.stderr.trim()) return
      const nudge = `[session-chronicle] ${res.stderr.trim()}`
      if (!dispatchCheckpoint(sessionID)) pendingNudge.set(sessionID, nudge)
    },

    "experimental.session.compacting": async (_input, output) => {
      const n = draftSignals()
      if (!n) return
      output.context.push(
        `session-chronicle: ${n} uncrystallised signal(s) are buffered in ${draftFile()}. ` +
          `Preserve this fact in the summary: at the next checkpoint they must be distilled into ` +
          `${docsRoot(worktree)}/sessions/ (session-chronicle workflow) and the draft truncated.`,
      )
    },

    tool: {
      memory_find: tool({
        description:
          "Search the project's session/topic memory notes by free-text query (BM25 over <docs-root>/sessions and <docs-root>/topics). Returns the top matching note bodies. Use when you need prior context on a subject but do not know its slug.",
        args: { query: tool.schema.string().describe("Free-text query, e.g. 'auth middleware decision'") },
        async execute({ query }) {
          const res = await py("retrieve-inject.py", [], hookPayload({ prompt: query }))
          return res.stdout.trim() || "(no matching memory notes)"
        },
      }),
      memory_recall: tool({
        description:
          "Recall a known memory subject by slug in one call: the distilled topic note body plus the session entries backlinking it (alias-aware). Use instead of cat+grep chains when the slug is known.",
        args: {
          slug: tool.schema.string().describe("Topic slug, kebab-case"),
          scope: tool.schema
            .enum(["all", "topic", "sessions"])
            .optional()
            .describe("What to return (default: all)"),
        },
        async execute({ slug, scope }) {
          const res = await sh("memory-recall.sh", [slug, `--${scope ?? "all"}`])
          if (res.code !== 0) return `error: ${res.stderr.trim() || "recall failed"}`
          return res.stdout.trim() || "(empty)"
        },
      }),
      memory_backlinks: tool({
        description:
          "List the session entries whose body wikilinks a given topic slug (aliases included). Use to reconstruct the history of a subject across sessions.",
        args: { slug: tool.schema.string().describe("Topic slug, kebab-case") },
        async execute({ slug }) {
          const res = await py("backlinks.py", [slug, "--base", base()])
          return res.stdout.trim() || "(none)"
        },
      }),
      memory_audit: tool({
        description:
          "Audit the health of the session/topic memory: orphans (topics with no backlinks), dups (near-duplicate slugs), dangling (links to missing topics), stale (topics not touched recently), candidates (subjects recurring across sessions that deserve a topic note). JSON output.",
        args: {
          mode: tool.schema.enum(["orphans", "dups", "dangling", "stale", "candidates"]),
        },
        async execute({ mode }) {
          const flag = mode === "candidates" ? "--materialization-candidates" : `--${mode}`
          const res = await py("memory-audit.py", [flag, "--base", base(), "--json"])
          return res.stdout.trim() || res.stderr.trim() || "(no findings)"
        },
      }),
    },
  }
}
