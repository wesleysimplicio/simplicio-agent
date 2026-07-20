---
iteration: 1
max_iterations: 5
completion_promise: "SIMPLICIO_LOOP_DONE"
evidence_required: true
mode: drain
started_at: "2026-07-16T16:00:00Z"
---

GOAL: Terminar todas as 85 issues do simplicio-agent via simplicio-loop. Triagem honesta:
- Issues com branch/worktree de OUTRO processo (10): NAO TOCO (lock protocol).
- Issues EPIC sem AC testavel (75): QUARANTINE com comentario honesto (deixar aberta, nao close falso).
- Issues com AC real: PR (nenhuma encontrada nas 75 livres).

NAO-CONFLITO: prefixo simplicio/ nos meus branches; lock por issue na memoria.
PR #409 ja aberta (adapter-requirements.toml). #2988/#3019 (runtime) ja fechadas.
