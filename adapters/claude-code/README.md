# Claude Code command-hook adapter — native qualification blocked

## Evidence and state (2026-10-15)

- Installed: **2.1.220**, supplied by the caller; native execution was not run.
- Release reference: **2.1.299**, not the installed build.
- Activation: **inert**. Package artifacts require explicit composition; no settings, plugins or UAT-generated files are installed/changed.
- Operational implementation: primary tool capture, checkpointing, index orientation, prompt BM25 retrieval and write guards use the shared worker. Native qualification and custom-tool transport remain blocked.

Official sources fetched on 2026-10-15:

1. [Hooks reference](https://code.claude.com/docs/en/hooks.md): Common input fields; SessionStart; UserPromptSubmit; PreToolUse; PostToolUse; PostToolUseFailure; Stop; PreCompact; PostCompact; SessionEnd; exit-code semantics.
2. [Published declarations](https://raw.githubusercontent.com/anthropics/claude-code/main/mods/types/claude-code.d.ts): fetched header **Written by Claude Code 2.1.277**, `BaseHookInput` explicitly says `agent_id` is absent on main, including `--agent` sessions. These are upstream declarations, not installed-build types. Qualify this invariant on 2.1.220 before activation.
3. [Create a mod](https://code.claude.com/docs/en/plugins/mods/create.md): minimum **2.1.287** and Get type definitions for your version.
4. [Mods API](https://code.claude.com/docs/en/plugins/mods/api.md) / [reference](https://code.claude.com/docs/en/plugins/mods/reference.md): `$.tool.register`, session methods and agent-loop provenance.

## Artifacts and explicit composition request

- `hook.py`: synchronous, one-shot native command hook and restricted operator diagnostics.
- `hooks.fragment.json`: settings-shaped request artifact, outside native discovery paths.
- `README.md`: evidence, behavior and remaining gates.

Composition owner: qualify an authorized runtime, replace each command's absolute package placeholder with a correctly shell-quoted `adapters/claude-code/hook.py` path, retain its fixed `--event`, and merge selected hook entries into the authorized settings layer while preserving existing entries. Review native `/hooks`. **Do not map these fragments onto UAT-generated settings.** No install or activation is implied by passing Python tests. Existing native skill entrypoints suffice; no duplicate slash commands are registered.

The resolver uses only `Path(__file__).resolve().parents[2]`, selecting package `core/chronicle.py`, otherwise source `skill/session-chronicle/scripts/chronicle.py`. Hook cwd, PATH, environment and siblings never select the worker. There is no daemon or last-session file.

## Behavior

| Event | Behavior |
| --- | --- |
| `SessionStart`, including compact/resume | Checkpoint only a trusted primary, then inject the read-only `index` as untrusted `additionalContext`. A fresh session needs no factual sources. Checkpoint failure does not prevent index retrieval. No semantic `context` target is created/adopted for orientation. |
| `UserPromptSubmit` | Attempt admissible capture separately; missing origin/ID produces a nonfatal diagnostic. Independently call `find` with the prompt and `includeEvidence: false`, injecting the worker's untrusted BM25 result through documented hook output. |
| `PreToolUse` Write/Edit | Preflight `replace`/`edit` guard. Invalid/protected mutations fail closed with denial and exit 2. |
| `PostToolUse` Write/Edit/Bash | Primary successful observations with native `tool_use_id` are selectively captured with `origin: unknown`. Tool observations do not require user-origin proof. Capture precedes post-write lint; lint failure reports a diagnostic without undoing capture or replacing the tool result. |
| `PostToolUseFailure` | Exclude failed activity from capture, report a nonfatal diagnostic. |
| `Stop`, `PreCompact`, `SessionEnd` | Primary checkpoint only. Missing actor provenance/failure preserves pending evidence and reports a diagnostic; Stop never requests another turn. |
| `PostCompact` | Not registered: use SessionStart `source: compact` for documented context injection. |

Session identity and absolute workspace come from native stdin `session_id`/`cwd`. Nonempty `agent_id` maps to delegated; absent maps to primary solely under source 2's explicit contract. Malformed child IDs block validation. Delegated actors cannot capture or checkpoint parent memory. `agent_type`, model-supplied `role`, `origin`, `model`, environment variables and transcript paths never establish identity. No generated/content-hashed event IDs or transcript parsing fill missing provenance.

**Prompt-capture blocker:** prompt hooks also fire for scheduled tasks, subagent reports and peer messages; no native origin discriminator is documented. An arbitrary `origin` input field is ignored. Unknown-origin prompts are not stored, but retrieval and the user's prompt continue normally. Missing prompt IDs likewise prevent capture only. Successful tool observations have independently documented completion and stable call identity.

## Failures

Registrations pin `--event`, so malformed/mismatched stdin on PreToolUse still yields `permissionDecision: deny`, stderr and exit 2. Passive prompt/tool/start/Stop failures use `systemMessage` and exit 0: diagnostics do not deny prompts, replace tool results, synthesize evidence or create Stop loops. Post-operation lint cannot undo completed effects. Claude discards PreCompact `systemMessage`; failures there use stderr and nonblocking exit 1. SessionEnd failures likewise use nonzero advisory reporting. Existing pending evidence is retained; no adapter cleanup or blind publication retries run.

Errors expose codes only, not prompts, transcripts, raw tool output or tracebacks. No prompt/transcript data is sent to UAT statistics.

## Operator diagnostics and native-tool blocker

`python3 /absolute/package/adapters/claude-code/hook.py --diagnostic OP --arguments JSON` reads an operator-provided hook fixture on stdin. Operations are `index` (no arguments), `find` (`query`, `includeEvidence`), `recall` (`slug`, `scope`), `backlinks` (`slug`) and `audit` (`mode`). Diagnostics force role `unknown` and reject identity arguments. `context` and the former `--read memory_session_context` path are unavailable: semantic context can mutate state, and operator/model fixtures do not authenticate a native session. This is not a model-facing fallback or native custom-tool discovery.

The installed 2.1.220 cannot host the documented >=2.1.287 mods surface. Build-matched declarations and a qualified per-call session/actor contract are missing; MCP has no qualified alternative binding. Obtain a supported build's generated declarations, verify trusted `tool.call` identity and process stdin contracts, then implement/qualify custom tools. No mod, types, server or tool registration is fabricated here.

## Verification

`python3 -B -m unittest discover -s tests -p test_native_hooks.py -v` exercises synthetic payload translation, mocked failure boundaries and isolated real-core integration when available. Coverage includes fresh-session index output, prompt retrieval despite capture gaps, successful Write deduplication/child exclusion, guard denial, pending preservation and sibling isolation. These tests do not establish native discovery, installed-build compatibility or live qualification.
