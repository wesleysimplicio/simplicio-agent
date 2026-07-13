# STT/TTS por Idioma — Tabela Completa

## Prioridades

| Prioridade | Quando usar | Recomendação |
|---|---|---|
| 1 — Máxima leveza + acurácia | EN, ES, PT-BR | Distil-Whisper fine-tunes |
| 2 — Asiáticos | JP, KO, ZH | Moonshine (edge optimized) |
| 3 — Menos comuns | RU, HI, AR, HE, PL, FR, IT, ID, MS | whisper.cpp quantizado |

## TTS (todos os idiomas)

**Piper TTS** — mais leve, cross-platform, funciona em 8GB.
Fallback: Edge TTS (cloud, gratuito).

## Tabela Completa STT

| Idioma | Modelo STT | Justificativa |
|---|---|---|
| pt-BR | freds0/distil-whisper-large-v3-ptbr | Fine-tune específico para português brasileiro |
| EN | distil-whisper/distil-large-v3 | Distil-Whisper padrão |
| ES | freds0/distil-whisper-large-v3-es | Fine-tune específico para espanhol |
| JP | Moonshine Japanese (Small/Medium) | Otimizado para edge, leve |
| KO | Moonshine Korean | Otimizado para edge, leve |
| ZH | Moonshine Mandarin | Otimizado para edge, leve |
| FR | distil-whisper/distil-large-v3 | Distil-Whisper multilingual |
| IT | distil-whisper/distil-large-v3 | Distil-Whisper multilingual |
| PL | distil-whisper/distil-large-v3 | Distil / Whisper multilingual |
| HI | openai/whisper-large-v3 (whisper.cpp) | Whisper via whisper.cpp |
| AR | openai/whisper-large-v3 (whisper.cpp) | Whisper via whisper.cpp |
| HE | openai/whisper-large-v3 (whisper.cpp) | Whisper via whisper.cpp |
| ID (Indonesian) | distil-whisper/distil-large-v3 ou Whisper quantizado | Distil / Whisper multilingual |
| MS (Malay) | distil-whisper/distil-large-v3 ou Whisper quantizado | Distil / Whisper multilingual |

## Critérios de Escolha

1. **Leve** — rodar em 8GB RAM sem travar
2. **Melhor acurácia possível no idioma** — fine-tune específico > multilíngue > quantizado
3. **Piper TTS** como padrão para todos os idiomas (mais leve que Edge)

## Regras de Retenção

- Áudio bruto (.mp3/.wav): **apagar após 24h** (cron `audio-cleanup-24h` ativo)
- Transcrição em texto: **manter para sempre** na SQLite neural
- Nunca perder o que foi dito, só o arquivo bruto de áudio

## Instalação

Configurado durante instalação desktop (3 cliques):
1. Detecta idioma do sistema
2. Baixa Piper TTS
3. Baixa STT conforme prioridade do idioma
4. Tudo configurado automaticamente
