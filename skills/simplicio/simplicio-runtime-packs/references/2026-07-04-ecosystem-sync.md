# Cross-Repo Ecosystem Sync — 2026-07-04

## Contexto

Verificação de alinhamento de versões entre 6 repositórios Simplicio interconectados.
Diagnóstico + correção em 3 frentes paralelas.

## Projetos e versões encontradas

| Projeto | Versão repo | Versão instalada | Gap |
|---|---|---|---|
| simplicio-runtime | v1.6.6-2-g74e24ee5 (git), v1.6.5 (Cargo.toml) | v1.6.4 (PATH) | +1 release |
| simplicio/ (distribuição) | v1.6.4 (SHA256SUMS) | v1.6.4 | Desatualizado vs runtime |
| simplicio-mapper | v0.15.0 (pyproject.toml) | v0.5.0 (pip) | +10 releases |
| simplicio-agent | v0.23.0 | N/A | OK |
| simplicio-loop | OK | N/A | OK |
| simplicio-dev-cli | OK | N/A | OK |

## Fluxo de correção

### Diagnóstico (1 chamada paralela)

```bash
for dir in ~/Projetos/ai/*/; do
  [ -d "$dir/.git" ] && git -C "$dir" pull --ff-only
done
simplicio version
cat ~/Projetos/ai/simplicio/VERSION.md
grep ^version ~/Projetos/ai/simplicio-runtime/Cargo.toml
pip show simplicio-mapper 2>/dev/null
cat ~/Projetos/ai/simplicio/SHA256SUMS
```

### Correção 1 — Build runtime

```bash
cargo build --release  # background, notify_on_complete
```

### Correção 2 — Instalar mapper (PEP 668)

```bash
cd ~/Projetos/ai/simplicio-mapper
python3 -m pip install --user --break-system-packages -e .
```

### Correção 3 — Atualizar distribuição pública

```bash
cp target/release/simplicio ~/Projetos/ai/simplicio/simplicio
shasum -a 256 ~/Projetos/ai/simplicio/simplicio
# patch SHA256SUMS + VERSION.md
```

## Armadilhas críticas

### Stale MCP processes → SIGKILL no novo binário

**Sintoma:** `simplicio version` crasha exit 137 (SIGKILL) após copiar binário novo.
`file ~/.local/bin/simplicio` mostra `Mach-O 64-bit executable arm64` — binário válido.
`target/release/simplicio` funciona perfeitamente.

**Causa:** Dezenas de processos `simplicio serve --mcp --stdio` rodando com binário antigo.
O macOS mata o novo binário por pressão de recursos.

**Solução:**

```bash
pkill -f "simplicio serve"        # matar TODOS os MCP servers antigos
cp target/release/simplicio ~/.local/bin/simplicio
simplicio version                 # verificar
```

**Prevenção:** `pkill -f "simplicio serve"` antes de copiar PATH binary.

### PEP 668 — pip bloqueado no Homebrew Python

```bash
python3 -m pip install --user --break-system-packages -e .
```

### cargo build lock — matar órfãos

```bash
pkill -f "cargo build"
pkill -f "rustc.*simplicio"
rm -f target/.cargo-lock
cargo build --release
```

## Correções estruturais resultantes desta sessão

Após diagnosticar os gaps de sincronia, implementei as seguintes correções estruturais
para evitar que os mesmos problemas se repitam:

| Problema | Correção | Localização |
|---|---|---|
| LTO lento (10+ min full) | thin LTO como padrão, fat só via `RUSTFLAGS="-Clto=fat"` | `Cargo.toml` (commit `987c579`) |
| Release manual sujeita a erro | `scripts/release.sh` — bump + fat LTO build + tag + publish | `scripts/release.sh` |
| MCP servers acumulando (SIGKILL) | `scripts/clean-mcp.sh` — mata se >10 | `scripts/clean-mcp.sh` + cron `clean-mcp-orphans` (1h) |
| Versão Cargo.toml vs tag dessincronizada | `hooks/pre-push` — bloqueia push na main se versão < tag | `hooks/pre-push` |
| v1.6.5 publicado como v1.6.5 (deveria ser v1.6.6) | Bump Cargo.toml para 1.8.0 + PR #2917 mergeado | `Cargo.toml` → v1.8.0 |

**Lições:**
- Cargo.toml version DEVE ser bumpado ANTES de buildar (hook pre-push agora garante)
- thin LTO é permanente (build 3x mais rápido, perda desprezível)
- MCP cron job previne acúmulo de processos
- Release script evita esquecer assets ou SHA256SUMS

```bash
simplicio version                   # v1.6.6
simplicio-mapper --version          # 0.15.0
head -3 ~/Projetos/ai/simplicio/SHA256SUMS  # v1.6.6 + hash novo
grep "Current Version" ~/Projetos/ai/simplicio/VERSION.md  # v1.6.6
```
