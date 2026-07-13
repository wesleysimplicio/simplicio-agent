# Browser Control — Técnicas da Sessão 03/07/2026

## AppleScript (Chrome real do usuário)

Funciona SEM CDP. Controla o navegador que o usuário está vendo.

```bash
# Navegar
osascript -e '
tell application "Google Chrome"
    activate
    tell window 1
        set URL of active tab to "https://google.com"
    end tell
end tell
'

# Pegar URL atual
osascript -e '
tell application "Google Chrome"
    return URL of active tab of window 1
end tell
'
```

## CDP (Chrome com debug port)

Chrome NÃO aceita `--remote-debugging-port` com perfil padrão (`~/Library/Application Support/Google/Chrome`).

**Sempre usar perfil TEMPORÁRIO:**
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/simplicio-chrome \
  --no-first-run --no-default-browser-check
```

⚠️ Copiar perfil real (`cp -R ~/Library/Application Support/Google/Chrome/Default /tmp/simplicio-chrome-profile`) funciona para cookies/logins mas Chrome morre após ~60s.

## Node.js + Playwright

```bash
# Node 16 do sistema é muito antigo (não aceita playwright)
# Usar Node 26 do Homebrew:
export PATH="/opt/homebrew/opt/node/bin:$PATH"
node --version  # 26.0.0

npm install playwright
npx playwright install chromium  # ~93MB

# Iniciar daemon
simplicio browser daemon start

# Navegar
simplicio browser navigate "https://google.com" --json
# Retorna: refs com elementos clicáveis (e1..eN)

simplicio browser click e7 --json
simplicio browser type e7 "texto" --json
simplicio browser press Enter --json
simplicio browser snapshot --json
```

⚠️ Google bloqueia headless com CAPTCHA (`/sorry/index`). Usar Chrome real para evitar.

## cliclick (mouse/teclado)

Requer permissão de Acessibilidade:
System Preferences → Privacy & Security → Accessibility

```bash
# Instalar: brew install cliclick
which cliclick  # /opt/homebrew/bin/cliclick

cliclick c:400,300   # click nas coordenadas X,Y
cliclick t:"texto"   # digitar texto
cliclick kd:enter ku:enter  # tecla Enter (formato correto)
```

⚠️ Sem permissão: `WARNING: Accessibility privileges not enabled. Many actions may fail.`

## computer-use (nativo do runtime)

Módulos no source:
- `src/computer_use.rs`
- `src/macos_computer_use.rs` (usa screencapture + cliclick + AppleScript)

Status: `disabled_by_policy (backend: none)` — backend macOS não compilado no binário.
Ativar:
```bash
export SIMPLICIO_COMPUTER_USE=1
export SIMPLICIO_COMPUTER_USE_BACKEND=macos
simplicio computer-use screenshot --json
```

Para recompilar com suporte:
```bash
cargo build --release --locked  # 20min
```

## Page Agent (Alibaba)

```bash
git clone https://github.com/alibaba/page-agent.git ~/Projetos/ai/page-agent
```

Bridge nativa: `src/page_agent_bridge.rs` (módulo Rust).
Injeção automática de LLM: SIMPLICIO_LLM_MODEL, SIMPLICIO_LLM_API_KEY, SIMPLICIO_LLM_BASE_URL (proxy).
