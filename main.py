import sys
import os

if len(sys.argv) > 2 and sys.argv[1] == "--webex-window":
    # Processo separado (mesmo executável/interpretador, relançado com essa
    # flag) que só abre o WebView2 oculto pra transmitir a câmera na
    # reunião do Webex - ver _start_broadcast() logo abaixo. Despachado
    # aqui, antes dos imports pesados (Tkinter etc.), porque esse processo
    # não precisa de nada disso.
    import webview
    webview.create_window("Camera360 - Webex", url=sys.argv[2], width=980, height=700, hidden=True)
    webview.start()
    sys.exit(0)

if getattr(sys, "frozen", False):
    # Empacotado com PyInstaller: os DLLs nativos (libgphoto2, tcl/tk, etc.)
    # ficam soltos na raiz do bundle (veja Camera360.spec) e o Tcl/Tk precisa
    # saber onde estão os scripts de init antes de tkinter ser importado.
    _bundle_dir = os.path.dirname(sys.executable)
    os.add_dll_directory(_bundle_dir)
    os.environ.setdefault("TCL_LIBRARY", os.path.join(_bundle_dir, "tcl", "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(_bundle_dir, "tcl", "tk8.6"))

import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
import threading
import time
import hashlib
import unicodedata
import webbrowser
import datetime
import subprocess

from camera_controller import CameraController
import gopro_controller
from gopro_controller import GoProWifiController
from overlay import draw_overlay
import location as geo
import webex_integration as webex
import webex_embed
from widgets import PillButton, Card, Pill, BG_CARD, GHOST_BG

SAVE_DIR = "capturas"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

BG_ROOT = "#101114"
BG_PANEL = "#17181c"
BG_PREVIEW = "#000000"
FG_TEXT = "#e8e8ea"
FG_MUTED = "#8a8d96"
ACCENT = "#00e0a0"
REC_RED = "#ff4d4d"
BORDER = "#2a2c33"
BORDER_LIGHT = "#33353d"

# Quantas vezes mais devagar o vídeo em câmera lenta é reproduzido em
# relação ao que foi realmente capturado. Nenhum frame é inventado: são os
# mesmos frames reais da câmera, só gravados no arquivo com um fps de
# reprodução menor, esticando o tempo real ao assistir.
SLOWMO_FACTOR = 4

# O login salvo do Webex foi revogado no lado do servidor (confirmado via
# API - refresh_token inválido) e não há como renovar sem abrir o navegador
# pra um login novo. Até decidir fazer esse login de novo, os botões do
# Webex ficam desativados (nada tenta abrir o navegador sozinho).
WEBEX_ENABLED = False


def _parse_invitees(raw_text):
    """Converte o texto do campo "Convidar" em uma lista de e-mails."""
    return [part.strip() for part in raw_text.replace("\n", ",").split(",") if part.strip()]


def _invalid_invitees(invitees):
    """E-mails que não têm cara de e-mail (sem '@'), pra avisar antes de
    mandar pra API do Webex em vez de só descobrir depois com um erro 400."""
    return [email for email in invitees if "@" not in email]


def _format_meeting_time(iso_str):
    """Formata um horário ISO (UTC, com 'Z') da API do Webex para hora local."""
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m %H:%M")
    except Exception:
        return iso_str or ""


class Camera360App:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera360 - Controle de Câmera")
        self.root.geometry("1024x768")
        self.root.configure(bg=BG_ROOT)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.camera = CameraController()
        self.running = True
        self.is_recording = False
        self.recording_mode = None
        self.video_frames = []
        self.video_fps = 10
        self.preview_fps = 10
        self.current_mode = "photo"
        self.current_frame = None
        self.frame_hash = None
        self.photo_image = None
        self.last_location = None
        self._webex_embed_server = None
        self._webex_process = None
        self._webex_meeting_id = None
        self._webex_meeting_link = None
        self._webex_live = False
        self._webex_participants_job = None

        self._setup_style()
        self.create_widgets()
        # Força o Tk a terminar a geometria (barra de controles + preview)
        # antes do primeiro frame, senão winfo_width/height() no primeiro
        # update_video() pode ler valores errados (ainda não assentados).
        self.root.update_idletasks()
        self.connect_camera()
        self.update_video()
        self._poll_location()

    def _poll_location(self):
        """Atualiza o lat/lon mostrado no cabeçalho a cada 60s, em segundo
        plano (a consulta ao Windows Location Services pode levar alguns
        segundos e não pode travar a interface)."""
        def worker():
            loc = geo.get_current_location()
            self.root.after(0, lambda: self._update_location_label(loc))

        threading.Thread(target=worker, daemon=True).start()
        if self.running:
            self.root.after(60000, self._poll_location)

    def _update_location_label(self, loc):
        if not loc:
            self.location_label.config(text="Localização indisponível")
            return
        self.last_location = loc
        self.map_btn.config(state="normal")
        self.location_label.config(text=f"Lat {loc['lat']:.5f}, Lon {loc['lon']:.5f}")

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.TFrame", background=BG_PANEL)
        style.configure("Dark.TLabel", background=BG_PANEL, foreground=FG_TEXT)
        style.configure("Muted.TLabel", background=BG_PANEL, foreground=FG_MUTED)
        style.configure("Rec.TLabel", background=BG_PANEL, foreground=REC_RED, font=("Segoe UI", 10, "bold"))
        style.configure("Brand.TLabel", background=BG_PANEL, foreground=FG_TEXT,
                         font=("Segoe UI", 12, "bold"))

        # Variantes dos estilos acima pra uso dentro dos cards (Card usa um
        # fundo BG_CARD levemente diferente do painel/sidebar ao redor).
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
        self.root.option_add("*TCombobox*Listbox.background", BG_PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#062018")

    def create_widgets(self):
        main_frame = tk.Frame(self.root, bg=BG_ROOT)
        main_frame.pack(fill=tk.BOTH, expand=True)
        # Sem isso, o Label do preview "puxa" a janela para crescer sempre que
        # a imagem exibida é maior que o espaço atual (feedback loop: mais
        # espaço -> imagem maior -> pede ainda mais espaço).
        main_frame.pack_propagate(False)

        # --- Cabeçalho: marca + status de conexão ---
        header = ttk.Frame(main_frame, style="Dark.TFrame")
        header.pack(fill=tk.X, side=tk.TOP)
        header_body = ttk.Frame(header, style="Dark.TFrame")
        header_body.pack(fill=tk.X, padx=16, pady=10)
        ttk.Label(header_body, text="Camera360", style="Brand.TLabel").pack(side=tk.LEFT)

        self.recording_indicator = ttk.Label(header_body, text="", style="Rec.TLabel")
        self.recording_indicator.pack(side=tk.RIGHT)
        self.status_dot = tk.Canvas(header_body, width=10, height=10, bg=BG_PANEL,
                                     highlightthickness=0)
        self.status_dot.pack(side=tk.LEFT, padx=(16, 6))
        self.status_label = ttk.Label(header_body, text="Desconectado", style="Muted.TLabel")
        self.status_label.pack(side=tk.LEFT)
        self._draw_status_dot(False)

        # Só aparece quando a câmera falha por causa do driver WPD do
        # Windows já ter "agarrado" o dispositivo ([-53] Could not claim) -
        # deixa corrigir sem precisar abrir PowerShell manualmente.
        self.fix_camera_btn = PillButton(header_body, text="Corrigir e tentar de novo",
                                          variant="ghost", width=200, height=30,
                                          font=("Segoe UI", 9, "bold"),
                                          command=self._fix_camera_driver_conflict)

        header_border = tk.Frame(main_frame, bg=BORDER, height=1)
        header_border.pack(fill=tk.X, side=tk.TOP)

        # --- Barra de controles (reservada ANTES do preview: garante que
        # sua altura nunca é engolida pelo painel de vídeo) ---
        control_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        control_frame.pack(fill=tk.X, side=tk.BOTTOM)
        top_row = tk.Frame(control_frame, bg=BORDER, height=1)
        top_row.pack(fill=tk.X, side=tk.TOP)

        body = ttk.Frame(control_frame, style="Dark.TFrame")
        body.pack(fill=tk.X, pady=10, padx=14)

        left = ttk.Frame(body, style="Dark.TFrame")
        left.pack(side=tk.LEFT)
        self.mode_photo_btn = PillButton(left, text="Foto", icon="camera", variant="ghost-active",
                                          width=110, height=38, command=lambda: self.set_mode("photo"))
        self.mode_photo_btn.pack(side=tk.LEFT)
        self.mode_video_btn = PillButton(left, text="Vídeo", icon="video", variant="ghost",
                                          width=110, height=38, command=lambda: self.set_mode("video"))
        self.mode_video_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.mode_slowmo_btn = PillButton(left, text="Câmera lenta", icon="hourglass", variant="ghost",
                                           width=160, height=38, command=lambda: self.set_mode("slowmo"))
        self.mode_slowmo_btn.pack(side=tk.LEFT, padx=(6, 0))

        center = ttk.Frame(body, style="Dark.TFrame")
        center.pack(side=tk.LEFT, expand=True)
        self.capture_canvas = tk.Canvas(center, width=64, height=64, bg=BG_PANEL,
                                         highlightthickness=0, cursor="hand2")
        self.capture_canvas.pack()
        self.capture_canvas.bind("<Button-1>", lambda e: self.on_capture())
        self._draw_capture_button()

        right = ttk.Frame(body, style="Dark.TFrame")
        right.pack(side=tk.RIGHT)
        PillButton(right, text="Sair", icon="power", variant="danger", width=110, height=38,
                   command=self.on_close).pack(side=tk.RIGHT)
        PillButton(right, text="Mídia", icon="folder", variant="ghost", width=110, height=38,
                   command=self.open_media_folder).pack(side=tk.RIGHT, padx=(0, 8))

        # --- Barra lateral direita retrátil: sessão do Webex (entrar agora,
        # agendar reunião, reuniões agendadas). Empacotada ANTES do preview
        # para reservar sua largura primeiro. ---
        sidebar_container = tk.Frame(main_frame, bg=BG_PANEL)
        sidebar_container.pack(fill=tk.Y, side=tk.RIGHT)

        self.sidebar_open = True
        self.sidebar_toggle_btn = tk.Button(
            sidebar_container, text="»", command=self.toggle_sidebar,
            bg=BG_PANEL, fg=FG_MUTED, activebackground=BG_PANEL, activeforeground=FG_TEXT,
            bd=0, highlightthickness=0, font=("Segoe UI", 11), width=2, cursor="hand2")
        self.sidebar_toggle_btn.pack(fill=tk.Y, side=tk.LEFT)

        tk.Frame(sidebar_container, bg=BORDER, width=1).pack(fill=tk.Y, side=tk.LEFT)

        self.sidebar_content = tk.Frame(sidebar_container, bg=BG_PANEL, width=300)
        self.sidebar_content.pack(fill=tk.Y, side=tk.LEFT)
        self.sidebar_content.pack_propagate(False)

        sidebar_pad = tk.Frame(self.sidebar_content, bg=BG_PANEL)
        sidebar_pad.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        # --- Card inferior: Google Maps (localização atual) - empacotado
        # com side=BOTTOM ANTES da lista de reuniões, para reservar seu
        # espaço e não deixar a lista (que expande) engolir o card. ---
        maps_card = Card(sidebar_pad)
        maps_card.pack(fill=tk.X, side=tk.BOTTOM, pady=(12, 0))
        maps_section = maps_card.content

        ttk.Label(maps_section, text="Google Maps", style="DarkCard.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.location_label = ttk.Label(maps_section, text="Localizando...", style="MutedCard.TLabel")
        self.location_label.pack(anchor="w", pady=(0, 10))
        self.map_btn = PillButton(maps_section, text="Ver no mapa", icon="pin", variant="ghost",
                                   width=260, height=36, bg=BG_CARD,
                                   command=self.open_last_location)
        self.map_btn.pack(fill=tk.X)
        self.map_btn.set_state("disabled")

        # --- Card: configurações de gravação de vídeo (resolução/FPS) -
        # só a GoPro expõe isso por essa API; DSLR (Nikon/Canon) não grava
        # em 4K, então esse card fica desativado enquanto não for ela a
        # câmera ativa (ver _update_video_settings_availability). ---
        settings_card = Card(sidebar_pad)
        settings_card.pack(fill=tk.X, side=tk.BOTTOM, pady=(12, 0))
        settings_section = settings_card.content

        ttk.Label(settings_section, text="Configurações de vídeo", style="DarkCard.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.video_settings_hint = ttk.Label(
            settings_section, text="Disponível só com a GoPro conectada",
            style="MutedCard.TLabel", wraplength=230, justify=tk.LEFT)
        self.video_settings_hint.pack(anchor="w", pady=(0, 8))

        ttk.Label(settings_section, text="Resolução", style="MutedCard.TLabel").pack(anchor="w")
        self.video_resolution_combo = ttk.Combobox(
            settings_section, state="disabled", style="Dark.TCombobox",
            values=list(gopro_controller.VIDEO_RESOLUTIONS.keys()))
        self.video_resolution_combo.current(list(gopro_controller.VIDEO_RESOLUTIONS).index("1080p"))
        self.video_resolution_combo.bind("<<ComboboxSelected>>", self._on_video_resolution_change)
        self.video_resolution_combo.pack(fill=tk.X, pady=(2, 10))

        ttk.Label(settings_section, text="FPS", style="MutedCard.TLabel").pack(anchor="w")
        self.video_fps_combo = ttk.Combobox(
            settings_section, state="disabled", style="Dark.TCombobox")
        self.video_fps_combo.pack(fill=tk.X, pady=(2, 12))
        self._refresh_fps_options()

        self.video_settings_apply_btn = PillButton(
            settings_section, text="Aplicar", icon="camera", variant="ghost",
            width=260, height=36, bg=BG_CARD, command=self.apply_video_settings)
        self.video_settings_apply_btn.pack(fill=tk.X)
        self.video_settings_apply_btn.set_state("disabled")

        # --- Card superior: Webex. Transmissão só de saída (a câmera do
        # Camera360 vai para os outros participantes) - por isso não existe
        # nenhuma tela de vídeo recebido aqui, só o status "ao vivo" e quem
        # está na reunião. ---
        webex_card = Card(sidebar_pad)
        webex_card.pack(fill=tk.X, side=tk.TOP, pady=(0, 12))
        webex_section = webex_card.content

        ttk.Label(webex_section, text="Webex", style="BrandCard.TLabel").pack(anchor="w")

        ttk.Label(webex_section, text="Convidar (e-mails, separados por vírgula)",
                  style="MutedCard.TLabel", wraplength=230, justify=tk.LEFT).pack(anchor="w", pady=(12, 4))
        self.webex_invitees_entry = ttk.Entry(webex_section, style="Dark.TEntry")
        self.webex_invitees_entry.pack(fill=tk.X, pady=(0, 12))

        self.webex_join_now_btn = PillButton(
            webex_section, text="Entrar agora" if WEBEX_ENABLED else "Webex desativado",
            icon="play", variant="primary", width=260, height=42, bg=BG_CARD,
            command=self.webex_join_now)
        if not WEBEX_ENABLED:
            self.webex_join_now_btn.set_state("disabled")
        self.webex_join_now_btn.pack(fill=tk.X, pady=(0, 20))

        # --- Estado "ao vivo": some o botão "Entrar agora" e mostra o
        # indicador + quem está na reunião + botão de sair. Construído já
        # aqui, mas só empacotado quando a transmissão realmente começa. ---
        self.webex_live_frame = tk.Frame(webex_section, bg=BG_CARD)

        live_status_row = tk.Frame(self.webex_live_frame, bg=BG_CARD)
        live_status_row.pack(fill=tk.X, pady=(12, 12))
        self.webex_live_dot = tk.Canvas(live_status_row, width=10, height=10, bg=BG_CARD,
                                         highlightthickness=0)
        self.webex_live_dot.pack(side=tk.LEFT, padx=(0, 8))
        self.webex_live_dot.create_oval(1, 1, 9, 9, fill=REC_RED, outline="")
        ttk.Label(live_status_row, text="Transmitindo ao vivo", style="DarkCard.TLabel").pack(side=tk.LEFT)

        self.webex_copy_link_btn = PillButton(self.webex_live_frame, text="Copiar link", icon="link",
                                               variant="ghost", width=260, height=36, bg=BG_CARD,
                                               command=self._copy_webex_meeting_link)
        self.webex_copy_link_btn.pack(fill=tk.X, pady=(0, 8))

        self.webex_leave_btn = PillButton(self.webex_live_frame, text="Sair da reunião", icon="hangup",
                                           variant="danger", width=260, height=36, bg=BG_CARD,
                                           command=self.webex_leave_meeting)
        self.webex_leave_btn.pack(fill=tk.X, pady=(0, 16))

        ttk.Label(self.webex_live_frame, text="Participantes", style="DarkCard.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        self.webex_participants_frame = tk.Frame(self.webex_live_frame, bg=BG_CARD)
        self.webex_participants_frame.pack(fill=tk.X, pady=(0, 20))

        self.webex_schedule_label = ttk.Label(webex_section, text="Agendar reunião", style="DarkCard.TLabel",
                                               font=("Segoe UI", 10, "bold"))
        self.webex_schedule_label.pack(anchor="w", pady=(0, 10))

        ttk.Label(webex_section, text="Título", style="MutedCard.TLabel").pack(anchor="w")
        self.webex_title_entry = ttk.Entry(webex_section, style="Dark.TEntry")
        self.webex_title_entry.insert(0, "Camera360 - Reunião")
        self.webex_title_entry.pack(fill=tk.X, pady=(2, 10))

        ttk.Label(webex_section, text="Quando", style="MutedCard.TLabel").pack(anchor="w")
        self.webex_when_combo = ttk.Combobox(
            webex_section, state="readonly", style="Dark.TCombobox",
            values=["Agora", "Em 15 minutos", "Em 30 minutos", "Em 1 hora", "Amanhã às 9h"])
        self.webex_when_combo.current(0)
        self.webex_when_combo.pack(fill=tk.X, pady=(2, 10))

        ttk.Label(webex_section, text="Duração", style="MutedCard.TLabel").pack(anchor="w")
        self.webex_duration_combo = ttk.Combobox(
            webex_section, state="readonly", style="Dark.TCombobox",
            values=["30 minutos", "60 minutos", "90 minutos"])
        self.webex_duration_combo.current(1)
        self.webex_duration_combo.pack(fill=tk.X, pady=(2, 16))

        self.webex_schedule_btn = PillButton(
            webex_section, text="Agendar", icon="calendar", variant="ghost", width=260, height=36,
            bg=BG_CARD, command=self.schedule_webex_meeting)
        if not WEBEX_ENABLED:
            self.webex_schedule_btn.set_state("disabled")
        self.webex_schedule_btn.pack(fill=tk.X, pady=(0, 20))

        list_header = tk.Frame(webex_section, bg=BG_CARD)
        list_header.pack(fill=tk.X)
        ttk.Label(list_header, text="Reuniões agendadas", style="DarkCard.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        refresh_btn = PillButton(list_header, text="", icon="refresh", variant="ghost",
                                  width=30, height=30, bg=BG_CARD,
                                  command=self.refresh_webex_meetings)
        if not WEBEX_ENABLED:
            refresh_btn.set_state("disabled")
        refresh_btn.pack(side=tk.RIGHT)

        meetings_card = Card(sidebar_pad, expand=True, pady=12)
        meetings_card.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=(0, 12))
        self.webex_meetings_list_frame = meetings_card.content

        # --- Área dedicada do preview: painel emoldurado, centralizado,
        # que preenche o espaço restante sem nunca cortar o HUD desenhado
        # sobre o frame (ajuste "contain", com tarjas quando a proporção
        # não bate exatamente). ---
        preview_outer = tk.Frame(main_frame, bg=BG_ROOT)
        preview_outer.pack(fill=tk.BOTH, expand=True, side=tk.TOP, padx=18, pady=16)

        preview_panel = tk.Frame(preview_outer, bg=BORDER_LIGHT, highlightthickness=1,
                                  highlightbackground=BORDER_LIGHT)
        preview_panel.pack(fill=tk.BOTH, expand=True)

        self.video_label = tk.Label(preview_panel, bg=BG_PREVIEW)
        self.video_label.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Pílula "REC mm:ss" flutuante sobre o preview - só aparece
        # gravando (place_forget no resto do tempo), com cronômetro
        # atualizado por _tick_recording_timer().
        self.rec_pill = Pill(preview_panel, text="", dot_color=REC_RED, bg="#1c1c1e")
        self._rec_start_time = None

        self.set_mode("photo")
        if WEBEX_ENABLED:
            self.refresh_webex_meetings()
        else:
            ttk.Label(self.webex_meetings_list_frame, text="Webex desativado temporariamente.",
                      style="MutedCard.TLabel", wraplength=260, justify=tk.LEFT).pack(anchor="w")

    def _draw_status_dot(self, connected):
        c = self.status_dot
        c.delete("all")
        color = ACCENT if connected else "#5a5d66"
        c.create_oval(1, 1, 9, 9, fill=color, outline="")

    def _is_video_like_mode(self):
        return self.current_mode in ("video", "slowmo")

    def _draw_capture_button(self):
        c = self.capture_canvas
        c.delete("all")
        recording_now = self._is_video_like_mode() and self.is_recording
        ring_color = REC_RED if recording_now else ACCENT
        c.create_oval(2, 2, 62, 62, outline=ring_color, width=3)
        if recording_now:
            c.create_rectangle(22, 22, 42, 42, fill=REC_RED, outline="")
        else:
            c.create_oval(8, 8, 56, 56, fill="white", outline="")

    def set_mode(self, mode):
        self.current_mode = mode
        buttons = {
            "photo": self.mode_photo_btn,
            "video": self.mode_video_btn,
            "slowmo": self.mode_slowmo_btn,
        }
        for name, btn in buttons.items():
            btn.set_variant("ghost-active" if name == mode else "ghost")
        self._draw_capture_button()

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

    def update_status(self, msg, connected=None, usb_conflict=False):
        self.status_label.config(text=msg)
        if connected is not None:
            self._draw_status_dot(connected)
        if usb_conflict:
            self.fix_camera_btn.pack(side=tk.LEFT, padx=(16, 0))
        else:
            self.fix_camera_btn.pack_forget()

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
            # Disable-PnpDevice falha com "Falha genérica" (HRESULT
            # 0x80041001) pra esse tipo de dispositivo WPD, mesmo com
            # permissão de administrador - pnputil (utilitário nativo do
            # Windows) consegue desativar onde o cmdlet do PowerShell falha.
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
            error = self.camera.get_last_error() if self.camera.connected else None
            message = error if error else "Sem sinal da camera"
            # cv2.putText só sabe desenhar ASCII - acentos viram "??"; tira os
            # acentos só para o texto desenhado no frame (a barra de status
            # em Tk mostra a mensagem original, com acentos, normalmente).
            ascii_message = unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode("ascii")
            cv2.putText(frame, ascii_message, (20, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2)
            if error:
                self.update_status(error)

        cam_info = {
            "recording": self.is_recording,
            "focus_confirmed": self.camera.get_focus_confirmed(),
        }
        frame = draw_overlay(frame, show_grid=True, show_ruler=True, cam_info=cam_info)
        self.current_frame = frame

        if self.is_recording:
            self.video_frames.append(frame.copy())

        new_hash = hashlib.md5(frame.tobytes()).hexdigest()
        if new_hash != self.frame_hash:
            self.frame_hash = new_hash
            try:
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_pil = Image.fromarray(img_rgb)

                label_width = self.video_label.winfo_width()
                label_height = self.video_label.winfo_height()
                if label_width < 10 or label_height < 10:
                    label_width, label_height = 800, 600

                # Ajusta ao painel de preview sem cortar nada (estilo
                # "contain"): amplia/encolhe mantendo a proporção inteira do
                # frame - incluindo cantos, régua etc. - e centraliza sobre
                # fundo preto quando a proporção não bate exatamente.
                img_w, img_h = img_pil.size
                scale = min(label_width / img_w, label_height / img_h)
                new_w, new_h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
                img_pil = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)

                canvas = Image.new("RGB", (label_width, label_height), (0, 0, 0))
                canvas.paste(img_pil, ((label_width - new_w) // 2, (label_height - new_h) // 2))

                imgtk = ImageTk.PhotoImage(master=self.root, image=canvas)
                self.photo_image = imgtk
                self.video_label.config(image=imgtk)
                self.video_label.image = imgtk
            except Exception as e:
                print(f"Erro ao atualizar imagem: {e}")

        self.root.after(50, self.update_video)

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
                return
            self.root.after(0, lambda: self._update_location_label(loc))
        threading.Thread(target=worker, daemon=True).start()

    def toggle_sidebar(self):
        if self.sidebar_open:
            self.sidebar_content.pack_forget()
            self.sidebar_toggle_btn.config(text="«")
        else:
            self.sidebar_content.pack(fill=tk.Y, side=tk.LEFT)
            self.sidebar_toggle_btn.config(text="»")
        self.sidebar_open = not self.sidebar_open

    def webex_join_now(self):
        """
        Cria uma reunião Webex e começa a transmitir a câmera do Camera360 para
        ela - tudo dentro da própria janela do Camera360. Não recebemos vídeo de
        ninguém, só enviamos: um WebView2 oculto (sem janela visível) roda em
        segundo plano só para negociar o WebRTC e empurrar o vídeo real da
        câmera (com a régua/overlay) como se fosse a webcam, via
        canvas.captureStream() (sem precisar de driver de câmera virtual). A
        própria barra lateral do Camera360 vira o "controle remoto": mostra o
        status ao vivo, quem entrou na reunião e o botão de sair.
        """
        if not WEBEX_ENABLED:
            return
        invitees = _parse_invitees(self.webex_invitees_entry.get())
        invalid = _invalid_invitees(invitees)
        if invalid:
            messagebox.showerror("Webex", "E-mail(s) inválido(s) em Convidar:\n\n" + "\n".join(invalid))
            return

        self.webex_join_now_btn.config(state="disabled", text="Entrando...")

        def worker():
            try:
                access_token = webex.get_access_token()
                meeting = webex.create_instant_meeting(invitees=invitees)
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._webex_join_result(error=err_msg))
                return
            self.root.after(0, lambda: self._webex_join_result(access_token=access_token, meeting=meeting))

        threading.Thread(target=worker, daemon=True).start()

    def _webex_join_result(self, access_token=None, meeting=None, error=None):
        if error:
            self.webex_join_now_btn.config(state="normal", text="Entrar agora")
            messagebox.showerror("Webex", f"Não foi possível entrar na reunião:\n\n{error}")
            return
        link = meeting.get("webLink")
        if not link:
            self.webex_join_now_btn.config(state="normal", text="Entrar agora")
            messagebox.showerror("Webex", "Reunião criada, mas sem link de acesso.")
            return
        self.refresh_webex_meetings()
        self._webex_meeting_id = meeting.get("id")
        self._webex_meeting_link = link
        self._start_broadcast(access_token, link)
        self._enter_live_state()

    def _copy_webex_meeting_link(self):
        """
        O organizador entra com a própria conta Webex (separada da que o
        Camera360 usa pra transmitir) - por isso ele precisa do link pra entrar
        pelo app/navegador dele, não pelo Camera360.
        """
        if not self._webex_meeting_link:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._webex_meeting_link)
        messagebox.showinfo("Webex", "Link da reunião copiado para a área de transferência.")

    def _start_broadcast(self, access_token, meeting_link):
        """
        Sobe o servidor HTTP local que serve o "vídeo falso" (canvas
        alimentado pelos frames reais da câmera) e o processo WebView2
        oculto que efetivamente entra na reunião e transmite. Nada disso
        abre uma janela visível - é só o motor de transmissão rodando em
        segundo plano; a interface do Webex que o usuário vê é a própria
        barra lateral do Camera360.
        """
        if self._webex_embed_server is None:
            self._webex_embed_server = webex_embed.WebexEmbedServer(
                get_frame_callback=lambda: self.current_frame)
            self._webex_embed_server.start()
        self._webex_embed_server.set_meeting(access_token, meeting_link)

        if getattr(sys, "frozen", False):
            # O próprio .exe empacotado, relançado com a flag - não há um
            # "webex_window_process.py" separado dentro do bundle.
            args = [sys.executable, "--webex-window", self._webex_embed_server.url]
        else:
            args = [sys.executable, __file__, "--webex-window", self._webex_embed_server.url]
        self._webex_process = subprocess.Popen(args)

    def _enter_live_state(self):
        self._webex_live = True
        self.webex_join_now_btn.pack_forget()
        self.webex_live_frame.pack(fill=tk.X, before=self.webex_schedule_label)
        self._poll_webex_participants()

    def webex_leave_meeting(self):
        """Encerra a transmissão: derruba o processo do WebView2 oculto e
        volta a barra lateral ao estado inicial (botão "Entrar agora")."""
        if self._webex_process is not None:
            try:
                self._webex_process.terminate()
            except Exception:
                pass
            self._webex_process = None
        self._webex_live = False
        self._webex_meeting_id = None
        self._webex_meeting_link = None
        if self._webex_participants_job is not None:
            self.root.after_cancel(self._webex_participants_job)
            self._webex_participants_job = None
        self.webex_live_frame.pack_forget()
        self.webex_join_now_btn.config(state="normal", text="Entrar agora")
        self.webex_join_now_btn.pack(fill=tk.X, pady=(0, 20), before=self.webex_schedule_label)

    def _poll_webex_participants(self):
        if not self._webex_live or not self._webex_meeting_id:
            return

        def worker():
            try:
                participants = webex.get_meeting_participants(self._webex_meeting_id)
            except Exception:
                participants = None
            self.root.after(0, lambda: self._update_participants_list(participants))

        threading.Thread(target=worker, daemon=True).start()
        self._webex_participants_job = self.root.after(8000, self._poll_webex_participants)

    def _update_participants_list(self, participants):
        for widget in self.webex_participants_frame.winfo_children():
            widget.destroy()
        if participants is None:
            ttk.Label(self.webex_participants_frame, text="Aguardando reunião começar...",
                      style="MutedCard.TLabel", wraplength=250, justify=tk.LEFT).pack(anchor="w")
            return
        if not participants:
            ttk.Label(self.webex_participants_frame, text="Só o Camera360, por enquanto.",
                      style="MutedCard.TLabel", wraplength=250, justify=tk.LEFT).pack(anchor="w")
            return
        for p in participants:
            name = p.get("displayName") or p.get("email") or "Participante"
            self._add_avatar_row(self.webex_participants_frame, name)

    def _add_avatar_row(self, parent, name):
        """Linha com avatar circular (inicial do nome) + texto, no estilo
        das listas de contatos/participantes do Webex."""
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill=tk.X, pady=(0, 6))
        avatar = tk.Canvas(row, width=22, height=22, bg=BG_CARD, highlightthickness=0)
        avatar.pack(side=tk.LEFT, padx=(0, 8))
        initial = (name.strip()[:1] or "?").upper()
        avatar.create_oval(1, 1, 21, 21, fill=GHOST_BG, outline="")
        avatar.create_text(11, 11, text=initial, fill=ACCENT, font=("Segoe UI", 9, "bold"))
        ttk.Label(row, text=name, style="DarkCard.TLabel", wraplength=210,
                  justify=tk.LEFT).pack(side=tk.LEFT)

    def schedule_webex_meeting(self):
        """Agenda uma reunião Webex com o título/horário/duração escolhidos na barra lateral."""
        if not WEBEX_ENABLED:
            return
        title = self.webex_title_entry.get().strip() or "Camera360 - Reunião"
        when_label = self.webex_when_combo.get()
        duration_minutes = {"30 minutos": 30, "60 minutos": 60, "90 minutos": 90}.get(
            self.webex_duration_combo.get(), 60)

        now_local = datetime.datetime.now()
        if when_label == "Em 15 minutos":
            start_local = now_local + datetime.timedelta(minutes=15)
        elif when_label == "Em 30 minutos":
            start_local = now_local + datetime.timedelta(minutes=30)
        elif when_label == "Em 1 hora":
            start_local = now_local + datetime.timedelta(hours=1)
        elif when_label == "Amanhã às 9h":
            start_local = (now_local + datetime.timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0)
        else:  # "Agora"
            start_local = now_local + datetime.timedelta(minutes=1)

        start_utc = start_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        end_utc = start_utc + datetime.timedelta(minutes=duration_minutes)

        invitees = _parse_invitees(self.webex_invitees_entry.get())
        invalid = _invalid_invitees(invitees)
        if invalid:
            messagebox.showerror("Webex", "E-mail(s) inválido(s) em Convidar:\n\n" + "\n".join(invalid))
            return

        self.webex_schedule_btn.config(state="disabled", text="Agendando...")

        def worker():
            try:
                meeting = webex.create_meeting(title, start_utc, end_utc, invitees=invitees)
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._webex_schedule_result(error=err_msg))
                return
            self.root.after(0, lambda: self._webex_schedule_result(meeting=meeting))

        threading.Thread(target=worker, daemon=True).start()

    def _webex_schedule_result(self, meeting=None, error=None):
        self.webex_schedule_btn.config(state="normal", text="Agendar")
        if error:
            messagebox.showerror("Webex", f"Não foi possível agendar a reunião:\n\n{error}")
            return
        link = meeting.get("webLink", "(sem link retornado)")
        self.root.clipboard_clear()
        self.root.clipboard_append(link)
        messagebox.showinfo("Webex", f"Reunião agendada! Link copiado para a área de transferência:\n\n{link}")
        self.refresh_webex_meetings()

    def refresh_webex_meetings(self):
        if not WEBEX_ENABLED:
            return
        for widget in self.webex_meetings_list_frame.winfo_children():
            widget.destroy()
        ttk.Label(self.webex_meetings_list_frame, text="Carregando...", style="MutedCard.TLabel").pack(anchor="w")

        def worker():
            try:
                meetings = webex.list_upcoming_meetings()
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._webex_meetings_result(error=err_msg))
                return
            self.root.after(0, lambda: self._webex_meetings_result(meetings=meetings))

        threading.Thread(target=worker, daemon=True).start()

    def _webex_meetings_result(self, meetings=None, error=None):
        for widget in self.webex_meetings_list_frame.winfo_children():
            widget.destroy()
        if error:
            ttk.Label(self.webex_meetings_list_frame, text=f"Erro: {error}", style="MutedCard.TLabel",
                      wraplength=260, justify=tk.LEFT).pack(anchor="w")
            return
        if not meetings:
            ttk.Label(self.webex_meetings_list_frame, text="Nenhuma reunião agendada.",
                      style="MutedCard.TLabel").pack(anchor="w")
            return
        for m in meetings:
            row = tk.Frame(self.webex_meetings_list_frame, bg=BG_CARD)
            row.pack(fill=tk.X, pady=(0, 12))
            title_row = tk.Frame(row, bg=BG_CARD)
            title_row.pack(fill=tk.X)
            dot = tk.Canvas(title_row, width=8, height=8, bg=BG_CARD, highlightthickness=0)
            dot.pack(side=tk.LEFT, padx=(0, 8))
            dot.create_oval(1, 1, 7, 7, fill=ACCENT, outline="")
            ttk.Label(title_row, text=m.get("title", "Sem título"), style="DarkCard.TLabel",
                      wraplength=220, justify=tk.LEFT).pack(side=tk.LEFT, anchor="w")
            ttk.Label(row, text=_format_meeting_time(m.get("start", "")),
                      style="MutedCard.TLabel").pack(anchor="w", padx=(16, 0))
            link = m.get("webLink")
            if link:
                PillButton(row, text="Entrar", icon="play", variant="ghost", width=110, height=30,
                           bg=BG_CARD, font=("Segoe UI", 9, "bold"),
                           command=lambda l=link: webbrowser.open(l)).pack(anchor="w", pady=(6, 0), padx=(16, 0))

    def open_last_location(self):
        if not self.last_location:
            return
        webbrowser.open(geo.maps_url(self.last_location["lat"], self.last_location["lon"]))

    def open_media_folder(self):
        os.startfile(os.path.abspath(SAVE_DIR))

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

    def on_capture(self):
        if self.is_recording:
            # Sempre para a gravação em andamento, mesmo que o modo tenha
            # sido trocado (FOTO/VÍDEO/CÂMERA LENTA) depois de começar.
            self.stop_recording()
        elif self.current_mode == "photo":
            self.capture_photo()
        elif self._is_video_like_mode():
            self.start_recording()

    def capture_photo(self):
        timestamp = int(time.time())
        filename = f"photo_{timestamp}.jpg"
        full_path = os.path.join(SAVE_DIR, filename)

        if self.camera.connected:
            try:
                data = self.camera.capture_photo()
                with open(full_path, "wb") as f:
                    f.write(data)
                self._tag_capture_with_location(full_path)
                messagebox.showinfo("Sucesso", f"Foto salva em: {full_path}")
                self.update_status(f"Foto salva: {filename}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao capturar foto: {e}")
        elif self.current_frame is not None:
            cv2.imwrite(full_path, self.current_frame)
            self._tag_capture_with_location(full_path)
            messagebox.showinfo("Sucesso", f"Foto simulada salva em: {full_path}")
            self.update_status(f"Foto salva: {filename}")
        else:
            messagebox.showerror("Erro", "Nenhum frame disponível")

    def start_recording(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.recording_mode = self.current_mode  # trava o modo até parar de gravar
        self.video_frames = []
        label = "● GRAVANDO (CÂMERA LENTA)" if self.recording_mode == "slowmo" else "● GRAVANDO"
        self.recording_indicator.config(text=label)
        self._draw_capture_button()
        self.update_status("Gravando vídeo...")

        self._rec_start_time = time.time()
        self.rec_pill.set_text("REC 00:00")
        self.rec_pill.place(relx=1.0, rely=0.0, x=-12, y=12, anchor="ne")
        self._tick_recording_timer()

    def _tick_recording_timer(self):
        if not self.is_recording or self._rec_start_time is None:
            return
        elapsed = int(time.time() - self._rec_start_time)
        mm, ss = divmod(elapsed, 60)
        self.rec_pill.set_text(f"REC {mm:02d}:{ss:02d}")
        self.root.after(1000, self._tick_recording_timer)

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.recording_indicator.config(text="")
        self._draw_capture_button()
        self.update_status("Salvando vídeo...")
        self._rec_start_time = None
        self.rec_pill.place_forget()

        if not self.video_frames:
            messagebox.showwarning("Aviso", "Nenhum frame capturado.")
            self.update_status("Pronto")
            return

        is_slowmo = self.recording_mode == "slowmo"
        # Câmera lenta honesta: mesmos frames reais, só gravados com um fps
        # de reprodução menor, o que estica o tempo real na hora de assistir
        # (sem inventar quadros por interpolação).
        write_fps = max(1, self.video_fps / SLOWMO_FACTOR) if is_slowmo else self.video_fps

        timestamp = int(time.time())
        tag = "slowmo" if is_slowmo else "video"
        filename = f"{tag}_{timestamp}.mp4"
        full_path = os.path.join(SAVE_DIR, filename)
        h, w = self.video_frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(full_path, fourcc, write_fps, (w, h))
        for frame in self.video_frames:
            out.write(frame)
        out.release()
        self.video_frames = []
        self._tag_capture_with_location(full_path)
        messagebox.showinfo("Sucesso", f"Vídeo salvo em: {full_path}")
        self.update_status("Pronto")

    def on_close(self):
        self.running = False
        if self.is_recording:
            self.stop_recording()
        if self._webex_process is not None:
            try:
                self._webex_process.terminate()
            except Exception:
                pass
        if self._webex_embed_server is not None:
            try:
                self._webex_embed_server.stop()
            except Exception:
                pass
        if self.camera.connected:
            try:
                self.camera.disconnect()
                print("[INFO] Câmera desconectada")
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = Camera360App(root)
    root.mainloop()
