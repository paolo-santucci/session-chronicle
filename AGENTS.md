---
docs-root: docs
---

# AGENTS.md

<!-- status-discipline-block:v3 BEGIN — managed by bootstrap-status-discipline skill; do not edit between sentinels -->

## ⭐️ Session Boot — MANDATORY

Before responding to the user's first message in any session:

1. Obtain the current state. If a `[status-inject]` section already appeared in this conversation, that **is** `./STATUS.yaml` — use it and do not read the file again. Otherwise read `./STATUS.yaml` yourself; if only the legacy `./STATUS.md` exists, read that instead — the next `/update-status` will migrate it to YAML.
2. Summarise it in **one line** before any other action: the active plan (if any), the most recent completion, and the most relevant in-progress item or blocker.
3. **If `pending-consolidation` is a non-empty array**, append a second line right after the summary: `⚠ <N> plan(s) archived with unconsolidated spec deltas — see pending-consolidation in STATUS.yaml`. This is a visibility signal, not a blocker — never refuse to proceed because of it.
4. If nothing was injected and no status file exists, ask the user for current project context before proceeding.

## ⚠️ Status Discipline — MANDATORY

Invoke the `update-status` skill (`/update-status`) **proactively**, without waiting to be asked, at every one of these:

- a completed task or logical group of changes;
- a `git commit`;
- a milestone, phase transition, or workflow handoff;
- a significant blocker;
- an explicit user signal: `"stop"`, `"checkpoint"`, `"save progress"`, `"end of session"`, `"that's it"`, `"talk to you tomorrow"`.

A `[status-freshness]` reminder in the conversation means unrecorded commits have already accumulated — act on it at the next natural break. Its **absence proves nothing**: that counter lives in the plugin process and does not survive a one-shot `opencode run`, so the triggers above hold whether or not the sidekick plugins are deployed here.

Do **not** defer to session-end. `STATUS.yaml` is the source of truth between sessions and must reflect reality at every checkpoint.

<!-- status-discipline-block:v3 END -->
