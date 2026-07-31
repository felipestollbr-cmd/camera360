"""
Carrega/salva config.json com os valores do totem (duração do giro,
contagem regressiva, motor, perfil de velocidade, música). Valores ausentes
no arquivo caem pro padrão em DEFAULT_CONFIG - assim um config.json antigo
ou incompleto nunca derruba o app, só usa o que faltar como padrão.
"""
import copy
import json
import os

from video_processor import DEFAULT_SPEED_PROFILE

CONFIG_PATH = "config.json"

DEFAULT_CONFIG = {
    "save_dir": "capturas",
    "preview_fps": 10,
    "share_port": 8090,
    "music_path": "",
    "speed_profile": DEFAULT_SPEED_PROFILE,
    "kiosk": {
        "countdown_seconds": 3,
        "spin_duration_seconds": 8,
        "preview_seconds": 12,
        "idle_timeout_seconds": 25,
    },
    "motor": {
        "enabled": False,
        "port": "COM5",
        "baud_rate": 9600,
        "start_command": "SPIN\n",
    },
}


def _deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path=CONFIG_PATH):
    config = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            config = _deep_merge(config, user_config)
        except Exception as e:
            print(f"Aviso: não foi possível ler {path} ({e}) - usando padrões")
    return config


def save_config(config, path=CONFIG_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
