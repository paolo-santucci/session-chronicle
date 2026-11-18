---
title: Spec Canon Index
last-generated: 2026-11-18
---

# Spec Canon — Index

Canonical description of what `session-chronicle` 0.2.1 does today. Product-capability slices are the spine; `runtime-architecture` and `harness-adapters` are the subordinate architecture/data-model slices. Declared limits are part of the truth, not caveats.

| Domain | Summary | Slice | Last verified |
|---|---|---|---|
| capability-gates | The adjudication surface that separates what Chronicle implements in source, what is only fixture-verified, and what is… | [capability-gates.md](capability-gates.md) | 2026-11-18 |
| capture | Zero-token, heuristic capture of meaningful session activity — user prompts, file writes/edits and significant shell… | [capture.md](capture.md) | 2026-11-18 |
| diagnostics | The operator-facing health surface of a Chronicle project: one read-only command that answers whether the plugin is… | [diagnostics.md](diagnostics.md) | 2026-11-18 |
| harness-adapters | Four native adapters translate each target harness's hook/extension events onto one neutral JSON envelope executed by… | [harness-adapters.md](harness-adapters.md) | 2026-11-18 |
| memory-tools | Five agent-facing tools — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`, `memory_session_context`… | [memory-tools.md](memory-tools.md) | 2026-11-18 |
| packaging-deployment | The distribution contract for `session-chronicle` 0.2.1: a deterministic, allowlisted source package built from the… | [packaging-deployment.md](packaging-deployment.md) | 2026-11-18 |
| retrieval | Prompt-time injection of prior project memory: on every user prompt the shared core ranks the project's topic and… | [retrieval.md](retrieval.md) | 2026-11-18 |
| runtime-architecture | One versioned process protocol and one on-disk memory layout, shared unchanged by every harness adapter. A workspace's… | [runtime-architecture.md](runtime-architecture.md) | 2026-11-18 |
| session-journal | Chronological memory of work sessions: captured activity is sealed into immutable factual evidence notes without… | [session-journal.md](session-journal.md) | 2026-11-18 |
| topic-memory | Durable, project-shared knowledge stored as one Markdown note per idea under `<docs-root>/topics/`, with three note… | [topic-memory.md](topic-memory.md) | 2026-11-18 |
| write-safety | The write-path guard: every supported direct native mutation into the memory store is checked before it lands and… | [write-safety.md](write-safety.md) | 2026-11-18 |
