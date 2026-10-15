---
description: 'Run ONCE per project to backfill the session journal from history that predates the plugin — reads prior specs, plans, decisions, STATUS and the git log, then synthesises an initial chronology plus the first topic notes. Trigger phrases "bootstrap session memory", "backfill the chronicle", "seed the session journal", "inizializza la memoria di sessione", "popola la cronologia dallo storico". Idempotent — refuses on an already-populated sessions/ unless passed --force. NOT for routine checkpoints, which are /session-chronicle.'
---

Load the `session-chronicle-bootstrap` skill with the `skill` tool and execute its workflow.

Arguments / context from the user: $ARGUMENTS
