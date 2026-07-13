# GitHub Release Management — Simplicio Ecosystem

## Release vazia = install.sh 404

**Descoberto em:** 2026-07-04, sessão de sincronização de ecossistema.

Uma release tag no GitHub pode existir SEM assets (`gh release view v1.6.5 --json assets` → `"assets": []`).
Nesse estado, o `install.sh` que baixa de `/releases/latest/download/<asset>` retorna 404.

### Detecção

```bash
gh release view <tag> --repo wesleysimplicio/simplicio --json assets
# Se assets: [], a release está vazia mesmo que o body/tag exista
```

### Upload de assets

Após `cargo build --release`, copiar binários para `~/Projetos/ai/simplicio/` e fazer upload:

```bash
cd ~/Projetos/ai/simplicio

# SHA256SUMS e manifest
shasum -a 256 simplicio simplicio-darwin-x64 simplicio-linux-x64 simplicio.exe > SHA256SUMS

# Upload (sempre com --clobber para sobrescrever se já existir)
gh release upload v1.6.5 \
  simplicio \
  simplicio-darwin-x64 \
  simplicio-linux-x64 \
  simplicio.exe \
  SHA256SUMS \
  simplicio-update-manifest.json \
  --repo wesleysimplicio/simplicio \
  --clobber

# Nome que o install.sh procura (ver install.sh → ASSET_CANDIDATES)
cp simplicio simplicio-macos-arm64
gh release upload v1.6.5 simplicio-macos-arm64 --repo wesleysimplicio/simplicio --clobber
```

### Nomes de assets que o install.sh espera

Fonte: `grep ASSET_CANDIDATES ~/Projetos/ai/simplicio/install.sh`

| Plataforma | Asset name procurado |
|---|---|
| macOS ARM64 | `simplicio-macos-arm64` |
| macOS Intel (x86_64) | `simplicio-darwin-x64` |
| Linux x86_64 | `simplicio-linux-x64` |
| Windows x86_64 | `simplicio.exe` |

O install.sh faz loop com fallbacks: `simplicio-$OS-$ARCH` → `simplicio-macos-$ARCH`.

### Verificação de integridade

```bash
# 1. Redirect funciona?
curl -sI "https://github.com/wesleysimplicio/simplicio/releases/latest/download/simplicio-macos-arm64"
# → HTTP 302 = OK. HTTP 404 = sem asset.

# 2. SHA256 confere?
RELEASE_HASH=$(curl -sL "https://github.com/wesleysimplicio/simplicio/releases/download/v1.6.5/SHA256SUMS" | grep "simplicio$" | awk '{print $1}')
LOCAL_HASH=$(shasum -a 256 ~/Projetos/ai/simplicio/simplicio | awk '{print $1}')
[ "$RELEASE_HASH" = "$LOCAL_HASH" ] && echo "OK" || echo "DIVERGE: release=$RELEASE_HASH local=$LOCAL_HASH"
```

### Cadeia de distribuição (não confundir com MCP)

```
Site (simpleti.com.br/simplicio) → link "Download" → GitHub releases
  → release <tag> → assets (binários)
  → install.sh baixa de /releases/latest/download/<asset>
```

Quando o usuário pergunta "o site tem o binário?", verificar:
1. `gh release view <tag> --json assets` (assets existem?)
2. URL do link de download no site (para onde aponta?)
3. `curl -sI <download-url>` (HTTP 200/302 ou 404?)
4. SHA256 match entre asset baixado e binário local

⚠️ **Não** verificar `simplicio serve --mcp` ou `simplicio version` — são canais diferentes.
