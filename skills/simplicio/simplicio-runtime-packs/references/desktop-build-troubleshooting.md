# Desktop Build Troubleshooting — macOS arm64

## ESM native binding error (@tailwindcss/oxide)

**Sintoma:** `Error: Cannot find native binding` com `@tailwindcss/oxide`.

**Causa:** O pacote foi instalado com Node 16 (x64) e as native bindings não são compatíveis com Node 26 (arm64 Apple Silicon).

**Solução — remover tailwindcss do vite config:**

```js
// vite.config.mjs — remover:
// import tailwindcss from '@tailwindcss/vite'
// plugins: [react(), tailwindcss()] → plugins: [react()]
```

Ou reinstalar tudo com Node 26+:
```bash
export PATH="/opt/homebrew/bin:$PATH"
rm -rf node_modules package-lock.json
npm install
```

## electron-builder package in wrong section

**Sintoma:** `Package "electron" is only allowed in "devDependencies"`

**Causa:** `electron` e `electron-builder` estavam em `dependencies` em vez de `devDependencies`.

**Solução:**
```bash
python3 -c "
import json
p = json.load(open('package.json'))
for dep in ['electron', 'electron-builder']:
    if dep in p.get('dependencies', {}):
        p.setdefault('devDependencies', {})[dep] = p['dependencies'].pop(dep)
json.dump(p, open('package.json', 'w'), indent=2)
"
```

## Build command (Node 26+)

```bash
export PATH="/opt/homebrew/bin:$PATH"
cd ~/Projetos/ai/simplicio-agent/desktop

# Step 1: Vite build
node --input-type=module -e "
import { build } from 'vite';
await build({ configFile: './vite.config.mjs', logLevel: 'warn' });
"

# Step 2: electron-builder (produz .dmg em release/)
npx electron-builder build --mac --config
```

Output em `release/`:
- `Simplicio-Agent-<version>-x64.dmg` (Intel)
- `Simplicio-Agent-<version>-arm64.dmg` (Apple Silicon)
