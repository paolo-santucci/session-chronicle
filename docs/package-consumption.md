# Consuming the portable Chronicle package

`session-chronicle` **0.2.0** is a schema-v1 UAT source package with exactly four
adapters: `opencode`, `claude-code`, `codex`, and `pi`. Loading and inspection
rendering are supported by the package contract; **synchronization currently
refuses its required capabilities**. No native compatibility or operational
readiness is established by these packaging tests.

Sources checked on 2026-10-15: this repository's [`plugin.yaml`](../plugin.yaml),
[`scripts/build-package.py`](../scripts/build-package.py), and the read-only UAT
checkout's `docs/design.md` §Portable plugins, `docs/implementation-contract.md`
§Neutral source v1 / Compiler → adapters, `docs/adapter-contracts.md` §Python
interface and evidence / Native artifacts and ownership, and
`docs/qualification.md` §Qualification and evidence. UAT source paths below are
relative to that checkout; they are references for maintainers, not package-time
dependencies on a sibling directory.

## Build a local source package

Do not pass the working checkout to `add_package` or `--plugin-package`. UAT
`uat/packages.py:add_package` recursively reads plugin resources using
`uat/definitions.py:read_resources`, which rejects symlinks and includes unrelated
files. Build a clean, deterministic stage first:

```sh
python3 -B scripts/build-package.py --write-manifest
python3 -B scripts/build-package.py \
  --output /tmp/opencode/chronicle-0.2.0-stage \
  --archive /tmp/opencode/chronicle-0.2.0.tar.gz
```

Choose new output paths on subsequent runs. The builder refuses existing stages
and archives (including symlinks) and stages inside the source checkout. Archives
are finalized and synced in a same-directory temporary file, then atomically
published using a no-clobber hard link on the supported local POSIX filesystem.
A failed archive build removes its temporary file and leaves the output absent
and retryable; a competing publisher's output is preserved. `--write-manifest` refreshes
only the root manifest's runtime file maps after adapter/core files have landed;
the build regenerates the staged maps from the same inventory. JSON serialization
in `plugin.yaml` is valid YAML and avoids a PyYAML build dependency.

The allowlist consists of immediate production `.py`/`.sh` core files, immediate
`.ts`/`.mjs`/`.py`/`.json` files under the four adapter directories and
`adapters/shared`, the three `skills/<id>/SKILL.md` files, immediate physical
`.md`/`.txt`/`.json` skill references, and the explicit neutral bootstrap
`scripts/scan-history.py` source. The builder also copies the same core bytes into
`skills/session-chronicle/scripts/` for neutral maintenance-script bindings.
The bundle includes physical `schemas/*.json`, the root and four adapter READMEs,
and `docs/{package-consumption,runtime-contracts,legacy-data,capability-matrix,uat-integration-request,verification}.md`.
An existing conventional LICENSE/COPYING file is included; no license is invented.
These instructions and schemas are bundle resources, not executable runtime maps.
The obsolete `checkpoint-nudge.py` is excluded from both runtime and skill helper
copies; its legacy source is preserved. Test modules, hidden files, nested runtime
directories, repository metadata, credentials, installed dependencies, and project
memory are excluded. Selected symlinks, including symlinked ancestors, fail the
build. References must be physical copies within the neutral skill directories.
This is a source-directory/suffix allowlist: maintainers must review new production
files added to those directories before releasing.

The package has this layout:

```text
plugin.yaml
README.md
schemas/                      # physical package-owned JSON schemas
docs/                         # allowlisted consumption and runtime contracts
core/                         # copied from skill/session-chronicle/scripts
  chronicle.py
  _docsroot.py
  ...                         # production Python and shell helpers only
adapters/
  opencode/                   # index.ts, entry.ts, README.md
  claude-code/                # hook.py, README.md; inert registration fragment
  codex/                      # hook.py, README.md; inert registration fragment
  pi/                         # index.ts, entry.ts, README.md
  shared/                     # physical supporting runtime modules
skills/
  session-chronicle/SKILL.md
  session-chronicle-bootstrap/SKILL.md
  session-chronicle-refactor/SKILL.md
  .../references/
  session-chronicle/scripts/    # generated physical copies of the shared core
  session-chronicle-bootstrap/scripts/scan-history.py
```

The legacy root `index.ts` shim, tests, build script, and working memory are not
package runtime inputs. The root manifest names physical legacy core source paths;
the staged manifest rewrites those **source keys** to `core/*`. Destination paths
are identical. Adapter modules retain their location beneath `adapters/<target>`
so `../../core/chronicle.py` resolves after rendering. OpenCode/Pi `entry.ts` files
map to the package's discoverable root `index.ts`; they must re-export
`./adapters/<target>/index.ts` there. Native artifacts are copied as bytes, without
portable-binding expansion (`uat/packages.py:apply_package_artifacts`). Neutral
skill bodies/textual resources do receive UAT bindings
(`uat/adapters/common.py:Artifacts.skills`, `auxiliary`, `bind`).

Build stdout reports the identity, exact version, per-file SHA-256 values, a
content-inventory SHA-256, and, when requested, `archive_sha256`. Pin the **archive**
digest when consuming an archive. The archive contains `plugin.yaml` at its root,
sorted regular-file entries, fixed modes, zero timestamps/UID/GID, empty owner
names, and a gzip header with no filename and timestamp zero
(`build-package.py:archive_package`).

## Load, select, and inspect through UAT

Add the staged package to a library using UAT's actual loader:

```python
from pathlib import Path
from uat.definitions import Library
from uat.packages import add_package

library = Library(Path("/path/to/neutral-library"))
resolved_package = add_package(library, Path("/tmp/opencode/chronicle-0.2.0-stage"))
```

Loading makes definitions available; roster selection activates dependency
resolution. A roster can select `plugins: [session-chronicle, status-inject]` and
`skills: [session-chronicle-bootstrap, session-chronicle-refactor]` alongside its
existing selections. Both workflows pull in the base `session-chronicle` skill;
the skills require the runtime plugin. Selecting only the plugin does not select
semantic workflows. The plugin must not require its dependent skills back:
UAT rejects dependency cycles, duplicate
identities, missing references and contradictory exclusions
(`uat/resolution.py:resolve`, `uat/definitions.py:Library.add`). Statistics adds
the `agent-statistics` plugin by default. This package does not choose models:
use an existing explicitly configured UAT model profile and native bindings.

For example, with an operator-provided library, roster and profile:

```sh
uat render --library /path/to/neutral-library \
  --plugin-package /tmp/opencode/chronicle-0.2.0-stage \
  --roster YOUR_ROSTER --profile YOUR_PROFILE \
  --harness opencode --harness-version 2.0.26 \
  --workspace /path/to/disposable-workspace \
  --output /tmp/opencode/chronicle-opencode-inspection
```

`render` exports into an empty output directory; it does not install into the
workspace (`uat/cli.py:_compile`, `uat/deployment.py:export_artifacts`). The UAT
reference baselines inspected are OpenCode `2.0.26`, Claude Code `2.1.299`, Codex
`0.162.1`, and Pi `1.2.0`; these are accepted render inputs, **not tested native
compatibility ranges** (`uat/adapters/common.py:BASELINES`).

## Pinned archive consumption

The tests exercise a real local archive with UAT's `unpack_package`, exact digest,
and exact version, then load the extracted package. For a locally built archive:

```python
from pathlib import Path
from uat.packages import unpack_package

archive = Path("/tmp/opencode/chronicle-0.2.0.tar.gz")
lock = unpack_package(
    archive.read_bytes(),
    "COPY_THE_EXACT_archive_sha256_FROM_BUILD_OUTPUT",
    "0.2.0",
    Path("/tmp/opencode/chronicle-0.2.0-unpacked"),
)
```

The placeholder is deliberately not a valid digest; replace it with the actual
pin. UAT validates digest and manifest version, rejects links/special files and
unsafe paths, and adds `uat-package-lock.json`
(`uat/packages.py:unpack_package`, `_unpack`). That lock is another resource read
by `add_package`, so extracted-package revisions/fingerprints can differ from the
unlocked local stage even when shipped runtime bytes match. Qualify the exact
consumption form. No remote release URL is asserted here. If a release is
published later, UAT `fetch-package` requires its actual HTTPS URL, exact version,
and lowercase SHA-256; tests do not simulate a published download.

## Ownership, activation, and current blockers

Chronicle's runtime mappings are confined to these package-owned subtrees:

| Target | Runtime destination |
| --- | --- |
| OpenCode | `.opencode/plugins/session-chronicle/{core,adapters}` plus `index.ts` |
| Claude Code | `.claude/hooks/session-chronicle/{core,adapters}` |
| Codex | `.codex/hooks/session-chronicle/{core,adapters}` |
| Pi | `.pi/extensions/session-chronicle/{core,adapters}` plus `index.ts` |

UAT independently renders neutral skills into its native per-target skill paths.
UAT's renderer also declares broader selected-harness replacement surfaces, so the
package-owned maps alone are not a promise to preserve local edits within those
surfaces. Inspect the complete `replace_paths` report before any separately
authorized installation (`uat/deployment.py:SURFACES`, `validate_output`).

The documented Python baseline is 3.11+ for the package and UAT integration.
Other prerequisites are native host dependencies for
TypeScript adapters (including Pi's `typebox` import), and the installed `uat` CLI
for UAT status/statistics. UAT's Codex hooks additionally require a Git worktree.
OpenCode must restart its server; Pi must trust/reload its extension. Claude/Codex
require native project/hook trust. These are activation requirements, not actions
performed by this builder (root manifest activation fields; UAT
`docs/adapter-contracts.md` §Status and telemetry implementation).

Claude/Codex Chronicle hook scripts are shipped but **not registered by UAT**.
Any registration JSON shipped under the package subtree is inert. UAT owns
`.claude/settings.json` and `.codex/hooks.json`; a package mapping to either would
collide rather than merge. The toolkit needs explicit Chronicle hook composition
that preserves status/statistics wiring. There is no arbitrary JSON-fragment
merge or native-artifact templating in this package. Export inspection confirms
UAT's own hooks survive and does not claim Chronicle's hooks run.

The package also declares known native gaps independently of toolkit integration.
Its aggregate required capabilities currently have these statuses
(`plugin.yaml` adapter capabilities/activation; packaged `docs/capability-matrix.md`):

| Adapter | Capture | Retrieval | Session context | Protected history |
| --- | --- | --- | --- | --- |
| OpenCode | unsupported | unverified | unverified | unverified |
| Claude Code | unsupported | unverified | unsupported | unverified |
| Codex | unsupported | unverified | unsupported | unverified |
| Pi | unsupported | unsupported | unsupported | unsupported |

These statuses concern the complete required guarantees, not the absence of code.
Selective tool observation is implemented, but complete original-user prompt
capture lacks the necessary provenance contracts on all four adapters.
Claude/Codex session context lacks trusted custom-tool transport; Pi also lacks
trusted actor/event provenance for session enrichment. Pi's explicit read tools
and selective deny-only guards are partial implementations: automatic capture and
retrieval injection and positive valid protected mutations remain unavailable.
OpenCode retrieval/context/history and Claude/Codex retrieval/history stay
unverified, rather than being claimed qualified. Native contract details and
partial coverage are documented in the bundled adapter READMEs and runtime
contracts. Fixing toolkit integration alone does not close these gaps; known
unsupported requirements remain unsupported until their native guarantees exist.

There is a separate UAT renderer blocker. In the inspected implementation,
`uat/adapters/common.py:Artifacts.finish` recognizes only its built-in plugin
allowlist and sets external plugins' **required capabilities to `unsupported`**.
`uat/packages.py:apply_package_artifacts` cannot promote an existing unsupported
capability using a package's `unverified` declaration. A targeted integration test
uses an inert synthetic external capability declared `unverified` to reproduce
this behavior without weakening Chronicle's production declarations. Consequently all four
targets retain required blockers for:

- `chronicle.capture`
- `chronicle.retrieval`
- `chronicle.session-context`
- `chronicle.protected-history`

UAT `compatibility_report`/`install` refuse these requirements. Unsupported
capabilities cannot be promoted by qualification attestations. Required
capabilities remain required; tests never remove them or manufacture passing
evidence. Native implementation gaps, toolkit integration, and genuine
exact-artifact qualification are separate gates. `statistics.capture`, `status.context`, skill
operations and agent permission requirements may add further blockers.

UAT's neutral policy enum also has no `memory.*` operation: do not invent policy
bindings for Chronicle tools (`uat/schemas/definition.json`, `policy.rules`).
Protected-history guards describe only implemented hook/tool coverage; they do
not establish shell, delegation, hosted-tool, or hostile-extension containment.

Memory belongs outside replaceable configuration. The packaged `_docsroot.py`
rejects docs roots overlapping `.opencode`, `.claude`, `.codex`, `.pi`, or
`.agents`. Tests preserve session notes, topics, drafts, pending batches,
continuations, native session files and other-harness settings during separate
inspection exports. This proves read-only rendering behavior and overlap
rejection, **not successful deployment preservation**.

## Reproduce integration checks

```sh
python3 -B -m unittest discover -s tests -p 'test_portable_package.py' -v
UAT_ROOT=../universal-agentic-toolkit \
  ../universal-agentic-toolkit/.venv/bin/python -B \
  -m unittest discover -s tests -p 'test_uat_package.py' -v
```

UAT is optional for the repository's dependency-free suite. Integration tests skip
with an explicit reason if neither `UAT_ROOT` nor the sibling supplies UAT, or if
PyYAML/jsonschema are unavailable. The sibling virtualenv supplies these packages;
`-B` prevents bytecode writes into the read-only dependency. All fixture/build/
export workspaces are disposable, under `/tmp/opencode` when available.

The integration suite uses the real `add_package`, resolver, compiler, four
renderers, capability reporter, export path and pinned archive unpacker. It checks
selection, cycles, exclusions, collisions, byte-exact native resources,
fingerprint changes, missing requirements, the external-plugin blocker, and
refusal before any installation writes. Fixture model bindings are explicitly
inert `fixture/inert` strings needed only by the render contract. Tests launch no
model, select no real model, deploy no configuration, and supply no qualification
or operational evidence.
