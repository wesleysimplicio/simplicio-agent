# MCP Guide — Conectando ao Simplicio Runtime (05/07/2026)

O Simplicio Runtime expõe 10 tools MCP via STDIO ou HTTP.

## Conexão STDIO (recomendada)
```json
{
  "mcpServers": {
    "simplicio": {
      "command": "simplicio",
      "args": ["serve", "--mcp", "--stdio"]
    }
  }
}
```

## Onde configurar
- **Claude Code**: `~/.claude/settings.json`
- **Cursor**: `~/.cursor/mcp.json`
- **VS Code**: `.vscode/mcp.json`
- **Cline**: `~/.config/cline/mcp_settings.json`
- **Continue**: `~/.continue/config.json`

## 10 Tools Expostas
| Tool | Descrição | Economia |
|---|---|---|
| `simplicio_map` | Orientação estrutural | ~80% tokens |
| `simplicio_memory` | Recall neural (FTS+vector) | ~90% |
| `simplicio_edit` | Edição determinística | 100% escrita |
| `simplicio_gate` | Gate de missão | — |
| `simplicio_validate` | Validação contratual | — |
| `simplicio_run` | Execução completa | ~60% |
| `simplicio_symbol` | Navegação de símbolos | ~50% |
| `simplicio_search` | Busca semântica | ~80% |
| `simplicio_read` | Leitura otimizada | ~70% |
| `simplicio_exec` | Shell compactado | ~60% |

## Verificação
```bash
simplicio runtime map --repo . --for-llm markdown
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | simplicio serve --mcp --stdio
```
