# macOS Code-Signing Recovery — Simplicio Runtime SIGKILL (exit 137)

> Sessão de 04/07/2026. Runtime v1.6.5, macOS 26.3 (25D125), MacBookPro17,1 (M1 arm64).

## Descoberta

O binário `simplicio` (1.6.5, ad-hoc linker-signed) crashava com SIGKILL (exit 137) em TODO
comando — `--version`, `--help`, `guardians`, `hbp`, `memory status`, TODOS. Nem sequer
iniciava o CLI. O mesmo binário funcionava SEM problemas no boot anterior.

### Sintomas

```bash
simplicio --version             →  Killed: 9  (exit 137)
simplicio doctor --json         →  Killed: 9  (exit 137)
simplicio memory status --json  →  Killed: 9  (exit 137)
```

### Diagnóstico

1. **Binary existe e é válido** — `file` retorna `Mach-O 64-bit executable arm64`, 26MB.
   `codesign -dvvv` mostra `adhoc,linker-signed` — assinatura presente.

2. **Não é OOM** — `vm_stat` mostra páginas livres + inativas suficientes. O processo é
   morto antes de alocar memória significativa (91MB VM reportado no crash dump).

3. **Crash reports revelam a causa real:**
   ```bash
   ls -lt ~/Library/Logs/DiagnosticReports/simplicio-*.ips 2>/dev/null | head -5
   cat ~/Library/Logs/DiagnosticReports/simplicio-*.ips | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(json.dumps({'exception':d.get('exception'),'termination':d.get('termination')},indent=2))"
   ```

   **Dados críticos no crash report:**
   ```json
   "exception": {
     "type": "EXC_CRASH",
     "signal": "SIGKILL (Code Signature Invalid)"
   },
   "termination": {
     "namespace": "CODESIGNING",
     "indicator": "Taskgated Invalid Signature"
   }
   ```

   **Campo `exception.signal`** → `SIGKILL (Code Signature Invalid)`.
   **Campo `termination.namespace`** → `CODESIGNING`.
   **Campo `termination.indicator`** → `Taskgated Invalid Signature`.

   **Outros sinais:**
   - `dyld_path_missing` e `main_executable_path_missing` nos `usedImages` — o dyld
     não conseguiu carregar o binário como imagem executável válida.
   - `bug_type: 309` — crash de código de inicialização (dyld/pre-main).
   - VM total 91.5MB — processo muito pequeno, não é OOM.

### Causa raiz

O macOS 26.3 (25D125) tem uma validação de código mais estrita que versões anteriores.
Binários compilados como Rust ad-hoc (linker-signed, sem Apple Developer ID) podem ser
rejeitados pelo `Taskgated` — o daemon de verificação de assinatura — após um reboot
ou atualização de segurança. A assinatura ad-hoc existente torna-se "invalid" para o
sistema, mesmo que o hash do binário não tenha mudado.

**Isso é DIFERENTE de corrupção de PATH binary ou stale MCP processes.** Neste caso:
- O mesmo binário funciona em um boot e não funciona no próximo
- SHA256 está consistente (não há divergência entre PATH e release)
- `rm -f + cp` **NÃO resolve** (é o mesmo binário)
- A solução é RE-ASSINAR com `codesign`

### Fix

```bash
# ✅ Único comando necessário:
codesign -f -s - /Users/wesleysimplicio/.local/bin/simplicio

# Verificar:
simplicio --version          # deve voltar a funcionar
simplicio doctor --json      # overall_status deve ser "ok" ou "warning" (não crash)
```

O `-f` força substituição da assinatura existente. O `-s -` gera uma nova assinatura
ad-hoc (sem identidade de desenvolvedor Apple). O macOS aceita a nova assinatura como
válida.

### Verificação pós-fix

```bash
simplicio --help | head -5          # mostra "simplicio 1.6.5" + USAGE
simplicio doctor --json | python3 -c "import json,sys;d=json.loads(sys.stdin.read());print(d['overall_status'])"  # "ok" ou "warning"
simplicio memory status --json      # deve retornar o guardian policy completo
```

## Guardiões e HBP no v1.6.5 — mudanças de comando

Na versão 1.6.5, os subcomandos `guardians` e `hbp` não existem mais como comandos
autônomos. Eles foram incorporados em outros comandos:

| Comando removido | Substituído por |
|---|---|
| `simplicio guardians --json` | O guardian triangle (Isa/Helo/Levi) aparece em `simplicio memory status --json` no campo `guardian_policy.guardians` |
| `simplicio hbp verify` | HBP (Hermes Bus Protocol) info está em `simplicio doctor --json` (runtime health) e `simplicio memory status --json` (guardian_policy) |
| `simplicio hbp len` | Sem equivalente direto — HBP tamanho é derivado da configuração |

### Como verificar os guardiões no v1.6.5

```bash
# Ver todos os 3 guardiões com status:
simplicio memory status --json | python3 -c "
import json,sys
d = json.load(sys.stdin)
for g in d['guardian_policy']['guardians']:
    print(f\"{g['name']}: {g['status']} — {g['role']}\")
print(f\"Summary: critical={d['guardian_policy']['summary']['critical']} warning={d['guardian_policy']['summary']['warning']}\")
"
```

**Isa** — user/project neural guardian. Status esperado: `active`.
**Helo** — runtime/function guardian. Status esperado: `idle` (quando ocioso).
**Levi** — gated external knowledge acquisition. Status esperado: `armed`.

## Comparação com outras causas de SIGKILL (exit 137)

| Causa | SHA256 | `diff` entre PATH e release | `codesign` reporta | Crash report mostra | Fix |
|---|---|---|---|---|---|
| **PATH binary diverge** | Diferente | Crash (exit 137) | Normal (linker-signed) | Sem crash report (kernel mata antes) | `rm -f + cp` |
| **Stale MCP processes** | Igual | Funciona | Normal | — (MCP server morre, não o CLI) | `pkill -f "simplicio serve"` |
| **Debug binary OOM (101MB)** | N/A | N/A | Normal | OOM killer | Usar release binary (~28MB) |
| **macOS 26.3 code signing invalid** | Igual | Funciona — binários idênticos | Normal (linker-signed, válido) | `Taskgated Invalid Signature` + `Code Signature Invalid` | `codesign -f -s -` |

**Sinal infalível de código inválido:** crash report .ips com `Taskgated Invalid Signature`.
Se não houver crash report, provavelmente não é este caso.

## Prevenção

Adicionar ao cron job de health check semanal:

```bash
# Verificar códigos de assinatura
CODESIGN_CHECK=$(codesign -dvvv /Users/wesleysimplicio/.local/bin/simplicio 2>&1)
if echo "$CODESIGN_CHECK" | grep -q "not valid"; then
    echo "MEASURED| Código inválido! Re-assinando..."
    codesign -f -s - /Users/wesleysimplicio/.local/bin/simplicio
elif echo "$CODESIGN_CHECK" | grep -q "adhoc,linker-signed"; then
    echo "MEASURED| Assinatura ad-hoc válida"
fi

# Verificar crash reports recentes
RECENT_CRASHES=$(find ~/Library/Logs/DiagnosticReports -name "simplicio-*.ips" -mmin -1440 2>/dev/null | wc -l)
if [ "$RECENT_CRASHES" -gt 0 ]; then
    echo "UNVERIFIED| $RECENT_CRASHES crash report(s) nas últimas 24h — verificar"
fi
```

Ou, de forma mais simples, um probe de sanidade:

```bash
simplicio version >/dev/null 2>&1 || {
    echo "Simplicio binary crashing! Attempting re-sign..."
    codesign -f -s - "$(which simplicio)" && echo "Re-signed OK"
}
```
