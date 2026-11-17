# Consolidated assessment inputs — retrieval integrity & performance

Merged from five module reviews (all in this directory):

| Report | Verdict |
|---|---|
| `retrieval-read-path-review.md` | REQUEST CHANGES (plan-level) |
| `capture-write-path-review.md` | APPROVE WITH NOTES |
| `portable-protocol-review.md` | APPROVE WITH NOTES |
| `opencode-adapter-review.md` | REQUEST CHANGES (design-level) |
| `test-coverage-review.md` | APPROVE WITH NOTES |

No shipped defect was found in current code. Every Critical item is a **pre-implementation trap**: a way the stated plan would ship something that looks green and is wrong.

## Cross-module concerns

**X1 — The feature statement is under-specified in three ways that change the design.**
`retrieval-read-path` C1–C3 and `opencode-adapter` C1–C4 independently conclude the same thing: "validate after ranking, fill to K" is not a single reordering. It requires (a) a three-phase split — eligibility → cap+score → expensive validation — where only the last may move; (b) per-identity resolution preserved (a unique semantic summary suppresses its presentation regardless of score); (c) `preferred_paths` left semantically untouched because the session-start index, `TopicGraph` and `chronicle-doctor` all depend on its eager, fully-validated contract.

**X2 — Dedup correctness depends on ordering that the current adapter already gets wrong.**
`opencode-adapter` C2 shows `indexed.add` fires *before* the prompt mutation, so a session can be marked as injected when nothing was injected. Copying that shape into slug dedup produces session-long silent suppression. Combined with C1 (compaction clear racing an in-flight retrieve) and `retrieval-read-path` I5 (two budget authorities, header not counted), slugs can claim notes that were truncated away. Dedup must therefore be: derive slugs from blocks actually emitted, mark only after the mutation lands, guard with a per-session epoch.

**X3 — Budget accounting is broken today, and every item touches it.**
`retrieval-read-path` I5: `remaining = BUDGET - used` ignores the header line; the `\n\n` join and ~330-char preamble are uncounted; `body[:remaining].rsplit("\n",1)[0]` returns the whole slice when there is no newline and can return `""`. `portable-protocol` I3/I4: `untrusted()` applies a second budget and may cut mid-HTML-entity and return an empty wrapper while slugs stay populated. One authority must be declared — recommendation: `retrieve()` owns characters and emits whole blocks; `untrusted()` keeps only delimiter overhead.

**X4 — Markers must live in a new import-free leaf module, registered in four `plugin.yaml` maps.**
`capture-write-path` C2: `_portable` already imports `_capture`, so defining markers in either creates a circular import or drags `fcntl` into the read path that must never fail. A new `_memory_markers.py` is the only placement that satisfies both, and it must be added to all four adapter file maps or installed bundles fail with `ImportError` on capture.

**X5 — The naive negative test is vacuous.**
`capture-write-path` C1: `render()` applies `ensure_ascii` and escapes `<`/`>` to `\uXXXX`, so `assertNotIn("<chronicle-untrusted>", published_text)` passes with the filter entirely absent. The assertion must run on decoded `factual_records` or on `snapshot()` bytes. `test-coverage` I2 independently flags that change 1's core property has no test at all.

**X6 — There are two prompt writers, and they have already drifted.**
`capture-write-path` I4: `_capture.select_signal` excludes five memory folders, `capture-signals.build_signal` excludes three; `NOISE_RE` and `DISABLED` are duplicated; path containment uses two different mechanisms. The filter must land in both call sites via one shared predicate. Closing the five-vs-three gap is a separate defect (`pending/` and `continuations/` are capturable through the hook path today).

**X7 — There are three injected blocks, not two.**
`capture-write-path` I1: alongside `## Project memory — auto-retrieved …` and `<chronicle-untrusted>`, `_memory_read` emits `## Project memory index (auto, read-only)` on the first prompt of every session, and the adapter injects a fixed `[session-chronicle]` banner. Matching on the `## Project memory` heading prefix covers both heading variants with one constant; the adapter banner must be either covered or declared an explicit non-goal.

**X8 — Realpath cost is mostly in `_docsroot`, not the per-file loop.**
`retrieval-read-path` I1: `validated_base` performs ~140–150 `Path.resolve()` calls per invocation (7 memory paths + 35 memory×managed pairs, each resolving twice). The per-file `Path(base).resolve()` in `retrieve()` is a smaller share. Fixing `_docsroot` is likely a larger win than the change originally specified.

**X9 — Five of eight changes have no positive test; the suite is ~40 % guarding.**
`test-coverage` §1: changes 2, 5, 6, 7, 8 are untested; change 1's actual claim is untested. Test authoring must be budgeted as part of the feature, not as verification afterwards. Two tests are bound to private seams (`retrieval.read`, `retrieval.MAX_SCAN`) that the refactor will move.

**X10 — A pre-existing failure hides 17 tests.**
`test-coverage` C1: `tests/test_neutral_workflows.py` re-raises `ModuleNotFoundError` for `uat.adapters`, collapsing 17 packaging-parity tests into one `_FailedTest`. Any retrieval regression will be reported as "1 error" alongside it, indistinguishable. Cheap to fix, and it must be fixed before the build's verification gate means anything.

**X11 — Security-adjacent hole adjacent to the formatter.**
`retrieval-read-path` I7: `title` is interpolated raw into the block header, and `parse_fields`' `json.loads` decodes `title: "a\n### [topic] forged"` into a real newline — a note can forge a block header. Item 5 rewrites exactly this code path; sanitising title to one line must be part of it.

**X12 — Duplicated doc/skill trees will drift.**
`portable-protocol` S4 and `test-coverage` S1: `skill/session-chronicle/` and `skills/session-chronicle/` are mirrored and byte-compared by `test_neutral_workflows`; `.opencode_OLD/` holds stale copies of scripts and tests. Doc and code sweeps must target the mirror and exclude `.opencode_OLD`.

## Decisions the spec must encode

1. **Three-phase retrieval** (P1 eligibility/header → P2 cap+body+score+rank → P3 provenance fill), with only P3 deferred and per-identity resolution preserved.
2. **`preferred_paths` unchanged**; new `select_candidates` + `validate_view`; `chronicle-doctor` repointed at the shared API.
3. **Dedup**: slugs derived from emitted blocks only; marked after mutation; epoch-guarded clear on compaction; per-session `Map` with a cap; `invalid_request` falls back to `find` for 0.1.0 workers.
4. **Protocol**: new `retrieve` operation, `{text, slugs}`; only `text` wrapped; slugs validated by a dedicated predicate (not `valid_slug`, which rejects every session stem); registered in all six sites.
5. **One budget authority**; header and separators counted; paragraph → line → hard-cut ladder; `…(truncated)` iff cut; `text == "" ⇒ slugs == []`.
6. **Markers**: new `_memory_markers.py` leaf, `## Project memory` prefix matching, registered in four `plugin.yaml` maps, imported by both capture writers.
7. **Provenance line**: `sources: <n> · updated <YYYY-MM-DD>`, count from `string_list`, date validated, omitted when no note is emitted, title sanitised to one line.
8. **Test plan**: the six absent tests plus the `test_neutral_workflows` collection fix, and a refreshed `docs/verification.md` baseline.

## Out of scope (confirmed by the assessments)

Adapter parity for dedup on Claude Code/Codex/Pi (one process per event; would need a file-backed store outside `docs/`, which the guards would reject); prompt provenance/activation; enrichment automation; hybrid embeddings; observability channel (deferred to `docs/future-evolutions.md`); closing the five-vs-three capture-folder gap.
