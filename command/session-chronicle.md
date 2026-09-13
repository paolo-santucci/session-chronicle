---
description: 'Explicitly enrich the trusted current session with a separate sourced semantic summary under <docs-root>/sessions/. Never edit presentations, evidence, pending batches, or drafts. NOT for STATUS.yaml or source code.'
---

Load the `session-chronicle` skill with the `skill` tool and execute its workflow.

Require an explicit enrichment request; an end-of-session signal alone never triggers this workflow. Call `memory_session_context` with `{}` to obtain the trusted SDK session ID, checkpointed sources, and summary target. If unavailable, denied, failed, or sources are empty, stop without writes. Never guess an ID or fall back to direct scripts with a model-supplied ID.

Modify only the returned matching open semantic summary or create the new returned target. Use only evidence records matching the exact returned `session_id` via `session_id`/`sessionID`, and cite batch IDs actually used. Preserve `id` (target stem), exact `session-id`, `started`, `date`, and target across midnight. Closed or duplicate summaries are errors: no reopening, replacement, or unrelated closes. Close only the current summary when the explicit enrichment request also asks for closure.

Arguments / context from the user: $ARGUMENTS
