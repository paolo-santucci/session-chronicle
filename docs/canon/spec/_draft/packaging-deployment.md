---
domain: packaging-deployment
last-updated: 2026-11-18
last-verified: 2026-11-18
---

# Packaging and Deployment

## Overview

The distribution contract for `session-chronicle` 0.2.1: a deterministic, allowlisted source package built from the checkout, plus a separate standalone OpenCode installer that installs a module, a plugin shim, and legacy skill/command definitions (`scripts/build-package.py`, `scripts/install-local.sh`). Chronicle owns its core, schemas, resources and adapters; the consuming integration layer (UAT) owns dependency resolution, rendering, configuration ownership, deployment transactions and qualification (`README.md:38-41`).

## Current behaviour

- **Builds a staged source package from an allowlist, not from the checkout.** The builder selects explicit documents, conventional license files, `schemas/*.json`, immediate core `.py`/`.sh`, immediate adapter `.ts`/`.mjs`/`.py`/`.json`, three `SKILL.md` files plus skill references, and the bootstrap scanner; every selected path must be a physical file, never a symlink including symlinked ancestors (`scripts/build-package.py:54-64`, `scripts/build-package.py:75-103`).
- **Deliberately excludes payload that is not release material.** The stage carries no project journal (`docs/sessions/`, `docs/topics/`), no draft or pending batches (`docs/.drafts/`), no credentials (`.env`, `*.pem`, `*.key`, credential/secret-named files), no sibling-checkout dependency, and no tests, hidden files, `__pycache__`, `node_modules`, `.uat` state, native session files, nested runtime directories or the legacy root `skill/` tree; `checkpoint-nudge.py` is excluded from both runtime and helper copies while its source is preserved (`scripts/build-package.py:67-72`, `scripts/build-package.py:85-99`, `scripts/install-local.sh:124`, `tests/test_portable_package.py:51-76`, `README.md:60-61`).
- **Refuses to overwrite anything.** An existing stage, a stage inside the source checkout, an existing archive, or an archive destination that is a symlink fails before writing; a failed archive removes its temporary file and stays retryable (`scripts/build-package.py:147-156`, `scripts/build-package.py:191-209`).
- **Publishes a byte-identical archive.** Sorted regular-file entries, fixed `0755`/`0644` modes by shebang, zero timestamps/UID/GID, empty owner names, gzip header with no filename and `mtime=0`, published by same-directory temporary file then a no-clobber hard link (`scripts/build-package.py:191-228`, `tests/test_portable_package.py:134-202`).
- **Reports exact identity and per-file digests.** stdout JSON carries `id`, `version`, a `source→sha256` file map, a `content_sha256` over that inventory, and `archive_sha256` when an archive was requested; archive consumers are told to pin the archive digest (`scripts/build-package.py:180-188`, `docs/package-consumption.md:97-102`).
- **Rewrites manifest runtime maps from the same inventory.** `--write-manifest` refreshes only `plugin.yaml`'s `adapters.*.files`; core sources are re-keyed to `core/*`, OpenCode/Pi `entry.ts` maps to the discoverable root `index.ts`, and core bytes are duplicated into `skills/session-chronicle/scripts/` (`scripts/build-package.py:106-134`, `scripts/build-package.py:142-144`, `scripts/build-package.py:166-170`).
- **Rejects a manifest that is not exactly this package.** Build fails unless the manifest declares `id`/`version` `session-chronicle`/`0.2.1` and exactly the four adapter keys (`scripts/build-package.py:126-131`).
- **Installs standalone only after proving UAT does not own the project.** The installer refuses when `.uat/deployments/opencode.json` exists, symlinks, or fails schema-version/harness/`replace_paths` validation — even with `--force` (`scripts/install-local.sh:48-66`, `tests/test_install_local.py:41-51`).
- **Requires `bun` and `python3`, verifies inputs, and resolves dependencies off-target.** It aborts without both tools, rejects symlinked release inputs and potential secrets, then runs `bun install --production --frozen-lockfile --ignore-scripts` inside the staged module so a failure leaves the target untouched (`scripts/install-local.sh:8-12`, `scripts/install-local.sh:118-131`).
- **Installs five surfaces and records them.** Module `.opencode/session-chronicle/`, shim `.opencode/plugins/session-chronicle.ts`, one `.opencode/skills/<name>` per bundled legacy skill, one `.opencode/commands/<name>.md` per bundled command, and a digest marker `.session-chronicle-install.json` (version 2) whose own bytes are excluded from the module digest (`scripts/install-local.sh:132-160`).
- **Protects local edits and rolls back on failure.** An unidentified or locally modified owned path needs explicit `--force`; replacement backs up each destination beside the target and restores in reverse order on error or `INT`/`TERM`, reporting `rollback incomplete` and retaining the backup when restoration itself fails (`scripts/install-local.sh:68-104`, `scripts/install-local.sh:162-212`, `tests/test_install_local.py:52-114`).
- **Mutates consuming configuration and requires authorization.** Running the installer changes workspace configuration and needs explicit authorization; it is a separate deployment owner from UAT and must not replace a UAT-managed workspace (`README.md:69-73`).
- **Building, inspecting or installing is not activation or qualification.** Package loading, artifact rendering and hook composition are supported by the package contract, while synchronization refuses unqualified required capabilities; no native compatibility, operational readiness, or activation is established by these steps (`docs/package-consumption.md:3-7`, `README.md:7-10`, `README.md:73`).

## Public contracts

- **Builder CLI**: `build-package.py [--source PATH] (--output PATH | --write-manifest) [--archive PATH]`; `--archive` requires `--output`; failures exit 1 with `Package build failed: <reason>` (`scripts/build-package.py:231-251`).
- **Build report JSON**: `{"id", "version", "files": {path: sha256}, "content_sha256", "archive_sha256"?}` (`scripts/build-package.py:180-188`).
- **Stage layout**: `plugin.yaml`, `README.md`, `schemas/*.json`, allowlisted `docs/`, `core/`, `adapters/{opencode,claude-code,codex,pi,shared}/`, `skills/{session-chronicle,session-chronicle-bootstrap,session-chronicle-refactor}/{SKILL.md,references/,scripts/}` (`docs/package-consumption.md:60-84`).
- **Manifest schema** (`plugin.yaml`, schema-version 1): `kind`, `id`, `version`, `requires{agents,skills,plugins}` (all empty), `capabilities{required,optional}`, and per adapter `{files, capabilities, hooks?, activation[]}` (`plugin.yaml:2-20`, `plugin.yaml:21-273`).
- **Two manifest key spaces**: the root manifest names physical legacy core sources; the staged manifest rewrites those source keys to `core/*` with identical destination paths (`docs/package-consumption.md:86-92`, `tests/test_portable_package.py:114-132`).
- **Installer CLI**: `install-local.sh <project-dir> [--force]` or `install-local.sh --global [--force]`; unknown flags and extra arguments are rejected, `<project-dir>` and `--global` are mutually exclusive (`scripts/install-local.sh:15-34`).
- **Ownership marker** `.opencode/session-chronicle/.session-chronicle-install.json`: `{"installer", "version": 2, "owned": {logical path: sha256}}`, with installer identity accepted from `session-chronicle` or the legacy `opencode-session-chronicle` (`scripts/install-local.sh:6-7`, `scripts/install-local.sh:68-98`, `scripts/install-local.sh:142-160`).
- **Consumed UAT deployment manifest**: `.uat/deployments/opencode.json` with `schema-version: 1`, `harness: "opencode"`, `replace_paths: [..]`; presence, symlink or malformed content blocks the standalone route (`scripts/install-local.sh:48-66`).
- **Preservation contract on separate exports**: session notes, topics, drafts, pending batches, continuations, `.uat` event times, native session files and other-harness settings must be byte-identical after a render/export (`tests/test_uat_package.py:351-374`).
- **npm package descriptor**: `name`/`version` `session-chronicle`/`0.2.1`, `main`/`exports` `./index.ts`, `files` list, dependency `@opencode/plugin@2.0.26`, peer `effect@4.0.0-rc.112` (`package.json:3-35`).

## Enumerated providers / limits

- **Adapters and package destinations** (`scripts/build-package.py:22-27`; `docs/package-consumption.md:176-183`): `opencode` → `.opencode/plugins/session-chronicle`; `claude-code` → `.claude/hooks/session-chronicle`; `codex` → `.codex/hooks/session-chronicle`; `pi` → `.pi/extensions/session-chronicle` (OpenCode and Pi additionally receive a root `index.ts`).
- **Neutral skills in the payload** (`scripts/build-package.py:21`): `session-chronicle`, `session-chronicle-bootstrap`, `session-chronicle-refactor`.
- **Standalone legacy surfaces** (`scripts/install-local.sh:10-11`, `scripts/install-local.sh:132-135`): every `skill/*` directory containing `SKILL.md`, and every `command/*.md` — currently `session-chronicle`, `session-chronicle-bootstrap`, `session-chronicle-refactor` skills and the matching three command files.
- **Required payload files** (`scripts/build-package.py:42-51`): `core/chronicle.py`, the bootstrap `scan-history.py`, and the four adapter entry modules; a missing one fails the build.
- **Declared capability set** (`plugin.yaml:12-19`): required `chronicle.capture`, `chronicle.retrieval`, `chronicle.session-context`, `chronicle.protected-history`; optional none.
- **Per-adapter capability status** (`plugin.yaml:54-59`, `plugin.yaml:96-101`, `plugin.yaml:138-143`, `plugin.yaml:264-269`): OpenCode capture `unsupported` / others `unverified`; Claude Code and Codex capture and session-context `unsupported`; Pi all four `unsupported`.
- **Codex hook registrations** (`plugin.yaml:144-227`): eight hooks — `SessionStart`, `PreToolUse` (`^apply_patch$`), `PostToolUse` (`^(apply_patch|Bash)$`), `UserPromptSubmit`, `Stop`, `PreCompact`, `Interrupt`, `SessionEnd` — all `owner: session-chronicle`, `order: 20`, `command: python3`; timeouts are `30` s except `Interrupt` and `SessionEnd` at `3` s (`tests/test_uat_package.py:131-134`).
- **Runtime baselines accepted as render inputs, not tested ranges** (`docs/package-consumption.md:142-144`): OpenCode `2.0.26`, Claude Code `2.1.299`, Codex CLI `0.163.0`, Pi `1.2.0`; package baseline Python 3.11+ (`README.md:45`, `docs/package-consumption.md:191`).
- **Marker and archive invariants**: marker version `2`; archive entries sorted, mode `0755`/`0644`, `mtime`/`uid`/`gid` zero, no symlinks or special files, no `..` components (`scripts/install-local.sh:7`, `scripts/build-package.py:212-228`, `tests/test_uat_package.py:333-341`).

## Cross-domain dependencies

- Packages the runtime that implements `capture`, `retrieval`, `session-context` and `protected-history` capabilities (`plugin.yaml:12-19`).
- Ships the `docs-root` boundary resolver (`core/_docsroot.py`) and requires docs roots not to overlap `.opencode`, `.claude`, `.codex`, `.pi`, `.agents` (`docs/package-consumption.md:254-261`).
- Ships memory-maintenance and retrieval scripts (`memory-audit.py`, `retrieve-inject.py`, `session-context.py`, `topic-maintenance.py`) into every adapter map (`plugin.yaml:38-52`).
- Depends on the external integration layer UAT for resolution, compilation, configuration ownership, deployment transactions and qualification (`README.md:38-41`, `docs/package-consumption.md:104-144`).
- Depends on native hosts: OpenCode `@opencode/plugin@2.0.26` and a host-supplied Effect instance, Pi `1.2.0` extensions including `typebox`, and a Git worktree for UAT Codex hook resolution (`package.json:31-41`, `README.md:75-77`, `docs/package-consumption.md:191-198`).
- Coordinates with sibling plugins in a roster: `status-inject`, `agent-statistics` (`docs/package-consumption.md:118-126`, `tests/test_uat_package.py:136-140`).
- Chronicles' memory artifacts (`docs/sessions`, `docs/topics`, `docs/.drafts`, `docs/continuations`) are explicitly *not* payload, but are the state an installation must preserve (`docs/package-consumption.md:254-261`, `tests/test_uat_package.py:351-357`).

## Gaps

1. `plugin.yaml` is both hand-authored and generated: `--write-manifest` rewrites only `adapters.*.files` while capabilities, hooks and activation stay authored, and the file must remain strict JSON because it is read with `json.loads` (`scripts/build-package.py:127-139`) — whether any other field is regenerated, and whether a `.yaml` name over JSON content is intended, is unstated.
2. The payload ships `docs/portability-plan.md` (`scripts/build-package.py:33`) but the consumption doc's enumeration of bundled docs omits it (`docs/package-consumption.md:49`) — the two lists of the same payload disagree, and the omitted document is described elsewhere as architecture and milestones (`README.md:14`).
3. The standalone installer copies all four adapter trees into `.opencode/session-chronicle/` but wires only the OpenCode shim and entry (`scripts/install-local.sh:120`, `scripts/install-local.sh:133`) — whether the Claude/Codex/Pi bytes in a standalone install are intended-usable or inert cargo is unclassified.
4. Legacy `skill/` and `command/` sources install to `.opencode/skills` and `.opencode/commands`, while the package ships neutral `skills/` — two parallel skill trees with no in-scope check that their content agrees (`scripts/install-local.sh:10-11`, `scripts/build-package.py:93-99`).
5. `--global` skips the UAT ownership guard entirely (`scripts/install-local.sh:53`), so the documented "must not replace a UAT-managed workspace" boundary is enforced only for project-scoped installs; whether XDG-global installs are considered outside that boundary is not stated.
6. `package.json` declares publishable `files`/`exports` (`package.json:7-22`) while the project states no portable bundle has been deployed or published (`README.md:10`) — no publish path exists in scope, so whether npm publication is shipped or aspirational cannot be decided from this code.
