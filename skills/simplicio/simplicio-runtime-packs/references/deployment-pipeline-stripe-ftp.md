# Stripe + Google Auth + FTP Deployment

## Credenciais (NUNCA capturar em memória ou skills)
Stripe keys, AbacatePay keys, FTP password, Google OAuth secrets — guardar em `config.php` no servidor.

## Landing page + Stripe checkout (PHP)
```
/public_html/simplicio/
├── index.html          → Landing page
└── api/
    ├── config.php      → Chaves Stripe + AbacatePay
    └── checkout.php    → POST: Stripe Checkout Session + 7 dias grátis
```

### checkout.php (POST /api/checkout.php)
```php
curl -X POST https://api.stripe.com/v1/checkout/sessions \
  -u STRIPE_SECRET: \
  -d "mode=subscription" \
  -d "line_items[0][price]=price_pt_br_brl" \
  -d "line_items[0][quantity]=1" \
  -d "subscription_data[trial_period_days]=7" \
  -d "success_url=https://simpleti.com.br/simplicio/obrigado" \
  -d "cancel_url=https://simpleti.com.br/simplicio/"
```
Retorna `{url}` para redirecionar ao Stripe Checkout.

### AbacatePay (fallback BR)
API key + webhook secret no config.php. Preço R$ 99/mês.

## FTP upload
```bash
curl -T arquivo.php ftp://ftp.simpleti.com.br/public_html/simplicio/ \
  --user "wesley@simpleti.com.br:<senha>"
```
Senha contém `!` — usar aspas no `--user`.

## Desktop .dmg build pipeline (Node 26)
```bash
export PATH="/opt/homebrew/bin:$PATH"  # Node 26
cd ~/Projetos/ai/simplicio-agent/desktop
cargo build --release -p simplicio  # runtime
rm -rf node_modules && npm install   # se native binding error
node --input-type=module -e "import{build}from'vite';await build({configFile:'./vite.config.mjs'});"
npx electron-builder build --mac --config
```
Output: `release/Simplicio-Agent-*-arm64.dmg` + `*-x64.dmg`

### Erros comuns no build
- `electron is only allowed in devDependencies` → mover para devDependencies
- `@tailwindcss/oxide native binding` → remover tailwindcss do config (CSS puro)
- `ESM file cannot be loaded by require` → usar `vite.config.mjs` (não .ts)
