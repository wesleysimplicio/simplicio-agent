# Canais de Distribuicao — Simplicio Agent

> **Issue:** #76 — [DISTRIBUTION] Canais: Homebrew, npm, Docker, Electron, download direto
> **Status:** Resolvido — Homebrew tap, npm package, e download direto ja existem.

## Canais Existentes

### 1. Homebrew (macOS + Linux)

**Formula:** simplicio-binary.rb

```bash
brew tap wesleysimplicio/tap https://github.com/wesleysimplicio/simplicio.git
brew install simplicio
```

A formula baixa o binario pre-compilado da GitHub Release.
Suporta macOS (arm64 + x86_64) e Linux (arm64 + x86_64).

**Localizacao:**
- packaging/homebrew/simplicio-binary.rb no repo simplicio-runtime
- scripts/simplicio.rb no dist directory

### 2. npm (cross-platform)

**Package:** simplicio

```bash
npm install -g simplicio
```

O postinstall script detecta SO + arquitetura e baixa o binario correto.
Suporta darwin (arm64, x64), linux (x64), win32 (x64).

**Localizacao:** packaging/npm/ no repo simplicio-runtime.

### 3. Download Direto (todas as plataformas)

Binary releases em https://github.com/wesleysimplicio/simplicio/releases

| Plataforma | Asset |
|---|---|
| macOS arm64 | simplicio |
| macOS x86_64 | simplicio-darwin-x64 |
| Linux x86_64 | simplicio-linux-x64 |
| Windows x86_64 | simplicio.exe |

Checksums SHA256 em SHA256SUMS. Manifest de update assinado ed25519.

### 4. Docker

Dockerfile em ~/Projetos/ai/simplicio-runtime/Dockerfile.
Usa s6-overlay para supervisao. Docker-compose suportado.

### 5. PyPI (Python wrapper)

```bash
pip install simplicio
```

Wrapper Python para o binario compilado. packaging/pypi/.

## Canais Planejados (Nao implementados)

- AUR (Arch Linux) — PKGBUILD existe em packaging/aur/.

### 6. Electron desktop app

`desktop/` (electron-builder, mac/win/linux) existe e e mantido ativamente —
a linha acima ("Electron .app ainda nao existe") estava desatualizada. O app
spawna o backend Python (`simplicio-agent serve`) via venv; o kernel `simplicio`
(Rust) e resolvido por PATH (`tools/kernel_binding.py`, override
`HERMES_KERNEL_BIN`). Desde 2026-07-06, `npm run build:*`/`dist:*` em
`desktop/` tambem embala o binario `simplicio` do host
(`scripts/stage-runtime-bin.cjs` + a entrada `bin` em `extraResources`), e
`main.cjs` aponta `HERMES_KERNEL_BIN` pra ele quando presente — sem binario
staged, cai de volta pro PATH, sem quebrar instalacoes existentes. Testado
de ponta a ponta so em Linux (binario real, script de staging e
`buildDesktopBackendEnv` unit-testados); mac/win tem a mesma logica mas sem
CI que gere o binario nessas plataformas ainda (`release.yml` roda so em
`ubuntu-latest`).

## Auto-Update

```bash
simplicio update check
simplicio update apply
simplicio update rollback
simplicio update status
```

## Referencias

- packaging/homebrew/simplicio-binary.rb — Homebrew
- packaging/npm/package.json — npm
- packaging/pypi/pyproject.toml — PyPI
- packaging/aur/PKGBUILD — AUR
- scripts/release.sh — script de release
- simplicio-update-manifest.json — manifest de update
