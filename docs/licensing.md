# Licenciamento — Simplicio Agent

> **Issue:** #74 — [LICENSING] License key + hardware fingerprint + ativação online\
> **Status:** Resolvido — `simplicio license status --json` já existe com ed25519 signing.

## Sistema de Licenciamento Existente

O Simplicio Runtime já implementa um sistema completo de licenciamento no
módulo `src/license.rs` (~1071 linhas). Nada precisa ser criado do zero.

### Comando Principal

```bash
simplicio license status --json
```

Retorna o payload JSON:

```json
{
  "schema": "simplicio.license/v1",
  "state": "free_missing",
  "issued_at": 0,
  "expires_at": 0,
  "stripe_customer_id": "",
  "google_email": "",
  "signature": ""
}
```

O campo `state` combina tier + status (ex.: `pro_active`, `free_missing`,
`trial_active`, `expired`).

### Arquitetura

| Componente | Descrição |
|---|---|
| **License key format** | `base64url(payload).base64url(ed25519_signature)` |
| **Algoritmo** | Ed25519 (não AES) — verificação local pura, sem chamada de rede |
| **Validação** | 100% offline — usa chave pública embarcada no binário |
| **Grace period** | 3 dias sem verificação de expiração |
| **Tiers** | `free` → `trial` (7 dias) → `economy` ($10/mo) → `pro` ($20/mo) |

### Tiers e Features

| Tier | Acesso | Preço |
|---|---|---|
| `free` | Comandos determinísticos apenas (map, edit, gate, checkpoint) | Grátis |
| `trial` | Acesso completo por 7 dias | Grátis |
| `economy` | CLI + token-savings proof | $10/mês |
| `pro` | Economy + local LLM + managed remote routing | $20/mês |

### Hardware Fingerprint

A issue original pedia hardware fingerprint (CPU ID + MAC + board serial). O
sistema atual NÃO implementa hardware binding — usa **license key por email**
(Stripe customer ID + Google email). Isso foi uma decisão arquitetural:

- **Simplicidade:** sem DRM pesado, sem travar hardware
- **Portabilidade:** o usuário pode usar a mesma key em múltiplas máquinas
- **Offline-first:** a verificação é puramente local, sem telemetria

### Ativação Online vs Offline

| Cenário | Comportamento |
|---|---|
| **Com key válida** | Agent funciona normalmente |
| **Sem key** | Modo free (funcionalidade reduzida) |
| **Key expirada** | Bloqueia com mensagem clara |
| **Sem internet (grace)** | Funciona por 3 dias sem verificação |
| **Stripe integration** | Geração automática de key via webhook |

### Rotas Relacionadas

- **API REST:** `GET /api/license/status` — dashboard endpoint (mesmo payload)
- **TUI:** `/license` comando no TUI
- **Desktop:** `desktop_1250::LicenseStatusPayload` — ponte desktop

### Stripe Integration

O Stripe checkout gera a license key automaticamente via webhook. A chave
privada ed25519 vive **apenas** no ambiente do Stripe webhook
(`SIMPLICIO_LICENSE_SIGNING_KEY`). O binário nunca tem acesso à chave privada.

### Referências

- `~/Projetos/ai/simplicio-runtime/src/license.rs` — implementação completa
- `src/dashboard_command.rs` — rota `GET /api/license/status`
- `src/growth_stripe.rs` — primitivas Stripe
- `simplicio login google --json` — login Google para associação de licença
- `simplicio license status --json` — comando principal
