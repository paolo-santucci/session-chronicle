# OpenCode V2 adapter contract

The adapter is a thin transport for the neutral `chronicle.py` worker envelope.
It resolves only the source bundle at `../../skill/session-chronicle/scripts/chronicle.py`
or deployed bundle at `../../core/chronicle.py`; it never searches the caller's cwd.

## Evidence admission limits

The OpenCode V2 prompt hook available to this checkout has no verified, immutable
original-user provenance field. `event.metadata` and `delivery` are not treated as
authority. Therefore native prompt evidence capture is deliberately blocked and logs
`prompt_capture_blocked:origin_unavailable`; retrieval still uses the mutable prompt
text. A release-source/API contract identifying a trusted user-origin field is required
before prompt capture can be enabled.

For pinned OpenCode V2.0.26, the native patch plugin's
[`output.applied`](https://raw.githubusercontent.com/anomalyco/opencode/v2.0.26/packages/core/src/tool/plugin/patch.ts)
contains successful `{ type, resource, target }` entries, with absolute `target` paths.
On completed calls the adapter captures only those entries, never patch headers, diffs,
or input contents. Each stable capture ID is `${nativeCallID}:patch:${appliedIndex}`;
move destinations are covered by the native `target` value.

Tool writes and edits are guarded before execution. Post-execution guard failures append
a warning because completed mutations cannot be rolled back; successful observations are
captured before that warning is added. Session directories must be absolute runtime paths.

Startup calls the neutral `recover` operation only when OpenCode supplies an absolute
setup workspace. It has no fabricated session identity and only recovers already
attributed pending evidence. Relative setup paths are rejected.
