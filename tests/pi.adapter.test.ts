import { expect, mock, test } from "bun:test"
import { spawn } from "node:child_process"
import { EventEmitter } from "node:events"
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent"

mock.module("typebox", () => ({ Type: { Object: (value: unknown) => value, String: () => ({}), Boolean: () => ({}), Optional: (value: unknown) => value, Literal: (value: unknown) => value, Union: (value: unknown) => value } }))
const { createWorkerRunner, registerPiExtension } = await import("../adapters/pi/index")

type Tool = { name: string; execute: (id: string, input: unknown, signal: AbortSignal | undefined, update: unknown, context: ExtensionContext) => Promise<{ content: unknown; details: undefined; isError?: boolean }> }
type Handler = (event: unknown, context: ExtensionContext) => unknown

function fixture(): { pi: ExtensionAPI; tools: Map<string, Tool>; events: Map<string, Handler>; context: ExtensionContext } {
  const tools = new Map<string, Tool>()
  const events = new Map<string, Handler>()
  const pi = {
    registerTool: (tool: Tool) => tools.set(tool.name, tool),
    on: (name: string, handler: Handler) => { events.set(name, handler); return () => {} },
  } as unknown as ExtensionAPI
  const context = { cwd: "/workspace", sessionManager: { getSessionId: () => "ses_1" } } as unknown as ExtensionContext
  return { pi, tools, events, context }
}

test("returns a core-backed read result with Pi tool-result details", async () => {
  const { pi, tools, context } = fixture()
  registerPiExtension(pi, async (operation) => operation === "find" ? { ok: true, result: { hits: ["topic"] } } : { ok: false, error: { code: "unexpected", message: "unexpected" } })
  const result = await tools.get("memory_find")!.execute("call", { query: "topic" }, undefined, undefined, context)
  expect(result).toEqual({ content: [{ type: "text", text: JSON.stringify({ hits: ["topic"] }) }], details: undefined })
})

test("allows an ordinary write after the core guard and blocks a protected write", async () => {
  const { pi, events, context } = fixture()
  registerPiExtension(pi, async (_operation, _context, arguments_) =>
    arguments_.path === "src/app.ts" ? { ok: true, result: { allowed: true } } : { ok: false, error: { code: "protected_path", message: "blocked" } },
  )
  const guard = events.get("tool_call")!
  expect(await guard({ type: "tool_call", toolName: "write", toolCallId: "native-write", input: { path: "src/app.ts", content: "export {}" } }, context)).toBeUndefined()
  expect(await guard({ type: "tool_call", toolName: "write", toolCallId: "native-memory", input: { path: "docs/sessions/x.md", content: "secret" } }, context)).toEqual({ block: true, reason: "session-chronicle: write guard unavailable (protected_path)" })
})

test("uses Pi's actual edit array shape and does not invent a prompt event ID", async () => {
  const { pi, events, context } = fixture()
  const calls: Record<string, unknown>[] = []
  const warning = console.warn
  let warnings = 0
  console.warn = () => { warnings++ }
  try {
    registerPiExtension(pi, async (_operation, _context, arguments_) => { calls.push(arguments_); return { ok: true, result: { allowed: true } } })
    const guard = events.get("tool_call")!
    expect(await guard({ type: "tool_call", toolName: "edit", toolCallId: "native-edit", input: { path: "src/app.ts", edits: [{ oldText: "one", newText: "two" }] } }, context)).toBeUndefined()
    await events.get("message_end")!({ type: "message_end", message: { role: "user", content: [{ type: "text", text: "token=secret" }] } }, context)
    expect(calls).toEqual([{ kind: "edit", path: "src/app.ts", old_text: "one", new_text: "two", phase: "pre" }])
    expect(warnings).toBe(1)
  } finally {
    console.warn = warning
  }
})

test("awaits compaction lifecycle failure without leaking worker details", async () => {
  const { pi, events, context } = fixture()
  const warning = console.warn
  const messages: unknown[] = []
  console.warn = (message: unknown) => { messages.push(message) }
  try {
    registerPiExtension(pi, async () => ({ ok: false, error: { code: "worker_failed", message: "/private/path token=secret" } }))
    await events.get("session_before_compact")!({ type: "session_before_compact" }, context)
    expect(messages).toEqual(["session-chronicle: checkpoint unavailable"])
  } finally {
    console.warn = warning
  }
})

function fakeWorker() {
  let wasKilled = false
  const stdin = Object.assign(new EventEmitter(), { end: (_input: string) => {} })
  const stdout = Object.assign(new EventEmitter(), { setEncoding: (_encoding: string) => stdout })
  const stderr = Object.assign(new EventEmitter(), { resume: () => {} })
  const child = Object.assign(new EventEmitter(), { stdin, stdout, stderr, kill: () => { wasKilled = true; return true } })
  return { child, spawned: child as unknown as ReturnType<typeof spawn>, killed: () => wasKilled }
}

test("times out and kills a non-responsive worker without waiting for the production deadline", async () => {
  const { context } = fixture()
  const worker = fakeWorker()
  const run = createWorkerRunner({ timeoutMs: 1, resolveWorker: async () => "/bundle/core/chronicle.py", spawnWorker: () => worker.spawned })
  await expect(run("find", context, { query: "topic" })).resolves.toEqual({ ok: false, error: { code: "worker_timeout", message: "Session Chronicle worker did not respond in time." } })
  expect(worker.killed()).toBe(true)
})

test("caps noisy worker stdout and kills the child", async () => {
  const { context } = fixture()
  const worker = fakeWorker()
  const run = createWorkerRunner({ maxStdoutBytes: 3, resolveWorker: async () => "/bundle/core/chronicle.py", spawnWorker: () => {
    queueMicrotask(() => worker.child.stdout.emit("data", "four"))
    return worker.spawned
  } })
  await expect(run("find", context, { query: "topic" })).resolves.toEqual({ ok: false, error: { code: "worker_protocol", message: "Session Chronicle worker response exceeded the protocol limit." } })
  expect(worker.killed()).toBe(true)
})
