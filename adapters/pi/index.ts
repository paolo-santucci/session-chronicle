import { spawn } from "node:child_process"
import { access } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import { Type } from "typebox"
import type { AgentToolResult, ExtensionAPI, ExtensionContext, ToolCallEvent } from "@earendil-works/pi-coding-agent"

type Role = "primary" | "delegated" | "unknown"
type Operation = "capture" | "checkpoint" | "context" | "find" | "recall" | "backlinks" | "audit" | "index" | "guard" | "continuation"
type WorkerReply = { ok: true; result: object | string } | { ok: false; error: { code: string; message: string } }
type RunWorker = (operation: Operation, context: ExtensionContext, arguments_: Record<string, unknown>) => Promise<WorkerReply>
type WorkerRunnerOptions = {
  timeoutMs?: number
  maxStdoutBytes?: number
  resolveWorker?: () => Promise<string | undefined>
  spawnWorker?: (worker: string) => ReturnType<typeof spawn>
}

const AUDIT_MODES = ["orphans", "dups", "dangling", "stale", "candidates", "quality"] as const
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const WORKER_CANDIDATES = [
  fileURLToPath(new URL("../../core/chronicle.py", import.meta.url)),
  fileURLToPath(new URL("../../skill/session-chronicle/scripts/chronicle.py", import.meta.url)),
] as const

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined
}

function contextPayload(context: ExtensionContext): { harness: "pi"; session_id: string; workspace: string; role: Role } | undefined {
  const sessionID = context.sessionManager.getSessionId()
  if (!sessionID || !context.cwd.startsWith("/")) return undefined
  // Pi 1.2.0 documents no primary/delegated role or UAT provenance field.
  return { harness: "pi", session_id: sessionID, workspace: context.cwd, role: "unknown" }
}

function toolError(code: string, message: string): AgentToolResult<undefined> {
  return { content: [{ type: "text", text: JSON.stringify({ ok: false, error: { code, message } }) }], details: undefined, isError: true }
}

function toolReply(reply: WorkerReply): AgentToolResult<undefined> {
  if (!reply.ok) return toolError(reply.error.code, reply.error.message)
  return { content: [{ type: "text", text: typeof reply.result === "string" ? reply.result : JSON.stringify(reply.result) }], details: undefined }
}

async function resolveWorker(): Promise<string | undefined> {
  for (const candidate of WORKER_CANDIDATES) {
    try {
      await access(candidate)
      return candidate
    } catch {
      // Only package-relative locations are permitted; never discover from ctx.cwd.
    }
  }
  return undefined
}

function parseWorkerReply(stdout: string): WorkerReply | undefined {
  try {
    const reply = record(JSON.parse(stdout) as unknown)
    if (reply?.ok === true && typeof reply.result === "string") return { ok: true, result: reply.result }
    const result = record(reply?.result)
    if (reply?.ok === true && result) return { ok: true, result }
    const error = record(reply?.error)
    if (reply?.ok === false && typeof error?.code === "string" && typeof error.message === "string")
      return { ok: false, error: { code: error.code, message: error.message } }
  } catch {
    // Worker output is a protocol boundary.
  }
  return undefined
}

/** Creates a bounded worker transport; injection exists only for transport contract tests. */
export function createWorkerRunner(options: WorkerRunnerOptions = {}): RunWorker {
  const timeoutMs = options.timeoutMs ?? 30_000
  const maxStdoutBytes = options.maxStdoutBytes ?? 1_048_576
  const resolve = options.resolveWorker ?? resolveWorker
  const start = options.spawnWorker ?? ((worker: string) => spawn("python3", [worker], { stdio: ["pipe", "pipe", "pipe"] }))
  return async (operation, context, arguments_) => {
    const payload = contextPayload(context)
    if (!payload) return { ok: false, error: { code: "identity_unavailable", message: "Pi session ID or absolute workspace is unavailable." } }
    const worker = await resolve()
    if (!worker) return { ok: false, error: { code: "worker_unavailable", message: "Session Chronicle worker is not installed." } }
    const stdin = JSON.stringify({ schema_version: 1, operation, context: payload, arguments: arguments_ })
    return await new Promise((resolveReply) => {
      let stdout = ""
      let settled = false
      let deadline: ReturnType<typeof setTimeout> | undefined
      const finish = (reply: WorkerReply) => {
        if (settled) return
        settled = true
        if (deadline) clearTimeout(deadline)
        resolveReply(reply)
      }
      try {
        const child = start(worker)
        deadline = setTimeout(() => {
          child.kill()
          finish({ ok: false, error: { code: "worker_timeout", message: "Session Chronicle worker did not respond in time." } })
        }, timeoutMs)
        if (!child.stdin || !child.stdout || !child.stderr) {
          child.kill()
          finish({ ok: false, error: { code: "worker_unavailable", message: "Session Chronicle worker pipes are unavailable." } })
          return
        }
        child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
          stdout += chunk
          if (Buffer.byteLength(stdout) > maxStdoutBytes) {
            child.kill()
            finish({ ok: false, error: { code: "worker_protocol", message: "Session Chronicle worker response exceeded the protocol limit." } })
          }
        })
        child.stderr.resume()
        child.once("error", () => finish({ ok: false, error: { code: "worker_unavailable", message: "Unable to start Session Chronicle worker." } }))
        child.once("close", (code) => {
          const reply = parseWorkerReply(stdout)
          if (code !== 0) return finish(reply?.ok === false ? reply : { ok: false, error: { code: "worker_failed", message: "Session Chronicle worker failed." } })
          finish(reply ?? { ok: false, error: { code: "worker_protocol", message: "Worker returned invalid JSON." } })
        })
        child.stdin.once("error", () => finish({ ok: false, error: { code: "worker_unavailable", message: "Session Chronicle worker input failed." } }))
        child.stdin.end(stdin)
      } catch {
        finish({ ok: false, error: { code: "worker_unavailable", message: "Unable to start Session Chronicle worker." } })
      }
    })
  }
}

const runWorker = createWorkerRunner()

function guardArguments(event: ToolCallEvent): Record<string, unknown>[] | undefined {
  if (event.toolName === "write") {
    const input = record(event.input)
    const path = text(input?.path)
    const content = text(input?.content)
    return path === undefined || content === undefined ? undefined : [{ kind: "replace", path, content, phase: "pre" }]
  }
  if (event.toolName === "edit") {
    const input = record(event.input)
    const path = text(input?.path)
    const edits = Array.isArray(input?.edits) ? input.edits.map(record) : undefined
    if (path === undefined || !edits?.length) return undefined
    const mapped: Record<string, unknown>[] = []
    for (const edit of edits) {
      const oldText = text(edit?.oldText)
      const newText = text(edit?.newText)
      if (oldText === undefined || newText === undefined) return undefined
      mapped.push({ kind: "edit", path, old_text: oldText, new_text: newText, phase: "pre" })
    }
    return mapped
  }
  return undefined
}

function guardBlocks(reply: WorkerReply): { block: boolean; reason: string } | undefined {
  if (!reply.ok) return { block: true, reason: `session-chronicle: write guard unavailable (${reply.error.code})` }
  const result = record(reply.result)
  if (result?.allowed === false || result?.block === true) return { block: true, reason: "session-chronicle: write blocked by memory guard" }
  return undefined
}

/** Pi 1.2.0 extension. Capture remains inactive until Pi supplies a prompt identity and role contract. */
export function registerPiExtension(pi: ExtensionAPI, run: RunWorker = runWorker): void {
  const call = async (operation: Operation, arguments_: Record<string, unknown>, context: ExtensionContext): Promise<AgentToolResult<undefined>> => {
    if (!contextPayload(context)) return toolError("identity_unavailable", "Pi session ID or absolute workspace is unavailable.")
    return toolReply(await run(operation, context, arguments_))
  }
  const lifecycle = async (operation: "index" | "checkpoint", context: ExtensionContext): Promise<void> => {
    const reply = await call(operation, {}, context)
    if (reply.isError) console.warn(`session-chronicle: ${operation} unavailable`)
  }

  pi.registerTool({ name: "memory_find", label: "Memory find", description: "Search session memory.", parameters: Type.Object({ query: Type.String(), includeEvidence: Type.Optional(Type.Boolean()) }), execute: async (_id, input, _signal, _update, context) => {
    const args = record(input); const query = text(args?.query)
    return !query ? toolError("invalid_arguments", "query must be a non-empty string") : call("find", { query, ...(typeof args?.includeEvidence === "boolean" ? { includeEvidence: args.includeEvidence } : {}) }, context)
  } })
  pi.registerTool({ name: "memory_recall", label: "Memory recall", description: "Recall memory by slug.", parameters: Type.Object({ slug: Type.String(), scope: Type.Optional(Type.Union([Type.Literal("all"), Type.Literal("topic"), Type.Literal("sessions")])) }), execute: async (_id, input, _signal, _update, context) => {
    const args = record(input); const slug = text(args?.slug); const scope = text(args?.scope)
    return !slug || !SLUG.test(slug) || (scope !== undefined && !["all", "topic", "sessions"].includes(scope)) ? toolError("invalid_arguments", "slug or scope is invalid") : call("recall", { slug, ...(scope ? { scope } : {}) }, context)
  } })
  pi.registerTool({ name: "memory_backlinks", label: "Memory backlinks", description: "List memory backlinks.", parameters: Type.Object({ slug: Type.String() }), execute: async (_id, input, _signal, _update, context) => {
    const slug = text(record(input)?.slug)
    return !slug || !SLUG.test(slug) ? toolError("invalid_arguments", "slug is invalid") : call("backlinks", { slug }, context)
  } })
  pi.registerTool({ name: "memory_audit", label: "Memory audit", description: "Audit memory health.", parameters: Type.Object({ mode: Type.Union(AUDIT_MODES.map((mode) => Type.Literal(mode))) }), execute: async (_id, input, _signal, _update, context) => {
    const mode = text(record(input)?.mode)
    return mode === undefined || !AUDIT_MODES.includes(mode as typeof AUDIT_MODES[number]) ? toolError("invalid_arguments", "audit mode is invalid") : call("audit", { mode }, context)
  } })
  pi.registerTool({ name: "memory_session_context", label: "Memory session context", description: "Get trusted session context (primary only).", parameters: Type.Object({}), execute: async (_id, _input, _signal, _update, context) => toolError("provenance_unavailable", "Pi 1.2.0 provides no documented primary-role provenance.") })

  pi.on("tool_call", async (event, context) => {
    const arguments_ = guardArguments(event)
    if (event.toolName !== "write" && event.toolName !== "edit") return undefined
    if (!arguments_) return { block: true, reason: "session-chronicle: write guard received invalid tool input" }
    for (const argumentsForEdit of arguments_) {
      const blocked = guardBlocks(await run("guard", context, argumentsForEdit))
      if (blocked) return blocked
    }
    return undefined
  })
  pi.on("message_end", (event) => {
    if (event.message.role === "user") console.warn("session-chronicle: prompt capture unavailable; Pi supplies no stable prompt event ID.")
  })
  pi.on("session_start", async (_event, context) => { await lifecycle("index", context) })
  pi.on("session_before_compact", async (_event, context) => { await lifecycle("checkpoint", context) })
}

export default function extension(pi: ExtensionAPI): void {
  registerPiExtension(pi)
}
