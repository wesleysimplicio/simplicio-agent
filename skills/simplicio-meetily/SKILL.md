---
name: simplicio-meetily
description: "Integracao com Meetily — transcricao Parakeet 4x mais rapida que Whisper, diarizacao de falantes, sumarizacao Ollama"
version: 1.0.0
author: Simplicio Agent + Zackriya Solutions
source: https://github.com/Zackriya-Solutions/meetily
---

# Meetily — Skill de Integracao

## O que e

Meetily e um assistente de reunioes local (14K+ stars no GitHub) que usa **Parakeet** para transcricao ao vivo 4x mais rapida que Whisper, com diarizacao de falantes (SortFormer) e sumarizacao via Ollama.

## Padroes Absorvidos

| Pattern | Meetily | Simplicio |
|---|---|---|
| STT rapido | Parakeet (4x whisper.cpp) | Alternativa ao Distil-Whisper |
| Diarizacao | SortFormer + speaker labels | Voice diarization pipeline |
| Sumarizacao | Ollama (local LLM) | Simplicio loop + memoria neural |
| UI | Tauri (Rust + React) | Electron desktop |
| Offline-first | 100% local, zero cloud | Runtime nativo |

## Como usar

### Parakeet como STT alternativo
```bash
# Adicionar Parakeet ao pipeline de voz
simplicio voice --stt parakeet --model meetily-parakeet
```

### Diarizacao de falantes
```bash
# Transcrever com identificacao de quem falou
simplicio voice transcribe --diarize --input reuniao.wav
```

### Sumarizacao de reuniao
```bash
# Reuniao inteira → notas + pontos de acao
simplicio run "sumarizar reuniao" --input reuniao-transcrita.txt
```

## Proveniencia
- Repositorio original: https://github.com/Zackriya-Solutions/meetily
- Licenca: MIT
- Stars: 14K+
- Linguagem: Rust (backend) + Tauri (desktop)
