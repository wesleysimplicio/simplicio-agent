# Voice Transcription Pipeline — Discord Messages

## Arquitetura

Fluxo de uma mensagem de voz do Discord até a transcrição chegar no agente:

```
Usuário envia áudio (Discord voice message)
    ↓
gateway.run on_message() — recebe o evento do Discord
    ↓
adapter.py on_message() — handler do discord.py
    ↓
adapter.py _handle_message() — processa o conteúdo da mensagem
    ↓
Detecta attachment de áudio com content_type="audio/ogg" ou None
    ↓
_check_: _is_discord_voice_message_attachment() verifica
  - is_voice_message attribute (discord.py nativo)
  - ou (duration + waveform) como fallback
    ↓
_cache_discord_audio() — baixa o OGG para ~/.simplicio_agent/audio_cache/
    ↓
transcribe_audio(cached_path) — transcreve via faster-whisper
    ↓
pending_text_injection = "[Transcricao da mensagem de voz]: <texto>"
    ↓
event_text = transcription + original_text
    ↓
Agente recebe o texto transcrito como se fosse texto digitado
```

## Patches Aplicados (adapter.py)

### Patch 1 — Transcrição após cache
Local: `~/.simplicio_agent/plugins/platforms/discord/adapter.py` (linha ~6001)
Adiciona chamada a `transcribe_audio()` após o áudio ser baixado e cacheado.
O resultado é injetado em `pending_text_injection` como `[Transcricao da mensagem de voz]: <texto>`.

### Patch 2 — msg_type VOICE quando content_type=None
Local: linha ~5926 no `else: msg_type = MessageType.DOCUMENT`
Corrige: quando `att.content_type` é None, verificar `_is_discord_voice_message_attachment()`
antes de classificar como DOCUMENT.

### Patch 3 — Processamento de áudio quando content_type=None
Local: linha ~5997 no `elif content_type.startswith("audio/")`
Adiciona condicional: `or (content_type == "unknown" and msg_type == MessageType.VOICE and is_voice_message)`
para que voice messages sem content_type ainda sejam processadas como áudio.

## Dependências

```bash
# Instalar no venv do gateway ANTES de iniciar
~/.hermes/hermes-agent/venv/bin/pip install faster-whisper
```

O `transcribe_audio()` em `tools/transcription_tools.py` usa:

1. `faster_whisper` (prioritário, detectado via `_HAS_FASTER_WHISPER`)
2. fallback: `openai-whisper` (quebrado: numba import error)

A detecção é feita no **import time** — se faster-whisper não estava instalado quando
o gateway iniciou, `_HAS_FASTER_WHISPER` é False e o gateway tenta whisper (quebrado).
**Solução:** instalar faster-whisper ANTES de iniciar o gateway.

## Teste de Transcrição Direto

```bash
~/.hermes/hermes-agent/venv/bin/python -c "
import sys
sys.path.insert(0, '/Users/wesleysimplicio/.hermes/hermes-agent')
from tools.transcription_tools import transcribe_audio
result = transcribe_audio('/path/to/audio.ogg')
print(result)  # {'success': True, 'transcript': '...', 'provider': 'local'}
"
```

## Cache de Áudio

- `~/.simplicio_agent/audio_cache/audio_<hash>.ogg` — arquivos de voz baixados
- `~/.hermes/audio_cache/` — cache legado
- Arquivos .ogg são mantidos (sem limpeza automática ainda)

## Logs de Gateway

- `~/.simplicio_agent/logs/gateway.log` — log principal do gateway
- Buscar por: `[Discord] Cached user audio`, `[Discord] Transcribed voice msg`, `Voice transcription failed`
- Para ver em tempo real: `simplicio_agent logs gateway -n 50`
