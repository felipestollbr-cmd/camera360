"""
Lançador do produto (Giro360 / FotoCabine, ver product.py): abre a janela e mostra o splash NA HORA, enquanto os
módulos pesados (OpenCV, numpy, Pillow, gphoto2 - kiosk_app.py) carregam em
segundo plano. Só depois entrega a janela pro totem, que tira o splash do ar
quando a primeira checagem de licença termina.
"""
import json
import os
import sys
import threading
import time
import traceback

if getattr(sys, "frozen", False):
    # Empacotado com PyInstaller: os DLLs nativos (libgphoto2, tcl/tk, etc.)
    # ficam soltos na raiz do bundle (veja Product.spec) e o Tcl/Tk precisa
    # saber onde estão os scripts de init antes de tkinter ser importado.
    _bundle_dir = os.path.dirname(sys.executable)
    os.add_dll_directory(_bundle_dir)
    os.environ.setdefault("TCL_LIBRARY", os.path.join(_bundle_dir, "tcl", "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(_bundle_dir, "tcl", "tk8.6"))

if getattr(sys, "frozen", False):
    # Executável sem console: grava erros/prints em app.log (ao lado de config.json) pra
    # dar pra investigar um problema no cliente - sem isso eles simplesmente somem.
    try:
        _log = open("app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = _log
        print(f"--- início {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except OSError:
        pass

import tkinter as tk

import product
import theme
from PIL import ImageTk
from widgets import FestiveBackground, ICONS


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_branding():
    """Marca do splash (white-label): nome, imagem PNG opcional, cor e tempo
    mínimo na tela. Lê os JSON direto, sem importar nada pesado. A cor/nome do
    config.json têm prioridade; senão vale a última marca vista na licença."""
    config = _read_json("config.json")
    license_data = _read_json("license.json")
    return {
        "brand_name": (config.get("brand_name") or license_data.get("brand_name")
                       or product.current()["name"]),
        "brand_color": (config.get("brand_color") or license_data.get("brand_color")
                        or product.current()["accent"]),
        "splash_image": config.get("splash_image") or "",
        "min_seconds": float(config.get("splash_min_seconds", 2.5)),
    }


class Splash(FestiveBackground):
    """
    Tela de abertura: fundo em degradê da marca com confete caindo, logo (ou
    selo + nome), barra de progresso em degradê e mensagem de status.
    """

    BAR_W, BAR_H = 420, 12

    def __init__(self, parent, branding):
        super().__init__(parent, static_confetti=False)
        self._branding = branding
        self._logo = None
        self._badge = None
        self._track = None
        self._bar_photo = None
        self._bar_phase = 0.0
        self._bar_job = None
        self._status = ""
        self.bind("<Configure>", self._relayout, add="+")
        self.start_confetti(44)
        self._animate_bar()

    def _load_logo(self):
        path = self._branding["splash_image"]
        if path and os.path.isfile(path):
            try:
                from PIL import Image
                image = Image.open(path).convert("RGBA")
                image.thumbnail((560, 300))
                return ImageTk.PhotoImage(image, master=self)
            except Exception:
                return None
        return None

    def _relayout(self, event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 64 or h < 64:
            return
        self.delete("content")
        cx, cy = w / 2, h * 0.43
        self._logo = self._load_logo()
        if self._logo is not None:
            self.create_image(cx, cy, image=self._logo, tags="content")
            below = cy + self._logo.height() / 2 + 28
        else:
            icon_path = product.icon_png()
            if icon_path:
                from PIL import Image
                icon = Image.open(icon_path).convert("RGBA").resize((148, 148), Image.LANCZOS)
                self._badge = ImageTk.PhotoImage(icon, master=self)
                self.create_image(cx, cy - 76, image=self._badge, tags="content")
            else:
                self._badge = ImageTk.PhotoImage(theme.rounded_image(132, 132, 66, theme.GRADIENT), master=self)
                self.create_image(cx, cy - 70, image=self._badge, tags="content")
                before = set(self.find_all())
                ICONS["star"](self, cx, cy - 70, 62, theme.TEXT_ON_ACCENT)
                for item in set(self.find_all()) - before:
                    self.addtag_withtag("content", item)
            self.create_text(cx, cy + 36, text=self._branding["brand_name"], fill=theme.FG_TEXT,
                             font=theme.font(54, "black"), tags="content")
            self.create_text(cx, cy + 96, text=product.current()["tagline"], fill=theme.FG_MUTED,
                             font=theme.font(16, "semibold"), tags="content")
            below = cy + 150
        self._bar_y = below + 34
        self._bar_x = cx - self.BAR_W / 2
        self._track = ImageTk.PhotoImage(theme.rounded_image(self.BAR_W, self.BAR_H, self.BAR_H // 2,
                                                             theme.BG_CARD, theme.BORDER, 1), master=self)
        self.create_image(self._bar_x, self._bar_y, anchor="nw", image=self._track, tags="content")
        self.create_text(cx, self._bar_y + 40, text=self._status, fill=theme.FG_MUTED, width=620,
                         font=theme.font(13), justify="center", tags=("content", "status"))
        self._draw_bar()

    def _draw_bar(self):
        if not hasattr(self, "_bar_x"):
            return
        self.delete("barfill")
        chunk = 150
        left = self._bar_phase * (self.BAR_W + chunk) - chunk
        x1, x2 = max(0, left), min(self.BAR_W, left + chunk)
        if x2 - x1 < 6:
            return
        image = theme.gradient_image(int(x2 - x1), self.BAR_H, theme.GRADIENT, "h")
        self._bar_photo = ImageTk.PhotoImage(image, master=self)
        self.create_image(self._bar_x + x1, self._bar_y, anchor="nw", image=self._bar_photo, tags="barfill")

    def _animate_bar(self):
        self._bar_phase = (self._bar_phase + 0.018) % 1.0
        self._draw_bar()
        self._bar_job = self.after(33, self._animate_bar)

    def bring_to_front(self):
        # Canvas.lift()/tkraise() sobem ITENS do canvas; aqui queremos o widget todo
        self.tk.call("raise", self._w)

    def set_status(self, text):
        self._status = text
        self.itemconfig("status", text=text)

    def stop(self):
        if self._bar_job is not None:
            self.after_cancel(self._bar_job)
            self._bar_job = None
        self.stop_confetti()

    def close(self):
        self.stop()
        self.destroy()


def main():
    started = time.time()
    branding = _load_branding()

    theme.apply(branding["brand_color"] or None)
    root = tk.Tk()
    root.title(branding["brand_name"])
    root.configure(bg=theme.BG_ROOT)
    root.geometry("1024x768")
    root.attributes("-fullscreen", True)

    splash = Splash(root, branding)
    splash.place(x=0, y=0, relwidth=1, relheight=1)
    splash.set_status("Carregando...")
    root.update()

    loaded = {}

    def load_modules():
        try:
            import kiosk_app
            loaded["module"] = kiosk_app
        except Exception:
            loaded["error"] = traceback.format_exc()

    threading.Thread(target=load_modules, daemon=True).start()

    def poll():
        if "error" in loaded:
            print(loaded["error"], file=sys.stderr)
            splash.stop()
            splash.set_status("Não foi possível iniciar o programa.\n" + loaded["error"].strip().splitlines()[-1])
            return
        if "module" in loaded:
            splash.set_status("Iniciando...")
            root.update_idletasks()
            loaded["module"].Camera360Kiosk(
                root, splash=splash, splash_started=started, splash_min_seconds=branding["min_seconds"])
            return
        root.after(50, poll)

    root.after(50, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
