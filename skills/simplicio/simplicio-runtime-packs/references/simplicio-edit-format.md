# simplicio edit — Formato e Armadilhas

## Schema

```json
{
  "file": "caminho/absoluto/ou/relativo/ao/repo",
  "operations": [
    {
      "op": "replace",
      "find": "texto EXATO",
      "with": "novo texto"
    }
  ]
}
```

Ops disponíveis: `replace`, `replace_all`, `insert_before`, `insert_after`, `replace_line`.

## Armadilhas Comuns

### 1. "pattern not found" no find

**Causa:** o find não é exato. Diferenças comuns:
- Espaço vs tab na indentação
- Quebra de linha diferente (`\n` vs `\r\n`)
- Caractere escapado no JSON vs literal no arquivo

**Solução:** usar substring curto e único. Em vez de buscar 50 linhas de código, buscar:
```
"find": "#[cfg(feature = \"ureq\")]"
```
E substituir por string vazia (deleta a linha), depois fazer outro replace para o resto.

### 2. Strings muito grandes no shell

**Problema:** JSON inline no shell com blocos >200 chars causa problemas de escaping.

**Solução:** criar arquivo plano:
```bash
cat > /tmp/plan.json << 'ENDJSON'
{"file": "src/exemplo.rs", "operations": [
  {"op": "replace", "find": "A", "with": "B"}
]}
ENDJSON
simplicio edit --plan /tmp/plan.json --json
```

### 3. Escaping de aspas no shell

Para inline (funciona no bash/zsh):
```bash
simplicio edit '{"file":"x.rs","operations":[{"op":"replace","find":"texto","with":"novo"}]}'
```

Para strings com `"` dentro: usar `\"` no JSON:
```json
{"find": "#[cfg(feature = \"ureq\")]"}
```

### 4. Bloco grande para remover (função inteira)

Quando uma função inteira precisa ser removida, quebrar em operações:

1. Primeiro: encontrar a linha `#[cfg(feature = "X")]` e substituir por vazio
2. Segundo: encontrar a linha `#[cfg(not(feature = "X"))]` e substituir por vazio

Se houver código real atrás do cfg (que não compila sem a dep), substituir a função inteira + cfg + o stub cfg + stub por apenas o stub:

```
find: [cfg(feature = "X")] + função real + [cfg(not(feature = "X"))] + fn stub(
with: fn stub(
```

### 5. Verificação

```bash
cargo check 2>&1 | grep -c "error\["
# Deve retornar 0
```

### 6. Erro "pattern not found" com bloco multi-linha contendo `\\n`

Quando o find tem `\\n` (quebra de linha literal no JSON), `simplicio edit` pode não encontrar mesmo com o texto visualmente idêntico. **Solução:** usar `printf` para criar o JSON com quebras de linha reais:

```bash
printf '{
  "file": "src/arquivo.rs",
  "operations": [
    {
      "op": "replace",
      "find": "linha 1\\nlinha 2",
      "with": "nova linha"
    }
  ]
}' > /tmp/plan.json
```

Ou usar `jq` para construir o JSON corretamente com quebras de linha.

---

## Error Message Map — Roteiro de Resposta Rápida

Quando `simplicio edit` rejeita seu plano, a mensagem de erro **diz exatamente o que falta**. Use esta tabela para corrigir sem tentativa e erro:

| Erro | Causa | Correção |
|---|---|---|
| `plan must contain an "operations" array` | Usou `"edits"` em vez de `"operations"` | Trocar `"edits"` por `"operations"` |
| `operation 0 is missing string field "op"` | Falta `"op"` na operação | Adicionar `"op": "replace"` ou `"op": "create"` |
| `operation 0 is missing required string field "find"` | Usou `"old_string"` em vez de `"find"` | Trocar `"old_string"` por `"find"` |
| `operation 0 is missing required string field "with"` | Usou `"new_string"`, `"replace"`, ou outro nome | Trocar para `"with"` |

**Resumo do formato canônico em uma linha:**

```json
{"op":"replace","find":"texto exato","with":"novo texto"}
```

**NÃO usar:** `edits`, `old_string`, `new_string`, `replace_field`, `target`.  
**USAR:** `operations`, `op`, `find`, `with`.

---

## Comandos úteis

```bash
# Encontrar todas as ocorrências de cfg feature no repo
rg 'cfg\(feature\s*=\s*"' --type rust -n

# Ver linhas afetadas com contexto
cat -n src/arquivo.rs | sed -n 'LINHA_INICIO,LINHA_FIMp'

# Diff antes/depois de um replace (dry-run)
simplicio edit '{"file":"x","operations":[...]}' --dry-run --json
```
