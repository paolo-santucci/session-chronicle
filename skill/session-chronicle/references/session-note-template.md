---
# Canonical SESSION note — chronological journal entry.
# Filename: ${docs-root}/sessions/YYYY-MM-DD--<theme-slug>.md   (stem == id)
# APPEND-ONLY: once `status: closed`, this file is immutable history.
#
# Required fields (enforced by note-lint.py PostToolUse): id, type, date, title, status.
# Recommended (not enforced): started, updated — full ISO-8601 timestamps that order
#   same-day sessions and survive a session crossing midnight (the date/filename do not).
# Free-form prose below is written in the SESSION LANGUAGE; slugs/tags are English/kebab.
id: YYYY-MM-DD--theme-slug          # stable; equals filename stem (filename = START date)
type: session
date: YYYY-MM-DD                    # the session's START date (matches filename stem)
started: YYYY-MM-DDTHH:MM:SS+ZZ:ZZ  # set ONCE at creation; orders same-day sessions chronologically
updated: YYYY-MM-DDTHH:MM:SS+ZZ:ZZ  # refreshed every checkpoint; tie-breaks multiple open entries
session-id: YYYY-MM-DD--theme-slug  # CLAUDE session_id if known, else date-slug
title: "Short human title of the session"
topics: []                          # de-normalised list of [[slug]] used in the body
commits: []                         # short SHAs touched this session (provenance)
plans: []                           # spec/plan doc paths touched (provenance), else []
status: open                        # open (current session) | closed (immutable)
---

## What has been done
<!-- What was done this session. Reuse the recently-completed summaries. Terse. -->
- …

## Decisions and why
<!-- Each decision + its reason. This is the in-line decision log; the retrieval hook reads it back. -->
- Deciso X su [[some-topic]]. **Perché:** …

## Open threads
<!-- Questions / work left open, with forward links. -->
- … → [[another-topic]]
