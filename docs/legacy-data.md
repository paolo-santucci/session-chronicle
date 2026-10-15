---
date: 2026-10-15
status: compatibility-policy
---

# Historical data and portable identities

## Existing memory stays readable

Chronicle does not migrate existing evidence in place. Generic session notes,
unqualified native session IDs, factual batches, presentations, summaries and
legacy topics remain readable by the shared selectors and validators. Existing
daily drafts and sealed pending batches retain their original content and batch
identity through recovery. Malformed data is reported for operator repair rather
than discarded or assigned an invented owner.

An unqualified historical ID has **unknown harness provenance**, even in a checkout
whose previous adapter was OpenCode. A new qualified ID does not silently adopt
its old summary target. Two notes with the same title/date are not proof of shared
identity. Retrieval may find old and new records together while preserving this
distinction. Immutable factual files are never rewritten to add missing fields.

A historical bare ID that happens to match the new reserved identity namespace
remains legacy. New attribution or source validation encountering that ambiguity
fails explicitly rather than adopting the historical record. No automatic mapping
or in-place migration is introduced.

## New identity format

New runtime records use the versioned identity in `schemas/identity.schema.json`.
The canonical string is `chronicle:v1:<harness>:<base64url(native-session-id)>`,
where the opaque native ID is UTF-8 encoded without base64 padding. Harness IDs
are exactly `opencode`, `claude-code`, `codex`, and `pi`. Filename hashes derive
from the complete qualified identity; native task/run/turn IDs are separate.

The adapter obtains native identity, workspace and actor role from trusted runtime
context. A schema-valid process request is not by itself proof of that provenance:
the model-facing tools do not accept context fields. Missing provenance cannot
fall back to another project, latest session, timestamp or generated UUID.

## Continuation is additive

An explicit continuation connects distinct records with concrete supporting
evidence. It does not rename historical identities, merge native runtime sessions,
change the session count, reopen a closed summary, or simulate native resume.
Only a deliberate, validated continuation may establish the relation; similarly
named notes or equal bare ID strings cannot.

## Configuration synchronization

The validated docs-root holds `sessions/`, `topics/`, `.drafts/`, pending batches
and continuation metadata. These are worktree data, not configuration artifacts.
The package builder must never include the current project's memory in a release.
Custom docs-root locations inside managed harness configuration are rejected.
An existing overlapping root needs explicit operator-led relocation; no automatic
data move is authorized by installing a new package or changing a schema version.

UAT must also check this boundary before replacing configuration, because a plugin
cannot protect files already deleted before it starts. See request 6 in
`uat-integration-request.md`. Successful refused-sync preservation fixtures do not
establish successful native deployment or preservation on every filesystem.
