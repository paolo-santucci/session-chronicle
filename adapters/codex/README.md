# Codex command-hook adapter — 0.163.0 implementation

## Evidence and state (2026-10-23)

- Baseline: **codex-cli 0.163.0**, upstream tag `rust-v0.163.0`, commit
  `83086188ae0614bd882818ff1aa23f3194962012`.
- Chronicle did not install, activate or invoke Codex and did not modify Ansel.
  UAT's authenticated model and app-server smoke results are external integration
  evidence, not Chronicle qualification.
- `plugin.yaml` declares eight artifact-bound `adapters.codex.hooks` contributions.
  UAT composes them into its settings while preserving native status/statistics
  groups and emits an owned contribution inventory. The legacy
  `hooks.fragment.json` remains inert reference material and is not an activation
  source.
- `chronicle.retrieval` and `chronicle.protected-history` are implemented but
  unverified. `chronicle.capture` and `chronicle.session-context` remain explicitly
  unsupported, so required-capability blockers remain.

## Pinned producer semantics

The following conclusions come from the exact 0.163.0 source, not merely its JSON
schemas:

- [`core/src/hook_runtime.rs`](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/hook_runtime.rs)
  creates prompt hooks from the pending `TurnInput::UserInput` before recording it
  and before adding hook context. Its native `turn_context.sub_id` is passed as
  `turn_id`, but the producer processes pending input items individually and does
  not prove that a turn ID uniquely identifies one prompt event. Chronicle refuses
  prompt capture and never hashes prompt content into an ID.
- The same producer calls `run_post_tool_use_hooks` only after a tool has produced
  a successful output. Chronicle may therefore treat `PostToolUse` as completed;
  it does not inspect prose or ad-hoc `tool_response` fields for success.
- `thread_spawn_subagent_hook_context` supplies `agent_id` and `agent_type` only
  for `SessionSource::SubAgent(SubAgentSource::ThreadSpawn)`. Other sources,
  including internal/synthetic sessions, produce neither field. Presence proves a
  delegated thread-spawn actor, but absence does **not** prove a primary actor.
- `SessionEnd` and `Interrupt` explicitly reject every `SessionSource::SubAgent` in
  the producer. Those lifecycle events can checkpoint as primary. `Stop`, prompt,
  tool and compaction hooks retain `unknown` when child fields are absent.
- [`hooks/src/events/post_tool_use.rs`](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/hooks/src/events/post_tool_use.rs)
  preserves native `tool_use_id`; prompt and tool schemas make `turn_id` required.
  Schema presence alone was not used as actor or success evidence.

The adapter uses the original prompt for read-only retrieval but refuses prompt
capture because event identity and actor attribution remain unproven. Successful
Bash calls retain native tool IDs and `origin: unknown`, then refuse journal
mutation because the actor remains unknown. A known child is delegated and also
excluded. `apply_patch` capture is not collapsed into one invented path.
Protected-memory patch preflight is separate and still applies to intercepted
children and unknown actors.

## Composed handlers

| Event | Matcher | Behavior |
| --- | --- | --- |
| `SessionStart` | all | Read-only index orientation; unknown actor cannot checkpoint. |
| `PreToolUse` | `^apply_patch$` | Reconstruct patch proposal and call the shared guard. Explicit denials use native deny output and exit 2. |
| `PostToolUse` | `^(apply_patch\|Bash)$` | Preserve successful native IDs/status, but do not capture without primary attribution. |
| `UserPromptSubmit` | all | BM25 retrieval from the original pending input; capture remains blocked on actor attribution. |
| `Stop`, `PreCompact` | all | Checkpoint only if primary; current absent actor fields remain unknown. |
| `SessionEnd`, `Interrupt` | all | Root-only checkpoint with a 2-second worker timeout inside UAT's retained 3-second native limit. |

All declarations use `python3`, the exact `adapters/codex/hook.py` source key and a
fixed `--event` argument. Matchers and fixed events are declaration data, not
shell-generated paths. UAT's Git-root command resolves the deployed artifact;
there are no absolute sibling paths. Native matching handlers may execute
concurrently, so declaration order does not establish prompt provenance or guard
sequencing.

## Failures and protected-history limits

Malformed or mismatched `PreToolUse` input, worker errors and protected-memory
rejection emit a nonempty denial reason and exit 2. Codex 0.163.0 itself fails open
for hook exceptions, timeouts, malformed output and unsupported `ask`; a successful
sibling cannot override a supported explicit denial, but this is not a complete
security boundary. `PostToolUse` cannot undo effects. Shell, `write_stdin`, hosted
tools and unobserved delegation paths need UAT's scoped driver/effect broker rather
than a broader Chronicle claim.

Other passive hook failures return content-free diagnostics without replacing
native prompt/tool results. Session-end errors are advisory and cannot prevent
shutdown. Pending evidence is retained. Journal, prompt and tool payloads are never
forwarded to UAT telemetry.

## Memory-operation API still required from UAT

Chronicle needs a versioned broker call for each of `memory_find`, `memory_recall`,
`memory_backlinks`, `memory_audit` and `memory_session_context` with:

1. trusted thread/turn/workspace and selected principal binding supplied outside
   model arguments;
2. primary/delegated/unknown actor classification and operation-specific policy
   decision;
3. immutable validated model arguments containing only each operation's documented
   query/slug/scope/mode fields;
4. an effect result distinguishing success, denial, unresolved ask and error;
5. no prompt, query, note, journal or arbitrary tool payload in lifecycle telemetry.

`memory_session_context` has empty model arguments, requires mutation permission,
may checkpoint and must use the broker's trusted binding. UAT's short-lived
0.163.0 app-server transport already binds principal/thread/turn for callbacks, but
it disables native hooks and has no production policy/effect broker or Chronicle
bridge. Chronicle does not invent a private metadata field or infer identity from
model input.

## Verification boundary

`python3 -B -m unittest discover -s tests -p test_native_hooks.py -v` exercises
translation, unknown/delegated exclusion, read-only retrieval, guarded writes,
failure behavior and isolated real-core calls. The UAT package suite validates the
eight declarations, composed inventory, preserved native settings and exact copied
artifact bytes. Neither suite activates Codex or creates native qualification.
