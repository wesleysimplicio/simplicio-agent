# Asolaria Integration — Pattern Extraction Methodology

2026-07-03 — Sessão de integração dos melhores conceitos do ecossistema JesseBrown1980.

## Princípio: Extrair conceitos, NÃO copiar código

Usuário corrigiu DURAMENTE: "Não é copiar tudo, é utilizar os melhores conceitos e aplicar no nosso."

**O ERRO:** Copiar arquivos inteiros de `federation-1024` para `src/asolaria/` sem adaptar. 21 arquivos mortos que não compilam.

**A CORREÇÃO:** Identificar o padrão, entender o problema que ele resolve, implementar uma versão adaptada ao nosso ecossistema.

```
❌ COPIA CEGA: rustc --edition 2021 src/asolaria/fedenv.rs → erro (no_std, alloc, sha2)
✅ EXTRACAO: ler fedenv.rs → entender envelope tipado → criar struct Envelope adaptada
```

## Os 5 padrões que valeram a pena

### 1. Watcher Gate (N-Nest-Prime)
**Problema:** Agente "acha" que fez algo mas não fez (alucinação em loops)
**Implementação:** `action_gate.rs` — função `watcher_verify()` que re-computa o resultado
**Ganho:** Anti-alucinação determinístico

### 2. Observation Lifecycle (ai-memory)
**Problema:** Cada skill/agente faz logging do seu jeito
**Implementação:** `telemetry.rs` — `ObservationKind` enum + `ObservationRegistry` + hooks
**Ganho:** Eventos padronizados, hookable

### 3. Writer Serialization (ai-memory)
**Problema:** `database locked` com 32 agents escrevendo em paralelo
**Implementação:** `store_writer.rs` — `WriterHandle` (1 thread) + `ReaderPool` (N readers)
**Ganho:** Zero database locked

### 4. Handoff entre agents (ai-memory)
**Problema:** Agente A para no meio, agente B recomeça do zero
**Implementação:** `handoff.rs` — `HandoffState` com stop_point, completed, next_planned, contexto
**Ganho:** Continuidade cross-agent

### 5. Glyph Addressing (BEHCS-256)
**Problema:** Identidade de agentes é string solta sem verificação
**Implementação:** `glyph.rs` — `sha256(input)[:8]` → base62
**Ganho:** ID determinístico de 8 bytes

## O que NÃO implementamos (por decisão consciente)

| Conceito | Motivo |
|---|---|
| Microkernel `no_std` 16 syscalls | Rodamos em macOS, não em RTOS |
| Cosign chain ed25519 | Crypto em cada ação é caro demais |
| Hookwall 64 slots | Não temos 64 tools |
| 7-tier AccessTier | Não temos caso de uso |
| Peer FSM 7 estados | Lifecycle binário serve |
| Lock-free MPMC 100K env/s | Não temos 100K agents |

## Metodologia de extração de padrões

### Passo 1: Identificar o padrão
- Ler README + arquivos principais do repositório fonte
- Entender qual problema específico ele resolve
- Verificar se JÁ temos equivalente no runtime

### Passo 2: Extrair o conceito
- Isolar a essência do padrão (2-3 parágrafos)
- Identificar as structs/enums/funções centrais
- Ignorar detalhes de implementação específicos do contexto fonte

### Passo 3: Implementar adaptado
- Usar apenas stdlib (não copiar dependências externas)
- Adaptar para nossa arquitetura (async, tokio, macOS)
- Criar no módulo correto (não em `src/asolaria/`)

### Passo 4: Verificar
- `cargo check --lib` — zero erros
- Testes unitários passando
- Nome dos módulos não conflita com existentes (E0428)

## Problemas comuns de compilação

### E0428 — nome definido múltiplas vezes
Quando dois módulos definem o mesmo tipo (ex: `telemetry.rs` define `ObservationKind` e `asolaria/observation.rs` também).
**Solução:** O módulo `telemetry` já existe em `src/infra/mod.rs`. Não declarar `pub mod telemetry;` no `lib.rs`.

### E0369 — PartialEq faltando em genérico
Função genérica usa `==` mas constraint só tem `Display`.
**Solução:** Adicionar `+ PartialEq` na constraint.

### E0204 — Copy em tipo com String
Enum com `Other(String)` não pode derivar `Copy`.
**Solução:** Remover `Copy`, manter `Clone`.

### E0119 — trait duplicado no derive
`#[derive(Debug)]` aparece duas vezes no mesmo struct.
**Solução:** Remover duplicata.

## simplicio edit — formato (validado nesta sessão)

```json
{
  "file": "caminho/absoluto/para/arquivo.rs",
  "operations": [
    {"op": "replace", "find": "texto EXATO para encontrar", "with": "texto substituto"},
    {"op": "replace_all", "find": "texto", "with": ""},
    {"op": "insert_after", "find": "texto", "text": "texto a inserir depois"},
    {"op": "create", "text": "conteudo COMPLETO do arquivo"},
    {"op": "append", "text": "texto a adicionar no final"}
  ]
}
```

**Regras:**
- `create` espera campo `text` (não `with`)
- `replace` espera `find` + `with` (não `old_string`/`new_string`)
- `insert_after` espera `find` + `text` (não `insert`)
- Find deve ser **exato** — case-sensitive, espaços, quebras de linha
- Se falhar ("pattern not found"), tentar substring menor e única
