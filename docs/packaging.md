# Packaging — Simplicio Agent

> **Issue:** #73 — [PACKAGING] Compilar Agent com Nuitka → binário standalone\
> **Status:** Resolvido — Nuitka é desnecessário. O runtime Simplicio já é compilado em Rust.

## Arquitetura de Packaging

O Simplicio Agent **já é um binário compilado em Rust** (`simplicio`). Não há código Python
para compilar com Nuitka. O packaging consiste em copiar o binário estático para o `$PATH`.

### O Binário

| Propriedade | Valor |
|---|---|
| **Binário** | `simplicio` |
| **Localização** | `~/.local/bin/simplicio` (ou qualquer diretório no `$PATH`) |
| **Formato** | Mach-O 64-bit arm64 (macOS) / ELF 64-bit (Linux) / PE (Windows) |
| **Tamanho** | ~27 MB (macOS arm64, stripped, LTO) |
| **Dependências** | Zero — binário totalmente estático |
| **Linguagem** | Rust compilado (source em `~/Projetos/ai/simplicio-runtime`) |

### Como funciona o packaging

1. O CI (`scripts/release.sh`, `scripts/publish-binary.sh`) compila o Rust com
   `cargo build --release` (LTO, strip, codegen-units=1).
2. Gera checksums SHA256 (`scripts/generate-checksums.sh`).
3. Faz upload dos binários para GitHub Releases.
4. Os manifests de atualização (`simplicio-update-manifest.json`) e checksums
   (`SHA256SUMS`) são publicados junto com a release.

### Nuitka — Por que NÃO usamos

A issue original (#73) pedia compilação com Nuitka porque o agente ainda era
Python. Desde a migração do runtime para Rust:

- **Não há Python para compilar.** O agente inteiro (runtime, CLI, MCP server,
  TUI) é Rust compilado.
- **Nuitka adicionaria complexidade** sem benefício: o binário Rust já é
  standalone, menor que um Nuitka build típico (~50MB+), e não precisa de
  Python ou venv instalado.
- **Cross-compilation** é feita com `cargo build --target`, não com Nuitka.

## Binários por Plataforma

| Plataforma | Asset name | SHA256 (v1.6.4) |
|---|---|---|
| macOS arm64 | `simplicio` | `50affbf647d9bb032049d7be86ce8f700b28ccec6df016d0c58cdcfd2d84db4c` |
| macOS x86_64 | `simplicio-darwin-x64` | `931975ba69ceae2e5ad71c895bc163e0ba996e5ed820b56cd8aa8a746b6d6e81` |
| Linux x86_64 | `simplicio-linux-x64` | `78337ef62b86f754755d1dbc474e532e9461a943785ddf34c6a8c92591bdb992` |
| Windows x86_64 | `simplicio.exe` | `93860620f29344251823ebb22e65702e904d39a987108c0a12874d5ea289dba0` |

## Self-Update

O runtime tem um subsistema de auto-update embutido:

```bash
simplicio update check        # verifica nova versão
simplicio update apply        # baixa e aplica atualização
simplicio update rollback     # volta para versão anterior
simplicio update status       # status do canal de update
```

O manifest de update é assinado com ed25519 e verificado pelo binário antes de aplicar.

## Referências

- `~/Projetos/ai/simplicio-runtime/scripts/release.sh` — script de release
- `~/Projetos/ai/simplicio-runtime/scripts/publish-binary.sh` — publish
- `simplicio update auto status --json` — status do auto-update
- `simplicio version --json` — versão atual
