# Produção de Vídeo — Python Pillow + ffmpeg

Workflow para criar vídeos de demonstração/marketing sem depender de Node 22+ ou GPUs.

## Stack
- **Python Pillow** — geração de frames (imagens PNG)
- **ffmpeg** — composição do vídeo MP4/GIF
- **Formato:** 1080x1920 vertical (Reels/Shorts/TikTok) ou 1920x1080 horizontal

## Pipeline

```bash
# 1. Gerar frames
python3 render_video.py
# → /tmp/simplicio-frames/frame_%05d.png (900 frames = 30s a 30fps)

# 2. Compor MP4
ffmpeg -y -framerate 30 -i /tmp/simplicio-frames/frame_%05d.png \
  -c:v libx264 -pix_fmt yuv420p -preset medium -crf 23 \
  /tmp/output.mp4

# 3. Criar GIF (redes sociais)
ffmpeg -y -i /tmp/output.mp4 -vf "fps=10,scale=540:960" -c:v gif /tmp/output.gif
```

## Estrutura do script (render_video.py)

```python
from PIL import Image, ImageDraw, ImageFont

# Configurações
W, H = 1080, 1920  # vertical
FPS = 30
DURACAO = 30  # segundos
TOTAL_FRAMES = FPS * DURACAO

# Cores (dark theme tech)
BG = "#0a0a0f"
ACCENT = "#22d3ee"  # cyan
GREEN = "#34d399"    # green
VIOLET = "#a78bfa"   # violet
ROSE = "#fb7185"     # rose

def draw_bg(draw):
    draw.rectangle([0,0,W,H], fill=BG)

def draw_text(draw, text, y, font, color, center=True):
    bbox = draw.textbbox((0,0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2 if center else 100
    draw.text((x, y), text, font=font, fill=color)

def draw_card(draw, x, y, w, h, color, label, desc):
    draw.rounded_rectangle([x,y,x+w,y+h], radius=16, fill="#12121a", outline=color)
    draw_text(draw, label, y+20, font_m, color)
    draw_text(draw, desc, y+80, font_s, "#9898b0")

# Cenas temporizadas
for t in range(TOTAL_FRAMES):
    sec = t / FPS
    
    # Cena 1: Intro (0-5s)
    if sec < 5:
        draw_emoji(draw, "💚", 400, 120)
        draw_text(draw, "Título", 600, font_xl, ACCENT)
    
    # Cena 2: Feature cards (5-12s)
    elif sec < 12:
        # Aparecem um por um com fade
        phase = (sec - 5) / 7
        for i, (name, desc, color) in enumerate(cards):
            show = max(0, min(1, (phase - 0.2*i) * 3))
            if show > 0:
                draw_card(draw, 100, 700+i*200, W-200, 150, color, name, desc)
    
    # Cena 3: CTA (19-25s)
    elif sec < 25:
        draw_text(draw, "Pronto pra usar?", 500, font_xl, ACCENT)
        draw_text(draw, "curl ... install.sh | sh", 700, font_s, GREEN)
    
    # Salvar frame
    img.save(f"/tmp/frames/frame_{t:05d}.png")
```

## Fontes
- macOS: `/System/Library/Fonts/Helvetica.ttc` (títulos) e `Apple Color Emoji.ttc` (emoji)
- Linux: `DejaVuSans.ttf`
- Usar `try/except` com fallback pra `ImageFont.load_default()`

## Dicas
- 30s é o ideal para Reels/Shorts/TikTok
- Manter 4-5 cenas no máximo
- Cada cena: 1 ideia principal + transição suave
- Incluir CTA com preço nos últimos 5s
- GIF ~172KB, MP4 ~282KB para 30s em 1080x1920
