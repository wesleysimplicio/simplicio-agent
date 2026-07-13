# Monetization & Business Strategy — 2026-07-03

## Sistema de Licenciamento (já codificado, desligado)

O runtime tem um sistema completo de licenciamento via Stripe + Ed25519:

| Componente | Status | Localização |
|---|---|---|
| Stripe subscription | ❌ Desligado | `SIMPLICIO_STRIPE_ENTITLEMENT_ENDPOINT`, `SIMPLICIO_STRIPE_PRICE_OR_PRODUCT`, `SIMPLICIO_GOOGLE_LOGIN_ENABLED=true` |
| Google OAuth | ❌ Desligado | Provider google_gmail: enabled=false |
| License tokens | ✅ Codificado | `docs/STRIPE_SUBSCRIPTION.md` — Ed25519 keypair, webhook minting |
| Entitlement tiers | ✅ Codificado | free (always) → economy/pro (paid) em `simplicio license status` |
| Subscription check | ❌ Desligado | Roda na janela noturna mas não bloqueia |
| Auto-update | ✅ Ativo | Checa 2x/dia, baixa em background, aplica na próxima sessão |

### Para ativar:
1. Gerar authority keypair Ed25519 (substituir DEMO key em `src/license.rs`)
2. Criar Price no Stripe + Checkout link
3. Configurar webhook `invoice.paid` → mint token
4. Setar env vars: `SIMPLICIO_STRIPE_ENTITLEMENT_ENDPOINT`, `SIMPLICIO_STRIPE_PRICE_OR_PRODUCT`, `SIMPLICIO_GOOGLE_LOGIN_ENABLED=true`
5. Ativar Google OAuth: `simplicio login google`
6. Ligar subscription_check: `enabled=true` no auto-update config

## Modelo de Monetização

### Plano atual (landing page)
- **Pro:** R$49/mês ou R$499/ano
- **Free:** Deterministic commands sempre funcionam (map, validate, gate, edit)

### Posicionamento de venda
- **Valor principal:** Economia de 80-90% em tokens de IA
- **Problema que resolve:** Devs gastam R$200-2000/mês em tokens. Simplicio corta isso.
- **Público:** Devs que usam Claude Code, Codex, Cursor, Hermes — qualquer LLM/IDE

### Canais de venda identificados
1. **CLI subscription** — R$49/mês, self-serve
2. **Time consulting** — R$5000-15000 setup + treinamento
3. **Enterprise license** — R$10000-50000/ano, runtime privado
4. **Skill bundles** — R$999/ano, 120+ skills prontas
5. **Desktop app** — R$79/licença one-time

## Gaps para produto vendável
1. Stripe desligado — ninguém consegue pagar
2. Benchmarks existem em docs/benchmark/ mas NÃO estão na landing page
3. Landing page é feature-focused, não transformation-focused
4. MCP server precisa de auto-start (launchd/systemd)
5. Popup de atualização não existe
6. Google OAuth desligado — sem identidade de usuário
