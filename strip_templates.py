"""
Templates do Camera360 - cada um é um JSON em strip_templates/ com o tamanho
da saída, a cor de fundo e uma lista de camadas (imagem, texto, retângulo,
elipse e o quadro de mídia) - a ordem da lista é a ordem de empilhamento (a
última fica na frente). Dois tipos:

- "strip" (tirinha de fotos): papel (4x6, 2x6...) com N camadas "photo";
  quantas fotos o convidado tira = quantas camadas "photo" o template tem.
- "video" (arte do vídeo 360): tamanho de saída (9:16, 16:9, 1:1...) com
  exatamente UMA camada "video" (onde o vídeo aparece); camadas abaixo dela
  viram o fundo e as acima ficam por cima do vídeo.

Dado operacional da instalação (fica fora do git).
"""
import copy
import json
import os
import shutil
import uuid

TEMPLATES_DIR = "strip_templates"
ASSETS_DIR = "strip_assets"

KIND_STRIP = "strip"
KIND_VIDEO = "video"
KINDS = [KIND_STRIP, KIND_VIDEO]
KIND_LABELS = {KIND_STRIP: "Tirinha", KIND_VIDEO: "Vídeo 360"}

# Tamanho em pixels a 300 dpi, na orientação vertical.
PAPER_SIZES = {
    "4x6": (1200, 1800),
    "2x6": (600, 1800),
    "5x7": (1500, 2100),
    "6x8": (1800, 2400),
}
PAPER_CHOICES = ["4x6", "2x6", "5x7", "6x8", "custom"]
ORIENTATION_CHOICES = ["vertical", "horizontal"]

# Tamanho de saída (px) dos templates de vídeo.
VIDEO_SIZES = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
VIDEO_SIZE_CHOICES = ["9:16", "16:9", "1:1", "custom"]

LAYER_TYPES = {
    KIND_STRIP: ["photo", "image", "text", "rect", "ellipse"],
    KIND_VIDEO: ["video", "image", "text", "rect", "ellipse"],
}


def template_kind(template):
    return template.get("kind", KIND_STRIP)


def layer_types(kind):
    return LAYER_TYPES.get(kind, LAYER_TYPES[KIND_STRIP])


def paper_dimensions(paper, orientation, custom=None):
    """(largura, altura) em px. Em 'custom', vale exatamente o (largura,
    altura) digitado (a orientação é implícita nele)."""
    if paper == "custom":
        width, height = custom or PAPER_SIZES["4x6"]
        return int(width), int(height)
    width, height = PAPER_SIZES.get(paper, PAPER_SIZES["4x6"])
    short, long_ = min(width, height), max(width, height)
    if orientation == "horizontal":
        return long_, short
    return short, long_


def video_dimensions(size, custom=None):
    if size == "custom":
        width, height = custom or VIDEO_SIZES["9:16"]
        return int(width), int(height)
    return VIDEO_SIZES.get(size, VIDEO_SIZES["9:16"])


def new_layer(layer_type, template):
    """Camada nova com tamanho/posição padrão razoáveis, centralizada."""
    tw, th = template["width"], template["height"]
    base = {"type": layer_type, "rotation": 0}
    if layer_type == "photo":
        w = int(min(tw, th) * 0.6)
        h = int(w * 2 / 3)
        base.update(slot=0, w=w, h=h)
    elif layer_type == "video":
        if tw >= th:
            base.update(w=int(tw * 0.9), h=int(th * 0.9))
        else:
            base.update(w=int(tw * 0.9), h=int(th * 0.6))
    elif layer_type == "text":
        size = max(24, int(th * 0.07))
        base.update(text="Seu texto", font="Segoe UI", size=size, bold=False, italic=False,
                    color="#000000", shadow_color="", shadow_distance=4,
                    w=int(tw * 0.6), h=int(size * 1.6))
    elif layer_type == "rect":
        base.update(fill="#ffffff", outline="", outline_width=0,
                    w=int(tw * 0.4), h=int(th * 0.2))
    elif layer_type == "ellipse":
        base.update(fill="#ffffff", outline="", outline_width=0,
                    w=int(min(tw, th) * 0.3), h=int(min(tw, th) * 0.3))
    else:  # image
        base.update(path="", w=int(min(tw, th) * 0.3), h=int(min(tw, th) * 0.3))
    base["x"] = (tw - base["w"]) // 2
    base["y"] = (th - base["h"]) // 2
    return base


def normalize_slots(template):
    """Numera as camadas de foto 1..N (mantendo a ordem dos números atuais,
    senão a ordem na lista) - sempre uma permutação, sem buracos."""
    photos = [layer for layer in template["layers"] if layer["type"] == "photo"]
    photos.sort(key=lambda layer: layer.get("slot") or 10 ** 6)
    for i, layer in enumerate(photos, start=1):
        layer["slot"] = i


def photo_slot_count(template):
    return sum(1 for layer in template["layers"] if layer["type"] == "photo")


def video_layer(template):
    """A camada do quadro de vídeo (ou None)."""
    for layer in template["layers"]:
        if layer["type"] == "video":
            return layer
    return None


def new_template(name, paper="4x6", orientation="horizontal", custom=None, kind=KIND_STRIP):
    if kind == KIND_VIDEO:
        size = paper if paper in VIDEO_SIZE_CHOICES else "9:16"
        width, height = video_dimensions(size, custom)
        paper, orientation = size, ("horizontal" if width >= height else "vertical")
        background = "#101114"
    else:
        width, height = paper_dimensions(paper, orientation, custom)
        background = "#ffffff"
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "kind": kind,
        "paper": paper,
        "orientation": orientation,
        "width": width,
        "height": height,
        "background_color": background,
        "layers": [],
    }


def _photo(x, y, w, h, slot):
    return {"type": "photo", "slot": slot, "x": x, "y": y, "w": w, "h": h, "rotation": 0}


def _layer(layer_type, template, **overrides):
    layer = new_layer(layer_type, template)
    layer.update(overrides)
    return layer


def _default_four_poses():
    t = new_template("4 poses, tira única (horizontal)", "4x6", "horizontal")
    margin, gap = 40, 20
    cell_w = (t["width"] - 2 * margin - gap) // 2
    cell_h = (t["height"] - 2 * margin - gap) // 2
    slot = 1
    for row in range(2):
        for col in range(2):
            t["layers"].append(_photo(margin + col * (cell_w + gap), margin + row * (cell_h + gap),
                                      cell_w, cell_h, slot))
            slot += 1
    text = new_layer("text", t)
    text.update(text="Nome & Nome", size=150, bold=True, color="#ffffff",
                shadow_color="#000000", shadow_distance=6)
    text["x"] = (t["width"] - text["w"]) // 2
    text["y"] = (t["height"] - text["h"]) // 2
    t["layers"].append(text)
    return t


def _default_one_large_three_small():
    t = new_template("1 grande + 3 pequenas (horizontal)", "4x6", "horizontal")
    t["layers"] += [
        _photo(130, 60, 1005, 670, 1),
        _photo(40, 787, 560, 373, 2),
        _photo(620, 787, 560, 373, 3),
        _photo(1200, 787, 560, 373, 4),
    ]
    text = new_layer("text", t)
    text.update(text="Seu evento", size=110, bold=True, w=560, h=200)
    text["x"], text["y"] = 1200, 260
    t["layers"].append(text)
    return t


def _default_video_portrait():
    t = new_template("Vídeo 9:16 com moldura", "9:16", kind=KIND_VIDEO)
    t["layers"] += [
        _layer("rect", t, x=30, y=250, w=1020, h=1220, fill="#00e0a0"),   # moldura (atrás do vídeo)
        _layer("video", t, x=40, y=260, w=1000, h=1200),
        _layer("text", t, text="Seu evento", size=110, bold=True, color="#ffffff",
               x=40, y=70, w=1000, h=150),
        _layer("text", t, text="Nome & Nome", size=80, color="#ffffff", shadow_color="#000000",
               x=40, y=1530, w=1000, h=140),
    ]
    return t


def _default_video_landscape():
    t = new_template("Vídeo 16:9 simples", "16:9", kind=KIND_VIDEO)
    t["layers"] += [
        _layer("video", t, x=0, y=0, w=1920, h=1080),
        _layer("text", t, text="Seu evento", size=72, bold=True, color="#ffffff", shadow_color="#000000",
               x=460, y=930, w=1000, h=110),
    ]
    return t


def _template_path(template_id):
    return os.path.join(TEMPLATES_DIR, f"{template_id}.json")


def save_template(template):
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(_template_path(template["id"]), "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)


def load_template(template_id):
    with open(_template_path(template_id), "r", encoding="utf-8") as f:
        template = json.load(f)
    template.setdefault("kind", KIND_STRIP)
    return template


def delete_template(template_id):
    path = _template_path(template_id)
    if os.path.isfile(path):
        os.remove(path)


def _scan_templates():
    result = []
    if not os.path.isdir(TEMPLATES_DIR):
        return result
    for name in os.listdir(TEMPLATES_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(TEMPLATES_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            result.append({"id": data["id"], "name": data["name"], "kind": data.get("kind", KIND_STRIP)})
        except Exception:
            continue
    return result


def list_templates(kind=None):
    """[{id, name, kind}] ordenado por nome (de um tipo ou de todos). Cria os
    templates de exemplo de cada tipo que ainda não tem nenhum."""
    items = _scan_templates()
    kinds_present = {item["kind"] for item in items}
    if KIND_STRIP not in kinds_present:
        save_template(_default_four_poses())
        save_template(_default_one_large_three_small())
    if KIND_VIDEO not in kinds_present:
        save_template(_default_video_portrait())
        save_template(_default_video_landscape())
    if len(kinds_present) < len(KINDS):
        items = _scan_templates()
    if kind is not None:
        items = [item for item in items if item["kind"] == kind]
    return sorted(items, key=lambda item: item["name"].lower())


def duplicate_template(template):
    copy_ = copy.deepcopy(template)
    copy_["id"] = uuid.uuid4().hex[:8]
    copy_["name"] = f"{template['name']} (cópia)"
    return copy_


def copy_asset(source_path):
    """Copia a imagem escolhida pra strip_assets/ - o template não depende
    do arquivo original continuar no mesmo lugar (mesmo padrão do
    event_manager.create_event pro PNG do evento)."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    ext = os.path.splitext(source_path)[1] or ".png"
    dest = os.path.join(ASSETS_DIR, f"{uuid.uuid4().hex[:8]}{ext}")
    shutil.copyfile(source_path, dest)
    return dest
