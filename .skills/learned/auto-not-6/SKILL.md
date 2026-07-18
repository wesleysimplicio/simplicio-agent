---
name: auto-not-6
description: Learned skill  -- when the task mentions "not", run this proven sequence (5 successful runs, confidence 1.00).
metadata:
  type: learned
  source: meta-loop-auto
---

# auto-not-6

**Trigger:** the task mentions `not`.

**Proven steps** (mined deterministically from 5 successful runs):

1. `runtime.changed-files --repo /Users/wesleysimplicio/Projetos/ai/simplicio-agent`
2. `runtime.targeted-tests`
3. `runtime.build-check`
4. `runtime.api-smoke --contracts .simplicio/endpoint-inventory.json`
5. `playwright test`
6. `runtime.full-repo-validation`
