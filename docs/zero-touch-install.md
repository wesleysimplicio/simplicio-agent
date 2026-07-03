# Zero-touch Install — `simplicio install --global`

O comando `simplicio install --global` (ou simplesmente `simplicio install`)
faz a instalação completa do Simplicio Agent com **zero toques**: copia o
binário, registra no PATH, configura adaptadores de assistente (Claude Code,
etc.) e prepara serviços.

## Uso

```bash
simplicio install          # modo dry-run (mostra o plano sem aplicar)
simplicio install --yes    # aplica a instalação para valer
```

## O que o instalador faz

1. **Copia o binário** para `~/.local/bin/simplicio`
2. **Registra no PATH** (verifica se `~/.local/bin` já está no PATH)
3. **Configura adaptadores de assistente**:
   - Claude Code (`~/.claude.json`)
   - MCP (Model Context Protocol)
   - HTTP local
   - STDIO
4. **Cria manifesto de rollback** — segurança com backup, diff e reversão

## Opções

| Flag | Descrição |
|------|-----------|
| `--yes` | Aplica a instalação (sem dry-run) |
| `--dry-run` | Mostra o plano sem escrever nada (padrão sem `--yes`) |
| `--help` | Mostra ajuda do comando |

## Modos de instalação

| Modo | Descrição |
|------|-----------|
| `local` | Instalação para o usuário atual em `~/.local/bin/` |
| `global` | (planejado) Instalação para todos os usuários do sistema |

## Verificação pós-instalação

```bash
simplicio doctor           # verifica runtime, política, adaptadores, modelo, repositório
simplicio doctor --repair  # tenta corrigir problemas detectados
simplicio runtime map      # mapeia o contexto do runtime
```

## Segurança

- O instalador faz **backup** dos arquivos existentes antes de modificar.
- Gera um **manifesto de rollback** para desfazer a instalação se necessário.
- Usa `diff` para mostrar exatamente o que mudou.

## Notas

- O comando `simplicio install` sem `--yes` executa em **dry-run** por padrão
  — mostrando o plano completo sem modificar nada.
- Para instalação real, adicione `--yes`: `simplicio install --yes`.
- A instalação é **idempotente** — pode ser executada múltiplas vezes sem efeitos
  colaterais.
