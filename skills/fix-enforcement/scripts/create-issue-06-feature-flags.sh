#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[RELEASE] Feature flags para comandos experimentais + canary releases (stable/beta/nightly)" \
'## Contexto

Hoje cada novo comando é compilado direto no binário. Se quebrar, quebra tudo. Não há feature flags, canais de release, ou kill switch.

## O que precisa acontecer

1. **Feature gates no Cargo.toml**:
   ```toml
   stable = ["core", "edit", "gate", "gateway-core"]
   beta = ["stable", "organism", "agent-ipc", "video"]
   nightly = ["beta", "wavespeed", "autonomia", "navegacao"]
   ```

2. **`simplicio update check --channel stable|beta|nightly`**:
   - Cada canal tem tag de release própria
   - Upgrade automático dentro do canal

3. **Kill switch**:
   - Se novo módulo crasha na inicialização → auto-rollback
   - `simplicio update rollback` restaura último binário estável

4. **`simplicio feature list|enable|disable`**:
   - Lista/ativa/desativa features
   - Estado persistido em `.simplicio/config.yaml`

## Critérios de sucesso
- [ ] Feature gates separam stable/beta/nightly
- [ ] `simplicio update check --channel beta` funciona
- [ ] Kill switch: rollback automático em crash na inicialização
- [ ] `simplicio feature list` mostra todas as features
- [ ] Compilação mínima (`--no-default-features`) produz binário < 5MB' \
"release,feature-flags,prioridade-média"
