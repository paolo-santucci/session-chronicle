# Test Coverage Review — retrieval integrity & performance (pre-implementation)

**Method:** static review of all 15 test modules (the brief said 23 script files; there are **8** in `skill/session-chronicle/scripts/` and **7** in `tests/`). Suites could **not** be executed: `shell` is denied for this agent. Per-file test counts and the baseline below are derived statically and validated against the last recorded green run in `docs/verification.md:16-44,104-105` (which reports exactly 119 / 186).

**Summary:** The suite is unusually strong on write-boundary, no-mutation and provenance invariants, and it already pins the three retrieval ordering invariants the feature is most likely to break. Against the eight planned changes it is *asymmetric*: changes 3 and 4 are heavily constrained, changes 2, 5, 6, 7, 8 have **no positive test at all**, and change 1's core claim ("injected text never enters evidence") is asserted nowhere. The suite also silently loses 17 tests to one module-level import error, so a green run today is weaker evidence than it looks.

## Current baseline

| Suite | Collected (static count) | Last documented green | Expected now |
|---|---|---|---|
| `skill/session-chronicle/scripts` (8 files) | **127** | 119 (`docs/verification.md:37`) | 127 pass, 0 skip |
| `tests` (7 files) | **186** | 186 (`docs/verification.md:105`) | **149 pass, 20 skip, 17 never collected** |

Per-file: scripts — checkpoint 19, chronicle_doctor 7, memory_contracts 17, session_context 12, topic_graph 27, topic_patch 22, topic_review 13, write_boundaries 10. tests — install_local 10, lint_agents 21, native_hooks 44, neutral_workflows 17, portable_core 60, portable_package 14, uat_package 20.

**Known pre-existing failure (confirmed by reading, not running):** `tests/test_neutral_workflows.py:36-47` inserts `UAT_ROOT` on `sys.path`, then imports `uat.adapters.common`. The `except ModuleNotFoundError` re-raises unless `error.name` is in `{"uat","yaml","jsonschema"}`; for a missing submodule the name is `"uat.adapters"`, so it propagates. This is a **module-level** failure, so all **17** tests in the file error as a single `_FailedTest` and never appear individually.
**Skips:** `test_neutral_workflows.py:93` (1, unreachable today), `tests/test_uat_package.py:77` (20, gated on `UAT_ROOT/uat/packages.py` existing — correct pattern), `tests/test_native_hooks.py:359` (15 RealCoreTests, skip only if `chronicle.py` missing → runs).

## 1. Change-by-change test mapping

| # | Change | Already constrained by | Breaks if | Untested |
|---|---|---|---|---|
| 1 | capture write filter for injected markers | `memory_contracts:197,210,223`; `checkpoint:198`; `portable_core:297,305` | filter applied as an early `return` → `memory_contracts:231` reads `records()[-1]` | **yes** — no test that evidence lacks injected text |
| 2 | early empty-query return | indirect only (`portable_core:776` empty *result*) | early return placed before `resolve_base` → invalid docs-root silently succeeds (no test) | **yes** — no zero-I/O assertion |
| 3 | frontmatter memoisation | `topic_review:152,165,178,189`; `_session_notes.py:30` comment is a hard rule | any module-level cache → `topic_review:178` fails (3 in-process rewrites) | **yes** — frontmatter open count in retrieval |
| 4 | single `realpath(base)` | `portable_core:349,776`; `topic_graph:239` (symlink escape) | per-file symlink check dropped → both portable tests fail | **yes** — no test that base is resolved once |
| 5 | provenance line (count + updated) | exact-empty asserts: `memory_contracts:87`, `write_boundaries:150`, `portable_core:778`; block format asserts `memory_contracts:63,64`, `topic_graph:293` | header emitted when `out` is empty → **3 tests fail** | **yes** — no test of the line's content |
| 6 | paragraph-boundary truncation | `portable_core:341` (≤350), `index.test.ts:138` (≤240) | nothing existing | **yes** — no truncation test at all |
| 7 | adapter per-session dedup, cleared on compaction | only `index.test.ts:108-111` (one prompt → exactly one `<chronicle-untrusted>`), `:156,181` | dedup surviving compaction drops the re-injected index | **yes** — zero Python coverage; `bun test` not in baseline |
| 8 | validate-after-ranking fill to K | `topic_graph:285` (TOPK=1), `memory_contracts:50,67`, `topic_patch:266`, `session_context:129` | fill re-scans beyond the capped list → factual/retained bodies leak into `memory_contracts:65` / `topic_graph:294`; extra body reads → `topic_patch:282` | **yes** — no positive "K notes when ≥K match"; `remaining < 200` break path untested |

## 2. Ordering / I/O invariants that must survive

- **`test_body_reads_for_ordinary_ranking_respect_candidate_cap`** (`test_topic_patch.py:266-283`) — asserts `len(calls) == 2` with `MAX_SCAN=2` and that every read is under `docs/topics`. It is bound to two *private* seams: module-global `retrieval.read` and module-global `retrieval.MAX_SCAN`. Changes 2/3/4/8 all rewrite `retrieve()`. If `read(f)` is inlined or `MAX_SCAN` becomes a local, the test fails loudly (good) — but if a body cache is added, the assertion still passes while real I/O becomes unbounded (bad). Needs a companion `read_frontmatter` open counter.
- **`test_factual_backlog_does_not_consume_automatic_retrieval_budget`** (`test_memory_contracts.py:50`) — 65 factual notes + 1 semantic + 1 topic, `MAX_SCAN=60`: exclusion must precede the cap. This is the tripwire for change 8 filling from an unfiltered pool.
- **`test_topics_never_age_out_of_the_scan_window`** (`:67`) — `MAX_SCAN=3`, 10 newer sessions; topics take the first slots. Change 8 must not reorder topic-first allocation.
- **`test_write_boundaries.py`** (all 10) — byte-snapshot equality before/after every hook; establishes "retrieval/checkpoint never write". Any change that opens a file for append, writes a cache, or touches mtime breaks these.
- **`test_neutral_workflows.py`** — byte-for-byte resource parity, deterministic archives, git-failure-vs-empty. Its 17 tests are the release gate for packaging and are currently **invisible**. Also load-bearing for this feature: `:57-59` compares `skill/*/references` bytes to `skills/*` — any new reference doc added for this feature must be mirrored there.
- Extra invariants to add to the list: `test_retrieval_and_index_dedupe_before_budget_and_fallback` (`test_session_context.py:129`, `MAX_SCAN=1`) and `test_retrieval_filters_retained_nodes_before_budget_and_weights_structure` (`test_topic_graph.py:285`, `TOPK=1`) — both encode "filter, then budget".

## 3. Coverage gaps (answers to the three questions)

- **Captured evidence never contains injected text — no test.** The only near-miss is `test_checkpoint.py:212-220` (wikilinks inside captured prompts are stripped at publication), which protects a different property.
- **Truncation boundaries — no test.** No test mentions `…(truncated)`, and none exercises a body longer than the budget. `test_find_total_output_budget_includes_header_trust_wrapper_and_escaping` passes because `_portable.untrusted()` hard-slices escaped text, which will *also* mask a broken paragraph boundary: escaping expands text, so the wrapper cut lands at a different offset than the core cut.
- **Session-start index exclusion semantics — partially tested.** `test_startup_index_selects_latest_eight_semantic_and_legacy_sessions` (`test_memory_contracts.py:104`) covers factual-evidence exclusion, body-text false positives, and the 8-item recency order. It does **not** cover `semantic-summary` dedup, `session-presentation` exclusion, or the `started > date > filename` tie-break in `_session_notes.py:70-72`.
- Also absent: empty-query zero-I/O; adapter dedup/compaction; any assertion on the injected header text (free to change, which is both an opportunity and a hazard).

## 4. House style to match

- **Subprocess + env, never in-process for CLI tests:** `run_script(name, payload, environment=None)` (`test_memory_contracts.py:20`) with `PROJECT_ROOT` and `SESSION_CHRONICLE_CAPTURE_*`; `run_cli(script, *args, payload=..., env=...)` (`test_topic_graph.py:29`) auto-selects `bash` for `*.sh`. Timeouts 10–20 s; assert on `returncode` and `stderr`.
- **Tempdir fixtures:** `tempfile.TemporaryDirectory()` + `addCleanup`, tree built in `setUp`, attributes `self.project / self.base / self.topics / self.sessions`. One test in `tests/` uses `/tmp/opencode` (`test_native_hooks.py:362`).
- **Module loaders for hyphenated names:** `importlib.util.spec_from_file_location(name.replace("-", "_"), path)` (`test_topic_patch.py:223`, `test_topic_review.py`, `test_session_context.py:14`). Filenames like `retrieve-inject.py` are never importable directly.
- **Fixture reuse by aliasing:** `setUp = OtherTests.setUp`, `run_cli = ...`, `topic_text = ...` — 4 files depend on `test_topic_graph.TopicGraphTests` / `test_memory_contracts.MemoryContractTests`. Tests within `scripts/` are a single import namespace; adding a new helper module there is safe, but renaming a shared fixture method breaks 4 files.
- **Determinism aids:** `os.utime(path, (1, 1))` to pin recency, `snapshot()` → `{relpath: bytes}` for no-mutation, `patch.object(module, "read", wraps=...)` for I/O counts.

## Findings

### Critical

**C1 — `tests/test_neutral_workflows.py:39-47` → 17 tests silently uncollected.**
`error.name` for a missing submodule is `"uat.adapters"`, which is not in the tolerated set, so the exception is re-raised at import time and the whole module becomes one `_FailedTest`. Why it matters: the only green/red signal for packaging parity, the scanner, and reference-byte equality disappears, and a subsequent retrieval regression will be reported as "1 error" indistinguishable from this one.
Fix — replace the path probe with an existence gate, mirroring `tests/test_uat_package.py:29`:
```python
UAT_AVAILABLE = (UAT_ROOT / "uat/adapters/common.py").is_file()
if UAT_AVAILABLE:
    sys.path.insert(0, str(UAT_ROOT))
try:
    ...
except ModuleNotFoundError as error:
    if error.name not in {"uat", "uat.adapters", "uat.definitions", "yaml", "jsonschema"}:
        raise
    UAT_AVAILABLE = False
```

### Important

**I1 — `test_topic_patch.py:266-283` — the I/O invariant is bound to globals that all four core changes touch.** `patch.object(retrieval, "MAX_SCAN", 2)` and `patch.object(retrieval, "read", ...)` require both to stay module-level and `read` to stay the single body-read seam. Why: this is the only test forbidding unbounded body reads; if it is rewritten ad hoc during implementation, nothing else guards the cap.
Fix — keep `read()` and `MAX_SCAN` as module globals through the refactor, and add a sibling test for frontmatter opens:
```python
def test_frontmatter_memoisation_bounds_opens_per_path(self):
    for i in range(5):
        self.topic(f"claim-{i}", body="Octopus knowledge.")
    retrieval = load_script("retrieve-inject.py")
    opens = []
    original = _topic_graph.read_frontmatter
    def tracked(path):
        opens.append(Path(path)); return original(path)
    with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project)}), \
         patch.object(retrieval, "read_frontmatter", tracked), \
         patch.object(retrieval, "MAX_SCAN", 2), \
         patch("sys.stdin", io.StringIO('{"prompt":"octopus"}')), patch("sys.stdout", io.StringIO()):
        retrieval.main()
    self.assertLessEqual(max(Counter(opens).values(), default=0), 1)
```

**I2 — no test that injected text is excluded from capture (change 1).** Add to `test_memory_contracts.py` after `:229`:
```python
def test_injected_markers_never_reach_evidence(self):
    injected = ("## Project memory \u2014 auto-retrieved for this prompt (read-only)\n"
                "### [session] Octopus (2026-09-06--octopus)\nOctopus recalled prose.")
    self.capture({"hook_event_name": "UserPromptSubmit", "prompt": injected, "sessionID": "session-one"})
    self.capture({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                  "tool_input": {"command": "printf '%s' '" + injected.replace("'", "'\\''") + "'"}})
    self.assertEqual(self.records(), [])
```
Plus the portable twin in `tests/test_portable_core.py` via `capture`/`prompt.submit`, because there are **two** independent filter sites (`capture-signals.py:41-59` and `_capture.py:45-64`) and only the second is covered by `test_selective_capture_*`.

**I3 — no truncation or K-fill test (changes 6 and 8).** Two tests, both currently absent:
```python
def test_truncation_stops_on_a_paragraph_boundary(self):  # test_memory_contracts.py
    body = "\n\n".join(f"Paragraph {i} octopus statement." for i in range(200))
    (self.base / "topics" / "long.md").write_text(f"---\ntype: topic\ntitle: Long\nstatus: active\nnote-kind: atomic\n---\n{body}")
    out = self.run_script("retrieve-inject.py", {"prompt": "octopus"}, {"MEMORY_INJECT_BUDGET_CHARS": "600"}).stdout
    self.assertIn("\u2026(truncated)", out)
    self.assertNotIn("Paragraph 199", out)
    self.assertRegex(out.split("\u2026(truncated)")[0].rsplit("\n", 1)[0], r"statement\.$")

def test_ranking_fills_to_k_when_candidates_exceed_k(self):   # test_topic_graph.py
    for i in range(5):
        self.topic(f"claim-{i}", body="Octopus knowledge.")
    out = self.run_cli("retrieve-inject.py", payload={"prompt": "octopus"},
                       env={"MEMORY_INJECT_TOPK": "3"}).stdout
    self.assertEqual(out.count("### ["), 3)
```

**I4 — no empty-query zero-I/O test (change 2).** Without it, the change can be "implemented" by moving the guard three lines too far (before `resolve_base`) and no test objects. Assert both no output and no reads, and keep a separate test that a *broken* docs-root still fails with a non-empty prompt — today `test_write_boundaries.py:32` covers only `checkpoint.py` and `capture-signals.py`, so `retrieve-inject.py` has no docs-root failure test at all.

**I5 — change 7 has no coverage in either baseline command.** `index.ts:88` holds `const indexed = new Set<string>()`; `:129` injects the index once; `:187-201` is the compaction hook. Only `index.test.ts:106-111` constrains this, with a single prompt. Add a TS test: prompt → prompt (second must not repeat the same note) → `compaction` → prompt (must re-inject). Without it, "dedup never cleared" and "dedup never applied" are both silently acceptable.

**I6 — provenance line has no content test (change 5), and three exact-empty assertions constrain it.** `memory_contracts.py:87` (`automatic.stdout == ""`), `write_boundaries.py:150` (`stdout == ""`), `portable_core.py:778` (`{"ok": True, "result": ""}`). The line must be emitted only when at least one note is returned; add an assertion on `\d+ note` and the `updated` date so the feature is not shipped unverified.

### Suggestion

**S1 — stale duplicate suites in `.opencode_OLD/`.** Eight old `test_*.py` copies exist under `.opencode_OLD/session-chronicle/...` and `.opencode_OLD/skills/...` (e.g. an outdated `test_memory_contracts.py` with 217 lines vs 248 today). There is no `conftest.py`, `pytest.ini` or `setup.cfg`, so a bare `pytest` or root-level `unittest discover` collects them and hits basename-module collisions. Add a `conftest.py` with `collect_ignore_glob=["**/.opencode_OLD/**"]` or extend `.gitignore`.

**S2 — `test_topic_patch.py:278` leaks the ambient environment.** `patch.dict(os.environ, self.environment)` where `self.environment = {**os.environ, "PROJECT_ROOT": ...}` carries any developer-set `MEMORY_INJECT_*` into the test. Use `patch.dict(os.environ, {"PROJECT_ROOT": str(self.project)})`.

**S3 — index exclusion coverage is narrower than the feature.** Extend `test_startup_index_selects_latest_eight_semantic_and_legacy_sessions` with one `semantic-summary` + duplicate pair and one `session-presentation`, so change 5's provenance line is exercised on the paths that actually feed `print_recent_sessions`.

## What was done well

- **Write-boundary discipline is exemplary.** Every mutation test snapshots bytes before and asserts equality after (`test_topic_patch.py:33-41`, `test_write_boundaries.py` throughout); `test_agent_cannot_create_factual_evidence` and `test_invalid_record_identity_prevents_all_batch_publication` make forgery paths explicit.
- **The retrieval ordering contract is genuinely pinned, not aspirational.** The factual-backlog, topic-ageing and candidate-cap tests each encode a *failure mode* (crowding out, ageing out, unbounded reads) rather than a happy path, and they survived the earlier fairness change — the right shape for this feature.
- **Deterministic, hermetic fixtures without cloud or network.** Recency pinned by `os.utime`, git mocked (`test_neutral_workflows.py:129-138`), no shared journal writes, `TemporaryDirectory` + `addCleanup` everywhere. The suites are cheap and safe to run on every wave.

## Verdict

**APPROVE WITH NOTES.** No blocking defect beyond C1, which is pre-existing and cheap to fix. But the plan must budget for the six absent tests (I2–I6 plus I1's companion) — the eight changes are only ~40 % guarded today, and the retrieval I/O invariants sit on private seams that the refactor will move.

## Spec Inputs

**Components and files affected**
- `skill/session-chronicle/scripts/retrieve-inject.py` — changes 2, 3, 4, 5, 6, 8 (single file, `retrieve()` lines 118-200).
- `skill/session-chronicle/scripts/capture-signals.py` (`build_signal`, lines 41-59) **and** `skill/session-chronicle/scripts/_capture.py` (`select_signal`, lines 45-64) — change 1 must land in both; they already duplicate `NOISE_RE`/`DISABLED` and their event vocabularies diverge (`Write|Edit` vs `files.*`).
- `skill/session-chronicle/scripts/_topic_graph.py:130` (`read_frontmatter`) — change 3's cache home; consumed by `_session_notes.preferred_paths`, `_memory_read`, `retrieve-inject`.
- `skill/session-chronicle/scripts/_session_notes.py:29-74` — change 7's Python-side counterpart (selection dedup) and change 5's index provenance.
- `skill/session-chronicle/scripts/_portable.py:113-141` — `untrusted()` re-truncates `find` output; changes 5/6 must be reconciled with it.
- `adapters/opencode/index.ts:88,128-145,187-201` — change 7. `index.test.ts`.
- `skill/session-chronicle/scripts/chronicle-doctor.py:101` — reads `MEMORY_INJECT_MAX_SCAN`; must share whatever selection helper change 8 introduces.
- New: `docs/future-evolutions.md` (does not exist yet).

**Patterns to follow**
- Subprocess + `PROJECT_ROOT`/`MEMORY_INJECT_*` env; `tempfile.TemporaryDirectory` + `addCleanup`; `spec_from_file_location(name.replace("-","_"))` for hyphenated scripts; `snapshot()` dicts for no-mutation; `patch.object(module, "read", wraps=...)` for I/O counting; `os.utime(p, (1,1))` for recency.
- Reuse `test_topic_graph.TopicGraphTests` fixtures rather than new boilerplate.
- **Anti-patterns present:** module-level import of an optional external checkout (C1); patching private module globals (`retrieval.read`, `retrieval.MAX_SCAN`); `patch.dict(os.environ, {**os.environ, ...})`; duplicated filter logic across two capture modules; stale test trees in `.opencode_OLD/` with no collection guard.

**Integration constraints**
- `retrieve()` returns `str | None`; `None` means "no injection". Three tests assert exact-empty, so the provenance header is conditional on ≥1 note — non-negotiable.
- Block format `### [kind] title (slug)` is asserted by `(semantic)`, `(topic)`, `(octopus)`, `(atomic)`.
- Portable surface wraps the result once in `<chronicle-untrusted>` and asserts `count(...) == 1`; provenance text must not contain `<`/`>` and must be inside the wrapper.
- `_session_notes.preferred_paths` documents "never trust a cache across calls" (`:30`) — change 3 must be per-call/module-lifetime-bounded, and `test_topic_review.py:178` enforces it in-process.
- `read_frontmatter` raising is load-bearing: it is how a broken docs-root avoids masquerading as an empty search (`portable_core:349,776`).
- `MEMORY_INJECT_*` are read at import time (lines 43-45); `patch.object(retrieval, "MAX_SCAN", n)` depends on that.

**Tech debt that complicates the feature**
- Two capture filter implementations with different shapes — change 1 doubles the surface and can diverge silently.
- Two truncation layers (`retrieve-inject.py:189` char/paragraph; `_portable.untrusted` escaped-char) with no test bridging them.
- `retriever` writes no cache, and `test_write_boundaries.py` enforces that; change 3's memoisation must live in memory, not on disk.
- `.opencode_OLD/` duplicate suites + no pytest config.
- `docs/verification.md` records 119/186/22 (2026-10-23); the scripts suite is now 127 — the recorded baseline is 8 tests stale and does not mention the `uat.adapters` failure. It should be refreshed as part of this feature so the next review has a trustworthy reference.

**Test coverage baseline**
- `skill/session-chronicle/scripts`: **127** tests, 8 modules, no skips; documented-green 119 (8 added since).
- `tests`: **186** tests, 7 modules; **20 skip** (UAT absent), **17 uncollected** (C1), **149 expected to run**.
- TS: `bun test` 22 tests / 68 assertions, documented green; **not** in the requested baseline and the only guard for change 7.
- Net guard for the eight changes: 3 constrained-and-compatible, 2 (3, 4) strongly constrained, **5 (2, 5, 6, 7, 8) untested or only negatively planned**, 1 (change 1's core property) untested.
