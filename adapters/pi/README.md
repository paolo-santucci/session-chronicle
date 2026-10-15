# Pi adapter

Source entry point: `adapters/pi/index.ts`; the package builder loads
`adapters/pi/entry.ts`, which re-exports it. Bundle manifests therefore map the
deployed entry to the source adapter rather than executing source files from a
different root. Installed bundles must preserve the worker at `core/chronicle.py`.
The adapter also has an explicit source-layout fallback at
`skill/session-chronicle/scripts/chronicle.py`; it never searches from `ctx.cwd`.

Evidence: Pi extension API and `v1.2.0` source declarations were checked on
2026-10-15 at <https://pi.dev/docs/latest/extensions> and
<https://github.com/earendil-works/pi/blob/v1.2.0/packages/coding-agent/src/core/extensions/types.ts>.
The verified lifecycle literals used here are `session_start`, `message_end`,
`tool_call`, and `session_before_compact`; `tool_execution_start` is not used
as a completion/capture event.

The read-only `memory_find`, `memory_recall`, `memory_backlinks`, and
`memory_audit` tools are active when Pi supplies a session ID and an absolute
`ctx.cwd`. `memory_session_context` and prompt capture remain inactive because
Pi 1.2.0 documents no trustworthy primary/delegated role and `message_end`
does not expose a stable prompt ID. Checkpoints are awaited at compaction and
core returns the unavailable result for unknown role. Write and edit calls are sent
to the core guard with native Pi input mapping; core may permit ordinary source
writes and rejects protected paths. Guard unavailability blocks writes. The
adapter never infers a role, fabricates an event ID, falls back to another cwd,
or starts a daemon. Native runtime qualification is pending because `pi` is not
available on this machine.
