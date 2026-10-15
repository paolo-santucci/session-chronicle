# Codex command-hook adapter — native qualification blocked

## Evidence and state (2026-10-15)

- Installed: **absent**, supplied by the caller; no native Codex session was run.
- Release reference: **rust-v0.162.1** from the target mastery reference. Live docs are not proof of that release's exact behavior.
- Activation: **inert**; explicit composition is required. No native configuration or UAT-generated settings are changed.
- Operational implementation: index orientation, BM25 retrieval, patch preflight and primary-only lifecycle checkpoints use the shared worker. Native capture/custom-tool qualification remains blocked.

Official [Codex hooks documentation](https://developers.openai.com/codex/hooks.md), fetched 2026-10-15: Config shape, Review and trust hooks, Common input/output fields, Tool coverage, event-specific payloads/outputs, and Schemas. Official links also resolve into `learn.chatgpt.com`; linked `main` schemas may exceed release behavior. The registration fragment contains documented fields only.

## Artifacts and explicit composition request

- `hook.py`: synchronous, one-shot native command hook and restricted operator diagnostics.
- `hooks.fragment.json`: hooks-shaped request artifact outside native discovery paths.
- `README.md`: sources, behavior and remaining gates.

Composition owner: install/qualify an authorized build, replace each command placeholder with a correctly shell-quoted absolute `adapters/codex/hook.py` path, retain fixed `--event`, and compose selected entries into an authorized `hooks.json` beside an active configuration layer (or inline equivalent), preserving other entries. Review/trust the exact native `/hooks` definition. **Do not edit UAT-generated settings to activate this fragment.** Passing fixture tests does not activate or qualify the adapter.

Worker resolution uses only `Path(__file__).resolve().parents[2]`: package `core/chronicle.py`, otherwise source `skill/session-chronicle/scripts/chronicle.py`. Hook cwd, environment, PATH and siblings cannot select another worker. No daemon, MCP server or last-session identity file is created. Native skill entrypoints suffice; no duplicate slash commands are added.

## Behavior and blockers

| Event | Behavior |
| --- | --- |
| `SessionStart`, including `source: compact` | Unknown actor cannot checkpoint; emit a diagnostic and inject the read-only `index` through documented untrusted `additionalContext`. Fresh sessions need no factual sources. No semantic context/identity is adopted. |
| `UserPromptSubmit` | Capture remains unavailable without a stable prompt-event ID and origin discriminator. Emit a nonfatal diagnostic, independently call `find` with the prompt and `includeEvidence: false`, and inject untrusted BM25 results. The prompt proceeds. |
| `PreToolUse` `apply_patch` | `guard` with kind `patch`, `tool_input.command`, phase `pre`. Core allows unrelated work with unknown role; protected memory mutation fails closed. Edit/Write matcher aliases do not alter the canonical payload tool name. |
| `PostToolUse` | Capture unavailable: this event also follows nonzero command exits and `tool_response` has no proven success schema. Preserve the original result and report a nonfatal diagnostic. Shared patch validation is preflight only. |
| `Stop`, `PreCompact` | Unknown/delegated actors cannot checkpoint; diagnostic only, no synthetic continuation or stopping normal work. |
| `SessionEnd`, `Interrupt` | Docs explicitly exclude subagents: primary checkpoint, bounded to 2 seconds inside a 3-second hook budget. Failure retains pending evidence and is advisory. |
| `PostCompact` | Not registered; documented restoration occurs at SessionStart `source: compact`. |

Native `session_id` and absolute `cwd` supply identity/workspace. Known `agent_id` maps children to delegated. **An absent `agent_id` on tool/prompt/start/stop/compaction events does not prove primary**: the official tables do not establish that invariant, and a child can share its parent's session ID. Unknown role is preserved. Model-supplied role/status/origin/model and success-looking tool text cannot fill gaps. `tool_use_id` is checked, `turn_id` is not promoted to a prompt event ID, and IDs are never generated/content-hashed. No transcript parsing is used.

## Failures

Fixed `--event` lets malformed/mismatched PreToolUse stdin produce documented denial JSON, stderr and exit 2. Other passive failures use `systemMessage` at exit 0, preserving normal prompt/tool/Stop behavior. No `decision: block`, tool-result replacement or Stop-generated continuation is used for passive logging failures. SessionEnd/Interrupt worker failures return nonzero advisory errors without claiming to prevent shutdown/interruption. Pending evidence is never deleted or blindly retried. Errors contain codes, not raw prompts, transcripts, tool output or tracebacks. No prompt/transcript data is sent to UAT statistics.

## Operator diagnostics and native-tool blocker

`python3 /absolute/package/adapters/codex/hook.py --diagnostic OP --arguments JSON` reads an operator-provided hook fixture on stdin. Allowed operations: `index` (no arguments), `find` (`query`, `includeEvidence`), `recall` (`slug`, `scope`), `backlinks` (`slug`), `audit` (`mode`). Diagnostics force role `unknown` and reject identity arguments. Semantic `context` and the former `--read memory_session_context` mode are unavailable: context may mutate state, and fixture input is not runtime authentication. This CLI is not a model-facing context fallback or native tool discovery.

MCP tools and MCP hook handlers exist, but no checked contract binds a model-originated memory call to a trusted current session/workspace/actor. Hook templates alone do not establish that transport. Establish and qualify a build-specific per-call contract before implementing custom-tool registration. None is invented here.

## Verification

`python3 -B -m unittest discover -s tests -p test_native_hooks.py -v` exercises synthetic fixtures, mocked failure boundaries and isolated real-core checks when available. Positive checks cover fresh orientation, prompt retrieval despite capture gaps and unrelated unknown-role writes; negative checks cover protected writes, forged diagnostic identity, unsafe success inference, pending evidence and sibling isolation. Native discovery, installed-runtime behavior and full qualification remain blocked.
