"""
Renderiza um template de tirinha (strip_templates.py) numa imagem. É o MESMO
código pro editor (prévia reduzida, com caixas coloridas no lugar das
fotos) e pra saída final (resolução cheia, com as fotos do convidado) - o
que se vê no editor é exatamente o que sai na tirinha.
"""
import functools
import os

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

# (regular, negrito, itálico, negrito+itálico) em C:\Windows\Fonts
_FONT_FILES = {
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Impact": ("impact.ttf", "impact.ttf", "impact.ttf", "impact.ttf"),
    "Comic Sans MS": ("comic.ttf", "comicbd.ttf", "comici.ttf", "comicz.ttf"),
    "Trebuchet MS": ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
}

# Cores dos quadros de foto no editor (mesma paleta das referências).
PLACEHOLDER_COLORS = ["#ef4444", "#a9d159", "#6fb6b9", "#3f4b54"]

_SUPERSAMPLE = 2


def _fonts_dir():
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def available_fonts():
    fonts_dir = _fonts_dir()
    return [name for name, files in _FONT_FILES.items()
            if os.path.isfile(os.path.join(fonts_dir, files[0]))]


@functools.lru_cache(maxsize=128)
def load_font(name, size, bold=False, italic=False):
    size = max(1, int(size))
    files = _FONT_FILES.get(name)
    candidates = []
    if files:
        index = (1 if bold else 0) + (2 if italic else 0)
        candidates += [files[index], files[0]]
    for fallback in _FONT_FILES.values():
        candidates.append(fallback[0])
    fonts_dir = _fonts_dir()
    for filename in candidates:
        path = os.path.join(fonts_dir, filename)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size=size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


@functools.lru_cache(maxsize=32)
def _open_image(path, mtime):
    return Image.open(path).convert("RGBA")


def _color(value, alpha=255):
    """'#rrggbb' -> (r, g, b, a); vazio -> None (sem cor)."""
    if not value:
        return None
    r, g, b = ImageColor.getrgb(value)[:3]
    return (r, g, b, alpha)


def _paste_rotated(canvas, layer_img, cx, cy, rotation):
    """Cola layer_img (RGBA) centralizada em (cx, cy), girada `rotation`
    graus no sentido horário (como a rotação na tela do editor)."""
    if rotation:
        layer_img = layer_img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    x = int(round(cx - layer_img.width / 2))
    y = int(round(cy - layer_img.height / 2))
    canvas.paste(layer_img, (x, y), layer_img)


def _placeholder(width, height, number, scale):
    color = PLACEHOLDER_COLORS[(number - 1) % len(PLACEHOLDER_COLORS)]
    img = Image.new("RGBA", (width, height), _color(color))
    draw = ImageDraw.Draw(img)
    big = load_font("Segoe UI", max(12, min(width, height) * 0.28))
    draw.text((width * 0.06, height * 0.04), str(number), font=big, fill=(255, 255, 255, 255))
    small = load_font("Segoe UI", max(9, min(width, height) * 0.09))
    label = f"{int(width / scale)}x{int(height / scale)}"
    draw.text((width * 0.97, height * 0.96), label, font=small, fill=(255, 255, 255, 255), anchor="rd")
    return img


def _render_photo(layer, photos, scale):
    w, h = max(1, int(layer["w"] * scale)), max(1, int(layer["h"] * scale))
    slot = layer.get("slot", 1)
    if photos is not None and 1 <= slot <= len(photos) and photos[slot - 1] is not None:
        return ImageOps.fit(photos[slot - 1].convert("RGBA"), (w, h), method=Image.LANCZOS)
    if photos is None:
        return _placeholder(w, h, slot, scale)
    return Image.new("RGBA", (w, h), (200, 200, 200, 255))


def _render_image(layer, scale):
    path = layer.get("path") or ""
    w, h = max(1, int(layer["w"] * scale)), max(1, int(layer["h"] * scale))
    if not os.path.isfile(path):
        img = Image.new("RGBA", (w, h), (120, 120, 120, 120))
        ImageDraw.Draw(img).rectangle([0, 0, w - 1, h - 1], outline=(255, 255, 255, 200))
        return img
    return _open_image(path, os.path.getmtime(path)).resize((w, h), Image.LANCZOS)


def _render_shape(layer, scale):
    ss = _SUPERSAMPLE
    w, h = max(1, int(layer["w"] * scale)), max(1, int(layer["h"] * scale))
    img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outline_w = int(layer.get("outline_width", 0) * scale * ss)
    outline = _color(layer.get("outline")) if outline_w > 0 else None
    box = [0, 0, w * ss - 1, h * ss - 1]
    kwargs = {"fill": _color(layer.get("fill")), "outline": outline, "width": max(outline_w, 0)}
    if layer["type"] == "ellipse":
        draw.ellipse(box, **kwargs)
    else:
        draw.rectangle(box, **kwargs)
    return img.resize((w, h), Image.LANCZOS)


def _render_text(layer, scale):
    text = layer.get("text", "")
    size = max(1, int(layer.get("size", 48) * scale))
    font = load_font(layer.get("font", "Segoe UI"), size, bool(layer.get("bold")), bool(layer.get("italic")))
    box_w, box_h = max(1, int(layer["w"] * scale)), max(1, int(layer["h"] * scale))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.multiline_textbbox((0, 0), text, font=font, align="center")
    shadow_color = _color(layer.get("shadow_color"))
    distance = int(layer.get("shadow_distance", 0) * scale) if shadow_color else 0
    pad = size // 4 + distance
    canvas_w = int(max(box_w, bbox[2] - bbox[0] + 2 * pad) + 1)
    canvas_h = int(max(box_h, bbox[3] - bbox[1] + 2 * pad) + 1)
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = (canvas_w / 2, canvas_h / 2)
    if shadow_color and distance:
        draw.multiline_text((center[0] + distance, center[1] + distance), text, font=font,
                            fill=shadow_color, anchor="mm", align="center")
    draw.multiline_text(center, text, font=font, fill=_color(layer.get("color", "#000000")),
                        anchor="mm", align="center")
    return img


def _render_video_placeholder(layer, scale):
    """Caixa escura com um ▶ - só aparece no editor; na saída final o vídeo
    ocupa esse lugar."""
    w, h = max(1, int(layer["w"] * scale)), max(1, int(layer["h"] * scale))
    img = Image.new("RGBA", (w, h), (20, 22, 27, 255))
    draw = ImageDraw.Draw(img)
    cx, cy, r = w / 2, h / 2, min(w, h) * 0.12
    draw.polygon([(cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r), (cx + r * 1.1, cy)], fill=(0, 224, 160, 255))
    label = f"VÍDEO {int(w / scale)}x{int(h / scale)}"
    small = load_font("Segoe UI", max(9, min(w, h) * 0.07))
    draw.text((w * 0.5, h * 0.96), label, font=small, fill=(200, 200, 205, 255), anchor="md")
    return img


def _layer_image(layer, photos, scale):
    kind = layer["type"]
    if kind == "photo":
        return _render_photo(layer, photos, scale)
    if kind == "video":
        return _render_video_placeholder(layer, scale)
    if kind == "image":
        return _render_image(layer, scale)
    if kind == "text":
        return _render_text(layer, scale)
    return _render_shape(layer, scale)


def render_template(template, photos=None, scale=1.0):
    """Imagem RGB do template na escala dada. `photos`: lista de imagens PIL
    (índice = número da foto - 1); None = modo editor (caixas numeradas no
    lugar das fotos; o quadro de vídeo também aparece como uma caixa)."""
    width = max(1, int(template["width"] * scale))
    height = max(1, int(template["height"] * scale))
    canvas = Image.new("RGB", (width, height), ImageColor.getrgb(template.get("background_color", "#ffffff")))
    for layer in template["layers"]:
        img = _layer_image(layer, photos, scale)
        cx = (layer["x"] + layer["w"] / 2) * scale
        cy = (layer["y"] + layer["h"] / 2) * scale
        _paste_rotated(canvas, img, cx, cy, layer.get("rotation", 0))
    return canvas


def _composite_rotated(canvas, layer_img, cx, cy, rotation):
    """Como _paste_rotated, mas pra canvas RGBA (composição alfa de verdade,
    pra manter a transparência das camadas que ficam na frente do vídeo)."""
    if rotation:
        layer_img = layer_img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    x = int(round(cx - layer_img.width / 2))
    y = int(round(cy - layer_img.height / 2))
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay.paste(layer_img, (x, y))
    return Image.alpha_composite(canvas, overlay)


def render_template_split(template, scale=1.0):
    """Template de vídeo em duas imagens: o FUNDO (cor + camadas abaixo do
    quadro de vídeo, RGB) e a FRENTE (camadas acima do quadro, RGBA com fundo
    transparente), mais o retângulo (x, y, w, h) do quadro de vídeo. O ffmpeg
    põe o vídeo entre as duas. Sem camada de vídeo, o retângulo é None."""
    width = max(1, int(template["width"] * scale))
    height = max(1, int(template["height"] * scale))
    back = Image.new("RGBA", (width, height),
                     ImageColor.getrgb(template.get("background_color", "#ffffff")) + (255,))
    front = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rect = None
    for layer in template["layers"]:
        if layer["type"] == "video":
            rect = tuple(int(round(layer[key] * scale)) for key in ("x", "y", "w", "h"))
            continue
        img = _layer_image(layer, None, scale)
        cx = (layer["x"] + layer["w"] / 2) * scale
        cy = (layer["y"] + layer["h"] / 2) * scale
        if rect is None:
            back = _composite_rotated(back, img, cx, cy, layer.get("rotation", 0))
        else:
            front = _composite_rotated(front, img, cx, cy, layer.get("rotation", 0))
    return back.convert("RGB"), front, rect


def save_strip(image, path):
    image.convert("RGB").save(path, "JPEG", quality=95, dpi=(300, 300))
    return path
