# Atomicity examples

Illustrative authoring examples, **not claims about a target project**. Before using
any statement below in real memory, find and read that project's supporting sources.
The complete metadata shapes remain in the three shared templates.

## A short compound note should split

**Before — “Project memory”**

> Checkpointing persists captured inputs without a model. Search prefers a semantic
> summary over the corresponding presentation. Closed session history is immutable.

This is short, but it answers three independently changeable questions. A reader
may want to cite the checkpoint mechanism without also asserting a search policy.

**After — retain `project-memory` as a structure note**

> This map connects persistence, retrieval and history preservation:
> - [[checkpoints-persist-observed-inputs]] explains what capture preserves.
> - [[retrieval-selects-one-session-view]] explains which representation is searched.
> - [[closed-session-history-is-immutable]] explains which records can be revised.

Each child now explains one mechanism, citing the exact source/section supporting
it. The original subject still resolves from old session links. Children inherit
the relevant sources; they do not cite only this newly rewritten map as proof.

## A multi-sentence argument should stay together

**“A captured test command does not establish a passing test”**

> A record containing the command `pytest` establishes that this input was observed.
> It does not contain the test result. Therefore a semantic note cannot claim the
> tests passed from that record alone; it needs a recorded result or other verified
> evidence. This distinction qualifies [[checkpoint-evidence]].

The observation, limitation and conclusion form one argument. Splitting them into
three notes would make the reasoning harder to reuse. A source citation must show
what the particular capture record contains; another project's implementation may
capture results too, so the note's scope must be explicit.

## Related is not equivalent

“Retrieval excludes raw evidence by default” and “Checkpoints preserve raw evidence”
refer to the same material but assert different policies. They should be linked
with an explanation of that relationship, not merged under an alias.

Conversely, two notes asserting the same scoped retrieval policy can be merged
after checking their sources and qualifications. The retired slug becomes a
redirect; the survivor keeps the combined supporting references.

## Correct historical scope instead of inventing current truth

**Unsupported:** “The adapter automatically runs model enrichment.”

**Supported historical wording, if the source actually says this:** “The August
design used automatic enrichment; the cited session did not verify its runtime
behaviour.”

If a later source explicitly documents replacement by deterministic persistence,
revise the current idea accordingly and retain the old account in session history
and the refactoring snapshot. If later notes contain only commands or edit paths,
they do not prove the replacement succeeded. Record the uncertainty rather than
choosing whichever file is newest.

## A length warning can be retained

A note explaining one failure condition may need its assumptions, mechanism,
counterexample and limitations. If removing or extracting any of them would distort
the same idea, keep them together and record that the scope was reviewed. Do not
truncate the note, discard its qualifications or manufacture sibling notes to
silence `review-length`.
