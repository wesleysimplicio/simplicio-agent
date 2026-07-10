# Simplicio Agent Desktop — handoff audit (2026-07-10)

Status: **INCOMPLETO; não promover como release**.

- Electron/React Desktop, TokenMonitor/savings ledger e adapters para Claude, Codex, Cursor, VS Code, Antigravity e Hermes existem no código auditado.
- Issues P0 de layout `#126`, kernel único `#127`, savings `#128`, updater/flags `#129`, CI/release `#130` e readiness `#132–#135` estão abertas.
- Ainda falta provar caminho canônico (`desktop/` vs `apps/desktop`), Runtime único empacotado, installers/feed/assinatura/rollback, savings correlacionado, matriz MCP/CLI e E2E clean-machine.
- Google/Stripe continuam default-off; remover/gatear qualquer sucesso simulado antes da release.

Ordem: `#126` → `#127/#132` → `#128/#133` → `#129/#134` → `#130/#135`; depois Runtime `#3005` e release da épica `#2998`.

Critério: PR mergeado, CI verde, artefato instalável, logs/screenshots redigidos, checksum, install/update/rollback/uninstall reproduzidos e reconsulta live do GitHub.

Handoff central: Agent `#144`; Runtime `#3054`.
