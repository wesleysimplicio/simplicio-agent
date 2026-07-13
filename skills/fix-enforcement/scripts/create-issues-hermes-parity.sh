#!/usr/bin/env bash
# Continuation: Hermes parity extras (skills + tools + flexibilidade)
set -euo pipefail

REPO="${1:-wesleysimplicio/simplicio-runtime}"

create_issue() {
    local title="$1"
    local body="$2"
    local labels="$3"
    echo "Criando: $title"
    gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
    echo "---"
}

# ========================================================================
# ISSUE EXTRA 1: Skills em markdown (like Hermes)
# ========================================================================
create_issue \
"[SKILLS] Sistema de skills em markdown (como o Hermes) — criar skills sem compilar Rust" \
'## Contexto

Hoje, skills no Simplicio são **código Rust compilado** dentro do binário (ex: `skill_arxiv.rs`, `skill_github_code_review.rs`). Para criar uma skill nova, você precisa:

1. Escrever código Rust
2. Compilar o binário inteiro (~2-5 min)
3. Registrar no dispatch

Isso é extremamente pesado comparado ao Hermes, onde skills são **arquivos markdown** com YAML frontmatter que qualquer LLM ou humano pode criar em segundos.

## O que o Hermes tem

Hermes skills são arquivos `SKILL.md` com:
```yaml
---
name: minha-skill
description: "O que ela faz"
version: 1.0.0
---
# Conteúdo da skill em markdown

Passos, comandos, exemplos...
```

Sem compilação, sem rebuild, sem deploy — só criar o arquivo e a skill já está disponível.

## O que precisa acontecer no Simplicio

1. **Diretório de skills em markdown**: `~/.simplicio/skills/` e `.simplicio/skills/` (por projeto)
   - Skills são arquivos `.skill.md` com frontmatter YAML
   - Auto-descoberta na inicialização
   - Hot-reload (mudou o arquivo, a skill atualiza)

2. **`simplicio skill` comando**:
   ```
   simplicio skill list              # Lista skills disponíveis
   simplicio skill show <name>       # Mostra conteúdo
   simplicio skill create <name>     # Cria nova skill via template
   simplicio skill edit <name>       # Edita via $EDITOR
   simplicio skill search <query>    # Busca semântica nas skills
   simplicio skill recall "<task>"   # (já existe!) — rankeia skills relevantes
   simplicio skill import <url>      # Importa skill de URL
   simplicio skill publish <path>    # Publica no registry
   ```

3. **Engine de execução**:
   - Skill é carregada como contexto adicional do sistema
   - LLM lê a skill e segue as instruções
   - Skills podem invocar outras skills (composição)
   - Skills podem ter scripts Python/Rust associados

4. **Skill memory** (`simplicio skill-memory`):
   - Já existe esboço! Precisa ser expandido
   - SQLite-vec para busca semântica
   - Ranking por relevância à tarefa atual

5. **Integração com o loop de aprendizado**:
   - Skills aprendidas de trajectories viram skills markdown
   - `simplicio learn to-skill "padrão"` — extrai padrão como skill

## Arquitetura (Rust core + Python/markdown externo)

- Core em Rust: `simplicio skill` command, engine de carregamento, busca semântica
- Skills em markdown: arquivos `.skill.md` no filesystem, sem compilação
- Scripts associados: Python opcional para lógica mais complexa (via subprocess)

## Critérios de sucesso

- [ ] `simplicio skill list` mostra skills markdown do diretório
- [ ] Criar skill = criar arquivo .skill.md, sem rebuild
- [ ] Hot-reload: skills disponíveis imediatamente após salvar
- [ ] Busca semântica funciona (skill-memory)
- [ ] Skills podem ser compartilhadas entre projetos
- [ ] Tutorial: "Crie sua primeira skill em 30 segundos"' \
"skills,prioridade-alta,hermes-parity"

# ========================================================================
# ISSUE EXTRA 2: Hermes parity — tools, flexibilidade, plataformas
# ========================================================================
create_issue \
"[HERMES-PARITY] Alcançar paridade com Hermes em tools, flexibilidade e integração de plataformas" \
'## Contexto

O Hermes tem vantagens significativas sobre o Simplicio em várias áreas. Para o Simplicio ser um substituto completo, precisa alcançar paridade. Esta issue consolida todos os gaps identificados.

## Gaps atuais

### 1. Ferramentas e toolsets
| Funcionalidade | Hermes | Simplicio |
|---|---|---|
| Web search | ✅ Nativo (web_search) | ✅ `tools_web_search.rs` existe |
| Web extract | ✅ Nativo (web_extract) | ✅ `tools_web_extract.rs` existe |
| Browser automation | ✅ CDP nativo | `simplicio browser` existe mas CDP |
| Vision/image analysis | ✅ vision_analyze tool | ❌ Não tem |
| Image generation | ✅ image_generate tool | Plugin image_gen existe |
| TTS / STT | ✅ Nativo | ❌ Não tem |
| Skills hub | ✅ Hermes skills hub | ❌ Não tem |
| Cron jobs | ✅ Nativo com delivery | `simplicio cron` existe |
| MCP server | ✅ hermes mcp serve | `simplicio serve --mcp` existe |
| delegate_task | ✅ Subagentes com contexto isolado | `agents delegate` existe mas não testado |
| Session search | ✅ FTS5 no SQLite | ❌ Não tem |
| Memory management | ✅ Vários backends | `memory-v2` existe (SQLite+FTS5) |
| Checkpoints | ✅ Filesystem snapshots | ❌ Não tem |

### 2. Flexibilidade
| Funcionalidade | Hermes | Simplicio |
|---|---|---|
| Adicionar tool | 1 arquivo Python, reload | Compilar Rust (2-5 min) |
| Mudar provider/model | Imediato (/model) | Rebuild ou config |
| Gateway hot-swap | Imediato | Rebuild |
| Plugin system | Python plugins | Plugins em Rust compilados |
| Multi-profile | ✅ Profiles | `simplicio profile` existe |
| Config management | ✅ `hermes config set` | `simplicio config` existe |

### 3. Plataformas
Ambos têm 15+ plataformas de gateway, mas:

| Funcionalidade | Hermes | Simplicio |
|---|---|---|
| Adicionar nova plataforma | Minutos (Python adapter) | Dias (Rust compile + test) |
| Webhook subscriptions | ✅ Nativo | `webhook` comando existe |
| Multi-channel personas | ✅ channel_prompts | ❌ Não tem |
| Auto-reply config | ✅ free_response_channels | ❌ Não tem |

### 4. Comunidade/ecosistema
| Funcionalidade | Hermes | Simplicio |
|---|---|---|
| Skills catalog público | ✅ skills hub | ❌ Não tem |
| Docs completas | ✅ docusaurus site | ❌ Docs esparsas |
| Quick install | curl pipe bash | ✅ `simplicio install` existe |
| Contributing guide | ✅ CONTRIBUTING.md | ❌ Não tem |
| Test suite | ✅ 3000+ testes | ❌ Zero testes |

## O que precisa acontecer

### Fase 1: Gaps críticos (esse mês)
- [ ] Vision/image analysis tool (`tools_vision.rs`)
- [ ] TTS / STT tools
- [ ] Session search (FTS5 no SQLite de sessions)
- [ ] Skills em markdown (issue específica)
- [ ] Testes (issue específica)

### Fase 2: Gaps médios (próximo trimestre)
- [ ] Skills hub público
- [ ] Docs completas com docusaurus
- [ ] Checkpoints (snapshots de filesystem antes de edições)
- [ ] Hot-reload de tools (sem rebuild)
- [ ] Multi-channel personas no gateway

### Fase 3: Gaps de ecossistema (próximo semestre)
- [ ] Contributing guide + onboarding para contribuidores
- [ ] CI/CD completo
- [ ] Test suite com 1000+ testes
- [ ] Skills catalog com contribuição da comunidade

## Nota sobre arquitetura

> "Rust é motor central, mas camadas externas podem ser em Python"

Isso significa:
- Core de cada ferramenta em Rust (performance)
- Skills, scripts, adapters em Python/markdown (flexibilidade)
- Gateway em Rust (já está) com adapters em Python opcionais
- Plugin system em Python (como Hermes) para extensões rápidas' \
"hermes-parity,prioridade-média,ecossistema"

echo ""
echo "=== Issues extras criadas! ==="
echo ""
echo "Total: 12 issues criadas (1-6, 8-11 + 2 extras)"
echo "Pulei issue 7 (onboarding progressivo) conforme solicitado"
echo "Repo: $REPO"
