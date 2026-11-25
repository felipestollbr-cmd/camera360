"""
Sistema de design do Camera360: paleta derivada de UMA cor de marca, tipografia
e helpers de imagem (Pillow) pra suprir o que o Tkinter não tem: degradê,
cantos suaves com antialias, sombra borrada e confete.

`apply(cor)` troca a paleta - os widgets leem `theme.X` na hora de desenhar,
então chame antes de montar as telas (a marca vem do config.json / última
licença validada). Estilo "colorido e festivo": fundo escuro tingido pela
marca, destaque em degradê (marca -> +40° -> +80° de matiz) e confete.
"""
import colorsys
import functools
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULT_ACCENT = "#8b5cf6"  # violeta (vira degradê violeta -> magenta -> rosa)

FG_TEXT = "#f6f4fb"
DANGER = "#ff5470"
SUCCESS = "#4ade80"


# --- cores ----------------------------------------------------------------

def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _to_hls(value):
    r, g, b = (c / 255 for c in hex_to_rgb(value))
    return colorsys.rgb_to_hls(r, g, b)


def _from_hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, min(1, max(0, l)), min(1, max(0, s)))
    return rgb_to_hex((r * 255, g * 255, b * 255))


def mix(color_a, color_b, t):
    a, b = hex_to_rgb(color_a), hex_to_rgb(color_b)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def lighten(color, t):
    return mix(color, "#ffffff", t)


def darken(color, t):
    return mix(color, "#000000", t)


def luminance(color):
    r, g, b = (c / 255 for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _valid_hex(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) == 7 and value.startswith("#"):
        try:
            hex_to_rgb(value)
            return value.lower()
        except ValueError:
            return None
    return None


def apply(accent=None):
    """Recalcula toda a paleta a partir da cor de marca (inválida/vazia =
    cor padrão)."""
    global ACCENT, ACCENT2, ACCENT3, GRADIENT, TEXT_ON_ACCENT, PARTY
    global BG_ROOT, BG_PANEL, BG_CARD, BORDER, GHOST_BG, GHOST_HOVER, FG_MUTED, CURRENT_ACCENT

    CURRENT_ACCENT = _valid_hex(accent) or DEFAULT_ACCENT
    h, l, s = _to_hls(CURRENT_ACCENT)
    # mantém o destaque vivo e legível sobre o fundo escuro
    l = min(max(l, 0.45), 0.66)
    s = max(s, 0.6)
    ACCENT = _from_hls(h, l, s)
    # laranja/amarelo vão pra vermelho/rosa em vez de cair no verde-limão
    step = (-35 if 15 <= h * 360 < 75 else 35) / 360
    ACCENT2 = _from_hls(h + step, max(l, 0.55), max(s, 0.75))
    ACCENT3 = _from_hls(h + step * 2, max(l, 0.58), max(s, 0.8))
    GRADIENT = (ACCENT, ACCENT2, ACCENT3)
    TEXT_ON_ACCENT = "#ffffff" if luminance(ACCENT) < 0.62 else "#1a1330"

    BG_ROOT = _from_hls(h, 0.06, 0.32)
    BG_PANEL = _from_hls(h, 0.095, 0.30)
    BG_CARD = _from_hls(h, 0.13, 0.28)
    BORDER = _from_hls(h, 0.21, 0.24)
    GHOST_BG = _from_hls(h, 0.17, 0.26)
    GHOST_HOVER = _from_hls(h, 0.22, 0.28)
    FG_MUTED = mix(FG_TEXT, BG_CARD, 0.5)
    PARTY = ["#ffd23f", "#ff4f9a", "#3ec1ff", "#7cf29a", ACCENT, ACCENT2, ACCENT3]

    # imagens que usam cores da paleta "por padrão" ficam velhas se a marca mudar
    for cached in ("card_image", "festive_background"):
        func = globals().get(cached)
        if func is not None:
            func.cache_clear()


apply()


# --- tipografia -----------------------------------------------------------

FAMILY = "Segoe UI"
_PIL_FILES = {"normal": "segoeui.ttf", "semibold": "seguisb.ttf", "bold": "segoeuib.ttf", "black": "seguibl.ttf"}


def font(size, weight="normal"):
    """Fonte pro Tkinter. weight: normal | semibold | bold | black."""
    if weight == "black":
        return ("Segoe UI Black", size)
    if weight == "semibold":
        return ("Segoe UI Semibold", size)
    if weight == "bold":
        return (FAMILY, size, "bold")
    return (FAMILY, size)


@functools.lru_cache(maxsize=256)
def pil_font(size, weight="normal"):
    size = max(1, int(size))
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for filename in (_PIL_FILES.get(weight, "segoeui.ttf"), "segoeui.ttf", "arial.ttf"):
        path = os.path.join(fonts_dir, filename)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size=size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# --- imagens (Pillow) -----------------------------------------------------

@functools.lru_cache(maxsize=64)
def gradient_image(width, height, stops, direction="h"):
    """Degradê linear RGB. stops: tupla de cores hex; direction: h | v | d (diagonal)."""
    width, height = max(2, int(width)), max(2, int(height))
    if len(stops) == 1:
        stops = (stops[0], stops[0])
    colors = np.array([hex_to_rgb(c) for c in stops], dtype=np.float32)
    if direction == "h":
        t = np.tile(np.linspace(0, 1, width, dtype=np.float32), (height, 1))
    elif direction == "v":
        t = np.tile(np.linspace(0, 1, height, dtype=np.float32)[:, None], (1, width))
    else:
        xs = np.linspace(0, 1, width, dtype=np.float32)[None, :]
        ys = np.linspace(0, 1, height, dtype=np.float32)[:, None]
        t = (xs + ys) / 2
    pos = t * (len(stops) - 1)
    idx = np.clip(pos.astype(np.int32), 0, len(stops) - 2)
    frac = (pos - idx)[..., None]
    out = colors[idx] * (1 - frac) + colors[idx + 1] * frac
    return Image.fromarray(out.astype(np.uint8), "RGB")


_SS = 3  # supersampling dos cantos (antialias)


@functools.lru_cache(maxsize=256)
def rounded_image(width, height, radius, fill=None, outline=None, outline_width=0):
    """Retângulo arredondado RGBA com antialias. fill: hex, tupla de cores
    (vira degradê horizontal) ou None; outline: hex ou None."""
    width, height = max(2, int(width)), max(2, int(height))
    radius = max(0, min(int(radius), width // 2, height // 2))
    big = (width * _SS, height * _SS)
    mask = Image.new("L", big, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big[0] - 1, big[1] - 1], radius=radius * _SS, fill=255)
    mask = mask.resize((width, height), Image.LANCZOS)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if isinstance(fill, tuple):
        img.paste(gradient_image(width, height, fill, "h"), (0, 0), mask)
    elif fill:
        img.paste(Image.new("RGB", (width, height), fill), (0, 0), mask)
    if outline and outline_width:
        ring = Image.new("RGBA", big, (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle(
            [0, 0, big[0] - 1, big[1] - 1], radius=radius * _SS, outline=outline,
            width=int(outline_width * _SS))
        img.alpha_composite(ring.resize((width, height), Image.LANCZOS))
    return img


@functools.lru_cache(maxsize=64)
def shadow_image(width, height, radius, blur=14, alpha=120, color="#000000", pad=None):
    """Sombra borrada de um retângulo arredondado; a imagem é maior que o
    retângulo em `pad` px de cada lado (pra caber o borrão)."""
    pad = pad if pad is not None else blur * 2
    img = Image.new("RGBA", (int(width) + 2 * pad, int(height) + 2 * pad), (0, 0, 0, 0))
    r, g, b = hex_to_rgb(color)
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + width - 1, pad + height - 1],
                                          radius=radius, fill=(r, g, b, alpha))
    return img.filter(ImageFilter.GaussianBlur(blur))


@functools.lru_cache(maxsize=48)
def card_image(width, height, radius=22, margin=10, fill=None, border=None, shadow=True):
    """Cartão com sombra suave, preenchimento e borda finos, dentro de uma
    imagem width x height (a margem guarda a sombra)."""
    width, height = max(40, int(width)), max(40, int(height))
    fill = fill or BG_CARD
    border = border or BORDER
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    inner_w, inner_h = width - 2 * margin, height - 2 * margin - 2
    if shadow:
        sh = shadow_image(inner_w, inner_h, radius, blur=max(4, margin - 2), alpha=130)
        pad = max(4, margin - 2) * 2
        img.alpha_composite(sh, (margin - pad, margin - pad + 4))
    img.alpha_composite(rounded_image(inner_w, inner_h, radius, fill, border, 1), (margin, margin))
    return img


def glow_image(width, height, color, strength=0.5):
    """Mancha de luz suave (elipse borrada) pra decorar fundos."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    r, g, b = hex_to_rgb(color)
    # elipse bem dentro da imagem e blur menor que a margem: a borda termina
    # transparente (sem corte reto no fundo)
    ImageDraw.Draw(img).ellipse([width * 0.25, height * 0.25, width * 0.75, height * 0.75],
                                fill=(r, g, b, int(255 * strength)))
    return img.filter(ImageFilter.GaussianBlur(min(width, height) * 0.13))


def confetti_piece_image(size, color, shape):
    """Peça de confete RGBA (retângulo, círculo ou losango), pequena."""
    size = max(4, int(size))
    ss = 3
    img = Image.new("RGBA", (size * ss, int(size * ss * 0.6)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [0, 0, img.width - 1, img.height - 1]
    if shape == "circle":
        d.ellipse(box, fill=color)
    elif shape == "diamond":
        d.polygon([(img.width / 2, 0), (img.width - 1, img.height / 2),
                   (img.width / 2, img.height - 1), (0, img.height / 2)], fill=color)
    else:
        d.rounded_rectangle(box, radius=max(1, img.height // 5), fill=color)
    return img.resize((size, max(2, int(size * 0.6))), Image.LANCZOS)


@functools.lru_cache(maxsize=12)
def festive_background(width, height, accent, seed=7, confetti=True):
    """Fundo escuro com degradê diagonal tingido pela marca, luzes suaves e
    confete esparso. `accent` entra só na chave do cache (a paleta é global)."""
    width, height = max(64, int(width)), max(64, int(height))
    stops = (mix(BG_ROOT, ACCENT, 0.30), BG_ROOT, mix(BG_ROOT, ACCENT2, 0.26))
    img = gradient_image(width, height, stops, "d").convert("RGBA")
    glow_a = glow_image(int(width * 1.0), int(height * 1.0), ACCENT, 0.5)
    glow_b = glow_image(int(width * 0.9), int(height * 0.9), ACCENT2, 0.4)
    img.alpha_composite(glow_a, (-int(width * 0.3), -int(height * 0.35)))
    img.alpha_composite(glow_b, (int(width * 0.4), int(height * 0.3)))
    if confetti:
        rng = random.Random(seed)
        for _ in range(int(width * height / 22000)):
            piece = confetti_piece_image(rng.randint(8, 18), rng.choice(PARTY), rng.choice(("rect", "circle", "diamond")))
            piece = piece.rotate(rng.randint(0, 359), expand=True)
            piece.putalpha(piece.getchannel("A").point(lambda a: int(a * 0.35)))
            img.alpha_composite(piece, (rng.randint(0, width - piece.width), rng.randint(0, height - piece.height)))
    return img.convert("RGB")
