# Product Deployment: FTP + Stripe + .dmg Distribution

## FTP Upload (simpleti.com.br)

```bash
curl -T local/file.ext ftp://ftp.simpleti.com.br/public_html/simplicio/dest.ext --user "user:pass"
curl -Q "MKD /public_html/simplicio/pasta" ftp://ftp.simpleti.com.br/ --user "user:pass"
```

**Armadilhas:** Senhas com `!` quebram URL. Usar `--user "user:pass"`. `MKD` em path existente falha.

## Landing Page — Apple-style

Skill `popular-web-designs`, template `apple.md`. Hero: black bg, 56px h1, 2 CTAs (blue fill + outline). Nav: `rgba(0,0,0,0.8)` + `backdrop-filter: blur(20px)`. Seções alternam `#000` / `#f5f5f7`.

## Stripe Checkout

PHP: `mode: 'subscription'`, `trial_period_days: 7`. Config em `config.php`.

## .dMG Build

```bash
export PATH="/opt/homebrew/bin:$PATH"  # Node 26
cd ~/Projetos/ai/simplicio-agent/desktop
rm -rf node_modules package-lock.json && npm install
node --input-type=module -e "import{build}from'vite';await build({configFile:'./vite.config.mjs'})"
npx electron-builder build --mac --config
```

Vite config: `.mjs` (ESM), não `.ts` — plugins ESM-only. @tailwindcss/oxide falha em arm64 — remover se necessário.

## Onboarding

Nome, profissão, estuda?, país, idioma. Guardar em `observed_preferences`.
