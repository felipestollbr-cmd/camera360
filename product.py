"""
Produtos do mesmo código-base: cada um vira seu próprio executável/instalador.

  - Giro360:    cabine giratória 360° (vídeo em câmera lenta + QR)
  - FotoCabine: cabine de fotos/tirinhas (templates, impressão/QR)

O ponto de entrada de cada produto (giro360.py / fotocabine.py) chama
`select()` antes de qualquer outra coisa. Em desenvolvimento, sem entrada
específica, vale a variável de ambiente CAMERA_PRODUCT (ou "giro360").

`module` é o id que a plataforma de licenças devolve em "modules": o app só
abre se a licença incluir o módulo do produto.
"""
import os
import sys

PRODUCTS = {
    "giro360": {
        "id": "giro360",
        "name": "Giro360",
        "tagline": "Cabine giratória 360°",
        "module": "video360",
        "mode": "video",
        "accent": "#8b5cf6",          # violeta -> magenta -> rosa
        "exe": "Giro360",
        "app_id": "{B3B6E9B0-6C5C-4E58-8F7B-9B7C7A2E3B10}",
    },
    "fotocabine": {
        "id": "fotocabine",
        "name": "FotoCabine",
        "tagline": "Cabine de fotos e tirinhas",
        "module": "photobooth",
        "mode": "strip",
        "accent": "#ff7a1a",          # laranja -> vermelho -> rosa
        "exe": "FotoCabine",
        "app_id": "{5E0C7D52-3A41-4D0E-9B6F-1C2A8E4F7A91}",
    },
}

DEFAULT_PRODUCT = "giro360"
_current = None


def select(product_id):
    global _current
    if product_id not in PRODUCTS:
        raise ValueError(f"Produto desconhecido: {product_id!r} (use {', '.join(PRODUCTS)})")
    _current = PRODUCTS[product_id]
    return _current


def current():
    if _current is None:
        select(os.environ.get("CAMERA_PRODUCT", DEFAULT_PRODUCT))
    return _current


def resource_path(*parts):
    """Caminho de um recurso do app (assets/...), no código-fonte ou no
    bundle do PyInstaller."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def icon_png(product_id=None, size=None):
    """Caminho do PNG do ícone do produto (ou None se ainda não foi gerado)."""
    path = resource_path("assets", f"{product_id or current()['id']}.png")
    return path if os.path.isfile(path) else None
