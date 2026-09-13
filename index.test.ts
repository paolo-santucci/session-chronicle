import { expect, test } from "bun:test"
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { SessionChronicle } from "./index"

test("startup, idle and compaction persist without any model or command response", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const drafts = join(worktree, "docs", ".drafts")
    await mkdir(drafts, { recursive: true })
    await writeFile(join(drafts, "2000-01-01.draft.jsonl"), '{"kind":"prompt","text":"pending"}\n')
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }), command: () => { throw Error("No model") } } },
    } as any)
    const sessions = join(worktree, "docs", "sessions")
    expect((await readdir(sessions)).filter(name => name.endsWith(".md"))).toHaveLength(1)
    expect(await hooks.tool!.memory_find.execute({ query: "pending" }, {} as any)).toBe("(no matching memory notes)")
    expect(await hooks.tool!.memory_find.execute({ query: "pending", includeEvidence: true }, {} as any)).toContain('"text": "pending"')
    await hooks["tool.execute.after"]!({
      tool: "edit", sessionID: "primary", callID: "call-one", args: { filePath: "source.ts" },
    }, { title: "", output: "", metadata: {} })
    await Promise.all([1, 2].map(() => hooks.event!({
      event: { type: "session.idle", properties: { sessionID: "primary" } },
    })))
    expect((await readdir(sessions)).filter(name => name.endsWith(".md"))).toHaveLength(3)
    await hooks["tool.execute.after"]!({
      tool: "bash", sessionID: "primary", callID: "call-two", args: { command: "bun test" },
    }, { title: "", output: "", metadata: {} })
    const output = { context: [] as string[] }
    await hooks["experimental.session.compacting"]!({ sessionID: "primary" }, output)
    expect(output.context.join()).toContain("captured evidence persisted")
    const notes = (await readdir(sessions)).filter(name => name.endsWith(".md"))
    expect(notes).toHaveLength(4)
    const factual = notes.find(name => name.includes("--evidence-"))!
    expect(await readFile(join(sessions, factual), "utf8")).toContain("record-kind: factual-evidence")
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("prompt recovery filters synthetic text and child sessions", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async ({ path }: { path: { id: string } }) => ({
        data: path.id === "child" ? { parentID: "primary" } : {},
      }) } },
    } as any)
    const output = {
      message: { id: "message-one" },
      parts: [
        { type: "text", text: "Real user input" },
        { type: "text", text: "Synthetic instruction", synthetic: true },
      ],
    }
    await hooks["chat.message"]!({ sessionID: "primary" }, output as any)
    await hooks["tool.execute.after"]!({
      tool: "edit", sessionID: "child", callID: "child-call", args: { filePath: "child.ts" },
    }, { title: "", output: "", metadata: {} })
    await hooks["chat.message"]!({ sessionID: "child" }, {
      message: { id: "child-message" }, parts: [{ type: "text", text: "Child input" }],
    } as any)
    await hooks.event!({ event: { type: "session.idle", properties: { sessionID: "primary" } } })
    const sessions = join(worktree, "docs", "sessions")
    const notes = (await readdir(sessions)).filter(name => name.endsWith(".md"))
    expect(notes).toHaveLength(2)
    const factual = notes.find(name => name.includes("--evidence-"))!
    const text = await readFile(join(sessions, factual), "utf8")
    expect(text).toContain("Real user input")
    expect(text).not.toContain("Synthetic instruction")
    expect(text).not.toContain("Child input")
    expect(text).not.toContain("child.ts")
    expect(text).toContain('"eventID": "message-one"')
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("value-only edits cannot forge a generated session presentation", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const sessions = join(worktree, "docs", "sessions")
    await mkdir(sessions, { recursive: true })
    const summary = join(sessions, "summary.md")
    await writeFile(summary, "---\nid: summary\ntype: session\nrecord-kind: semantic-summary\nstatus: open\n---\n\nSummary.\n")
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }) } },
    } as any)
    await expect(hooks["tool.execute.before"]!(
      { tool: "edit", sessionID: "primary", callID: "forge" },
      { args: { filePath: summary, oldString: "semantic-summary", newString: "session-presentation" } },
    )).rejects.toThrow("semantic-summary session-id and record-kind are immutable")
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("child sessions cannot edit generated session presentations", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const sessions = join(worktree, "docs", "sessions")
    const presentation = join(sessions, "presentation.md")
    await mkdir(sessions, { recursive: true })
    await writeFile(presentation, "---\nid: presentation\ntype: session\nrecord-kind: session-presentation\nstatus: open\n---\n\nOriginal.\n")
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: { parentID: "primary" } }) } },
    } as any)
    await expect(hooks["tool.execute.before"]!(
      { tool: "edit", sessionID: "child", callID: "child-edit" },
      { args: { filePath: presentation, oldString: "Original", newString: "Modified" } },
    )).rejects.toThrow("session-presentation files are generated")
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("session context uses the SDK identity and checkpoints its sources", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }) } },
    } as any)
    await hooks["chat.message"]!({ sessionID: "trusted-sdk-session" }, {
      message: { id: "message-one" },
      parts: [{ type: "text", text: "Persist this source" }],
    } as any)
    const result = await hooks.tool!.memory_session_context.execute(
      { session_id: "untrusted-argument" } as never,
      { sessionID: "trusted-sdk-session" } as any,
    )
    const context = JSON.parse(result as string)
    expect(context.session_id).toBe("trusted-sdk-session")
    expect(context.sources).toHaveLength(1)
    expect(context.semantic_summary).toBeNull()
    expect(context.presentation).toMatch(/^docs\/sessions\/.*\.md$/)
    expect(context.target).toMatch(/^docs\/sessions\/session--.+--summary\.md$/)
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("session context rejects missing SDK identity without inferring an argument identity", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }) } },
    } as any)
    const result = await hooks.tool!.memory_session_context.execute(
      { session_id: "untrusted-argument" } as never,
      { sessionID: "" } as any,
    )
    const error = JSON.parse(result as string).error
    expect(error.code).toBe("session_context_failed")
    expect(error.message).toContain("SDK session identity")
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})

test("session context rejects an unsafe docs root without writing outside its worktree", async () => {
  const parent = await mkdtemp(join(tmpdir(), "chronicle-parent-"))
  const worktree = join(parent, "worktree")
  const outside = join(parent, "outside")
  try {
    await mkdir(worktree)
    await writeFile(join(worktree, "AGENTS.md"), "---\ndocs-root: ../outside\n---\n")
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }) } },
    } as any)
    const result = await hooks.tool!.memory_session_context.execute(
      {},
      { sessionID: "trusted-sdk-session" } as any,
    )
    const error = JSON.parse(result as string).error
    expect(error.code).toBe("session_context_failed")
    expect(error.message).toContain("docs-root")
    expect(await readdir(parent)).toEqual(["worktree"])
    await expect(readFile(join(outside, "sessions"), "utf8")).rejects.toThrow()
  } finally {
    await rm(parent, { recursive: true, force: true })
  }
})

test("semantic summary writes require the trusted SDK session identity", async () => {
  const worktree = await mkdtemp(join(tmpdir(), "chronicle-"))
  try {
    const hooks = await SessionChronicle({
      worktree,
      client: { session: { get: async () => ({ data: {} }) } },
    } as any)
    await hooks["chat.message"]!({ sessionID: "owner" }, {
      message: { id: "message-one" },
      parts: [{ type: "text", text: "Persist this source" }],
    } as any)
    const context = JSON.parse(await hooks.tool!.memory_session_context.execute(
      {},
      { sessionID: "owner" } as any,
    ) as string)
    const target = join(worktree, context.target)
    const id = context.target.split("/").at(-1)!.replace(/\.md$/, "")
    const content = `---\nid: ${id}\ntype: session\nrecord-kind: semantic-summary\nsession-id: owner\ndate: 2026-09-13\ntitle: Owner summary\nstatus: open\nsources: [${context.sources[0]}]\n---\n\nOwner summary.\n`
    const spoofedArgs = { filePath: target, content, sessionID: "owner" }
    await expect(hooks["tool.execute.before"]!(
      { tool: "write", sessionID: "foreign", callID: "foreign-write" },
      { args: spoofedArgs },
    )).rejects.toThrow("trusted SDK sessionID")
    await expect(hooks["tool.execute.before"]!(
      { tool: "write", sessionID: "owner", callID: "owner-write" },
      { args: spoofedArgs },
    )).resolves.toBeUndefined()
  } finally {
    await rm(worktree, { recursive: true, force: true })
  }
})
