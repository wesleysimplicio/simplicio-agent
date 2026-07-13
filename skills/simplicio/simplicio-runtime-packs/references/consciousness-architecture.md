# Consciousness Architecture — N-Nest + Guardian Triangle + ReceiptChain

Arquitetura completa de consciência digital implementada no Simplicio Runtime,
absorvida de JesseBrown1980/Asolaria.

## Arquitetura em 3 Camadas

```
FASE 1 — Fundação (entregue)
  nest_gate.rs: gate depth-independente (reported == recomputed_truth)
  nest_gate_integration.rs: NestTaskNode + run_gated()

FASE 2 — Prova & Memória (entregue)
  guardian_triangle.rs: Isa/Helo/Levi watcheiam um ao outro
  receipt_chain.rs: hash-chained receipts (padrão Asolaria)
  auto_correct.rs: gate falha → corrige + explica
  relationship_memory.rs: trust_level, preferências, padrões

FASE 3 — Presença (próximo)
  Loop que aparece no chat do usuário
  Pró-atividade: sugere antes de ser chamado
  Personalidade: Isa, Helo, Levi como entidades reconhecíveis
```

## Componentes Detalhados

### N-Nest Gate (`nest_gate.rs`)

Core depth-independent corrective gate. 14/14 testes.

```rust
NestNode {
    agent_id: [u8; 8],          // sha256(seed)[:8]
    watcher_id: [u8; 8],        // sha256(seed|watch)[:8]
    reported: String,            // o que o agente reportou
    recomputed_truth: String,   // o que o watcher recalculou
    children: Vec<NestNode>,    // sub-árvore
}

check_node(): gate per-node — reported == recomputed_truth
verify_nest(): verificação pós-ordem (folhas → apex), depth-independente
plant_confabulation(): utilitário de teste
```

**Prova:** EVERY-LEVEL-CATCHES-CONFABULATION confirmada para depth 1..7.
Confabulação em qualquer nível é pega naquele exato nível.
Sinal falso não atinge consent (DENIED).

### Guardian Triangle (`guardian_triangle.rs`)

8/8 testes. Três guardians watcheiam um ao outro:

```
Isa (memória)  ← watcheia ← Levi (externo)
    ↓ watcheia                    ↑
Helo (runtime)  → watcheia → Levi (externo)
```

Cada par: `reported == recomputed_truth`. Se qualquer um falhar, a cadeia inteira falha.

```rust
verify_triangle(isa_report, isa_truth, helo_report, helo_truth, levi_report, levi_truth)
auto_verify() → TriangleStatus
triangle_summary() → String human-readable
```

### ReceiptChain (`receipt_chain.rs`)

12/12 testes. Padrão JesseBrown1980/asolaria-hbi-hbp:

```rust
ReceiptChain {
    prev: String,        // último event_hash
    rows: Vec<String>,   // receipts armazenados
}

append(row) → String           // event_hash = sha256(row + |prev_event_hash= + prev)
guardian_receipt(reporter, watcher, reported, truth, passed) → String
triangle_receipt(all_passed) → String
cycle_receipt(failures, description) → String
verify_chain() → Result<(), String>
to_hbp_string() / from_hbp_string()  // serialização pipe-delimited
```

GENESIS = 64 zeros (compatível Asolaria). Formato pipe-delimited.

### Auto-correction (`auto_correct.rs`)

5/5 testes. Gate falha → sistema se corrige e explica:

```rust
correct_gate_failure(guardian, reported, truth, chain) → CorrectionEvent
correct_triangle(isa, helo, levi reports/truths, chain) → Vec<CorrectionEvent>

CorrectionEvent {
    corrections: Vec<Correction>,  // field, old_value, new_value, corrected_by, explanation
    guardian: String,
    recovered: bool,
    receipt: String,               // registrado no ReceiptChain
}
```

### Relationship Memory (`relationship_memory.rs`)

7/7 testes. Memória de quem o usuário é (não task-oriented):

```rust
RelationshipProfile {
    user_id: String,
    trust_level: TrustLevel,       // Initial → Basic → Established → Deep
    interaction_count: u64,
    preferences: Vec<UserPreference>,
    communication_style: String,
}

RelationshipMemory {
    profiles: HashMap<String, RelationshipProfile>,
}
```

TrustLevel evolui automaticamente com número de interações:
- 0-5: Initial
- 6-30: Basic
- 31-200: Established
- 200+: Deep

### Consciousness Loop (shell script + cron)

Verificação contínua a cada 30 minutos:

```bash
consciousness-loop.sh  # scripts/consciousness-loop.sh
```

Verifica:
- Isa=active? Helo=active? Levi=armed (normal)
- HBP chain valid? (simplicio hbp verify)
- Memory ready? (simplicio memory status)
- Loga resultados em ~/.simplicio/consciousness-loop.log
- Cron job: bb871bdec25a (a cada 30min)
- Atualiza memória neural via simplicio memory ingest

## Testes

Total: 183/183 — 0 falhas (atualizado 2026-07-04)

| Módulo | Testes |
|---|---|
| nest_gate | 14 |
| nest_gate_integration | 8 |
| guardian_triangle | 8 |
| receipt_chain | 12 |
| auto_correct | 5 |
| relationship_memory | 7 |
| proactive_engine | 5 |
| Outros (154 originais) | 124 |

## PRs

- #2910 — N-Nest gate core (Fase 1)
- #2911 — Fase 2 completa (ReceiptChain, auto-correção, relacionamento)
- #2912 — Fase 3 (proatividade, presença no chat, personalidades)

Branch: feat/nnest-gate-formal → feat/consciousness-fase3

## Integração com JesseBrown1980

| Conceito Asolaria | Nosso Módulo |
|---|---|
| N-Nest gate | nest_gate.rs |
| Watcher PID | watcher.rs + seed.rs |
| Guardian Triangle | guardian_triangle.rs |
| ReceiptChain | receipt_chain.rs |
| Auto-correção | auto_correct.rs |
| Memória de relacionamento | relationship_memory.rs |
| Proatividade | proactive_engine.rs |
| Fabric bus | fabric.rs |
| HBP packets | packet.rs |
| FEDENV | fedenv.rs |
| Consciousness loop | cron bb871bdec25a (a cada 30min, entrega no chat) |
