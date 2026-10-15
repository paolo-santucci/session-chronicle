# Session Chronicle

Independently owned project memory for **OpenCode, Claude Code, Codex CLI and Pi**.
The repository, npm package and portable plugin share the name `session-chronicle`,
version **0.2.0**.

**This is an implementation with explicit integration gates, not four-harness
operational certification.** UAT can inspect package artifacts, but its current
external-plugin capability handling, custom-tool policy and hook composition block
full activation. No portable bundle has been deployed or published during this work.

- [Workflow/capability matrix](docs/capability-matrix.md)
- [Architecture and milestones](docs/portability-plan.md)
- [Package consumption](docs/package-consumption.md)
- [Exact verification evidence](docs/verification.md)
- [Focused UAT integration requests](docs/uat-integration-request.md)
- [Native contracts and enforcement coverage](docs/runtime-contracts.md)
- [Legacy data and identity policy](docs/legacy-data.md)

Chronicle keeps a **chronological session memory** under `<docs-root>/sessions/`
and distilled topic notes under `<docs-root>/topics/`, written for later retrieval.
Its shared workflows cover:

- **Passive capture** — meaningful tool activity (file writes/edits, non-trivial bash, user prompts) is mirrored into a draft buffer, at zero token cost.
- **Retrieval injection** — on every user prompt, the top-k relevant session/topic bodies are BM25-ranked and appended to the submitted prompt text. Retrieval and the session-start index prefer a semantic summary over its presentation for the same `session-id`; deduplication and factual-evidence exclusion happen before the retrieval candidate budget.
- **Write-path guard** — supported direct native mutations are checked for closed history, provenance and secret-like patterns. This does not protect arbitrary shell or external filesystem writes.
- **Factual checkpoints** — captured evidence is persisted without an LLM through supported lifecycle hooks and recovery. Optional explicit `session-chronicle` enrichment adds a separate semantic summary. See each adapter's activation gates.
- **Explicit memory tools** — `memory_find`, `memory_recall`, `memory_backlinks`, `memory_audit`, `memory_session_context`.

The shared Python/Bash implementation remains in `skill/session-chronicle/scripts/`
for source compatibility. Packaging places the runtime under `core/`; native
translation lives under `adapters/<harness>/`, and neutral workflow sources under
`skills/<skill-id>/`. The versioned `chronicle.py` process protocol uses operations
and trusted adapter context. Legacy command-hook stdin wrappers are compatibility
entrypoints, not proof that those hooks work unchanged on every harness.

Chronicle owns its core, schemas, resources and adapters. UAT owns dependency
resolution, compilation, configuration ownership, deployment transactions and
qualification. Chronicle does not copy its implementation into UAT or run a
continuously running orchestration service.

## Requirements

- Python 3.11+ (`python3`, shared runtime uses the standard library) and `bash` on `PATH`.
- A local POSIX filesystem supporting `flock`, hard links, atomic rename and directory `fsync`, with cooperating writers. Linux fixture tests do not certify macOS/WSL.
- Target-specific native APIs and actual permissions; see the adapter READMEs and capability matrix.
- Bun and TypeScript for development; UAT's own pinned Python environment for real package integration tests.

Reference targets are OpenCode 2.0.26, Claude Code 2.1.299, Codex CLI 0.162.1 and
Pi 1.2.0. Installed probes found OpenCode 2.0.29 and Claude 2.1.220, with Codex/Pi
absent. These are separate facts, not a tested compatibility range. See
`docs/verification.md` for static/fixture results and remaining native checks.

## Package and activation

Use the allowlisted, reproducible local-package/archive workflow in
[package-consumption.md](docs/package-consumption.md). Loading the raw checkout
with UAT is unsuitable: its resource loader recursively includes files regardless
of Git ignore rules. The release stage contains physical code/resources and no
project journal, pending batches, credentials or sibling-checkout dependencies.

UAT adapter files are copied as bytes. They do not receive template expansion or
arbitrary settings merging. Chronicle does not overwrite UAT's generated settings,
relax unknown-tool restrictions or self-declare capabilities verified. Required
unsupported guarantees remain deployment blockers. Native skill invocation supplies
the portable workflow entrypoints; redundant commands are not required.

The standalone OpenCode compatibility installer is `scripts/install-local.sh`.
It installs the legacy native skill/command surface and the current OpenCode source
adapter; it is a separate deployment owner and must not replace a UAT-managed
workspace. Running it changes configuration and needs explicit authorization.
Source packaging and inspection rendering do not imply installation or activation.

OpenCode's V2 host supplies runtime instances of public `@opencode/plugin` and
`effect` entrypoints. Do not bundle another Effect instance. Pi and command-hook
requirements are described beside their respective adapters.

Add the draft buffer to the target project's `.gitignore`:

```
docs/.drafts/
```

## Where memory lives (`docs-root`)

All paths are rooted at `<project>/<docs-root>`:

| Path | Content |
|---|---|
| `<docs-root>/sessions/*.md` | one mutable `record-kind: session-presentation` per captured session, optional semantic summaries, and immutable factual-evidence batches |
| `<docs-root>/topics/*.md` | atomic ideas, annotated structure notes, and retained redirects |
| `<docs-root>/reports/session-chronicle-refactor-<run-id>/` | explicit refactoring coverage/report and original-topic snapshots; excluded from retrieval |
| `<docs-root>/.drafts/*.draft.jsonl` | durable, uncommitted capture buffers; never age-pruned |
| `<docs-root>/.drafts/pending/*.jsonl` | sealed batches awaiting publication or acknowledgement |
| `<docs-root>/continuations/*.json` | sourced links between distinct qualified sessions; shared-core API, native entrypoints pending |

`docs-root` defaults to `docs` and is overridable via a `docs-root:` field in the project instruction file's YAML frontmatter. `AGENTS.md` is read first and `CLAUDE.md` second. Scripts and the TypeScript adapter use `skill/session-chronicle/scripts/_docsroot.py` as the shared boundary-validating resolver; an invalid declaration never silently falls back to `docs`.

The `CLAUDE.md` fallback is this plugin's path-resolution behavior, not OpenCode V2 instruction discovery. Put agent instructions in `AGENTS.md`.

> ⚠ **A valid but incorrect `docs-root` can hide existing memory.** Removing its declaration can redirect future capture to the default root. The session-start index diagnoses an empty root when a chronicle exists elsewhere in the project. Invalid or escaping roots instead disable passive prompt processing and fail closed for guarded writes; explicit memory operations report errors. Check the configured root by hand:
>
> ```bash
> python3 .opencode/skills/session-chronicle/scripts/_docsroot.py --check .
> ```
>
> Silence means the resolution is sound.

## Native adapters

| Adapter | Native surface | Integration boundary |
|---|---|---|
| `adapters/opencode/` | V2 session/tool hooks and five registered memory tools | Trusted session location/parent; original prompt provenance and UAT tool policy require qualification |
| `adapters/claude-code/` | Native command-hook translation | Per-event fields and build gates; UAT hook composition and custom-tool discovery remain explicit dependencies |
| `adapters/codex/` | Native command-hook translation | Missing actor/success provenance cannot become journal evidence; trusted memory-tool invocation needs a supported transport |
| `adapters/pi/` | Native extension/tool registration | Read tools use session manager/cwd; unknown role and missing stable prompt IDs block capture/enrichment |

Adapters normalize operations before calling the shared core. No adapter may use
model-supplied current-session IDs, a latest-session file or another project's
directory. Guards and capture have different scopes: children are excluded from
journaling, but intercepted protected mutations still require validation. See the
capability matrix for each unavailable or unverified workflow.

## Tools

| Tool | Args | Does |
|---|---|---|
| `memory_find` | `query`, `includeEvidence?` | BM25 search over semantic sessions + topics; explicitly set `includeEvidence: true` to include factual records |
| `memory_recall` | `slug`, `scope?` (`all\|topic\|sessions`) | canonical topic note + supporting session-note IDs (filename stems), including source provenance |
| `memory_backlinks` | `slug` | supporting session-note IDs via wikilinks/provenance, resolving aliases and redirects; these are not SDK session IDs |
| `memory_audit` | `mode` (`orphans\|dups\|dangling\|stale\|candidates\|quality`) | memory health report, JSON; quality findings are structural and require semantic review |
| `memory_session_context` | `{}` | obtains native trusted identity/workspace, checkpoints, and resolves the current semantic-summary target and sources; requires mutation permission |

`memory_session_context` returns `{session_id, presentation, semantic_summary, target, sources}`: paths are project-relative, `presentation` and `semantic_summary` may be `null`, and `sources` contains factual batch IDs. Session identity comes only from SDK context, never model arguments. A closed summary or duplicate summaries cause an error.

Automatic injection and successful `memory_find`/`memory_recall` results delimit persisted note text as untrusted reference data, not instructions. These labels aid model interpretation; they are not a security boundary against prompt injection.

Permissions remain native and UAT-owned. Current UAT mappings cannot express all
five custom tools; do not use a wildcard permission or a shell fallback to defeat
that gate. A rendered skill is not proof that its required tool is available.

## Tunables (environment)

| Variable | Default | Meaning |
|---|---|---|
| `MEMORY_INJECT_BUDGET_CHARS` | `6000` | retrieval injection budget (~1500 tokens) |
| `MEMORY_INJECT_TOPK` | `3` | max notes injected per prompt |
| `MEMORY_INJECT_MAX_SCAN` | `60` | newest-first eligible candidate cap; automatic retrieval excludes factual records before counting. File discovery/header classification are not bounded by this cap. |
| `SESSION_CHRONICLE_CAPTURE_PROMPTS` | `1` | set to `0`, `false`, `no`, or `off` to disable future prompt capture independently |
| `SESSION_CHRONICLE_CAPTURE_BASH` | `1` | set to `0`, `false`, `no`, or `off` to disable future Bash command capture independently |
| `MEMORY_HEALTH_STALE_MAX` / `MEMORY_HEALTH_DANGLING_MAX` | `5` / `10` | thresholds for the index health line |
| `MEMORY_TOPIC_REVIEW_WORDS` | `300` | topic-body length review warning; never truncates or rejects an otherwise valid long idea |
| `MEMORY_INDEX_MAX_TOPICS` | `40` | topic entries shown in the startup orientation index; omitted count is reported |

## Privacy controls

**Captured evidence becomes durable files under `<docs-root>/sessions/` and may be committed, shared, or explicitly read by a model.** Ignoring `.drafts/` does not ignore published evidence. Exclusion from automatic retrieval is not a storage or confidentiality guarantee.

Set `SESSION_CHRONICLE_CAPTURE_PROMPTS=0` and/or `SESSION_CHRONICLE_CAPTURE_BASH=0` in the adapter process environment to opt out of those capture channels. Eligible file-operation capture remains enabled. These controls only affect future capture: existing drafts and pending batches remain recoverable, and existing notes are not deleted. Review storage/sharing policy and existing records before enabling capture for sensitive projects.

Known GitHub/API/AWS/Slack token patterns, private-key headers, and non-loopback IPv4 addresses are redacted heuristically before durable capture and before presentation excerpts are bounded. This is **not comprehensive redaction**: arbitrary passwords, credentials, private-key bodies, personal information, file paths, and unknown token formats may remain. Prefer disabling the relevant capture channel when its inputs may be sensitive.

## The bundled skills

Optional semantic workflows ship as three UAT-neutral definitions under `skills/`.
The singular `skill/` tree retains standalone OpenCode compatibility definitions.
Native invocation/discovery and permissions remain adapter-specific:

| Skill | Role | When it runs |
|---|---|---|
| `session-chronicle` | **Optional enrichment.** Uses trusted tool targeting to write one separate semantic summary per session ID, with source batch IDs, wikilinks, affected-topic refresh and recurring-subject materialisation. Never edits presentations, evidence, pending batches, or drafts. | Explicit native skill invocation or explicit enrichment request. |
| `session-chronicle-bootstrap` | **Backfill.** Seeds the journal and the first topic notes from a project's pre-existing history (specs, plans, decisions, STATUS, git log). | Exactly once per project, on explicit request. |
| `session-chronicle-refactor` | **Full topic maintenance.** Reviews the complete topic/session inventory; refines ideas, splits compound notes, merges duplicates and preserves provenance and historical addresses. `--dry-run` reviews without writes; `--resume <report-path>` continues an interrupted workflow. | Explicit command or explicit full topic-refactoring request. |

Bootstrap and refactoring depend on the shared chronicle skill's templates,
research and helper resources. UAT resolves explicit dependencies; merely loading
a package does not select every skill. Missing dependencies or required guarded
tools stop the workflow rather than producing an invented note shape.

The legacy standalone surface retains matching command shims under `command/`.
The portable package uses native skill invocation and does not require redundant
commands. Neither skills nor commands are needed for deterministic factual persistence.

Chronicle does not dispatch semantic work automatically or select a model. Explicit
enrichment uses the active harness's normal model and permissions; failure or refusal
leaves factual records intact. On OpenCode headless runs, explicitly request skill
loading: V2 does not support `opencode run --command`, and slash-prefixed prompt
text is not command dispatch. Other harnesses use their native skill entrypoint.

Enrichment requires `memory_session_context({})`. If the tool is unavailable, denied, fails, or returns empty sources, the agent stops without writes; guessed IDs and model-supplied direct-script fallbacks are forbidden. Mixed batches contribute only records whose `session_id`/`sessionID` matches the exact returned ID, and summaries cite only batch IDs actually used. No matching records means no writes.

Only the returned matching open semantic summary may be updated, or the returned new target created. Existing summaries keep their target across midnight; new targets use `session--<sha256(ID)>--summary.md`. `id` equals the target stem, `session-id` is the exact tool ID, and `id`, `session-id`, `started`, `date`, and target remain stable on updates. Presentations and immutable evidence remain separately stored; enrichment never replaces either.

An end-of-session signal alone never triggers enrichment. Only an explicit enrichment request that also asks for closure closes the current summary; a closed summary cannot be reopened or replaced. Duplicate summaries cause a stop, not automatic repair or unrelated closes. These are workflow instructions; skill `allowed-tools` metadata grants no runtime permissions.

## Atomic topic memory and Zettelkasten

Topic notes express **one independently reusable idea**, with enough explanation
and qualification to stand alone. A short paragraph listing several mechanisms
can still need splitting; a longer argument can remain one coherent note. Length
warnings are review heuristics, not methodological compliance checks.

Newly authored topics retain `type: topic` and add `note-kind`:

- **`atomic`** — a specific claim, concept, argument, decision/rationale or mechanism.
- **`structure`** — a brief, annotated route through related notes.
- **`redirect`** — an old address retained after merging, with `redirects-to` pointing
  to the canonical idea. Redirects are not injected as current knowledge.

The shared [atomic-topic contract](skill/session-chronicle/references/atomic-topic-contract.md)
requires concrete source references, source/section citations beside claims, and
contextual links explaining the relationships. Legacy notes without `note-kind`
remain readable and are upgraded when reviewed. A broad note split into several
ideas keeps its original slug as a structure note; old session references still
lead somewhere meaningful. Extracted notes inherit the supporting source paths.

Routine enrichment refreshes affected existing topics before considering new
materialisation candidates. Recurrence counts distinct sessions rather than files;
quoted factual records do not count as topic mentions. The two-session threshold
is a noise-control policy. Explicit refactoring may extract a useful idea from a
single supporting source without requiring its new slug to exist historically.

### Refactor an existing collection

After installing the bundled command and skill:

```text
/session-chronicle-refactor --dry-run
/session-chronicle-refactor
/session-chronicle-refactor --resume docs/reports/session-chronicle-refactor-<run-id>/report.md
```

The workflow inventories the full corpus rather than relying on capped retrieval.
It reads all topics and logical session views in batches, checks supporting
evidence, and records coverage and unresolved claims. Before replacing a topic it
saves the original under the run report directory. Destinations are written before
links and redirects; session history is preserved. Hashes recorded in the report
support conflict checking and resumption. Publication is ordered and resumable,
not a multi-file atomic transaction. The agent must have ordinary write permissions.
It uses guarded write/edit tools or the native patch tool's complete-topic subset;
partial topic patches, deletions, moves and mixed topic/source patches are rejected.
The topic patch subset uses LF-only UTF-8 and rejects symlink/hard-linked update
targets; an original without a final newline requires `*** End of File`.
Resumption accepts only a run report inside the current project's report directory,
checks its ledger and hashes, and revalidates pending decisions against current sources.

The refactoring workflow's `--dry-run` makes no note or report edits; the plugin's
normal passive journaling still operates. In apply mode the final report gives
old-to-new mappings, corrections, deferred findings and validation results. A run
can complete with explicitly unresolved factual questions; inaccessible or
unreviewed material is reported as partial coverage rather than silently skipped.

The deterministic helpers are also available independently (paths below assume a
project-local skill install):

```bash
python3 .opencode/skills/session-chronicle/scripts/topic-maintenance.py inventory --project "$PWD"
python3 .opencode/skills/session-chronicle/scripts/topic-maintenance.py validate --project "$PWD"
python3 .opencode/skills/session-chronicle/scripts/memory-audit.py --quality --base docs --json
```

Use the project's declared `docs-root` in place of `docs` for the audit command.
Inventory reports content hashes and sources without a top-k limit. Validation
checks structure and references; `memory_audit` with `mode: quality` exposes the
same class of findings to the agent. None of these checks establishes that a claim
is true or that its idea is atomic: those require semantic review of the sources.

Recall/backlinks retain file-addressable note IDs: read
`<docs-root>/sessions/<returned-id>.md` for the source. These differ from the stable
SDK `session-id`, which is used to group representations when counting recurrence.

The [research notes](skill/session-chronicle/references/zettelkasten-method.md)
document the basis and the plugin-specific adaptations: Schmidt's account of
Luhmann's stable addresses, linking and retained history (2018, §§4–7), Tietze's
separation-of-concerns formulation (2013, “Phase 3”), and Fast's distinction between
atomicity and brevity (“What is Atomicity?”, accessed 2026-10-15).

## Design notes

- **Native integration, no orchestrator daemon.** OpenCode registers tools with its V2 transform API; Pi uses native extension tools. Command-hook targets require their documented discovery/composition contracts. A one-shot worker is not a trusted current-session service for arbitrary callers.
- **Single writer and durable publication.** Capture and checkpoint processes share a project-local advisory `flock`. Under that lock, non-empty daily drafts (including old dates) are atomically renamed to UUID-named pending batches. A batch ID remains stable across retries. Every batch is published as immutable factual evidence and updates the one derived presentation for each unambiguous captured `sessionID`. Presentation filenames use a readable normalized ID fragment plus a hash; `session-id`, not title or filename, is the identity. A fully written, synced temporary note is hard-linked into its final name without overwriting history, then the sessions directory is synced. Only then is that specific pending batch removed and its directory synced. Appends wait for the lock and go into a new draft; no draft is truncated. Duplicate dispatches with no new evidence are no-ops.
- **Factual, not semantic.** Notes reuse the session schema and lint helpers. `record-kind: factual-evidence` has `batch-id` and `provenance: captured_signals`; it is immutable and may contain several sessions. `record-kind: session-presentation` is the updatable, derived view for one stable `session-id`; its deterministic title uses bounded safe words from the first prompt and upgrades a no-prompt fallback when a prompt later arrives. Titles can collide, so `session-id` remains the identity. Captured inputs are quoted as untrusted JSON; no outcomes, commits, decisions, or topics are inferred from commands or edits. Source session/event IDs are retained when provided.
- **Kind-specific validation.** Factual notes require a valid dated batch ID matching `id`/`date`, `type: session`, closed status, and `captured_signals` provenance. Semantic summaries and session presentations require non-empty `sources:` referencing existing valid factual batch IDs; presentations also require `session-id`. Generic legacy session notes without `record-kind` remain valid. Historical batches without a captured session ID are retained as factual evidence and are not migrated into a presentation.
- **Failure visibility.** Missing identity, invalid workspace and worker failures must be reported explicitly; pending evidence remains retryable. Guard infrastructure failure is not permission to write without validation. A post-write diagnostic cannot undo a completed native operation.
- **Recovery limits.** Guarantees cover successfully synced capture on a cooperating local filesystem, not events lost before capture, external draft edits, non-cooperating writers, network filesystems or disk corruption. Supported lifecycle checkpoints and explicit operator recovery retry pending evidence. A malformed batch or publication conflict stops publication and requires repair; evidence is not silently discarded. A killed process can leave ignored temporary files. Publication across evidence and derived views is resumable, not a multi-file transaction. Backlogs are processed synchronously.
- **Filtering and privacy limits.** Direct memory writes, explicit chronicle prompts and recognized maintenance invocations are excluded. Shell wrappers, interpreter options and compound commands are conservatively retained rather than guessed. Arbitrary shell commands that modify memory cannot reliably be classified. Original user-input provenance must be established before capture; running before this adapter's own injection does not prove another plugin has not already modified the text. Older draft data may contain secrets.
- **Replay versus checkpoint retries.** The new neutral capture protocol requires stable native event IDs and worktree-local durable duplicate checks. It does not collapse distinct events merely because their text matches. Legacy capture wrappers retain their weaker historical semantics; a successful checkpoint retry is not evidence of native delivery deduplication. Missing native event identity remains an adapter capability gap.
- **Maintenance-copy limit.** Direct maintenance exclusion recognizes the executing core's exact helper directory. Generated skill-resource copies are not silently trusted by matching filenames; their commands may still produce selective observations until a trusted installation mapping is defined. Use `-B` for Python maintenance to avoid configuration-tree bytecode caches.
- **Guarded topic patches.** The complete-topic preflight reconstructs proposed contents/graph and checks sources, links and secrets. It accepts complete additions and exact whole-file replacements; partial/mixed/move/delete protected mutations are rejected. Native syntax support belongs to each adapter. Preflight is not a transaction with native execution, and arbitrary shell/external writers remain outside the guard.
- **No mandatory semantic workflow.** Factual persistence needs neither command shims nor skills. Enrichment/bootstrap/refactor remain explicit workflows. Their consent, factual accuracy and semantic atomicity are not established by structural validation alone.

## Development

```bash
bun install
bun run typecheck
bun test
python3 scripts/lint-agents.py
python3 -m unittest discover -s skill/session-chronicle/scripts -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The structural linter needs PyYAML; UAT integration tests use its pinned environment
and real loader/compiler. See `docs/verification.md` for exact commands, counts and
blocked checks. Native qualification requires an authorized isolated installation,
exact runtime/artifact versions, real discovery, primary/child attribution,
negative permission probes, interactive/headless lifecycle and recovery behavior.
Do not run qualification against the live journal or fabricate attestations to
make UAT accept an unsupported capability.

## License

MIT
