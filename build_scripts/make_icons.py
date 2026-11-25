"""Gera os ícones dos produtos (assets/<produto>.png e .ico) com o Pillow.

Cada produto tem um selo em degradê (cor do produto, ver product.py) com um
símbolo branco: Giro360 = órbita com seta em volta da lente; FotoCabine =
tira de fotos com brilho. Rode de novo se mudar as cores/símbolos:

    python build_scripts/make_icons.py
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import product  # noqa: E402
import theme  # noqa: E402

SIZE = 1024  # desenhado grande e reduzido (antialias)
WHITE = (255, 255, 255, 255)


def _badge(accent):
    theme.apply(accent)
    return theme.gradient_image(SIZE, SIZE, theme.GRADIENT, "d").convert("RGBA")


def _rounded_mask(radius):
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    return mask


def _shadowed(layer, offset=(0, 18), blur=22, alpha=90):
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha / 255)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, offset)
    out.alpha_composite(layer)
    return out


def _glyph_giro360(mid_color):
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, r, w = SIZE / 2, 318, 62
    start, end = 205, 205 + 292            # órbita quase completa, com folga pra seta
    d.arc([c - r, c - r, c + r, c + r], start=start, end=end, fill=WHITE, width=w)
    # ponta da seta (tangente no fim do arco)
    a = math.radians(end)
    tip_r = r
    px, py = c + math.cos(a) * tip_r, c + math.sin(a) * tip_r
    tx, ty = -math.sin(a), math.cos(a)      # direção do giro
    nx, ny = math.cos(a), math.sin(a)       # normal (pra fora)
    head, half = 120, 110
    d.polygon([(px + tx * head, py + ty * head),
               (px + nx * half, py + ny * half),
               (px - nx * half, py - ny * half)], fill=WHITE)
    # lente no centro
    lens = 150
    d.ellipse([c - lens, c - lens, c + lens, c + lens], fill=WHITE)
    inner = 100
    d.ellipse([c - inner, c - inner, c + inner, c + inner], fill=mid_color)
    core = 52
    d.ellipse([c - core, c - core, c + core, c + core], fill=WHITE)
    return _shadowed(layer)


def _sparkle(draw, cx, cy, size, fill):
    pts = []
    for i in range(8):
        a = math.radians(-90 + i * 45)
        rad = size if i % 2 == 0 else size * 0.28
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    draw.polygon(pts, fill=fill)


def _glyph_fotocabine(mid_color, accent_color):
    strip = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    sw, sh = 330, 700
    x0, y0 = (SIZE - sw) / 2, (SIZE - sh) / 2
    d.rounded_rectangle([x0, y0, x0 + sw, y0 + sh], radius=44, fill=WHITE)
    pad, gap = 38, 28
    fh = (sh - 2 * pad - 2 * gap) / 3
    for i in range(3):
        fy = y0 + pad + i * (fh + gap)
        d.rounded_rectangle([x0 + pad, fy, x0 + sw - pad, fy + fh], radius=22,
                            fill=mid_color if i != 1 else accent_color)
    strip = strip.rotate(-12, resample=Image.BICUBIC, center=(SIZE / 2, SIZE / 2))
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    layer.alpha_composite(strip)
    d2 = ImageDraw.Draw(layer)
    _sparkle(d2, 770, 262, 120, WHITE)
    _sparkle(d2, 262, 760, 64, WHITE)
    return _shadowed(layer)


def build(product_id):
    info = product.PRODUCTS[product_id]
    base = _badge(info["accent"])
    mid, accent = theme.ACCENT2, theme.ACCENT
    glyph = _glyph_giro360(mid) if product_id == "giro360" else _glyph_fotocabine(mid, accent)

    badge = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    badge.paste(base, (0, 0), _rounded_mask(230))
    # brilho suave no topo (acabamento de ícone)
    gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse([-200, -520, SIZE + 200, 440], fill=(255, 255, 255, 34))
    gloss = gloss.filter(ImageFilter.GaussianBlur(36))  # sem borda dura
    gloss.putalpha(Image.composite(gloss.getchannel("A"), Image.new("L", (SIZE, SIZE), 0), _rounded_mask(230)))
    badge.alpha_composite(gloss)
    badge.alpha_composite(glyph)

    out_dir = PROJECT / "assets"
    out_dir.mkdir(exist_ok=True)
    png = badge.resize((512, 512), Image.LANCZOS)
    png.save(out_dir / f"{product_id}.png")
    badge.save(out_dir / f"{product_id}.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                     (128, 128), (256, 256)])
    # imagens do assistente do instalador (Inno Setup): painel 164x314 e selo 55x55
    panel = theme.gradient_image(164, 314, (theme.darken(theme.ACCENT, 0.15), theme.ACCENT2, theme.ACCENT3), "d")
    panel = panel.convert("RGBA")
    panel.alpha_composite(png.resize((116, 116), Image.LANCZOS), (24, 70))
    d = ImageDraw.Draw(panel)
    font = theme.pil_font(24, "black")
    text = info["name"]
    width = d.textlength(text, font=font)
    d.text(((164 - width) / 2, 200), text, font=font, fill="white")
    sub_font = theme.pil_font(11, "semibold")
    sub = info["tagline"]
    d.text(((164 - d.textlength(sub, font=sub_font)) / 2, 236), sub, font=sub_font, fill=(255, 255, 255, 220))
    panel.convert("RGB").save(out_dir / f"{product_id}_wizard.bmp")
    small = Image.new("RGB", (55, 55), "white")
    small.paste(png.resize((55, 55), Image.LANCZOS), (0, 0), png.resize((55, 55), Image.LANCZOS))
    small.save(out_dir / f"{product_id}_small.bmp")
    print(f"ok: assets/{product_id}.png / .ico / _wizard.bmp / _small.bmp")


if __name__ == "__main__":
    for pid in product.PRODUCTS:
        build(pid)
    theme.apply(None)
