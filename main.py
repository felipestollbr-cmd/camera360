"""
Lançador do Camera360: abre a janela e mostra o splash NA HORA, enquanto os
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
    # ficam soltos na raiz do bundle (veja Camera360.spec) e o Tcl/Tk precisa
    # saber onde estão os scripts de init antes de tkinter ser importado.
    _bundle_dir = os.path.dirname(sys.executable)
    os.add_dll_directory(_bundle_dir)
    os.environ.setdefault("TCL_LIBRARY", os.path.join(_bundle_dir, "tcl", "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(_bundle_dir, "tcl", "tk8.6"))

import tkinter as tk
from tkinter import ttk

BG = "#101114"
FG = "#e8e8ea"
MUTED = "#8a8d96"
ACCENT = "#00e0a0"


def _load_branding():
    """Marca do splash vinda do config.json (white-label): nome, imagem PNG
    opcional e tempo mínimo na tela. Lê o JSON direto, sem importar nada
    pesado."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        config = {}
    return {
        "brand_name": config.get("brand_name") or "Camera360",
        "splash_image": config.get("splash_image") or "",
        "min_seconds": float(config.get("splash_min_seconds", 2.5)),
    }


class Splash(tk.Frame):
    def __init__(self, parent, branding):
        super().__init__(parent, bg=BG)
        center = tk.Frame(self, bg=BG)
        center.place(relx=0.5, rely=0.46, anchor="center")

        self._image = None
        image_path = branding["splash_image"]
        if image_path and os.path.isfile(image_path):
            try:
                self._image = tk.PhotoImage(file=image_path)
            except tk.TclError:
                self._image = None
        if self._image is not None:
            tk.Label(center, image=self._image, bg=BG).pack()
        else:
            tk.Label(center, text=branding["brand_name"], font=("Segoe UI", 48, "bold"),
                     bg=BG, fg=FG).pack()
            tk.Label(center, text="Controle de câmera 360°", font=("Segoe UI", 14),
                     bg=BG, fg=MUTED).pack(pady=(4, 0))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Splash.Horizontal.TProgressbar", troughcolor="#23252b", background=ACCENT,
                        bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self.bar = ttk.Progressbar(center, mode="indeterminate", length=320,
                                   style="Splash.Horizontal.TProgressbar")
        self.bar.pack(pady=(36, 10))
        self.bar.start(12)
        self.status = tk.Label(center, text="", font=("Segoe UI", 11), bg=BG, fg=MUTED,
                               wraplength=520, justify=tk.CENTER)
        self.status.pack()

    def set_status(self, text):
        self.status.config(text=text)

    def close(self):
        self.bar.stop()
        self.destroy()


def main():
    started = time.time()
    branding = _load_branding()

    root = tk.Tk()
    root.title(branding["brand_name"])
    root.configure(bg=BG)
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
            splash.bar.stop()
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
