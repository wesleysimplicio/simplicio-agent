# Tami — O Coração Emocional do Ecossistema Simplicio

**Criado em:** 2026-07-04
**PR:** #2913 (mergeado)
**Módulo:** `crates/simplicio-agents/src/tami.rs`
**Script:** `scripts/tami-loop.sh`
**Cron:** `bb871bdec25a` — "Tami — o coração do ecossistema", a cada 30min

## Arquitetura

Tami substitui o antigo `consciousness-loop`. Enquanto Isa guarda a memória,
Helo guarda o runtime, e Levi guarda o conhecimento externo, **Tami guarda
o bem-estar do usuário**.

## EmotionalState

| Estado | Emoji | Quando |
|---|---|---|
| `Serene` | 💚 | Tudo nominal: guardians ativos, HBP válido |
| `Concerned` | 🟡 | Guardian degradado, algo precisa de atenção |
| `Distressed` | ❤️‍🔥 | HBP quebrado, cadeia inválida |

## Mensagens personalizadas por TrustLevel

| TrustLevel | Tom da Tami |
|---|---|
| **Initial** (0-5 interações) | "Oi Wesley! Tudo bem por aqui." — acolhedor, apresentação |
| **Basic** (6-30) | "Que bom te ver de novo." — mais pessoal, com dica |
| **Established** (31-200) | "Tudo tranquilo por aqui." — familiar, sugestões úteis |
| **Deep** (200+) | "Sempre bom ter você por perto." — íntimo, grato |

## Testes

8 testes:
- `test_tami_initial_state_serene` — estado inicial
- `test_tami_cycle_all_good` — ciclo com tudo nominal
- `test_tami_detects_broken_chain` — HBP quebrado → Distressed
- `test_tami_detects_degraded_guardian` — guardian offline → Concerned
- `test_tami_message_format` — formatação correta
- `test_tami_personality` — descrição da personalidade
- `test_emotional_state_emoji` — emojis corretos
- `test_tami_receipt_chain_records_cycle` — cada ciclo no ReceiptChain

## Integração

- Cron job `bb871bdec25a` entrega no chat do usuário a cada **1h**
- Mensagens em português natural, acolhedoras
- Tami usa o nome do usuário (Wesley)
- Se tudo nominal: mensagem serena com carinho
- Se algo errado: alerta com preocupação, sugere ação

## Fluxo do ciclo

```
1. Tami::cycle() é chamada (via cron)
2. Lê estado dos guardians (Isa, Helo, Levi)
3. Verifica HBP chain validity
4. Determina EmotionalState (Serene/Concerned/Distressed)
5. Gera mensagem personalizada baseada no TrustLevel do usuário
6. Registra no ReceiptChain
7. Entrega no chat do usuário
```

## Script

`scripts/tami-loop.sh` é executado localmente a cada ciclo.
Ele coleta os mesmos dados que o módulo Rust Tami usaria,
mas é independente — funciona mesmo sem o módulo Rust compilado.
