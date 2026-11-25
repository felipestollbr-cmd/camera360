import io
import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
import numpy as np
from PIL import Image, ImageTk
import threading
import time
import hashlib
import subprocess

try:
    import winsound
except ImportError:
    winsound = None

from camera_controller import CameraController
import gopro_controller
from gopro_controller import GoProWifiController
import location as geo
from widgets import PillButton, Card, BG_CARD
import app_config
import product
import event_manager
import license_client
import motor_controller
import strip_editor
import strip_renderer
import strip_templates
import video_processor
import qr_share
from ffmpeg_utils import find_ffmpeg

SAVE_DIR = "capturas"
RAW_DIR = os.path.join(SAVE_DIR, "raw")
OUTPUT_DIR = os.path.join(SAVE_DIR, "final")
for _dir in (SAVE_DIR, RAW_DIR, OUTPUT_DIR):
    if not os.path.exists(_dir):
        os.makedirs(_dir)

BG_ROOT = "#101114"
BG_PANEL = "#17181c"
BG_PREVIEW = "#000000"
FG_TEXT = "#e8e8ea"
FG_MUTED = "#8a8d96"
ACCENT = "#00e0a0"
REC_RED = "#ff4d4d"
BORDER = "#2a2c33"
BORDER_LIGHT = "#33353d"

STATE_IDLE = "idle"
STATE_COUNTDOWN = "countdown"
STATE_RECORDING = "recording"
STATE_PROCESSING = "processing"
STATE_PREVIEW = "preview"
STATE_QR = "qr"
STATE_SETTINGS = "settings"
STATE_EVENTS = "events"
STATE_ACTIVATION = "activation"
STATE_CAPTURING = "capturing"
STATE_STRIP_EDITOR = "strip_editor"

MODE_VIDEO = "video"
MODE_STRIP = "strip"

# Módulos que a licença pode liberar (ids que a plataforma devolve em "modules"). Cada
# produto (product.py) só trabalha com o seu: Giro360 = video360, FotoCabine = photobooth.
ALL_MODULES = {product.current()["module"]}


class Camera360Kiosk:
    def __init__(self, root, splash=None, splash_started=None, splash_min_seconds=2.5):
        self.root = root
        self.root.title(product.current()["name"])
        self.root.geometry("1024x768")
        self.root.configure(bg=BG_ROOT)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", self._toggle_fullscreen)
        self.root.attributes("-fullscreen", True)
        self._is_fullscreen = True

        # Splash vindo do lançador (main.py): fica por cima das telas até a
        # primeira checagem de licença terminar e o tempo mínimo passar.
        self._splash = splash
        self._splash_started = splash_started if splash_started is not None else time.time()
        self._splash_min_seconds = splash_min_seconds

        self.config = app_config.load_config()
        self.root.title(self.config.get("brand_name") or product.current()["name"])
        self.events_data = event_manager.load_events()
        self.motor = motor_controller.MotorController(self.config["motor"])
        self.share_backend = qr_share.LocalShareBackend(OUTPUT_DIR, port=self.config["share_port"])

        self.camera = CameraController()
        self.running = True
        self.is_recording = False
        self.video_frames = []
        self.preview_fps = self.config.get("preview_fps", 10)
        self.current_frame = None
        self.frame_hash = None
        self.photo_image = None

        self.state = None
        self._countdown_value = 0
        self._recording_start = None
        self._raw_video_path = None
        self._final_media_path = None
        self.modules = set(ALL_MODULES)
        self._mode = MODE_VIDEO
        self._strip_template = None
        self._strip_photos = []
        self._strip_total = 0
        self._preview_cap = None
        self._preview_frame_delay = 40
        self._preview_audio_wav = None
        self._qr_reset_job = None

        self._setup_style()
        self._build_screens()
        if self._splash is not None:
            self._splash.bring_to_front()  # as telas recém-criadas ficam por cima; a splash volta ao topo
        self.root.update_idletasks()

        self._update_active_event_label()
        self._set_state(STATE_ACTIVATION)
        if self._splash is not None:
            self._splash.bring_to_front()
            self._splash.set_status("Verificando licença...")
        self._check_license(initial=True)

    def _dismiss_splash(self):
        if self._splash is not None:
            self._splash.close()
            self._splash = None

    # --- estilo / infraestrutura de telas -------------------------------

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background=BG_PANEL)
        style.configure("Dark.TLabel", background=BG_PANEL, foreground=FG_TEXT)
        style.configure("Muted.TLabel", background=BG_PANEL, foreground=FG_MUTED)
        style.configure("Brand.TLabel", background=BG_PANEL, foreground=FG_TEXT,
                         font=("Segoe UI", 12, "bold"))
        style.configure("DarkCard.TFrame", background=BG_CARD)
        style.configure("DarkCard.TLabel", background=BG_CARD, foreground=FG_TEXT)
        style.configure("MutedCard.TLabel", background=BG_CARD, foreground=FG_MUTED)
        style.configure("BrandCard.TLabel", background=BG_CARD, foreground=FG_TEXT,
                         font=("Segoe UI", 12, "bold"))
        style.configure("Dark.TEntry", fieldbackground=BG_PANEL, foreground=FG_TEXT,
                         insertcolor=FG_TEXT, borderwidth=1, bordercolor=BORDER_LIGHT)
        style.configure("Dark.TCombobox", fieldbackground=BG_PANEL, background=BG_PANEL,
                         foreground=FG_TEXT, arrowcolor=FG_MUTED, borderwidth=1)
        style.map("Dark.TCombobox", fieldbackground=[("readonly", BG_PANEL)],
                  foreground=[("readonly", FG_TEXT)])
        style.configure("Dark.TCheckbutton", background=BG_CARD, foreground=FG_TEXT)
        self.root.option_add("*TCombobox*Listbox.background", BG_PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#062018")

    def _build_screens(self):
        self.container = tk.Frame(self.root, bg=BG_ROOT)
        self.container.pack(fill=tk.BOTH, expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        self.screens = {}
        self._build_activation_screen()
        self._build_camera_screen()
        self._build_processing_screen()
        self._build_preview_screen()
        self._build_qr_screen()
        self._build_settings_screen()
        self._build_events_screen()
        self._build_strip_editor_screen()

    def _add_screen(self, name, frame):
        frame.grid(row=0, column=0, sticky="nsew")
        self.screens[name] = frame

    def _set_state(self, state):
        self.state = state
        print(f"[{time.strftime('%H:%M:%S')}] estado -> {state}", flush=True)  # vai pro app.log no executável
        # --- overlays exclusivos do camera_screen: um por estado ---
        overlays = {
            STATE_IDLE: (self.idle_overlay, {"relx": 0.5, "rely": 0.5, "anchor": "center"}),
            STATE_COUNTDOWN: (self.countdown_overlay, {"relx": 0.5, "rely": 0.5, "anchor": "center"}),
            STATE_CAPTURING: (self.capture_overlay, {"relx": 0.5, "rely": 0.5, "anchor": "center"}),
            STATE_RECORDING: (self.recording_overlay, {"relx": 0.5, "rely": 0.88, "anchor": "s"}),
        }
        for overlay, _place in overlays.values():
            overlay.place_forget()
        if state in overlays:
            overlay, place_args = overlays[state]
            if state == STATE_IDLE:
                self._refresh_idle_buttons()
            overlay.place(**place_args)

        if state in (STATE_IDLE, STATE_COUNTDOWN, STATE_CAPTURING, STATE_RECORDING):
            self.screens["camera"].tkraise()
        elif state == STATE_PROCESSING:
            self.screens["processing"].tkraise()
        elif state == STATE_PREVIEW:
            self.screens["preview"].tkraise()
        elif state == STATE_QR:
            self.screens["qr"].tkraise()
        elif state == STATE_SETTINGS:
            self._refresh_settings_fields()
            self.screens["settings"].tkraise()
        elif state == STATE_EVENTS:
            self._refresh_events_list()
            self._refresh_template_choices()
            self.screens["events"].tkraise()
        elif state == STATE_ACTIVATION:
            self.screens["activation"].tkraise()
        elif state == STATE_STRIP_EDITOR:
            self.strip_editor.open()
            self.screens["strip_editor"].tkraise()

    def _toggle_fullscreen(self, _event=None):
        self._is_fullscreen = not self._is_fullscreen
        self.root.attributes("-fullscreen", self._is_fullscreen)

    # --- tela de ativação da licença (trava o app até validar online) -----

    def _build_activation_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("activation", screen)

        center = tk.Frame(screen, bg=BG_ROOT)
        center.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(center, text=self.config.get("brand_name") or product.current()["name"], font=("Segoe UI", 28, "bold"),
                 bg=BG_ROOT, fg=FG_TEXT).pack(pady=(0, 4))
        self.activation_status_label = tk.Label(
            center, text="Verificando licença...", font=("Segoe UI", 13),
            bg=BG_ROOT, fg=FG_MUTED, wraplength=420, justify=tk.CENTER)
        self.activation_status_label.pack(pady=(0, 16))

        self.activation_form = tk.Frame(center, bg=BG_ROOT)
        ttk.Label(self.activation_form, text="Chave de licença", style="Dark.TLabel").pack(anchor="w")
        self.activation_key_entry = ttk.Entry(self.activation_form, style="Dark.TEntry", width=32,
                                               font=("Segoe UI", 14))
        self.activation_key_entry.pack(pady=(4, 12))
        PillButton(self.activation_form, text="Ativar", icon="play", variant="primary",
                   width=200, height=48, command=self._activate_license_from_form).pack()

        self.activation_hwid_label = tk.Label(
            center, text="", font=("Segoe UI", 9), bg=BG_ROOT, fg=FG_MUTED)
        self.activation_hwid_label.pack(pady=(20, 0))

    def _check_license(self, initial=False):
        api_url = self.config.get("license_api_url", "")

        def worker():
            result = license_client.validate(api_url)
            self.root.after(0, lambda: self._on_license_check_result(result, initial))

        threading.Thread(target=worker, daemon=True).start()

    def _on_license_check_result(self, result, initial):
        if initial and self._splash is not None:
            # O splash fica no mínimo splash_min_seconds na tela (pra não
            # piscar quando a checagem de licença é instantânea).
            remaining = self._splash_min_seconds - (time.time() - self._splash_started)
            if remaining > 0:
                self.root.after(int(remaining * 1000) + 50,
                                lambda: self._on_license_check_result(result, initial))
                return
            self._dismiss_splash()

        result = self._require_product_module(result)
        if result.get("valid"):
            self._set_modules(result)
            if initial:
                self._start_app()
            else:
                self._apply_modules()  # o administrador pode ter mudado os módulos
                self._schedule_periodic_license_check()
            return

        # Licença inválida/expirada/revogada, ou sem internet - trava o
        # totem na tela de ativação, mesmo que já estivesse rodando (a
        # revalidação periódica também cai aqui se a licença deixar de ser
        # válida no meio do uso).
        self.running = False
        self._set_state(STATE_ACTIVATION)
        saved_key = license_client.get_saved_license_key()
        message = result.get("message", "Licença inválida")
        if saved_key:
            self.activation_status_label.config(text=f"{message}\nChave: {saved_key}")
            self.activation_key_entry.delete(0, tk.END)
            self.activation_key_entry.insert(0, saved_key)
        else:
            self.activation_status_label.config(text=message)
        self.activation_form.pack(before=self.activation_hwid_label)
        self.activation_hwid_label.config(text=f"ID desta máquina: {license_client.get_hardware_id()}")

    def _activate_license_from_form(self):
        key = self.activation_key_entry.get().strip()
        if not key:
            return
        api_url = self.config.get("license_api_url", "")
        self.activation_status_label.config(text="Ativando...")
        self.activation_form.pack_forget()

        def worker():
            result = license_client.activate(api_url, key)
            self.root.after(0, lambda: self._on_activation_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _require_product_module(self, result):
        """Licença válida mas sem o módulo deste produto (ex.: licença só de
        FotoCabine tentando abrir o Giro360) vira 'inválida' com mensagem
        clara. Servidor antigo, sem o campo "modules" = tudo liberado."""
        if not result.get("valid"):
            return result
        modules = result.get("modules")
        if modules is None or product.current()["module"] in modules:
            return result
        return {"valid": False,
                "message": f"Esta licença não inclui o {product.current()['name']}. "
                           "Fale com o seu fornecedor."}

    def _on_activation_result(self, result):
        result = self._require_product_module(result)
        if result.get("valid"):
            self._set_modules(result)
            self._start_app()
            return
        self.activation_status_label.config(text=result.get("message", "Não foi possível ativar"))
        self.activation_form.pack(before=self.activation_hwid_label)

    def _set_modules(self, result):
        """Módulos liberados pela licença (vêm na resposta da plataforma).
        Servidor antigo, sem o campo = tudo liberado."""
        modules = result.get("modules")
        self.modules = set(modules) & ALL_MODULES if modules is not None else set(ALL_MODULES)

    def _apply_modules(self):
        """Mostra/esconde o que depende do módulo: botões da tela inicial,
        cartões de Configurações do 360, campos do formulário de evento e os
        tipos de template que o editor oferece."""
        kinds = []
        if "photobooth" in self.modules:
            kinds.append(strip_templates.KIND_STRIP)
        if "video360" in self.modules:
            kinds.append(strip_templates.KIND_VIDEO)
        self.strip_editor.set_allowed_kinds(kinds)
        self._layout_settings_cards()
        self._layout_events_form()
        if self.state == STATE_IDLE:
            self._refresh_idle_buttons()

    def _start_app(self):
        """Só roda depois da primeira validação de licença dar certo -
        conecta câmera/motor e libera o fluxo normal do totem."""
        self.running = True
        self.activation_form.pack_forget()
        self._apply_modules()
        self._set_state(STATE_IDLE)
        self.connect_camera()
        threading.Thread(target=self.motor.connect, daemon=True).start()
        self.update_video()
        self._schedule_periodic_license_check()

    def _schedule_periodic_license_check(self):
        interval_minutes = self.config.get("license_check_interval_minutes", 30)
        self.root.after(int(interval_minutes) * 60 * 1000, lambda: self._check_license(initial=False))

    # --- tela principal: idle / contagem / gravação ----------------------

    def _build_camera_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("camera", screen)

        top_bar = tk.Frame(screen, bg=BG_PANEL)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_body = ttk.Frame(top_bar, style="Dark.TFrame")
        top_body.pack(fill=tk.X, padx=16, pady=8)
        ttk.Label(top_body, text=self.config.get("brand_name") or product.current()["name"],
                  style="Brand.TLabel").pack(side=tk.LEFT)
        self.status_dot = tk.Canvas(top_body, width=10, height=10, bg=BG_PANEL, highlightthickness=0)
        self.status_dot.pack(side=tk.LEFT, padx=(16, 6))
        self.status_label = ttk.Label(top_body, text="Conectando...", style="Muted.TLabel")
        self.status_label.pack(side=tk.LEFT)
        self._draw_status_dot(False)
        self.active_event_label = ttk.Label(top_body, text="", style="Muted.TLabel")
        self.active_event_label.pack(side=tk.LEFT, padx=(16, 0))
        self.fix_camera_btn = PillButton(top_body, text="Corrigir e tentar de novo",
                                          variant="ghost", width=200, height=28,
                                          font=("Segoe UI", 9, "bold"),
                                          command=self._fix_camera_driver_conflict)
        gear_btn = tk.Label(top_body, text="⚙", font=("Segoe UI", 16), bg=BG_PANEL,
                             fg=FG_MUTED, cursor="hand2")
        gear_btn.pack(side=tk.RIGHT)
        gear_btn.bind("<Button-1>", lambda e: self._set_state(STATE_SETTINGS))

        preview_area = tk.Frame(screen, bg=BG_PREVIEW)
        preview_area.pack(fill=tk.BOTH, expand=True)
        self.video_label = tk.Label(preview_area, bg=BG_PREVIEW)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        # --- overlays sobrepostos ao preview via place() (mesmo padrão já
        # usado pra pílula "REC" no app original) ---
        self.idle_overlay = tk.Frame(preview_area, bg=BG_PANEL)
        tk.Label(self.idle_overlay, text="Toque para começar", font=("Segoe UI", 20, "bold"),
                 bg=BG_PANEL, fg=FG_TEXT).pack(padx=30, pady=(24, 12))
        self.video_btn = PillButton(self.idle_overlay, text="Iniciar giro 360°", icon="play", variant="primary",
                                    width=320, height=64, font=("Segoe UI", 14, "bold"),
                                    command=self.start_countdown)
        self.video_btn.pack(padx=30, pady=(0, 24))
        # só aparece quando o evento ativo tem template de tirinha (_refresh_idle_buttons)
        self.strip_btn = PillButton(self.idle_overlay, text="Tirinha de fotos", icon="camera", variant="ghost",
                                    width=320, height=64, font=("Segoe UI", 14, "bold"),
                                    command=self.start_strip_session)

        self.countdown_overlay = tk.Frame(preview_area, bg=BG_PANEL)
        self.countdown_caption = tk.Label(self.countdown_overlay, text="", font=("Segoe UI", 18, "bold"),
                                          bg=BG_PANEL, fg=FG_MUTED)
        self.countdown_caption.pack(padx=60, pady=(24, 0))
        self.countdown_label = tk.Label(self.countdown_overlay, text="3", font=("Segoe UI", 96, "bold"),
                                         bg=BG_PANEL, fg=ACCENT)
        self.countdown_label.pack(padx=60, pady=(0, 30))

        self.capture_overlay = tk.Frame(preview_area, bg=BG_PANEL)
        self.capture_label = tk.Label(self.capture_overlay, text="SORRIA!", font=("Segoe UI", 40, "bold"),
                                      bg=BG_PANEL, fg=ACCENT)
        self.capture_label.pack(padx=60, pady=30)

        self.recording_overlay = tk.Frame(preview_area, bg="#1c1c1e")
        self.recording_label = tk.Label(self.recording_overlay, text="GIRANDO...",
                                         font=("Segoe UI", 18, "bold"), bg="#1c1c1e", fg=REC_RED)
        self.recording_label.pack(padx=24, pady=12)

    def _draw_status_dot(self, connected):
        c = self.status_dot
        c.delete("all")
        color = ACCENT if connected else "#5a5d66"
        c.create_oval(1, 1, 9, 9, fill=color, outline="")

    def update_status(self, msg, connected=None, usb_conflict=False):
        self.status_label.config(text=msg)
        if connected is not None:
            self._draw_status_dot(connected)
        if usb_conflict:
            self.fix_camera_btn.pack(side=tk.LEFT, padx=(16, 0))
        else:
            self.fix_camera_btn.pack_forget()

    def connect_camera(self):
        def worker():
            connected = self.camera.connect()
            if not connected:
                # Sem DSLR no USB - tenta uma GoPro na rede Wi-Fi (gphoto2
                # não faz live view/captura em GoPro, só reconhece o
                # modelo, então isso é um caminho totalmente separado).
                gopro = GoProWifiController()
                if gopro.connect():
                    self.camera = gopro
                    connected = True

            if connected:
                self.camera.start_live_view(fps=self.preview_fps)
                model = self.camera.get_camera_model()
                self.root.after(0, lambda: self.update_status(f"Conectado: {model}", connected=True))
                self.root.after(0, self._update_video_settings_availability)
            else:
                usb_conflict = self.camera.is_usb_claim_conflict()
                self.root.after(0, lambda: self.update_status(
                    "Câmera não detectada (modo simulação)", connected=False, usb_conflict=usb_conflict))
        threading.Thread(target=worker, daemon=True).start()

    def _fix_camera_driver_conflict(self):
        """
        Desativa o dispositivo WPD (Windows Portable Devices) que está
        segurando a câmera - o Windows a reconhece automaticamente como
        dispositivo de mídia assim que é conectada, e isso impede o
        gphoto2 de reivindicar o acesso USB direto ([-53] Could not claim).
        Precisa de permissão de administrador (o Windows vai pedir via UAC).
        """
        self.fix_camera_btn.config(state="disabled", text="Corrigindo...")

        def worker():
            inner_cmd = (
                "Get-PnpDevice -Class WPD -Status OK | ForEach-Object "
                '{ pnputil /disable-device "$($_.InstanceId)" }'
            )
            wrapper_cmd = (
                f"Start-Process powershell -ArgumentList '-NoProfile','-Command','{inner_cmd}' "
                f"-Verb RunAs -Wait"
            )
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", wrapper_cmd],
                    timeout=60, check=False)
            except Exception as e:
                print(f"Erro ao tentar corrigir o driver da câmera: {e}")
            self.root.after(0, self._retry_camera_after_fix)

        threading.Thread(target=worker, daemon=True).start()

    def _retry_camera_after_fix(self):
        self.fix_camera_btn.config(state="normal", text="Corrigir e tentar de novo")
        self.fix_camera_btn.pack_forget()
        self.update_status("Reconectando...")
        self.connect_camera()

    def update_video(self):
        if not self.running:
            return

        frame = self.camera.get_frame()
        if frame is None:
            h, w = 480, 640
            frame = np.zeros((h, w, 3), dtype=np.uint8)
        self.current_frame = frame

        if self.is_recording:
            self.video_frames.append(frame.copy())

        if self.state in (STATE_IDLE, STATE_COUNTDOWN, STATE_CAPTURING, STATE_RECORDING):
            self._blit_frame(frame, self.video_label)

        self.root.after(50, self.update_video)

    def _blit_frame(self, frame, label):
        """Desenha um frame BGR (numpy) num tk.Label, ajustado ao espaço
        disponível sem cortar nada (estilo "contain", com tarjas quando a
        proporção não bate) - reaproveitado tanto pro preview ao vivo
        quanto pra reprodução do vídeo final na tela de prévia."""
        new_hash = hashlib.md5(frame.tobytes()).hexdigest()
        if label is self.video_label:
            if new_hash == self.frame_hash:
                return
            self.frame_hash = new_hash
        try:
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img_rgb)

            label_width = label.winfo_width()
            label_height = label.winfo_height()
            if label_width < 10 or label_height < 10:
                label_width, label_height = 800, 600

            img_w, img_h = img_pil.size
            scale = min(label_width / img_w, label_height / img_h)
            new_w, new_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
            img_pil = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)

            canvas = Image.new("RGB", (label_width, label_height), (0, 0, 0))
            canvas.paste(img_pil, ((label_width - new_w) // 2, (label_height - new_h) // 2))

            imgtk = ImageTk.PhotoImage(master=self.root, image=canvas)
            label.config(image=imgtk)
            label.image = imgtk
        except Exception as e:
            print(f"Erro ao atualizar imagem: {e}")

    def _tag_capture_with_location(self, capture_path):
        """Busca a localização atual (Windows Location Services) em segundo
        plano e grava um .location.txt ao lado do arquivo capturado, sem
        travar a interface enquanto espera o GPS/Wi-Fi responder."""
        def worker():
            loc = geo.get_current_location()
            if not loc:
                return
            try:
                geo.write_sidecar(capture_path, loc)
            except Exception as e:
                print(f"Erro ao salvar localização: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # --- fluxo do totem: contagem -> giro -> processamento -> prévia -> QR

    def start_countdown(self):
        if self.state != STATE_IDLE or "video360" not in self.modules:
            return
        self._mode = MODE_VIDEO
        self.countdown_caption.config(text="")
        self._countdown_value = self.config["kiosk"]["countdown_seconds"]
        self._set_state(STATE_COUNTDOWN)
        self._tick_countdown()

    def _tick_countdown(self):
        if self.state != STATE_COUNTDOWN:
            return
        if self._countdown_value <= 0:
            if self._mode == MODE_STRIP:
                self._capture_strip_photo()
            else:
                self._begin_recording()
            return
        self.countdown_label.config(text=str(self._countdown_value))
        self._countdown_value -= 1
        self.root.after(1000, self._tick_countdown)

    # --- fluxo da tirinha: N fotos -> montagem no template -> prévia -> QR ---

    def _refresh_idle_buttons(self):
        """A tela inicial só oferece os módulos que a licença libera (um só
        ou os dois)."""
        self.video_btn.pack_forget()
        self.strip_btn.pack_forget()
        if "video360" in self.modules:
            self.video_btn.pack(padx=30, pady=(0, 24))
        if "photobooth" in self.modules:
            self.strip_btn.pack(padx=30, pady=(0, 24))

    def start_strip_session(self):
        if self.state != STATE_IDLE or "photobooth" not in self.modules:
            return
        event = event_manager.get_active_event(self.events_data) or {}
        template_id = event.get("strip_template_id", "")
        try:
            if not template_id:
                # evento sem template de tirinha: usa o primeiro disponível
                available = strip_templates.list_templates(strip_templates.KIND_STRIP)
                template_id = available[0]["id"] if available else ""
            template = strip_templates.load_template(template_id)
        except Exception as e:
            messagebox.showerror("Tirinha", f"Não foi possível abrir o template da tirinha: {e}")
            return
        total = strip_templates.photo_slot_count(template)
        if total == 0:
            messagebox.showerror("Tirinha", "Esse template não tem nenhum quadro de foto.")
            return
        self._mode = MODE_STRIP
        self._strip_template = template
        self._strip_total = total
        self._strip_photos = []
        self._begin_strip_countdown()

    def _begin_strip_countdown(self):
        number = len(self._strip_photos) + 1
        self.countdown_caption.config(text=f"Foto {number} de {self._strip_total}")
        self._countdown_value = self.config["kiosk"]["countdown_seconds"]
        self._set_state(STATE_COUNTDOWN)
        self._tick_countdown()

    def _grab_photo(self):
        """Uma foto: câmera real (GoPro/DSLR) se conectada; senão o frame
        atual do preview, só pra poder testar o fluxo sem câmera."""
        if self.camera.connected:
            return Image.open(io.BytesIO(self.camera.capture_photo())).convert("RGB")
        frame = self.current_frame
        if frame is None:
            raise Exception("Sem imagem da câmera")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def _capture_strip_photo(self):
        self.capture_label.config(text="SORRIA!")
        self._set_state(STATE_CAPTURING)

        def worker():
            try:
                image = self._grab_photo()
                self.root.after(0, lambda: self._on_strip_photo(image, None))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._on_strip_photo(None, err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_strip_photo(self, image, error):
        if error:
            messagebox.showerror("Erro", f"Falha ao tirar a foto: {error}")
            self._set_state(STATE_IDLE)
            return
        self._strip_photos.append(image)
        done = len(self._strip_photos)
        if done >= self._strip_total:
            self._process_strip()
            return
        self.capture_label.config(text=f"Foto {done} de {self._strip_total}  OK")
        pause_ms = int(float(self.config.get("strip_pause_seconds", 2)) * 1000)
        self.root.after(pause_ms, self._next_strip_photo)

    def _next_strip_photo(self):
        if self.state == STATE_CAPTURING and self._mode == MODE_STRIP:
            self._begin_strip_countdown()

    def _process_strip(self):
        self._set_state(STATE_PROCESSING)
        template, photos = self._strip_template, list(self._strip_photos)

        def worker():
            try:
                image = strip_renderer.render_template(template, photos, 1.0)
                path = os.path.join(OUTPUT_DIR, f"strip_{int(time.time())}.jpg")
                strip_renderer.save_strip(image, path)
                self.root.after(0, lambda: self._on_strip_done(image, path, None))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._on_strip_done(None, None, err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_strip_done(self, image, path, error):
        if error:
            messagebox.showerror("Erro", f"Falha ao montar a tirinha: {error}")
            self._set_state(STATE_IDLE)
            return
        self._final_media_path = path
        self._tag_capture_with_location(path)
        self._set_state(STATE_PREVIEW)
        self._blit_frame(cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR), self.preview_video_label)

    def _begin_recording(self):
        self._set_state(STATE_RECORDING)
        self.motor.trigger_spin()
        self._recording_start = time.time()
        duration = self.config["kiosk"]["spin_duration_seconds"]
        is_gopro = isinstance(self.camera, GoProWifiController)

        def worker():
            try:
                if is_gopro:
                    raw_path = self._record_via_gopro(duration)
                else:
                    raw_path = self._record_from_preview(duration)
                self.root.after(0, lambda: self._on_recording_done(raw_path, None))
            except Exception as e:
                # Captura a mensagem AQUI dentro do except: "e" some assim
                # que o bloco termina (comportamento padrão do Python), e o
                # lambda só roda depois, agendado via root.after - sem isso
                # dá NameError ao tentar ler "e" de dentro do lambda.
                err_msg = str(e)
                self.root.after(0, lambda: self._on_recording_done(None, err_msg))

        threading.Thread(target=worker, daemon=True).start()
        self._tick_recording_progress()

    def _record_via_gopro(self, duration):
        self.camera.start_video_recording()
        time.sleep(duration)
        data = self.camera.stop_video_recording()
        raw_path = os.path.join(RAW_DIR, f"raw_{int(time.time())}.mp4")
        with open(raw_path, "wb") as f:
            f.write(data)
        return raw_path

    def _record_from_preview(self, duration):
        """Fallback pra quando não há GoPro conectada (DSLR ou simulação):
        grava do stream de preview local, só pra poder testar o fluxo do
        totem sem o rig de verdade - qualidade bem menor que a gravação
        real da GoPro."""
        self.video_frames = []
        self.is_recording = True
        time.sleep(duration)
        self.is_recording = False
        if not self.video_frames:
            raise Exception("Nenhum frame capturado (câmera não conectada?)")
        raw_path = os.path.join(RAW_DIR, f"raw_{int(time.time())}.mp4")
        h, w = self.video_frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(raw_path, fourcc, self.preview_fps, (w, h))
        for frame in self.video_frames:
            out.write(frame)
        out.release()
        self.video_frames = []
        return raw_path

    def _tick_recording_progress(self):
        if self.state != STATE_RECORDING:
            return
        duration = self.config["kiosk"]["spin_duration_seconds"]
        elapsed = time.time() - self._recording_start
        remaining = max(0, duration - elapsed)
        self.recording_label.config(text=f"GIRANDO... {int(remaining) + 1:02d}s")
        if remaining > 0:
            self.root.after(200, self._tick_recording_progress)

    def _on_recording_done(self, raw_path, error):
        if error:
            messagebox.showerror("Erro", f"Falha na gravação: {error}")
            self._set_state(STATE_IDLE)
            return
        self._raw_video_path = raw_path
        self._set_state(STATE_PROCESSING)

        active_event = event_manager.get_active_event(self.events_data)
        video_template = None
        template_id = (active_event or {}).get("video_template_id")
        if template_id:
            try:
                video_template = strip_templates.load_template(template_id)
            except Exception as e:
                print(f"Aviso: template de vídeo do evento não abriu ({e}) - usando formato simples")

        def worker():
            try:
                final_path = video_processor.process_capture(
                    raw_path, OUTPUT_DIR,
                    speed_profile=self.config.get("speed_profile"),
                    music_path=self.config.get("music_path") or None,
                    event=active_event, video_template=video_template)
                self.root.after(0, lambda: self._on_processing_done(final_path, None))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._on_processing_done(None, err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_processing_done(self, final_path, error):
        if error:
            messagebox.showerror("Erro", f"Falha ao processar vídeo: {error}")
            self._set_state(STATE_IDLE)
            return
        self._final_media_path = final_path
        self._tag_capture_with_location(final_path)
        self._set_state(STATE_PREVIEW)
        self._start_preview_playback(final_path)

    # --- tela de processamento -------------------------------------------

    def _build_processing_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("processing", screen)
        center = tk.Frame(screen, bg=BG_ROOT)
        center.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(center, text="Preparando seu vídeo...", font=("Segoe UI", 24, "bold"),
                 bg=BG_ROOT, fg=FG_TEXT).pack(pady=(0, 8))
        tk.Label(center, text="Isso leva só alguns segundos", font=("Segoe UI", 13),
                 bg=BG_ROOT, fg=FG_MUTED).pack()

    # --- tela de prévia (reprodução do vídeo final) -----------------------

    def _build_preview_screen(self):
        screen = tk.Frame(self.container, bg=BG_PREVIEW)
        self._add_screen("preview", screen)
        self.preview_video_label = tk.Label(screen, bg=BG_PREVIEW)
        self.preview_video_label.pack(fill=tk.BOTH, expand=True)

        controls = tk.Frame(screen, bg="#1c1c1e")
        controls.place(relx=0.5, rely=0.92, anchor="center")
        PillButton(controls, text="Refazer", icon="refresh", variant="ghost",
                   width=180, height=52, command=self._preview_retry).pack(side=tk.LEFT, padx=8, pady=8)
        PillButton(controls, text="Continuar", icon="play", variant="primary",
                   width=220, height=52, command=self._preview_continue).pack(side=tk.LEFT, padx=8, pady=8)

    def _start_preview_playback(self, path):
        self._preview_cap = cv2.VideoCapture(path)
        fps = self._preview_cap.get(cv2.CAP_PROP_FPS) or 25
        self._preview_frame_delay = max(20, int(1000 / fps))
        self._preview_audio_wav = self._extract_audio_wav(path)
        self._play_preview_audio()
        self._tick_preview_frame()

    def _tick_preview_frame(self):
        if self.state != STATE_PREVIEW or self._preview_cap is None:
            return
        ok, frame = self._preview_cap.read()
        if not ok:
            self._preview_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._play_preview_audio()
            self.root.after(self._preview_frame_delay, self._tick_preview_frame)
            return
        self._blit_frame(frame, self.preview_video_label)
        self.root.after(self._preview_frame_delay, self._tick_preview_frame)

    def _extract_audio_wav(self, video_path):
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            return None
        try:
            result = subprocess.run(
                [ffmpeg_path, "-y", "-loglevel", "error", "-i", video_path,
                 "-vn", "-f", "wav", "pipe:1"],
                capture_output=True, timeout=15)
            return result.stdout if result.returncode == 0 else None
        except Exception:
            return None

    def _play_preview_audio(self):
        if winsound is None or not self._preview_audio_wav:
            return
        try:
            winsound.PlaySound(self._preview_audio_wav, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            pass

    def _stop_preview_playback(self):
        if self._preview_cap is not None:
            self._preview_cap.release()
            self._preview_cap = None
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self._preview_audio_wav = None

    def _preview_retry(self):
        self._stop_preview_playback()
        self._set_state(STATE_IDLE)

    def _preview_continue(self):
        self._stop_preview_playback()
        self._show_qr(self._final_media_path)

    # --- tela de QR code ---------------------------------------------------

    def _build_qr_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("qr", screen)
        center = tk.Frame(screen, bg=BG_ROOT)
        center.place(relx=0.5, rely=0.5, anchor="center")
        self.qr_title_label = tk.Label(center, text="Escaneie para baixar seu vídeo!", font=("Segoe UI", 22, "bold"),
                                       bg=BG_ROOT, fg=FG_TEXT)
        self.qr_title_label.pack(pady=(0, 20))
        self.qr_image_label = tk.Label(center, bg=BG_ROOT)
        self.qr_image_label.pack()
        self.qr_status_label = tk.Label(center, text="", font=("Segoe UI", 12),
                                         bg=BG_ROOT, fg=FG_MUTED)
        self.qr_status_label.pack(pady=(16, 20))
        PillButton(center, text="Começar de novo", icon="camera", variant="primary",
                   width=260, height=56, command=self._reset_to_idle).pack()

    def _show_qr(self, video_path):
        self._set_state(STATE_QR)
        what = "sua tirinha" if self._mode == MODE_STRIP else "seu vídeo"
        self.qr_title_label.config(text=f"Escaneie para baixar {what}!")
        self.qr_image_label.config(image="")
        self.qr_status_label.config(text="Gerando QR code...")

        def worker():
            try:
                url = self.share_backend.publish(video_path)
                qr_img = qr_share.generate_qr_image(url)
                self.root.after(0, lambda: self._display_qr(qr_img, url))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._display_qr(None, err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _display_qr(self, qr_img, url_or_error):
        if qr_img is None:
            self.qr_status_label.config(text=f"Erro ao gerar QR: {url_or_error}")
            return
        photo = ImageTk.PhotoImage(qr_img)
        self.qr_image_label.config(image=photo)
        self.qr_image_label.image = photo
        self.qr_status_label.config(text=url_or_error)
        idle_timeout = self.config["kiosk"]["idle_timeout_seconds"]
        if self._qr_reset_job is not None:
            self.root.after_cancel(self._qr_reset_job)
        self._qr_reset_job = self.root.after(idle_timeout * 1000, self._reset_to_idle)

    def _reset_to_idle(self):
        if self._qr_reset_job is not None:
            self.root.after_cancel(self._qr_reset_job)
            self._qr_reset_job = None
        self._set_state(STATE_IDLE)

    # --- tela de configurações (operador) -----------------------------------

    def _build_settings_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("settings", screen)

        header = ttk.Frame(screen, style="Dark.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, text="Configurações", style="Brand.TLabel").pack(side=tk.LEFT, padx=16, pady=10)
        PillButton(header, text="Voltar", variant="ghost", width=110, height=32,
                   command=lambda: self._set_state(STATE_IDLE)).pack(side=tk.RIGHT, padx=16, pady=8)

        body = tk.Frame(screen, bg=BG_ROOT)
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # --- Giro / totem ---
        timing_card = Card(body)
        timing_card.pack(fill=tk.X, pady=(0, 12))
        t = timing_card.content
        ttk.Label(t, text="Giro e totem", style="BrandCard.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(t, text="Contagem (s)", style="MutedCard.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6))
        self.settings_countdown_entry = ttk.Entry(t, style="Dark.TEntry", width=8)
        self.settings_countdown_entry.grid(row=1, column=1, padx=(0, 20))
        self.settings_spin_label = ttk.Label(t, text="Duração do giro (s)", style="MutedCard.TLabel")
        self.settings_spin_label.grid(row=1, column=2, sticky="w", padx=(0, 6))
        self.settings_spin_entry = ttk.Entry(t, style="Dark.TEntry", width=8)
        self.settings_spin_entry.grid(row=1, column=3)
        ttk.Label(t, text="Tempo até resetar (s)", style="MutedCard.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.settings_idle_timeout_entry = ttk.Entry(t, style="Dark.TEntry", width=8)
        self.settings_idle_timeout_entry.grid(row=2, column=1, pady=(8, 0))

        # --- Motor ---
        motor_card = Card(body)
        motor_card.pack(fill=tk.X, pady=(0, 12))
        m = motor_card.content
        ttk.Label(m, text="Motor do braço giratório", style="BrandCard.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.settings_motor_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(m, text="Controlar motor via serial (desmarcado = rig com controlador próprio)",
                         variable=self.settings_motor_enabled_var,
                         style="Dark.TCheckbutton").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(m, text="Porta (ex.: COM5)", style="MutedCard.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.settings_motor_port_entry = ttk.Entry(m, style="Dark.TEntry", width=10)
        self.settings_motor_port_entry.grid(row=2, column=1, padx=(0, 20))
        ttk.Label(m, text="Baud rate", style="MutedCard.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6))
        self.settings_motor_baud_entry = ttk.Entry(m, style="Dark.TEntry", width=10)
        self.settings_motor_baud_entry.grid(row=2, column=3)

        # --- Perfil de velocidade (câmera lenta) ---
        speed_card = Card(body)
        speed_card.pack(fill=tk.X, pady=(0, 12))
        sp = speed_card.content
        ttk.Label(sp, text="Câmera lenta (trechos mais rápidos/lentos)", style="BrandCard.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(sp, text="Início %", style="MutedCard.TLabel").grid(row=1, column=1, padx=6)
        ttk.Label(sp, text="Fim %", style="MutedCard.TLabel").grid(row=1, column=2, padx=6)
        ttk.Label(sp, text="Velocidade", style="MutedCard.TLabel").grid(row=1, column=3, padx=6)
        self.settings_speed_rows = []
        for i in range(3):
            ttk.Label(sp, text=f"Trecho {i + 1}", style="MutedCard.TLabel").grid(row=2 + i, column=0, sticky="w", pady=3)
            start_entry = ttk.Entry(sp, style="Dark.TEntry", width=8)
            start_entry.grid(row=2 + i, column=1, padx=6)
            end_entry = ttk.Entry(sp, style="Dark.TEntry", width=8)
            end_entry.grid(row=2 + i, column=2, padx=6)
            speed_entry = ttk.Entry(sp, style="Dark.TEntry", width=8)
            speed_entry.grid(row=2 + i, column=3, padx=6)
            self.settings_speed_rows.append((start_entry, end_entry, speed_entry))
        ttk.Label(sp, text="Velocidade 1.0 = normal, menor que 1 = câmera lenta, maior que 1 = acelerado",
                  style="MutedCard.TLabel", font=("Segoe UI", 8)).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # --- Música ---
        music_card = Card(body)
        music_card.pack(fill=tk.X, pady=(0, 12))
        mc = music_card.content
        ttk.Label(mc, text="Música de fundo", style="BrandCard.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.settings_music_entry = ttk.Entry(mc, style="Dark.TEntry", width=50)
        self.settings_music_entry.grid(row=1, column=0, padx=(0, 8), sticky="w")
        PillButton(mc, text="Procurar", variant="ghost", width=110, height=32,
                   bg=BG_CARD, command=self._browse_music_file).grid(row=1, column=1)

        # --- GoPro: resolução/FPS de gravação ---
        gopro_card = Card(body)
        gopro_card.pack(fill=tk.X, pady=(0, 12))
        g = gopro_card.content
        ttk.Label(g, text="GoPro - vídeo gravado", style="BrandCard.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.video_settings_hint = ttk.Label(g, text="Disponível só com a GoPro conectada", style="MutedCard.TLabel")
        self.video_settings_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(g, text="Resolução", style="MutedCard.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 6))
        self.video_resolution_combo = ttk.Combobox(
            g, state="disabled", style="Dark.TCombobox", width=12,
            values=list(gopro_controller.VIDEO_RESOLUTIONS.keys()))
        self.video_resolution_combo.current(list(gopro_controller.VIDEO_RESOLUTIONS).index("1080p"))
        self.video_resolution_combo.bind("<<ComboboxSelected>>", self._on_video_resolution_change)
        self.video_resolution_combo.grid(row=2, column=1, padx=(0, 20))
        ttk.Label(g, text="FPS", style="MutedCard.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 6))
        self.video_fps_combo = ttk.Combobox(g, state="disabled", style="Dark.TCombobox", width=10)
        self.video_fps_combo.grid(row=2, column=3)
        self._refresh_fps_options()
        self.video_settings_apply_btn = PillButton(
            g, text="Aplicar na câmera", icon="camera", variant="ghost",
            width=200, height=36, bg=BG_CARD, command=self.apply_video_settings)
        self.video_settings_apply_btn.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="w")
        self.video_settings_apply_btn.set_state("disabled")

        # (cartão, é só do módulo Giro 360°?) - _layout_settings_cards esconde os do 360
        # quando a licença não libera esse módulo
        self._settings_cards = [(timing_card, False), (motor_card, True), (speed_card, True),
                                (music_card, True), (gopro_card, True)]

        # --- ações ---
        actions = tk.Frame(body, bg=BG_ROOT)
        actions.pack(fill=tk.X, pady=(4, 0))
        self._settings_actions = actions
        PillButton(actions, text="Salvar configurações", icon="calendar", variant="primary",
                   width=220, height=48, command=self._save_settings).pack(side=tk.LEFT)
        PillButton(actions, text="Eventos", icon="camera", variant="ghost",
                   width=160, height=48, command=lambda: self._set_state(STATE_EVENTS)).pack(side=tk.LEFT, padx=8)
        PillButton(actions, text="Templates", icon="camera", variant="ghost",
                   width=170, height=48, command=lambda: self._set_state(STATE_STRIP_EDITOR)).pack(side=tk.LEFT, padx=8)
        PillButton(actions, text="Abrir pasta de mídia", icon="folder", variant="ghost",
                   width=200, height=48, command=self.open_media_folder).pack(side=tk.LEFT, padx=8)
        PillButton(actions, text="Sair do totem", icon="power", variant="danger",
                   width=180, height=48, command=self.on_close).pack(side=tk.RIGHT)

    def _layout_settings_cards(self):
        """Motor, câmera lenta, música, vídeo da GoPro e a duração do giro só
        fazem sentido com o módulo Giro 360° liberado."""
        has_video = "video360" in self.modules
        for card, _only_video in self._settings_cards:
            card.pack_forget()
        for card, only_video in self._settings_cards:
            if has_video or not only_video:
                card.pack(fill=tk.X, pady=(0, 12), before=self._settings_actions)
        if has_video:
            self.settings_spin_label.grid()
            self.settings_spin_entry.grid()
        else:
            self.settings_spin_label.grid_remove()
            self.settings_spin_entry.grid_remove()

    def _refresh_settings_fields(self):
        k = self.config["kiosk"]
        self.settings_countdown_entry.delete(0, tk.END)
        self.settings_countdown_entry.insert(0, str(k["countdown_seconds"]))
        self.settings_spin_entry.delete(0, tk.END)
        self.settings_spin_entry.insert(0, str(k["spin_duration_seconds"]))
        self.settings_idle_timeout_entry.delete(0, tk.END)
        self.settings_idle_timeout_entry.insert(0, str(k["idle_timeout_seconds"]))

        mo = self.config["motor"]
        self.settings_motor_enabled_var.set(bool(mo["enabled"]))
        self.settings_motor_port_entry.delete(0, tk.END)
        self.settings_motor_port_entry.insert(0, str(mo["port"]))
        self.settings_motor_baud_entry.delete(0, tk.END)
        self.settings_motor_baud_entry.insert(0, str(mo["baud_rate"]))

        profile = self.config.get("speed_profile") or video_processor.DEFAULT_SPEED_PROFILE
        for i, (start_entry, end_entry, speed_entry) in enumerate(self.settings_speed_rows):
            seg = profile[i] if i < len(profile) else {"start_pct": 0, "end_pct": 0, "speed": 1.0}
            start_entry.delete(0, tk.END)
            start_entry.insert(0, str(round(seg["start_pct"] * 100)))
            end_entry.delete(0, tk.END)
            end_entry.insert(0, str(round(seg["end_pct"] * 100)))
            speed_entry.delete(0, tk.END)
            speed_entry.insert(0, str(seg["speed"]))

        self.settings_music_entry.delete(0, tk.END)
        self.settings_music_entry.insert(0, self.config.get("music_path") or "")

    def _browse_music_file(self):
        path = filedialog.askopenfilename(
            title="Escolher música de fundo",
            filetypes=[("Áudio", "*.mp3 *.wav *.m4a *.aac"), ("Todos os arquivos", "*.*")])
        if path:
            self.settings_music_entry.delete(0, tk.END)
            self.settings_music_entry.insert(0, path)

    def _save_settings(self):
        try:
            self.config["kiosk"]["countdown_seconds"] = int(self.settings_countdown_entry.get())
            self.config["kiosk"]["spin_duration_seconds"] = int(self.settings_spin_entry.get())
            self.config["kiosk"]["idle_timeout_seconds"] = int(self.settings_idle_timeout_entry.get())

            self.config["motor"]["enabled"] = self.settings_motor_enabled_var.get()
            self.config["motor"]["port"] = self.settings_motor_port_entry.get().strip()
            self.config["motor"]["baud_rate"] = int(self.settings_motor_baud_entry.get())

            profile = []
            for start_entry, end_entry, speed_entry in self.settings_speed_rows:
                profile.append({
                    "start_pct": float(start_entry.get()) / 100.0,
                    "end_pct": float(end_entry.get()) / 100.0,
                    "speed": float(speed_entry.get()),
                })
            self.config["speed_profile"] = profile

            self.config["music_path"] = self.settings_music_entry.get().strip()
        except ValueError as e:
            messagebox.showerror("Configurações", f"Valor inválido: {e}")
            return

        app_config.save_config(self.config)

        self.motor.disconnect()
        self.motor = motor_controller.MotorController(self.config["motor"])
        threading.Thread(target=self.motor.connect, daemon=True).start()

        messagebox.showinfo("Configurações", "Salvo com sucesso.")
        self._set_state(STATE_IDLE)

    def open_media_folder(self):
        os.startfile(os.path.abspath(SAVE_DIR))

    # --- tela de eventos (formato do vídeo + marca por evento) -------------

    def _build_events_screen(self):
        screen = tk.Frame(self.container, bg=BG_ROOT)
        self._add_screen("events", screen)

        header = ttk.Frame(screen, style="Dark.TFrame")
        header.pack(fill=tk.X)
        ttk.Label(header, text="Eventos", style="Brand.TLabel").pack(side=tk.LEFT, padx=16, pady=10)
        PillButton(header, text="Voltar", variant="ghost", width=110, height=32,
                   command=lambda: self._set_state(STATE_SETTINGS)).pack(side=tk.RIGHT, padx=16, pady=8)

        body = tk.Frame(screen, bg=BG_ROOT)
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        list_card = Card(body)
        list_card.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        ttk.Label(list_card.content, text="Eventos salvos", style="BrandCard.TLabel").pack(anchor="w", pady=(0, 8))
        self.events_list_frame = tk.Frame(list_card.content, bg=BG_CARD)
        self.events_list_frame.pack(fill=tk.BOTH, expand=True)

        create_card = Card(body)
        create_card.pack(fill=tk.X)
        c = create_card.content
        ttk.Label(c, text="Criar evento", style="BrandCard.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(c, text="Nome do evento", style="MutedCard.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 6))
        self.event_name_entry = ttk.Entry(c, style="Dark.TEntry", width=30)
        self.event_name_entry.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 20))

        # Linhas do módulo Giro 360° (video_widgets) e do Photobooth (strip_widgets):
        # _layout_events_form esconde as do módulo que a licença não libera.
        video_widgets, strip_widgets = [], []

        lbl = ttk.Label(c, text="Template do vídeo 360", style="MutedCard.TLabel")
        lbl.grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.event_video_combo = ttk.Combobox(c, state="readonly", style="Dark.TCombobox", width=38,
                                               values=["Nenhum (formato/texto simples abaixo)"])
        self.event_video_combo.current(0)
        self.event_video_combo.grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 0))
        video_widgets += [lbl, self.event_video_combo]
        self._video_template_ids = [""]

        lbl = ttk.Label(c, text="Formato do vídeo", style="MutedCard.TLabel")
        lbl.grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.event_aspect_combo = ttk.Combobox(c, state="readonly", style="Dark.TCombobox", width=10,
                                                values=event_manager.ASPECT_RATIO_CHOICES)
        self.event_aspect_combo.current(0)
        self.event_aspect_combo.grid(row=3, column=1, sticky="w", pady=(8, 0))
        hint = ttk.Label(c, text="(só sem template: 16:9 normal, 9:16 vertical, 1:1 quadrado)",
                         style="MutedCard.TLabel", font=("Segoe UI", 8))
        hint.grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 0))
        video_widgets += [lbl, self.event_aspect_combo, hint]

        lbl = ttk.Label(c, text="Texto na tela (opcional)", style="MutedCard.TLabel")
        lbl.grid(row=4, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.event_text_entry = ttk.Entry(c, style="Dark.TEntry", width=40)
        self.event_text_entry.grid(row=4, column=1, columnspan=3, sticky="w", pady=(8, 0))
        video_widgets += [lbl, self.event_text_entry]

        lbl = ttk.Label(c, text="Imagem/logo PNG (opcional)", style="MutedCard.TLabel")
        lbl.grid(row=5, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.event_png_label = ttk.Label(c, text="Nenhuma imagem escolhida", style="MutedCard.TLabel")
        self.event_png_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))
        png_btn = PillButton(c, text="Escolher PNG", variant="ghost", width=140, height=32,
                             bg=BG_CARD, command=self._browse_event_png)
        png_btn.grid(row=5, column=3, pady=(8, 0))
        video_widgets += [lbl, self.event_png_label, png_btn]

        lbl = ttk.Label(c, text="Template da tirinha", style="MutedCard.TLabel")
        lbl.grid(row=6, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.event_strip_combo = ttk.Combobox(c, state="readonly", style="Dark.TCombobox", width=38,
                                               values=["Automático (primeiro disponível)"])
        self.event_strip_combo.current(0)
        self.event_strip_combo.grid(row=6, column=1, columnspan=3, sticky="w", pady=(8, 0))
        strip_widgets += [lbl, self.event_strip_combo]
        self._strip_template_ids = [""]

        PillButton(c, text="Criar evento", icon="calendar", variant="primary",
                   width=200, height=44, command=self._create_event).grid(
            row=7, column=0, columnspan=4, pady=(16, 0), sticky="w")

        self._events_video_widgets = video_widgets
        self._events_strip_widgets = strip_widgets
        self._event_png_source = None

    def _layout_events_form(self):
        for widget in self._events_video_widgets:
            widget.grid() if "video360" in self.modules else widget.grid_remove()
        for widget in self._events_strip_widgets:
            widget.grid() if "photobooth" in self.modules else widget.grid_remove()

    def _refresh_template_choices(self):
        strips = strip_templates.list_templates(strip_templates.KIND_STRIP)
        self._strip_template_ids = [""] + [item["id"] for item in strips]
        self.event_strip_combo.config(
            values=["Automático (primeiro disponível)"] + [item["name"] for item in strips])
        self.event_strip_combo.current(0)
        videos = strip_templates.list_templates(strip_templates.KIND_VIDEO)
        self._video_template_ids = [""] + [item["id"] for item in videos]
        self.event_video_combo.config(
            values=["Nenhum (formato/texto simples abaixo)"] + [item["name"] for item in videos])
        self.event_video_combo.current(0)

    def _browse_event_png(self):
        path = filedialog.askopenfilename(
            title="Escolher imagem (PNG)", filetypes=[("PNG", "*.png"), ("Todos os arquivos", "*.*")])
        if path:
            self._event_png_source = path
            self.event_png_label.config(text=os.path.basename(path))

    def _create_event(self):
        name = self.event_name_entry.get().strip()
        if not name:
            messagebox.showerror("Eventos", "Dê um nome pro evento.")
            return
        event_manager.create_event(
            self.events_data, name,
            aspect_ratio=self.event_aspect_combo.get(),
            overlay_text=self.event_text_entry.get().strip(),
            overlay_png_source=self._event_png_source,
            strip_template_id=self._strip_template_ids[self.event_strip_combo.current()],
            video_template_id=self._video_template_ids[self.event_video_combo.current()])
        event_manager.save_events(self.events_data)

        self.event_name_entry.delete(0, tk.END)
        self.event_text_entry.delete(0, tk.END)
        self.event_aspect_combo.current(0)
        self.event_strip_combo.current(0)
        self.event_video_combo.current(0)
        self._event_png_source = None
        self.event_png_label.config(text="Nenhuma imagem escolhida")

        self._refresh_events_list()
        self._update_active_event_label()

    def _refresh_events_list(self):
        for widget in self.events_list_frame.winfo_children():
            widget.destroy()

        if not self.events_data["events"]:
            ttk.Label(self.events_list_frame, text="Nenhum evento criado ainda.",
                      style="MutedCard.TLabel").pack(anchor="w")
            return

        active_id = self.events_data.get("active_event_id")
        for event in self.events_data["events"]:
            row = tk.Frame(self.events_list_frame, bg=BG_CARD)
            row.pack(fill=tk.X, pady=(0, 8))
            is_active = event["id"] == active_id
            label_text = (f"{event['name']}  ({event['aspect_ratio']})"
                          + ("  + template de vídeo" if event.get("video_template_id") else "")
                          + ("  + tirinha" if event.get("strip_template_id") else "")
                          + ("  ✓ ativo" if is_active else ""))
            ttk.Label(row, text=label_text, style="DarkCard.TLabel" if is_active else "MutedCard.TLabel"
                      ).pack(side=tk.LEFT, padx=(0, 12))
            if not is_active:
                PillButton(row, text="Usar", variant="ghost", width=90, height=30, bg=BG_CARD,
                           command=lambda eid=event["id"]: self._activate_event(eid)).pack(side=tk.LEFT, padx=4)
            PillButton(row, text="Excluir", variant="danger", width=90, height=30, bg=BG_CARD,
                       command=lambda eid=event["id"]: self._delete_event(eid)).pack(side=tk.LEFT, padx=4)

    def _activate_event(self, event_id):
        event_manager.set_active_event(self.events_data, event_id)
        event_manager.save_events(self.events_data)
        self._refresh_events_list()
        self._update_active_event_label()

    def _delete_event(self, event_id):
        event_manager.delete_event(self.events_data, event_id)
        event_manager.save_events(self.events_data)
        self._refresh_events_list()
        self._update_active_event_label()

    def _build_strip_editor_screen(self):
        self.strip_editor = strip_editor.StripEditor(
            self.container, on_close=lambda: self._set_state(STATE_SETTINGS))
        self._add_screen("strip_editor", self.strip_editor)

    def _update_active_event_label(self):
        active = event_manager.get_active_event(self.events_data)
        self.active_event_label.config(text=f"Evento: {active['name']}" if active else "")

    def _update_video_settings_availability(self):
        """Resolução/FPS de gravação só existem na API da GoPro - as DSLRs
        (Nikon/Canon) não gravam em 4K, então o card fica travado com
        qualquer outra câmera (ou nenhuma)."""
        is_gopro = isinstance(self.camera, GoProWifiController)
        state = "normal" if is_gopro else "disabled"
        self.video_resolution_combo.config(state="readonly" if is_gopro else "disabled")
        self.video_settings_apply_btn.set_state(state)
        self.video_settings_hint.config(
            text="" if is_gopro else "Disponível só com a GoPro conectada")
        self._refresh_fps_options()
        self.video_fps_combo.config(state="readonly" if is_gopro else "disabled")

    def _on_video_resolution_change(self, _event=None):
        self._refresh_fps_options()

    def _refresh_fps_options(self):
        """A HERO7 Black não aceita qualquer combinação resolução+fps (ex.:
        4K não vai a 240fps) - só oferece os valores que a resolução
        escolhida realmente suporta, pra não deixar escolher algo que a
        câmera vai rejeitar."""
        resolution = self.video_resolution_combo.get()
        valid_fps = gopro_controller.VALID_FPS_FOR_RESOLUTION.get(
            resolution, list(gopro_controller.VIDEO_FRAME_RATES.keys()))
        current = self.video_fps_combo.get()
        self.video_fps_combo.config(values=valid_fps)
        if current in valid_fps:
            self.video_fps_combo.set(current)
        else:
            self.video_fps_combo.current(0)

    def apply_video_settings(self):
        if not isinstance(self.camera, GoProWifiController):
            return
        resolution = self.video_resolution_combo.get()
        fps = self.video_fps_combo.get()
        self.video_settings_apply_btn.config(state="disabled")

        def worker():
            try:
                ok, applied_res, applied_fps = self.camera.apply_video_settings(resolution, fps)
                result = (ok, applied_res, applied_fps, None)
            except Exception as e:
                result = (False, None, None, str(e))
            self.root.after(0, lambda: self._video_settings_result(*result))
        threading.Thread(target=worker, daemon=True).start()

    def _video_settings_result(self, ok, applied_res, applied_fps, error):
        self.video_settings_apply_btn.set_state("normal")
        if error:
            messagebox.showerror("Configurações de vídeo", f"Não foi possível aplicar: {error}")
        elif ok:
            messagebox.showinfo("Configurações de vídeo", "Aplicado com sucesso.")
        else:
            # A câmera respondeu OK mas manteve/aplicou outra coisa - essa
            # combinação não é suportada nessa unidade, mesmo que devesse
            # ser pela tabela oficial (já vimos isso acontecer na prática).
            self.video_resolution_combo.set(applied_res)
            self._refresh_fps_options()
            self.video_fps_combo.set(applied_fps)
            messagebox.showwarning(
                "Configurações de vídeo",
                f"Essa câmera não aceitou essa combinação.\n\n"
                f"Aplicado de verdade: {applied_res} / {applied_fps}")

    # --- encerramento -------------------------------------------------------

    def on_close(self):
        self.running = False
        self._stop_preview_playback()
        self.motor.disconnect()
        self.share_backend.stop()
        if self.camera.connected:
            try:
                self.camera.disconnect()
                print("[INFO] Câmera desconectada")
            except Exception:
                pass
        self.root.destroy()
