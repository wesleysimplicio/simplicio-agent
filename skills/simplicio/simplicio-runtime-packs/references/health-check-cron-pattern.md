# Health Check Cron Workflow — Ecossistema Simplicio

Consolidated one-liners for cron-driven ecosystem health checks.
Cada bloco é independente — pode ser executado isoladamente.

## 1. Runtime básico

```bash
simplicio version                     # deve responder em <5s
simplicio doctor --json > /tmp/doc.json; grep -E '"overall_status"|"version"' /tmp/doc.json
```

## 2. PATH binary integrity

```bash
REPO_SHA=$(shasum -a 256 ~/Projetos/ai/simplicio-runtime/target/release/simplicio 2>/dev/null | cut -d' ' -f1)
PATH_SHA=$(shasum -a 256 ~/.local/bin/simplicio 2>/dev/null | cut -d' ' -f1)
DIST_SHA=$(shasum -a 256 ~/Projetos/ai/simplicio/simplicio 2>/dev/null | cut -d' ' -f1)

echo "PATH=$PATH_SHA REPO=$REPO_SHA DIST=$DIST_SHA"
if [ "$REPO_SHA" != "$PATH_SHA" ] || [ "$REPO_SHA" != "$DIST_SHA" ]; then
  echo "WARNING: SHA256 divergence detected"
fi
```

## 3. MCP stale processes — detecção por idade

A armadilha: MCP processes acumulados com o mesmo `ELAPSED` time indicam
**connection storm** (cliente spamming conexões sem encerrar as anteriores).

```bash
# Contagem total
echo "MCP count: $(pgrep -f 'simplicio.*mcp' | wc -l)"

# Idade do mais antigo
ps -o pid,etime,command -p $(pgrep -f 'simplicio.*mcp' | tr '\n' ',') 2>/dev/null | sort -k2 | head -20

# Cluster por idade (detecta storm: N processos com ELAPSED idêntico)
ps -o etime= -p $(pgrep -f 'simplicio.*mcp' 2>/dev/null) 2>/dev/null | sort | uniq -c | sort -rn | head -5
```

**Sinais de storm:**
- 10+ processos com ELAPSED de segundos/minutos — storm ativo
- 10+ processos com ELAPSED idêntico (ex: todos `01:03:38`) — storm passado, processos órfãos

**Limpeza:**

```bash
pkill -f 'simplicio.*mcp'
```

## 4. Git divergence — todos os repositórios

```bash
for repo in \
  ~/Projetos/ai/simplicio-runtime \
  ~/Projetos/ai/simplicio \
  ~/Projetos/ai/simplicio-agent \
  ~/Projetos/ai/simplicio-mapper; do
  if [ -d "$repo/.git" ]; then
    cd "$repo"
    AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
    BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
    echo "$(basename $repo): ahead=$AHEAD behind=$BEHIND $(git rev-parse --short HEAD)"
  fi
done
```

**Padrão 1-ahead-1-behind:** ocorre após squash-merge sem sincronizar local.
Ambos os commits são do mesmo PR (PR mergido com squash, branch local manteve
pré-squash). Solução: `git reset --hard origin/main` (se não houver trabalho
local não-pusheado).

## 5. Distribuição — uncommitted changes after publish

Após `gh release upload`, a distribuição local acumula:

```bash
cd ~/Projetos/ai/simplicio
git status --short | grep -E 'SHA256SUMS|VERSION\.md|simplicio|manifest'
```

Se houver alterações, commitar e push:

```bash
cd ~/Projetos/ai/simplicio
git add SHA256SUMS VERSION.md simplicio simplicio-macos-arm64 simplicio-update-manifest.json
git commit -m "chore: sync distribution assets with release v<VERSION>"
git push origin main
```

## 6. GitHub release assets

```bash
gh release view $(gh release list --repo wesleysimplicio/simplicio --limit 1 --json tagName -q '.[0].tagName') \
  --repo wesleysimplicio/simplicio --json assets -q '.assets[].name'
```

**Assets esperados:** `SHA256SUMS`, `simplicio`, `simplicio-darwin-x64`, `simplicio-macos-arm64`, `simplicio-update-manifest.json`.

## 7. Load + memória

```bash
echo "load: $(uptime | awk -F'load averages:' '{print $2}')"
echo "disk: $(df -h / | tail -1 | awk '{print $4 " free (" $5 " used)"}')"
echo "mcp_pids: $(pgrep -f 'simplicio.*mcp' | wc -l)"
```

## 8. GGUF model path mismatch — detecção + fix

**Sintoma:** `simplicio doctor --json` mostra `overall_status: warning` com
`gguf-model: GGUF model absent at <path>` mesmo tendo o modelo em `~/.simplicio/models/`.
Comum após upgrade de runtime (ex: v1.6.6 → v1.9.0) quando o runtime muda a
resolução de `.simplicio/` — passa a checar o path do projeto (ex: `~/Projetos/ai/simplicio/.simplicio/models/`)
em vez de `~/.simplicio/models/`.

**Diagnóstico:**

```bash
# Modelo existe no home?
ls -lh ~/.simplicio/models/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf 2>/dev/null

# Modelo existe no path que o doctor reclama?
ls -lh ~/Projetos/ai/simplicio/.simplicio/models/ 2>/dev/null || echo "dir missing"

# Qual runtime_home o doctor reporta?
grep -E '"runtime_home"' /tmp/doc.json 2>/dev/null
```

**Fix — symlink (NUNCA copiar o GGUF — 1.2GB):**

```bash
# Criar diretório de modelos no projeto
mkdir -p ~/Projetos/ai/simplicio/.simplicio/models

# Symlink do modelo existente para o novo path
ln -sf ~/.simplicio/models/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf \
  ~/Projetos/ai/simplicio/.simplicio/models/

# Verificar
simplicio doctor --json > /tmp/doc2.json
grep -E '"overall_status"|"gguf"' /tmp/doc2.json
# overall_status deve ser "ok", gguf-model "ok"
```

**Regra:** symlink, não `cp`. O modelo GGUF tem 1.2GB — copiar desperdiça
espaço e tempo. O symlink resolve sem duplicar.

## 9. Post-detection auto-fix (cron mode)

Quando o cron detecta divergências, o fluxo de correção completo:

```bash
# A. Matar MCP velhos (previne SIGKILL no binário novo)
pkill -f "simplicio serve --mcp --stdio"
sleep 1

# B. Sincronizar PATH binary (rm -f, não só cp)
rm -f ~/.local/bin/simplicio
cp ~/Projetos/ai/simplicio-runtime/target/release/simplicio ~/.local/bin/simplicio
chmod +x ~/.local/bin/simplicio

# C. Verificar versão
simplicio version

# D. Verificar GGUF — se warning, criar symlink
simplicio doctor --json > /tmp/doc_fix.json
grep -q '"overall_status":"ok"' /tmp/doc_fix.json && echo "OK" || {
  echo "GGUF fix needed"
  mkdir -p ~/Projetos/ai/simplicio/.simplicio/models
  ln -sf ~/.simplicio/models/Qwen2.5-Coder-1.5B-Instruct-Q6_K_L.gguf \
    ~/Projetos/ai/simplicio/.simplicio/models/
  echo "GGUF fixed"
}

# E. Re-verificar doctor
simplicio doctor --json > /tmp/doc_final.json
grep -E '"overall_status"' /tmp/doc_final.json
```

## 10. Cron report format (structured table)

Após execução, reportar com tabela markdown:

```
## 📊 Relatório de Saúde — <data> <hora>

### ✅ Estado Geral: <ok|warning|error>

| Componente | Status | Detalhes |
|---|---|---|
| **Runtime** | ✅ vX.Y.Z | overall_status: ok |
| **PATH binary** | ✅ Sincronizado | de vA.B.C → vX.Y.Z |
| **MCP servers** | ✅ Limpos | N velhos mortos |
| **GGUF model** | ✅ OK | Presente |
| **Memória neural** | ✅ N MB | SQLite íntegro |
| **Disk** | ⚠️ N free / total | |
| **Load** | ⚠️ x / y / z | |

### 🔧 Ações Corretivas (N)
1. **🔄 PATH binary**: SHA256 divergia — corrigido
2. **🧹 Clean MCP**: N processos mortos
3. **🔗 Symlink GGUF**: doctor warning → ok

### ⚠️ Pendências
| Item | Detalhe | Sugestão |
|---|---|---|
| 1 commit não pushado | abc1234 | PR |
| Dist repo sujo | N modified + N untracked | Commit |
| Release missing | não encontrada | Publicar |
```

## One-shot completo (todos os checks)

```bash
echo "=== version ===" && simplicio version 2>&1
echo "=== doctor ===" && simplicio doctor --json > /tmp/doc.json && grep -E '"overall_status"|"version"' /tmp/doc.json
echo "=== sha256 ===" && REPO=$(shasum -a 256 ~/Projetos/ai/simplicio-runtime/target/release/simplicio 2>/dev/null | cut -d' ' -f1) && PATHB=$(shasum -a 256 ~/.local/bin/simplicio 2>/dev/null | cut -d' ' -f1) && echo "PATH=$PATHB REPO=$REPO" && [ "$REPO" = "$PATHB" ] && echo "SHA256: OK" || echo "SHA256: DIVERGENCE"
echo "=== mcp ===" && echo "count: $(pgrep -f 'simplicio.*mcp' | wc -l)" && ps -o etime= -p $(pgrep -f 'simplicio.*mcp' 2>/dev/null) 2>/dev/null | sort | uniq -c | sort -rn | head -3
echo "=== git ===" && for r in ~/Projetos/ai/simplicio-runtime ~/Projetos/ai/simplicio ~/Projetos/ai/simplicio-agent; do [ -d "$r/.git" ] && echo "$(basename $r): $(cd $r && git rev-list --count origin/main..HEAD 2>/dev/null)a $(cd $r && git rev-list --count HEAD..origin/main 2>/dev/null)b"; done
echo "=== load ===" && uptime
```
