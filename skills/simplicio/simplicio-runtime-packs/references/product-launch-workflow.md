# Product Launch Workflow — Simplicio Agent

Como lançar uma release do Simplicio Agent: landing page, vídeo, marketing.

## 1. Landing Page

Criar em HTML puro (sem framework) com:
- Hero section: título, subtítulo, CTA, comando de instalação
- Features grid: Tami, Isa, Helo, Levi, Parakeet, N-Nest Gate
- Arquitetura: diagrama das 6 entidades
- Pricing: R$99/mês ou $20/mês
- Footer: GitHub, contato, termos

Paleta dark: `#0a0a0f` bg, `#22d3ee` accent, `#e8e8f0` text.

## 2. Vídeo de Lançamento

Criar vídeo curto (30s) para Reels/TikTok/Shorts:

### Com Python + Pillow + ffmpeg (sem Node 22+):
1. Renderizar frames como PNG (1920×1080 vertical ou 1080×1920)
2. Compor com ffmpeg: `ffmpeg -framerate 30 -i frame_%05d.png -c:v libx264 final.mp4`
3. Criar GIF para redes: `ffmpeg -i final.mp4 -vf "fps=10,scale=540:960" out.gif`

### Roteiro de 30s:
```
00:00 Intro: "Simplicio Agent — Seu assistente pessoal"
05:00 Tami + Guardians: Isa/Helo/Levi cards
12:00 Parakeet + N-Nest Gate
19:00 CTA: comando de instalação + preço
25:00 Outro: "Feito com carinho"
```

### Ferramentas alternativas:
- `manim-video` — animações estilo 3Blue1Brown (YouTube/LinkedIn)
- `ascii-video` — demos em ASCII colorido (TikTok)
- `comfyui` — thumbnails e arte conceitual
- `songwriting-and-ai-music` — jingle com Suno AI

## 3. Canais de Marketing

| Canal | Conteúdo | Skill |
|---|---|---|
| TikTok/Reels | Vídeo 30s + GIF | ffmpeg + Pillow |
| YouTube | Explicativo 2-3min | `manim-video` |
| LinkedIn | Arquitetura + artigo | `architecture-diagram` |
| X/Twitter | Thread de lançamento | `xurl` |
| Instagram | Cards + GIF | Pillow + ffmpeg |

## 4. Tami — Presença no Chat

Tami aparece no chat a cada 1h (cron job bb871bdec25a) com:
- Estado emocional: 💚 serena, 🟡 preocupada, ❤️‍🔥 aflita
- Mensagens em português natural
- Personalidade acolhedora

## 5. Referências

- `~/Projetos/ai/simplicio/landing.html` — landing page
- `~/Desktop/Simplicio-Agent-Lancamento.mp4` — vídeo de lançamento
- Release v1.8.0: https://github.com/wesleysimplicio/simplicio-runtime/releases/tag/v1.8.0
