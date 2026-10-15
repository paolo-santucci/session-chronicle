---
id: "<returned-target-stem>"
type: session
record-kind: semantic-summary
sources: []
date: YYYY-MM-DD
started: YYYY-MM-DDTHH:MM:SS+ZZ:ZZ
updated: YYYY-MM-DDTHH:MM:SS+ZZ:ZZ
session-id: "<exact-tool-session_id>"
title: "Short human title of the session"
topics: []
commits: []
plans: []
status: open
---

Use only the target returned by `memory_session_context({})`; new filenames are `session--<sha256(ID)>--summary.md`. Replace every placeholder before writing. Filling `sources: []` with factual batch IDs actually used is mandatory; use only records matching the exact tool session ID. Preserve `id`, `session-id`, `started`, `date`, and target on updates. Closed summaries cannot be reopened or replaced. Remove this paragraph from the completed note.

## What has been done
- Verified work on [[some-topic]].

## Decisions and why
- Decision on [[some-topic]]. **Reason:** supporting rationale.

## Open threads
- Remaining work on [[another-topic]].
