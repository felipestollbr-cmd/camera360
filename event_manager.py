"""
Gerencia os "eventos" do totem (casamento, festa, etc.): cada um define o
formato de saída do vídeo (16:9/9:16/1:1) e uma marca opcional (texto e/ou
PNG) aplicada em toda captura enquanto esse evento estiver ativo. Guardado
em events.json, separado do config.json (que é a configuração fixa do
totem/motor/música, não algo que muda a cada evento).
"""
import copy
import json
import os
import shutil
import uuid

EVENTS_PATH = "events.json"
ASSETS_DIR = "event_assets"

DEFAULT_EVENTS_DATA = {"active_event_id": None, "events": []}

ASPECT_RATIO_CHOICES = ["16:9", "9:16", "1:1"]


def load_events(path=EVENTS_PATH):
    if not os.path.isfile(path):
        return copy.deepcopy(DEFAULT_EVENTS_DATA)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(DEFAULT_EVENTS_DATA)


def save_events(data, path=EVENTS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_active_event(data):
    active_id = data.get("active_event_id")
    if not active_id:
        return None
    for event in data["events"]:
        if event["id"] == active_id:
            return event
    return None


def create_event(data, name, aspect_ratio="16:9", overlay_text="", overlay_png_source=None,
                 strip_template_id="", video_template_id=""):
    """Cria um evento novo. Se overlay_png_source for informado, copia o
    arquivo pra event_assets/ (assim o evento não depende do arquivo
    original continuar no mesmo lugar no disco)."""
    event_id = uuid.uuid4().hex[:8]
    overlay_png_path = ""
    if overlay_png_source and os.path.isfile(overlay_png_source):
        os.makedirs(ASSETS_DIR, exist_ok=True)
        ext = os.path.splitext(overlay_png_source)[1] or ".png"
        overlay_png_path = os.path.join(ASSETS_DIR, f"{event_id}{ext}")
        shutil.copyfile(overlay_png_source, overlay_png_path)

    event = {
        "id": event_id,
        "name": name,
        "aspect_ratio": aspect_ratio if aspect_ratio in ASPECT_RATIO_CHOICES else "16:9",
        "overlay_text": overlay_text,
        "overlay_png_path": overlay_png_path,
        "strip_template_id": strip_template_id or "",
        "video_template_id": video_template_id or "",
    }
    data["events"].append(event)
    if not data.get("active_event_id"):
        data["active_event_id"] = event_id
    return event


def delete_event(data, event_id):
    data["events"] = [e for e in data["events"] if e["id"] != event_id]
    if data.get("active_event_id") == event_id:
        data["active_event_id"] = data["events"][0]["id"] if data["events"] else None
    asset_path = os.path.join(ASSETS_DIR)
    for filename in os.listdir(asset_path) if os.path.isdir(asset_path) else []:
        if filename.startswith(event_id):
            try:
                os.remove(os.path.join(asset_path, filename))
            except OSError:
                pass


def set_active_event(data, event_id):
    if any(e["id"] == event_id for e in data["events"]):
        data["active_event_id"] = event_id
