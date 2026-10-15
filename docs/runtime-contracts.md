---
date: 2026-10-15
status: source-evidence-not-runtime-certification
---

# Native runtime evidence and enforcement boundary

Official documentation was inspected on 2026-10-15. The implementation-specific
notes beside each adapter identify the fields actually used. Live documentation,
release types, fixture tests and observed native operation are distinct evidence.
UAT reference versions are not certification of Chronicle or compatibility ranges.

## Sources

| Target | Reference | Consequential contract |
|---|---|---|
| OpenCode | [V2 plugin documentation](https://opencode.ai/v2/docs/build/plugins), [2.0.26 session API](https://raw.githubusercontent.com/anomalyco/opencode/v2.0.26/packages/plugin/src/promise/session.ts), installed `@opencode/plugin` types | Session lookup supplies parent and current location; tool before-hooks can throw; after-hooks distinguish completed/error; tool registration uses transform; prompt text is mutable |
| Claude Code | [hooks reference](https://code.claude.com/docs/en/hooks.md), [mods API](https://code.claude.com/docs/en/plugins/mods/api.md), [mods build instructions](https://code.claude.com/docs/en/plugins/mods/create.md), [manifest](https://code.claude.com/docs/en/plugins/manifest-reference.md) | Hook fields/decisions vary by event and build; new mods can register tools but need compatible CLI/build types and verified trusted call context |
| Codex CLI | [hooks reference](https://developers.openai.com/codex/hooks.md), [MCP](https://learn.chatgpt.com/docs/extend/mcp.md), [0.162.1 schema](https://raw.githubusercontent.com/openai/codex/rust-v0.162.1/codex-rs/core/config.schema.json) | Hooks compose and require trust; PostToolUse alone does not prove success; schema acceptance is not tool discovery or complete actor attribution; stdio MCP does not itself supply a trusted current-session transport |
| Pi | [extensions](https://pi.dev/docs/latest/extensions), [skills](https://pi.dev/docs/latest/skills), [extension types](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/src/core/extensions/types.ts) | Extension context supplies cwd/session manager; tool_call can block, streaming observation cannot; input sources and native IDs must be checked before capture; external child provenance needs a documented contract |

Installed executable probes before implementation: `opencode --version` → 2.0.29;
`claude --version` → 2.1.220. Codex/Pi were absent from PATH. No native version was
installed, upgraded, authenticated or silently substituted for testing. Native
model execution is not a configuration lint.

## Enforcement coverage to qualify

| Surface | Mechanism | Limit / required probe |
|---|---|---|
| Direct file replacement/edit | Native before-hook reconstructs proposal; core validates history, provenance and secrets | Worker/parse failure must deny. Native preflight and subsequent execution are not a shared atomic transaction |
| Complete topic patch | Adapter maps only its verified native patch grammar to complete proposed files | No blanket cross-harness grammar equivalence; partial/mixed/move/delete forms must fail for protected memory |
| Drafts/pending/factual records | Core-owned mutation paths; agent direct mutations denied | Capture/checkpoint internals are not model tools; external filesystem access can still bypass |
| Session semantic summary | Trusted empty-argument context operation plus guarded exact target | Prompt consent is a workflow gate, not cryptographic proof; concurrent native changes still require revalidation |
| Delegated tools | Apply guards independently of primary-only capture selection | A child must not evade a guard, nor become primary journal evidence |
| Shell or nested/custom operations | Only explicitly intercepted native operations have guard coverage | Arbitrary shell/Python/external writers are not universally intercepted. Do not claim filesystem immutability |
| Secret-like content | Heuristic redaction on capture; rejection of recognized patterns on note mutation | Unknown credentials, private data and arbitrary passwords may remain; no universal secret detector |
| Retrieval | Explicit untrusted delimiters, evidence opt-in, bounded selection | Labels do not prevent all prompt injection; source truth and semantic atomicity require review |
| Runtime unavailable/disabled | Explicit unavailable or blocked operation, preserved pending evidence | No silently unguarded mutation, guessed ID, fallback project, or completion claim from exit zero |

Required guarantees missing on an adapter block its operational qualification.
Neither an activation paragraph nor a skill's instructions supplies runtime
enforcement. UAT's unknown-tool denies remain intact while integration is pending.

## Identity and provenance policy

Native session identity is trusted only when obtained by the adapter from runtime
context. The neutral stdin protocol is a process boundary, not an authentication
service: an arbitrary OS process can fabricate JSON. Do not expose its context
fields as model tool arguments or treat direct shell invocation as equivalent to
native current-session resolution. Authorized operators may run recovery helpers;
semantic workflows may not use them to bypass denied native tools.

Legacy bare session IDs remain unknown-harness records. A matching native string,
similar title or date does not establish a continuation. New qualified identities
remain distinct; explicit continuation is additive metadata, never historical
rewriting or native resume. Memory/state lives with each worktree, outside
replaceable configuration, and follows its validated docs-root.

## Statistics coexistence

Chronicle emits no duplicate lifecycle events to UAT statistics. Its journal may
retain selected prompts and command inputs under configurable capture policy;
UAT's metadata-only statistics schema must not receive those payloads. Identity
reuse requires the documented per-call contract, not substitution of a statistics
run ID for a Chronicle session. Unknown outcomes and missing observations remain
unknown; neither subprocess success nor a tool observation proves task completion.
