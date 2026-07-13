# Simplicio Voice Server — Pattern de Implementação

## Origem

Implementado em 03/07/2026 a partir do [hf-realtime-voice](https://huggingface.co/spaces/smolagents/hf-realtime-voice) da HuggingFace (smolagents).

## Arquivos criados

| Arquivo | Tamanho | Descrição |
|---|---|---|
| `tools/voice_server.py` | 5.5 KB | Servidor FastAPI + WebSocket (OpenAI Realtime GA) |
| `tools/voice_cli.py` | 400 B | Entry point Python alternativo |
| `tools/voice/` | 264 KB (11 assets) | Frontend: index.html, main.js, style.css, ws/, ui/, worklets/ |
| `~/.local/bin/simplicio-voice` | 484 B | Entry point bash executável |

## Arquitetura do Voice Server

```
Browser ──WSS──▶ Simplicio Voice Server (FastAPI)
                     │
  GET /api/config    ├── HTTP REST: /api/config, /api/me, /health, /
  GET /api/me        │
  GET /health        │
  GET /              │
                     │
  WS /v1/realtime    └── WebSocket: OpenAI Realtime GA protocol
                           │
                      session.created
                           │
                      session.update
                           │
                      input_audio_buffer.append (PCM16 base64)
                           │
                      input_audio_buffer.commit
                           │
                      ┌────┴────┐
                      │  STT    │  transcription_tools (faster-whisper)
                      │  LLM    │  Ollama → litellm → echo fallback
                      │  TTS    │  tts_tool (Edge TTS) → ffmpeg PCM16
                      └────┬────┘
                           │
                      response.created
                      conversation.item.created
                      response.audio.delta (PCM16 24kHz base64)
                      response.done
```

## Protocolo WebSocket

Segue o protocolo OpenAI Realtime GA (WebSocket):

1. **server → client:** `session.created` — confirmação de conexão
2. **client → server:** `session.update` — configura voz, instruções
3. **server → client:** `rate_limits.updated`
4. **client → server:** `input_audio_buffer.append` — PCM16 16kHz base64
5. **client → server:** `input_audio_buffer.commit` — processar áudio
6. **server → client:** `response.created`
7. **server → client:** `conversation.item.created` (user transcript)
8. **server → client:** `input_audio_buffer.transcription.completed`
9. **server → client:** `conversation.item.created` (assistant reply)
10. **server → client:** `response.output_item.added`
11. **server → client:** `response.content_part.added`
12. **server → client:** `response.audio.delta` (PCM16 24kHz base64 chunks)
13. **server → client:** `response.audio.done`
14. **server → client:** `response.done`

## Pipeline de dependências (todas opcionais — degradam graciosamente)

1. **STT:** `tools.transcription_tools` → faster-whisper (local, gratuito)
2. **LLM:** Ollama (http://localhost:11434) → litellm (http://localhost:4000) → fallback echo
3. **TTS:** `tools.tts_tool` → Edge TTS CLI → ffmpeg PCM16

## Pitfalls encontrados

1. **`simplicio edit` corrompe hash de arquivos novos** — após `simplicio edit --plan` com `op: create`, o arquivo pode ter hash inconsistente. Sempre copiar de `/tmp/` como fix.
2. **Python PATH divergence** — processos background usam `~/.local/bin/python3.14` (sem pacotes) vs terminal usa `/opt/homebrew/bin/python3.14` (com pacotes). Usar caminho absoluto.
3. **StaticFiles mount ordering** — montar em `/` captura WebSocket. Registrar WS handler ANTES do mount.
4. **exc_info=True** em WebSocket handlers — adicionar `logger.error("...", exc_info=True)` para capturar exceções silenciosas dentro do loop WebSocket.

## Como usar

```bash
# Iniciar servidor (porta 7860)
simplicio-voice --port 7860 --debug

# Testar health
curl http://localhost:7860/health

# Testar WebSocket (requer websockets Python)
python3.14 -c "
import asyncio, json
from websockets import connect
async def t():
    async with connect('ws://localhost:7860/v1/realtime') as ws:
        print((await asyncio.wait_for(ws.recv(), 5))[:100])
asyncio.run(t())
"

# Dependências
pip install --break-system-packages fastapi uvicorn websockets aiohttp
```
