#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[SKILLS] Sistema de skills em markdown (como Hermes) — criar skills sem compilar Rust" \
'## Contexto

Hoje skills no Simplicio são código Rust compilado. Para criar uma skill nova: escrever Rust → compilar 2-5 min → registrar no dispatch. No Hermes, skills são arquivos `.md` com YAML frontmatter — sem compilação.

## O que precisa acontecer

1. **Diretório de skills markdown**: `~/.simplicio/skills/` e `.simplicio/skills/`
   - Arquivos `.skill.md` com frontmatter YAML
   - Auto-descoberta na inicialização
   - Hot-reload (mudou o arquivo, skill atualiza)

2. **`simplicio skill` comando**:
   ```
   skill list       # Lista skills
   skill show <n>   # Mostra conteúdo
   skill create     # Novo template
   skill edit <n>   # Edita
   skill search     # Busca semântica
   skill recall     # JÁ EXISTE — expandir
   skill import     # Importa de URL
   ```

3. **Engine de execução**:
   - Skill carregada como contexto do sistema
   - LLM lê a skill e segue instruções
   - Skills podem invocar outras (composição)
   - Scripts Python/Rust opcionais

4. **Skill memory** (`simplicio skill-memory`):
   - Já existe esboço! Expandir com SQLite-vec
   - Ranking por relevância à tarefa

5. **Loop de aprendizado**:
   - `simplicio learn to-skill "padrão"` extrai padrão como skill

## Arquitetura
- **Core Rust**: `simplicio skill` command, engine de carregamento, busca semântica
- **Skills markdown**: arquivos `.skill.md`, sem compilação
- **Scripts**: Python opcional para lógica (subprocess)

## Critérios de sucesso
- [ ] `simplicio skill list` mostra skills do diretório
- [ ] Criar skill = criar .skill.md, sem rebuild
- [ ] Hot-reload: disponível imediatamente
- [ ] Busca semântica funciona
- [ ] Skills compartilháveis entre projetos' \
"skills,prioridade-alta,hermes-parity"
