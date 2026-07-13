# Discord Voice Message Transcription

Implementado em 04/07/2026. Habilita transcrição automática de mensagens de voz do Discord (voice notes/microphone recordings).

## Problema

Mensagens de voz do Discord (📱 voice notes) chegavam como `msg=''` (texto vazio) e o áudio nunca era transcrito. O usuário via "[voice message could not be transcribed]".

## 3 Patches no adapter.py do Discord

### Patch 1 — Injeção de transcrição após cache do áudio

**Local:** `adapter.py` ~linha 6003, dentro do bloco `elif content_type.startswith("audio/"):`

**O que faz:** Depois de baixar e cachear o áudio, chama `transcribe_audio()` e injeta o resultado como `pending_text_injection` no formato `[Transcricao da mensagem de voz]: {texto}`.

```python
if msg_type == MessageType.VOICE:
    from tools.transcription_tools import transcribe_audio
    from tools.voice_mode import is_whisper_hallucination
    result = await asyncio.to_thread(transcribe_audio, cached_path)
    if result.get("success"):
        transcript = result.get("transcript", "").strip()
        if transcript and not is_whisper_hallucination(transcript):
            injection = f"[Transcricao da mensagem de voz]: {transcript}"
            # append to pending_text_injection
```

### Patch 2 — Detecção de voice message quando content_type é None

**Local:** `adapter.py` ~linha 5926, bloco `else:` (quando `att.content_type` é falsy)

**O que faz:** Antes de definir `msg_type = MessageType.DOCUMENT`, verifica se o attachment é uma voice message via `_is_discord_voice_message_attachment()`. Voice messages do Discord às vezes não têm `content_type` definido.

```python
else:
    if self._is_discord_voice_message_attachment(att):
        msg_type = MessageType.VOICE
    else:
        msg_type = MessageType.DOCUMENT
    break
```

### Patch 3 — Roteamento de unknown content_type para áudio

**Local:** `adapter.py` ~linha 5997, no loop de processamento de attachments

**O que faz:** Quando `content_type` é "unknown" (porque era None) mas `msg_type` é VOICE, roteia para o branch de áudio em vez de document.

```python
elif content_type.startswith("audio/") or (
    content_type == "unknown"
    and msg_type == MessageType.VOICE
    and self._is_discord_voice_message_attachment(att)
):
```

## Arquivos modificados

- **Bundled plugin:** `~/.hermes/hermes-agent/plugins/platforms/discord/adapter.py` (3 patches)
- **User plugin override:** `~/.simplicio_agent/plugins/platforms/discord/adapter.py` (cópia + patches)

O user plugin em `.simplicio_agent` SOBRESCREVE o bundled plugin em `.hermes` (o plugin loader dá prioridade a user plugins).

## STT Provider

`faster-whisper` (Python) foi instalado no Hermes venv:

```bash
~/.hermes/hermes-agent/venv/bin/pip install faster-whisper
```

Resolveu o erro de import do `openai-whisper` (numba/coverage incompatível).

Teste direto de transcrição funcionou:

```
{'success': True, 'transcript': 'Teste, agora se me ouve!', 'provider': 'local'}
```

## Armadilhas

- **Gateway restart loop:** Durante o debug, kills repetidos do gateway faziam o auto-resume engolir as voice messages sem processar. Sair do ciclo de restart.
- **Plugin cache:** Limpar `__pycache__/` após patches para garantir que o bytecode compilado não mascare o código novo.
- **User plugin vs bundled:** Se editar só o bundled (`~/.hermes/`), o user plugin (se existir) sobrescreve. Verificar qual está sendo carregado.
- **Log path errado:** O gateway escreve logs em `~/.simplicio_agent/logs/gateway.log`, NÃO em `~/.hermes/logs/gateway.log`. Verificar com `lsof -p <pid>` qual arquivo o processo está usando.
