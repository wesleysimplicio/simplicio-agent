# PATH Binary Troubleshooting — Simplicio Runtime

> Sessão de 03/07/2026. Runtime v1.6.4, macOS arm64.

## Descoberta

O binário do Simplicio Runtime em `~/.local/bin/simplicio` estava 16 bytes maior que o
release em `target/release/simplicio` e crashava com SIGKILL (exit 137) em TODO comando.

### Cronologia de diagnóstico

```
1. simplicio doctor --json  →  Killed: 9  (exit 137)
2. simplicio version        →  Killed: 9  (exit 137)
3. simplicio --help         →  Killed: 9  (exit 137)

4. target/release/simplicio doctor --json  →  ✅ JSON completo, overall: warning
   → O release funciona. O PATH binary não.

5. which simplicio → /Users/wesleysimplicio/.local/bin/simplicio

6. SHA256:
   PATH: a814f4706079a92797a3babf152f5af15818e4e95d50f78f546f13f6d6df8a75
   REPO: 8ba02d9e827db16ad51350dab30855782156390439baa206e033eb32a5846c4f
   → DIFERENTES!

7. File sizes:
   PATH: 26,868,192 bytes (26MB)  — built Jul 3 13:48
   REPO: 26,868,176 bytes (26MB)  — built Jul 3 13:57
   → PATH é 16 bytes MAIOR que o release

8. Codesign: ambos "linker-signed" (adhoc), com.apple.provenance xattr presente em ambos.
   Nada anormal na assinatura.

9. diff PATH REPO → Killed: 9 (exit 137) — o kernel não consegue ler ambos os binários
   simultaneamente, indicando corrupção de inode ou página de memória.

10. cp PATH → /tmp/test-copy, /tmp/test-copy doctor --json → ✅ funciona.
    → O binário em si não é corrompido no disco, apenas o inode do PATH.
```

### Tentativa falha #1: overwrite cp

```bash
# ❌ NÃO FUNCIONOU:
cp target/release/simplicio ~/.local/bin/simplicio
# SHA256 continuava diferente! O inode manteve os dados antigos.
```

### Solução: rm -f + cp

```bash
# ✅ FUNCIONOU:
rm -f /Users/wesleysimplicio/.local/bin/simplicio
cp ~/Projetos/ai/simplicio-runtime/target/release/simplicio ~/.local/bin/simplicio
chmod +x ~/.local/bin/simplicio
```

**Verificação:**
- `simplicio version` → `simplicio-runtime 1.6.4`
- `simplicio doctor --json` → `overall_status: ok`
- SHA256 match: `8ba02d9e827db16ad51350dab30855782156390439baa206e033eb32a5846c4f` (ambos)

## Impacto no MCP

O `simplicio doctor --json` reportava:
```json
{
  "name": "mcp-host-registration",
  "status": "warning",
  "detail": "MCP server registered (~/.claude.json) but not responding to a stdio ping"
}
```

O MCP server em `~/.claude.json` estava configurado como:
```json
{
  "simplicio": {
    "command": "/Users/wesleysimplicio/.local/bin/simplicio",
    "args": ["serve", "--mcp", "--stdio"]
  }
}
```

O binário crashava antes de conseguir responder ao ping. Após corrigir o PATH binary,
o doctor passou a reportar:
```json
{
  "name": "mcp-host-registration",
  "status": "ok",
  "detail": "MCP server registered (~/.claude.json) and responding"
}
```

## Sinais de alerta

1. `simplicio` crasha com SIGKILL mas `target/release/simplicio` funciona
2. `diff` entre PATH e REPO binários crasha
3. SHA256 diverge (hash no PATH diferente do release)
4. Tamanho em bytes difere (mesmo que por poucos bytes)
5. `simplicio doctor --json` do release mostra `mcp-host-registration: warning`

## Prevenção

Health check semanal (cron job):
```bash
#!/bin/bash
# ~/.simplicio_agent/cron/path-binary-check.sh
REPO_BIN="$HOME/Projetos/ai/simplicio-runtime/target/release/simplicio"
PATH_BIN="$HOME/.local/bin/simplicio"

if [ ! -f "$REPO_BIN" ]; then
    echo "UNVERIFIED| Release binary not found at $REPO_BIN"
    exit 0
fi
if [ ! -f "$PATH_BIN" ]; then
    echo "UNVERIFIED| PATH binary not found at $PATH_BIN"
    exit 0
fi

REPO_SHA=$(shasum -a 256 "$REPO_BIN" | cut -d' ' -f1)
PATH_SHA=$(shasum -a 256 "$PATH_BIN" | cut -d' ' -f1)

if [ "$REPO_SHA" != "$PATH_SHA" ]; then
    echo "MEASURED| PATH binary divergiu do release! Corrigindo..."
    rm -f "$PATH_BIN"
    cp "$REPO_BIN" "$PATH_BIN"
    chmod +x "$PATH_BIN"
    echo "MEASURED| PATH binary corrigido. SHA256 agora: $(shasum -a 256 "$PATH_BIN" | cut -d' ' -f1)"
fi
```

Ou pós-build hook em `~/.cargo/config.toml`:
```toml
# Não há hook pós-build nativo no Cargo, mas pode-se usar um script wrapper:
# alias cargo='~/bin/cargo-with-postbuild'
```

## Referência cruzada

- `simplicio doctor --json` → `execution.binary` → mostra qual binário está em uso
- `simplicio doctor --json` → `health.checks[].mcp-host-registration` → diagnostica MCP
- `~/.claude.json` → `mcpServers.simplicio.command` → caminho do binário MCP
