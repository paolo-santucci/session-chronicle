import { access } from "node:fs/promises"
import { spawn } from "node:child_process"
import { resolve } from "node:path"

const MAX_STDOUT_BYTES = 1_048_576
const WORKER_TIMEOUT_MS = 30_000

export type ChronicleRole = "primary" | "delegated" | "unknown"

export type WorkerContext = {
  harness: "opencode"
  session_id: string
  workspace: string
  role: ChronicleRole
}

export type WorkerReply =
  | { ok: true; result: object | string }
  | { ok: false; error: { code: string; message: string } }

type WorkerRequest = {
  schema_version: 1
  operation: string
  context: WorkerContext
  arguments: Record<string, unknown>
}

type RecoveryRequest = {
  schema_version: 1
  operation: "recover"
  context: { harness: "opencode"; workspace: string }
  arguments: Record<string, never>
}

export class ChronicleWorkerClient {
  readonly candidates: readonly string[]

  constructor(candidates = [
    resolve(import.meta.dirname, "../../skill/session-chronicle/scripts/chronicle.py"),
    resolve(import.meta.dirname, "../../core/chronicle.py"),
  ]) {
    this.candidates = candidates
  }

  async call(operation: string, context: WorkerContext, arguments_: Record<string, unknown> = {}): Promise<WorkerReply> {
    const worker = await this.resolveWorker()
    if (!worker) return failure("worker_unavailable", "Session Chronicle worker is not installed.")

    const request: WorkerRequest = { schema_version: 1, operation, context, arguments: arguments_ }
    return this.run(worker, JSON.stringify(request))
  }

  async recover(workspace: string): Promise<WorkerReply> {
    const worker = await this.resolveWorker()
    if (!worker) return failure("worker_unavailable", "Session Chronicle worker is not installed.")
    const request: RecoveryRequest = {
      schema_version: 1,
      operation: "recover",
      context: { harness: "opencode", workspace },
      arguments: {},
    }
    return this.run(worker, JSON.stringify(request))
  }

  private async resolveWorker(): Promise<string | undefined> {
    for (const candidate of this.candidates) {
      try {
        await access(candidate)
        return candidate
      } catch {
        // Explicit package locations only; never discover from the caller's cwd.
      }
    }
    return undefined
  }

  private async run(worker: string, input: string): Promise<WorkerReply> {
    try {
      return await new Promise<WorkerReply>((resolveReply) => {
        const child = spawn("python3", [worker], { stdio: ["pipe", "pipe", "pipe"] })
        let stdout = ""
        let settled = false
        const finish = (reply: WorkerReply) => {
          if (settled) return
          settled = true
          clearTimeout(timeout)
          resolveReply(reply)
        }
        const timeout = setTimeout(() => {
          child.kill()
          finish(failure("worker_timeout", "Session Chronicle worker did not respond in time."))
        }, WORKER_TIMEOUT_MS)
        child.stdout?.setEncoding("utf8").on("data", (chunk: string) => {
          stdout += chunk
          if (Buffer.byteLength(stdout) > MAX_STDOUT_BYTES) {
            child.kill()
            finish(failure("worker_protocol", "Session Chronicle worker response exceeded the protocol limit."))
          }
        })
        // stderr is intentionally not returned: it can contain paths or payload fragments.
        child.stderr?.resume()
        child.once("error", () => finish(failure("worker_unavailable", "Unable to start Session Chronicle worker.")))
        child.once("close", (code) => {
          const reply = parseReply(stdout)
          if (code !== 0) {
            finish(reply?.ok === false ? reply : failure("worker_failed", "Session Chronicle worker failed."))
            return
          }
          finish(reply ?? failure("worker_protocol", "Worker returned invalid JSON."))
        })
        child.stdin?.once("error", () => finish(failure("worker_unavailable", "Session Chronicle worker input failed.")))
        child.stdin?.end(input)
      })
    } catch {
      return failure("worker_unavailable", "Unable to start Session Chronicle worker.")
    }
  }
}

function parseReply(output: string): WorkerReply | undefined {
  try {
    const value: unknown = JSON.parse(output)
    if (value === null || typeof value !== "object" || Array.isArray(value)) return undefined
    const reply = value as Record<string, unknown>
    if (reply.ok === true && (typeof reply.result === "string" || (reply.result !== null && typeof reply.result === "object"))) return reply as unknown as WorkerReply
    const error = reply.error
    if (reply.ok === false && error !== null && typeof error === "object" && typeof (error as Record<string, unknown>).code === "string" && typeof (error as Record<string, unknown>).message === "string") return reply as unknown as WorkerReply
  } catch {
    // A worker's stdout is a protocol boundary; malformed output is never executed or surfaced as trusted data.
  }
  return undefined
}

function failure(code: string, message: string): WorkerReply {
  return { ok: false, error: { code, message } }
}
