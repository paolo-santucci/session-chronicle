---
# Canonical TOPIC note — atomic evergreen concept (Zettelkasten permanent note).
# Filename: ${docs-root}/topics/<canonical-slug>.md   (stem == id == slug)
# UPSERT semantics: if it exists, UPDATE it (bump `updated`); never create a duplicate concept.
# NOTE: topic-note materialisation is DEFERRED to session-chronicle v1.1.0 (M2).
#       This template is the locked schema; note-lint.py already validates it.
#
# Required fields (enforced by note-lint.py PostToolUse): id, type, title, and CONCRETE
# provenance. Provenance is MANDATORY: with `provenance: derived_from_*` you MUST also
# populate `sources:` (non-empty); only `provenance: stated_by_user` may leave `sources` empty.
id: canonical-slug                  # equals filename stem; English kebab-case
type: topic
title: "Human title of the concept"
aliases: []                         # alternative slugs → anti-duplicate enforcement
tags: []                            # English kebab tags
created: YYYY-MM-DD
updated: YYYY-MM-DD
provenance: derived_from_sessions   # derived_from_sessions | stated_by_user | derived_from_plan
sources: []                         # provenance paths (plans/specs/sessions). MANDATORY (or `provenance:`)
status: active                      # active | superseded | merged
supersedes: []                      # [<slug>] if this replaces another note
links: []                           # [[slug]] associative edges to other topics
---

<!-- CURRENT distilled understanding of the concept. NOT a log: the history is reconstructed
     from the backlinks in sessions/ (grep for [[slug]]). Keep atomic and terse. -->
…
