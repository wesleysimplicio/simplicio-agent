# Mapper freshness and task-contract troubleshooting

## Symptoms

A valid `simplicio-loop run` can exit 0 while remaining blocked with:

- `current_action: mapping_failed`
- `mapper artifacts are missing or stale`
- `fresh: false` / `warnings: ["artifacts_not_fresh"]`
- `delivery.ready: false`, `completion.tag: UNVERIFIED`

This is a preflight blocker, not implementation evidence. Do not claim tests, PR, merge, or issue closure.

## Recovery sequence

1. Confirm the mapper itself has artifacts and identify freshness:
   ```bash
   simplicio-mapper status <repo> --json
   ```
2. Refresh synchronously after every loop-state mutation:
   ```bash
   simplicio-mapper index <repo> --json
   simplicio-mapper inspect <repo> --json --await
   simplicio-mapper handoff <repo> --json --await
   ```
3. Require `status.phase=complete`, `fresh=true`, `warnings=[]`, and handoff `ready=true` before retrying.
4. If the loop immediately turns the mapper stale again, inspect the mapper/loop freshness boundary. Generated `.orchestrator/` state must not invalidate the source-code fingerprint. Do not use fake mapper preflight variables or bypass the bound operators.
5. Record the repeated fingerprint in `journal.jsonl`; after the stall threshold, switch strategy or escalate instead of retrying unchanged.

## Task contract parser requirements

The task file passed to `simplicio-loop run --task` is not the scratchpad frontmatter. Use a separate contract file containing:

```text
Sistema: <system>
Funcionalidade: <feature>
Tipo: <type>

1. Critérios de Aceite
Cenário 1: <title>
Dado que <precondition>
Quando <action>
Então <observable result>

2. Regras de Negócio
- RN1 – <rule>

3. Requisitos Não Funcionais
- <NFR>
```

Scenarios must be inside the recognized `1. Critérios de Aceite` section. Passing the scratchpad (with YAML frontmatter) as `--task` can split it into multiple tasks and produce `no scenarios parsed`. Include an NFR section to avoid a contract warning.

## Evidence from the session

The loop compiled `SCN1` and created run manifests/journal/watcher state, but three runs remained blocked before mutation because the mapper reindexed loop-generated files and returned `fresh=false`. The correct status was `UNVERIFIED`, not success. The issue stayed open.
