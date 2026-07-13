# Controle de Tela macOS — cliclick + AppleScript

## cliclick (mouse/teclado)

```bash
# Instalar
brew install cliclick

# Usar (requer permissão de Acessibilidade)
cliclick c:400,300           # clicar em x,y
cliclick t:"texto"           # digitar texto
cliclick kd:cmd k:space ku:cmd  # tecla combo
cliclick w:100               # esperar 100ms
cliclick m:400,300           # mover mouse
```

**ATENÇÃO:** cliclick precisa de permissão:
System Preferences → Privacy & Security → Accessibility

## AppleScript (já tem permissão — usar primeiro)

```bash
# Navegar no Chrome real do usuário
osascript -e '
tell application "Google Chrome"
    activate
    tell window 1
        set URL of active tab to "https://google.com"
    end tell
end tell
'

# Fechar Chrome
osascript -e 'tell application "Google Chrome" to quit'
```

## screencapture (screenshot)

```bash
screencapture -C ~/Desktop/screenshot.png  # captura tela inteira
screencapture -R0,0,200,200 ~/Desktop/part.png  # captura região
```
