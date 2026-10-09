"""
Editor de templates da tirinha de fotos (tela do operador): canvas com a
prévia renderizada, camadas (foto, imagem, texto, retângulo, elipse) que se
arrasta/redimensiona, lista de camadas e painel de propriedades. A prévia é
desenhada por strip_renderer.render_template - o mesmo código da tirinha
final, então o editor mostra exatamente o que vai sair.
"""
import copy
import json
import math
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageTk

import strip_renderer
import strip_templates
from widgets import PillButton

BG_ROOT = "#101114"
BG_PANEL = "#17181c"
BG_CARD = "#1c1e24"
BG_CANVAS = "#1b1c20"
FG_TEXT = "#e8e8ea"
FG_MUTED = "#8a8d96"
ACCENT = "#00e0a0"

HANDLE_SIZE = 6
HANDLES = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0),
           "se": (1, 1), "s": (0, 1), "sw": (-1, 1), "w": (-1, 0)}
LAYER_LABELS = {"photo": "Foto", "video": "Vídeo", "image": "Imagem", "text": "Texto",
                "rect": "Retângulo", "ellipse": "Elipse"}
MIN_SIZE = 10
UNDO_LIMIT = 100


def _rotate(x, y, degrees):
    """Gira (x, y) `degrees` no sentido horário (eixo y pra baixo, como na tela)."""
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    return x * cos - y * sin, x * sin + y * cos


class StripEditor(tk.Frame):
    def __init__(self, parent, on_close):
        super().__init__(parent, bg=BG_ROOT)
        self.on_close = on_close
        self.allowed_kinds = list(strip_templates.KINDS)
        self.template = None
        self.template_ids = []
        self.selected = None
        self._undo = []
        self._redo = []
        self._last_coalesce = None
        self._dirty = False
        self._loading = False
        self._photo_ref = None
        self._scale = 1.0
        self._ox = 0
        self._oy = 0
        self._drag = None
        self._render_job = None

        self._setup_styles()
        self._build_topbar()
        body = tk.Frame(self, bg=BG_ROOT)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_canvas(body)
        self._build_right(body)

    # --- estilos / construção da tela ------------------------------------

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")  # só o clam respeita fieldbackground/arrowcolor nos campos escuros
        style.configure("SE.TFrame", background=BG_PANEL)
        style.configure("SE.TLabel", background=BG_PANEL, foreground=FG_TEXT)
        style.configure("SEMuted.TLabel", background=BG_PANEL, foreground=FG_MUTED)
        style.configure("SEHead.TLabel", background=BG_PANEL, foreground=FG_TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("SE.TEntry", fieldbackground=BG_CARD, foreground=FG_TEXT, insertcolor=FG_TEXT,
                        borderwidth=1)
        style.configure("SE.TCombobox", fieldbackground=BG_CARD, background=BG_CARD, foreground=FG_TEXT,
                        arrowcolor=FG_MUTED, borderwidth=1)
        style.map("SE.TCombobox", fieldbackground=[("readonly", BG_CARD)], foreground=[("readonly", FG_TEXT)])
        style.configure("SE.TCheckbutton", background=BG_PANEL, foreground=FG_TEXT)

    def _build_topbar(self):
        bar = ttk.Frame(self, style="SE.TFrame")
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Templates", style="SEHead.TLabel").pack(side=tk.LEFT, padx=(16, 12), pady=8)
        self.template_combo = ttk.Combobox(bar, state="readonly", style="SE.TCombobox", width=42)
        self.template_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.template_combo.bind("<<ComboboxSelected>>", self._on_template_selected)
        self.new_buttons = tk.Frame(bar, bg=BG_PANEL)
        self.new_buttons.pack(side=tk.LEFT)
        self._rebuild_new_buttons()
        for text, command in (("Duplicar", self._duplicate_template),
                              ("Excluir", self._delete_template), ("Salvar", self._save)):
            PillButton(bar, text=text, variant="primary" if text == "Salvar" else "ghost",
                       width=96, height=32, font=("Segoe UI", 9, "bold"), command=command).pack(side=tk.LEFT, padx=3)
        self.undo_btn = PillButton(bar, text="Desfazer", variant="ghost", width=96, height=32,
                                   font=("Segoe UI", 9, "bold"), command=self.undo)
        self.undo_btn.pack(side=tk.LEFT, padx=(14, 3))
        self.redo_btn = PillButton(bar, text="Refazer", variant="ghost", width=96, height=32,
                                   font=("Segoe UI", 9, "bold"), command=self.redo)
        self.redo_btn.pack(side=tk.LEFT, padx=3)
        self.status_label = ttk.Label(bar, text="", style="SEMuted.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=12)
        PillButton(bar, text="Voltar", variant="ghost", width=96, height=32,
                   font=("Segoe UI", 9, "bold"), command=self._close).pack(side=tk.RIGHT, padx=16, pady=8)

    def _build_left(self, body):
        left = tk.Frame(body, bg=BG_PANEL, width=250)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)
        pad = {"padx": 14}
        ttk.Label(left, text="Adicionar", style="SEHead.TLabel").pack(anchor="w", pady=(14, 6), **pad)
        self.add_frame = tk.Frame(left, bg=BG_PANEL)
        self.add_frame.pack(fill=tk.X, **pad)

        ttk.Label(left, text="Detalhes do template", style="SEHead.TLabel").pack(anchor="w", pady=(18, 2), **pad)
        self.kind_label = ttk.Label(left, text="", style="SEMuted.TLabel")
        self.kind_label.pack(anchor="w", pady=(0, 6), **pad)
        self.name_var = tk.StringVar()
        ttk.Label(left, text="Nome", style="SEMuted.TLabel").pack(anchor="w", **pad)
        name_entry = ttk.Entry(left, style="SE.TEntry", textvariable=self.name_var)
        name_entry.pack(fill=tk.X, pady=(0, 6), **pad)
        name_entry.bind("<KeyRelease>", self._on_name_change)

        self.paper_label = ttk.Label(left, text="Papel", style="SEMuted.TLabel")
        self.paper_label.pack(anchor="w", **pad)
        self.paper_combo = ttk.Combobox(left, state="readonly", style="SE.TCombobox",
                                        values=strip_templates.PAPER_CHOICES)
        self.paper_combo.pack(fill=tk.X, pady=(0, 6), **pad)
        self.paper_combo.bind("<<ComboboxSelected>>", self._on_paper_change)

        self.orientation_label = ttk.Label(left, text="Orientação", style="SEMuted.TLabel")
        self.orientation_label.pack(anchor="w", **pad)
        self.orientation_combo = ttk.Combobox(left, state="readonly", style="SE.TCombobox",
                                              values=strip_templates.ORIENTATION_CHOICES)
        self.orientation_combo.pack(fill=tk.X, pady=(0, 6), **pad)
        self.orientation_combo.bind("<<ComboboxSelected>>", self._on_paper_change)

        size_row = self.size_row = tk.Frame(left, bg=BG_PANEL)
        size_row.pack(fill=tk.X, **pad)
        self.width_var, self.height_var = tk.StringVar(), tk.StringVar()
        ttk.Label(size_row, text="L", style="SEMuted.TLabel").pack(side=tk.LEFT)
        self.width_entry = ttk.Entry(size_row, style="SE.TEntry", textvariable=self.width_var, width=7)
        self.width_entry.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(size_row, text="A", style="SEMuted.TLabel").pack(side=tk.LEFT)
        self.height_entry = ttk.Entry(size_row, style="SE.TEntry", textvariable=self.height_var, width=7)
        self.height_entry.pack(side=tk.LEFT, padx=4)
        for entry in (self.width_entry, self.height_entry):
            entry.bind("<Return>", self._on_custom_size)
            entry.bind("<FocusOut>", self._on_custom_size)
        ttk.Label(left, text="px a 300 dpi (1 cm ≈ 118 px)", style="SEMuted.TLabel",
                  font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 8), **pad)

        ttk.Label(left, text="Cor de fundo", style="SEMuted.TLabel").pack(anchor="w", **pad)
        self.bg_btn = tk.Button(left, text="      ", relief="flat", command=self._pick_background)
        self.bg_btn.pack(anchor="w", pady=(2, 0), **pad)

    def _build_canvas(self, body):
        self.canvas = tk.Canvas(body, bg=BG_CANVAS, highlightthickness=0, takefocus=True)
        self.canvas.grid(row=0, column=1, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._schedule_render())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Delete>", lambda e: self._delete_layer())
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.canvas.bind(f"<{key}>", lambda e, a=dx, b=dy: self._nudge(a, b))
            self.canvas.bind(f"<Shift-{key}>", lambda e, a=dx, b=dy: self._nudge(a * 10, b * 10))

    def _build_right(self, body):
        right = tk.Frame(body, bg=BG_PANEL, width=310)
        right.grid(row=0, column=2, sticky="ns")
        right.grid_propagate(False)
        pad = {"padx": 14}
        ttk.Label(right, text="Camadas", style="SEHead.TLabel").pack(anchor="w", pady=(14, 6), **pad)
        list_row = tk.Frame(right, bg=BG_PANEL)
        list_row.pack(fill=tk.X, **pad)
        self.layers_list = tk.Listbox(list_row, height=6, bg=BG_CARD, fg=FG_TEXT, selectbackground=ACCENT,
                                      selectforeground="#062018", highlightthickness=0, relief="flat",
                                      exportselection=False, activestyle="none")
        layers_scroll = ttk.Scrollbar(list_row, orient="vertical", command=self.layers_list.yview)
        self.layers_list.config(yscrollcommand=layers_scroll.set)
        self.layers_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        layers_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.layers_list.bind("<<ListboxSelect>>", self._on_list_select)

        btn_row = tk.Frame(right, bg=BG_PANEL)
        btn_row.pack(fill=tk.X, pady=(6, 0), **pad)
        for text, command in (("Frente", lambda: self._move_layer(1)), ("Trás", lambda: self._move_layer(-1)),
                              ("Duplicar", self._duplicate_layer), ("Excluir", self._delete_layer)):
            PillButton(btn_row, text=text, variant="danger" if text == "Excluir" else "ghost", width=62, height=28,
                       font=("Segoe UI", 8, "bold"), command=command).pack(side=tk.LEFT, padx=1)

        ttk.Label(right, text="Propriedades", style="SEHead.TLabel").pack(anchor="w", pady=(14, 6), **pad)
        self.geo_vars = {key: tk.StringVar() for key in ("x", "y", "w", "h", "rotation", "order")}
        geo = tk.Frame(right, bg=BG_PANEL)
        geo.pack(fill=tk.X, **pad)
        labels = (("x", "X"), ("y", "Y"), ("w", "L"), ("h", "A"), ("rotation", "Rot."), ("order", "Ordem"))
        for i, (key, text) in enumerate(labels):
            row, col = divmod(i, 2)
            ttk.Label(geo, text=text, style="SEMuted.TLabel").grid(row=row, column=col * 2, sticky="w", pady=2)
            entry = ttk.Entry(geo, style="SE.TEntry", textvariable=self.geo_vars[key], width=8)
            entry.grid(row=row, column=col * 2 + 1, padx=(4, 12), pady=2)
            entry.bind("<Return>", self._apply_geometry)
            entry.bind("<FocusOut>", self._apply_geometry)
        self.keep_ratio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Manter proporção ao redimensionar", variable=self.keep_ratio_var,
                        style="SE.TCheckbutton").pack(anchor="w", pady=(4, 0), **pad)

        self.type_container = tk.Frame(right, bg=BG_PANEL)
        self.type_container.pack(fill=tk.X, pady=(10, 0), **pad)
        self._build_photo_props()
        self._build_text_props()
        self._build_shape_props()
        self._build_image_props()

    def _build_photo_props(self):
        self.photo_frame = tk.Frame(self.type_container, bg=BG_PANEL)
        ttk.Label(self.photo_frame, text="Nº da foto", style="SEMuted.TLabel").pack(side=tk.LEFT)
        self.slot_combo = ttk.Combobox(self.photo_frame, state="readonly", style="SE.TCombobox", width=6)
        self.slot_combo.pack(side=tk.LEFT, padx=8)
        self.slot_combo.bind("<<ComboboxSelected>>", self._on_slot_change)

    def _build_text_props(self):
        f = self.text_frame = tk.Frame(self.type_container, bg=BG_PANEL)
        ttk.Label(f, text="Texto", style="SEMuted.TLabel").grid(row=0, column=0, sticky="w", columnspan=3)
        self.text_widget = tk.Text(f, height=3, width=30, bg=BG_CARD, fg=FG_TEXT, insertbackground=FG_TEXT,
                                   relief="flat", highlightthickness=0, font=("Segoe UI", 10))
        self.text_widget.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.text_widget.bind("<KeyRelease>", self._on_text_change)
        ttk.Label(f, text="Fonte", style="SEMuted.TLabel").grid(row=2, column=0, sticky="w")
        self.font_combo = ttk.Combobox(f, state="readonly", style="SE.TCombobox", width=16,
                                       values=strip_renderer.available_fonts())
        self.font_combo.grid(row=2, column=1, columnspan=2, sticky="w", pady=2)
        self.font_combo.bind("<<ComboboxSelected>>", self._on_text_prop)
        ttk.Label(f, text="Tamanho", style="SEMuted.TLabel").grid(row=3, column=0, sticky="w")
        self.size_var = tk.StringVar()
        size_entry = ttk.Entry(f, style="SE.TEntry", textvariable=self.size_var, width=6)
        size_entry.grid(row=3, column=1, sticky="w", pady=2)
        size_entry.bind("<Return>", self._on_text_prop)
        size_entry.bind("<FocusOut>", self._on_text_prop)
        self.bold_var, self.italic_var = tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(f, text="Negrito", variable=self.bold_var, style="SE.TCheckbutton",
                        command=self._on_text_prop).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(f, text="Itálico", variable=self.italic_var, style="SE.TCheckbutton",
                        command=self._on_text_prop).grid(row=4, column=1, sticky="w")
        ttk.Label(f, text="Cor", style="SEMuted.TLabel").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.text_color_btn = tk.Button(f, text="      ", relief="flat",
                                        command=lambda: self._pick_layer_color("color", allow_clear=False))
        self.text_color_btn.grid(row=5, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="Sombra", style="SEMuted.TLabel").grid(row=6, column=0, sticky="w", pady=2)
        self.shadow_btn = tk.Button(f, text="      ", relief="flat",
                                    command=lambda: self._pick_layer_color("shadow_color", allow_clear=True))
        self.shadow_btn.grid(row=6, column=1, sticky="w", pady=2)
        PillButton(f, text="Sem", variant="ghost", width=50, height=24, font=("Segoe UI", 8, "bold"),
                   command=lambda: self._clear_layer_color("shadow_color")).grid(row=6, column=2, sticky="w")
        ttk.Label(f, text="Distância", style="SEMuted.TLabel").grid(row=7, column=0, sticky="w")
        self.shadow_dist_var = tk.StringVar()
        dist_entry = ttk.Entry(f, style="SE.TEntry", textvariable=self.shadow_dist_var, width=6)
        dist_entry.grid(row=7, column=1, sticky="w", pady=2)
        dist_entry.bind("<Return>", self._on_text_prop)
        dist_entry.bind("<FocusOut>", self._on_text_prop)

    def _build_shape_props(self):
        f = self.shape_frame = tk.Frame(self.type_container, bg=BG_PANEL)
        ttk.Label(f, text="Preenchimento", style="SEMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.fill_btn = tk.Button(f, text="      ", relief="flat",
                                  command=lambda: self._pick_layer_color("fill", allow_clear=True))
        self.fill_btn.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        PillButton(f, text="Sem", variant="ghost", width=50, height=24, font=("Segoe UI", 8, "bold"),
                   command=lambda: self._clear_layer_color("fill")).grid(row=0, column=2)
        ttk.Label(f, text="Contorno", style="SEMuted.TLabel").grid(row=1, column=0, sticky="w")
        self.outline_btn = tk.Button(f, text="      ", relief="flat",
                                     command=lambda: self._pick_layer_color("outline", allow_clear=True))
        self.outline_btn.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        PillButton(f, text="Sem", variant="ghost", width=50, height=24, font=("Segoe UI", 8, "bold"),
                   command=lambda: self._clear_layer_color("outline")).grid(row=1, column=2)
        ttk.Label(f, text="Espessura", style="SEMuted.TLabel").grid(row=2, column=0, sticky="w")
        self.outline_w_var = tk.StringVar()
        entry = ttk.Entry(f, style="SE.TEntry", textvariable=self.outline_w_var, width=6)
        entry.grid(row=2, column=1, sticky="w", padx=6, pady=2)
        entry.bind("<Return>", self._on_shape_prop)
        entry.bind("<FocusOut>", self._on_shape_prop)

    def _build_image_props(self):
        self.image_frame = tk.Frame(self.type_container, bg=BG_PANEL)
        PillButton(self.image_frame, text="Trocar imagem", variant="ghost", width=140, height=30,
                   font=("Segoe UI", 9, "bold"), command=self._replace_image).pack(anchor="w")

    # --- ciclo de vida -----------------------------------------------------

    def open(self):
        """Chamado toda vez que a tela é mostrada."""
        self._reload_list(select_id=self.template["id"] if self.template else None)

    def _close(self):
        if self._confirm_discard():
            self.on_close()

    @staticmethod
    def _combo_label(kind, name):
        return f"[{strip_templates.KIND_LABELS.get(kind, kind)}] {name}"

    def set_allowed_kinds(self, kinds):
        """Tipos de template que a licença libera (tirinha = Photobooth, vídeo
        = Giro 360°). Se o template aberto ficou de fora, troca por outro."""
        self.allowed_kinds = [k for k in strip_templates.KINDS if k in kinds]
        self._rebuild_new_buttons()
        if self.template is not None and strip_templates.template_kind(self.template) not in self.allowed_kinds:
            self._dirty = False
            self._reload_list()

    def _rebuild_new_buttons(self):
        for widget in self.new_buttons.winfo_children():
            widget.destroy()
        labels = {strip_templates.KIND_STRIP: "Nova tirinha", strip_templates.KIND_VIDEO: "Novo vídeo"}
        for kind in self.allowed_kinds:
            PillButton(self.new_buttons, text=labels[kind], variant="ghost", width=116, height=32,
                       font=("Segoe UI", 9, "bold"),
                       command=lambda k=kind: self._new_template(k)).pack(side=tk.LEFT, padx=3)

    def _rebuild_add_buttons(self):
        """Botões de "Adicionar" do tipo do template aberto (tirinha: Foto;
        vídeo: Vídeo, que só pode existir uma vez)."""
        for widget in self.add_frame.winfo_children():
            widget.destroy()
        if self.template is None:
            return
        has_video = strip_templates.video_layer(self.template) is not None
        for layer_type in strip_templates.layer_types(strip_templates.template_kind(self.template)):
            button = PillButton(self.add_frame, text=LAYER_LABELS[layer_type], variant="ghost", width=220,
                                height=32, font=("Segoe UI", 9, "bold"),
                                command=lambda k=layer_type: self._add_layer(k))
            button.pack(pady=2)
            if layer_type == "video" and has_video:
                button.set_state("disabled")

    def _reload_list(self, select_id=None):
        items = [item for item in strip_templates.list_templates() if item["kind"] in self.allowed_kinds]
        self.template_ids = [item["id"] for item in items]
        self.template_combo.config(values=[self._combo_label(item["kind"], item["name"]) for item in items])
        target = select_id if select_id in self.template_ids else self.template_ids[0]
        self._load_template(target)

    def _load_template(self, template_id):
        self.template = strip_templates.load_template(template_id)
        strip_templates.normalize_slots(self.template)
        self.selected = None
        self._undo.clear()
        self._redo.clear()
        self._last_coalesce = None
        self._dirty = False
        self.template_combo.current(self.template_ids.index(template_id))
        self._rebuild_add_buttons()
        self._sync_template_fields()
        self._refresh_layers_list()
        self._sync_fields()
        self._schedule_render()
        self._update_status()

    def _on_template_selected(self, _event=None):
        new_id = self.template_ids[self.template_combo.current()]
        if new_id == self.template["id"]:
            return
        if not self._confirm_discard():
            self.template_combo.current(self.template_ids.index(self.template["id"]))
            return
        self._load_template(new_id)

    def _confirm_discard(self):
        if not self._dirty:
            return True
        answer = messagebox.askyesnocancel("Templates de tirinha", "Salvar as alterações deste template?")
        if answer is None:
            return False
        if answer:
            self._save()
        return True

    def _save(self):
        strip_templates.normalize_slots(self.template)
        strip_templates.save_template(self.template)
        self._dirty = False
        self._update_status("Salvo")

    def _new_template(self, kind=strip_templates.KIND_STRIP):
        if not self._confirm_discard():
            return
        if kind == strip_templates.KIND_VIDEO:
            template = strip_templates.new_template("Novo template de vídeo", "9:16", kind=kind)
            video = strip_templates.new_layer("video", template)
            video.update(x=40, y=260, w=template["width"] - 80, h=int(template["height"] * 0.62))
            template["layers"].append(video)
        else:
            template = strip_templates.new_template("Novo template", "4x6", "horizontal")
            photo = strip_templates.new_layer("photo", template)
            photo.update(x=60, y=60, w=template["width"] - 120, h=template["height"] - 120, slot=1)
            template["layers"].append(photo)
        strip_templates.save_template(template)
        self._reload_list(select_id=template["id"])

    def _duplicate_template(self):
        copy_ = strip_templates.duplicate_template(self.template)
        strip_templates.save_template(copy_)
        self._dirty = False
        self._reload_list(select_id=copy_["id"])

    def _delete_template(self):
        if not messagebox.askyesno("Templates de tirinha", f"Excluir o template \"{self.template['name']}\"?"):
            return
        strip_templates.delete_template(self.template["id"])
        self._dirty = False
        self.template = None
        self._reload_list()

    def _update_status(self, text=None):
        if text is None:
            text = "Alterações não salvas" if self._dirty else ""
        self.status_label.config(text=text)

    # --- desfazer / refazer --------------------------------------------------

    def _snapshot(self):
        return json.dumps(self.template)

    def _push_undo(self, key=None):
        """Guarda o estado antes de uma alteração. `key` agrupa edições
        seguidas do mesmo tipo (ex.: digitar um texto) numa só entrada."""
        self._dirty = True
        self._update_status()
        if key is not None and key == self._last_coalesce:
            return
        self._undo.append(self._snapshot())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self._last_coalesce = key

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())

    def _restore(self, snapshot):
        self.template = json.loads(snapshot)
        self._last_coalesce = None
        self._dirty = True
        if self.selected is not None and self.selected >= len(self.template["layers"]):
            self.selected = None
        self._rebuild_add_buttons()
        self._sync_template_fields()
        self._refresh_layers_list()
        self._sync_fields()
        self._schedule_render()
        self._update_status()

    # --- detalhes do template ------------------------------------------------

    def _is_video_template(self):
        return strip_templates.template_kind(self.template) == strip_templates.KIND_VIDEO

    def _sync_template_fields(self):
        t = self.template
        is_video = self._is_video_template()
        self._loading = True
        self.kind_label.config(text=f"Tipo: {strip_templates.KIND_LABELS[strip_templates.template_kind(t)]}")
        self.name_var.set(t["name"])
        # tirinha: papel + orientação; vídeo: só o tamanho de saída (a proporção já diz a orientação)
        self.paper_label.config(text="Tamanho de saída" if is_video else "Papel")
        self.paper_combo.config(
            values=strip_templates.VIDEO_SIZE_CHOICES if is_video else strip_templates.PAPER_CHOICES)
        self.paper_combo.set(t["paper"])
        self.orientation_combo.set(t["orientation"])
        if is_video:
            self.orientation_label.pack_forget()
            self.orientation_combo.pack_forget()
        elif not self.orientation_combo.winfo_ismapped():
            self.orientation_label.pack(anchor="w", padx=14, before=self.size_row)
            self.orientation_combo.pack(fill=tk.X, pady=(0, 6), padx=14, before=self.size_row)
        self.width_var.set(str(t["width"]))
        self.height_var.set(str(t["height"]))
        state = "normal" if t["paper"] == "custom" else "disabled"
        self.width_entry.config(state=state)
        self.height_entry.config(state=state)
        self.bg_btn.config(bg=t["background_color"], activebackground=t["background_color"])
        self._loading = False

    def _on_name_change(self, _event=None):
        if self._loading:
            return
        self._push_undo(key=("name",))
        self.template["name"] = self.name_var.get()
        label = self._combo_label(strip_templates.template_kind(self.template), self.template["name"])
        values = list(self.template_combo.cget("values"))
        index = self.template_ids.index(self.template["id"])
        values[index] = label
        self.template_combo.config(values=values)
        self.template_combo.set(label)

    def _on_paper_change(self, _event=None):
        if self._loading:
            return
        self._push_undo()
        t = self.template
        t["paper"] = self.paper_combo.get()
        if self._is_video_template():
            if t["paper"] == "custom":
                width, height = t["width"], t["height"]
            else:
                width, height = strip_templates.video_dimensions(t["paper"])
            t["orientation"] = "horizontal" if width >= height else "vertical"
        else:
            t["orientation"] = self.orientation_combo.get()
            if t["paper"] == "custom":
                width, height = t["width"], t["height"]
                if (t["orientation"] == "horizontal") != (width >= height):
                    width, height = height, width
            else:
                width, height = strip_templates.paper_dimensions(t["paper"], t["orientation"])
        t["width"], t["height"] = width, height
        self._sync_template_fields()
        self._schedule_render()

    def _on_custom_size(self, _event=None):
        if self._loading or self.template["paper"] != "custom":
            return
        try:
            width = max(100, min(6000, int(float(self.width_var.get()))))
            height = max(100, min(6000, int(float(self.height_var.get()))))
            if self._is_video_template():  # libx264 exige dimensões pares
                width, height = width - width % 2, height - height % 2
        except ValueError:
            self._sync_template_fields()
            return
        if (width, height) != (self.template["width"], self.template["height"]):
            self._push_undo()
            self.template["width"], self.template["height"] = width, height
            self.template["orientation"] = "horizontal" if width >= height else "vertical"
        self._sync_template_fields()
        self._schedule_render()

    def _pick_background(self):
        result = colorchooser.askcolor(color=self.template["background_color"], parent=self)
        if result and result[1]:
            self._push_undo()
            self.template["background_color"] = result[1]
            self._sync_template_fields()
            self._schedule_render()

    # --- camadas ----------------------------------------------------------------

    def _layer(self):
        if self.selected is None:
            return None
        return self.template["layers"][self.selected]

    def _add_layer(self, kind):
        if kind == "video" and strip_templates.video_layer(self.template) is not None:
            return  # só existe um quadro de vídeo por template
        layer = strip_templates.new_layer(kind, self.template)
        if kind == "image":
            path = filedialog.askopenfilename(
                title="Escolher imagem", filetypes=[("Imagens", "*.png *.jpg *.jpeg"), ("Todos", "*.*")])
            if not path:
                return
            layer["path"] = strip_templates.copy_asset(path)
            with Image.open(layer["path"]) as img:
                iw, ih = img.size
            limit = min(self.template["width"], self.template["height"]) * 0.5
            ratio = min(limit / iw, limit / ih, 1.0)
            layer["w"], layer["h"] = max(MIN_SIZE, int(iw * ratio)), max(MIN_SIZE, int(ih * ratio))
            layer["x"] = (self.template["width"] - layer["w"]) // 2
            layer["y"] = (self.template["height"] - layer["h"]) // 2
        self._push_undo()
        self.template["layers"].append(layer)
        strip_templates.normalize_slots(self.template)
        self.selected = len(self.template["layers"]) - 1
        self._after_layers_change()

    def _delete_layer(self):
        if self.selected is None:
            return
        self._push_undo()
        del self.template["layers"][self.selected]
        strip_templates.normalize_slots(self.template)
        self.selected = None
        self._after_layers_change()

    def _duplicate_layer(self):
        layer = self._layer()
        if layer is None or layer["type"] == "video":
            return
        self._push_undo()
        clone = copy.deepcopy(layer)
        clone["x"] += 30
        clone["y"] += 30
        if clone["type"] == "photo":
            clone["slot"] = 10 ** 6
        self.template["layers"].append(clone)
        strip_templates.normalize_slots(self.template)
        self.selected = len(self.template["layers"]) - 1
        self._after_layers_change()

    def _move_layer(self, direction):
        """direction +1 = para frente, -1 = para trás."""
        if self.selected is None:
            return
        target = self.selected + direction
        layers = self.template["layers"]
        if not 0 <= target < len(layers):
            return
        self._push_undo()
        layers[self.selected], layers[target] = layers[target], layers[self.selected]
        self.selected = target
        self._after_layers_change()

    def _after_layers_change(self):
        self._rebuild_add_buttons()
        self._refresh_layers_list()
        self._sync_fields()
        self._schedule_render()

    def _layer_label(self, layer):
        label = LAYER_LABELS[layer["type"]]
        if layer["type"] == "photo":
            return f"{label} {layer['slot']}"
        if layer["type"] == "text":
            return f"{label}: {layer.get('text', '').splitlines()[0] if layer.get('text') else ''}"[:34]
        if layer["type"] == "image":
            return f"{label}: {layer.get('path', '').replace(chr(92), '/').split('/')[-1]}"[:34]
        return label

    def _refresh_layers_list(self):
        self.layers_list.delete(0, tk.END)
        layers = self.template["layers"]
        for layer in reversed(layers):  # topo da lista = camada da frente
            self.layers_list.insert(tk.END, self._layer_label(layer))
        if self.selected is not None:
            self.layers_list.selection_set(len(layers) - 1 - self.selected)

    def _on_list_select(self, _event=None):
        if self._loading:
            return
        selection = self.layers_list.curselection()
        if not selection:
            return
        self.selected = len(self.template["layers"]) - 1 - selection[0]
        self._sync_fields()
        self._draw_selection()

    # --- propriedades da camada selecionada --------------------------------------

    def _sync_fields(self):
        layer = self._layer()
        self._loading = True
        for frame in (self.photo_frame, self.text_frame, self.shape_frame, self.image_frame):
            frame.pack_forget()
        if layer is None:
            for var in self.geo_vars.values():
                var.set("")
            self._loading = False
            return
        self._sync_geometry_fields()
        kind = layer["type"]
        if kind == "photo":
            count = strip_templates.photo_slot_count(self.template)
            self.slot_combo.config(values=[str(i) for i in range(1, count + 1)])
            self.slot_combo.set(str(layer["slot"]))
            self.photo_frame.pack(anchor="w")
        elif kind == "text":
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert("1.0", layer.get("text", ""))
            self.font_combo.set(layer.get("font", "Segoe UI"))
            self.size_var.set(str(layer.get("size", 48)))
            self.bold_var.set(bool(layer.get("bold")))
            self.italic_var.set(bool(layer.get("italic")))
            self.shadow_dist_var.set(str(layer.get("shadow_distance", 0)))
            self._paint_button(self.text_color_btn, layer.get("color"))
            self._paint_button(self.shadow_btn, layer.get("shadow_color"))
            self.text_frame.pack(anchor="w", fill=tk.X)
        elif kind in ("rect", "ellipse"):
            self._paint_button(self.fill_btn, layer.get("fill"))
            self._paint_button(self.outline_btn, layer.get("outline"))
            self.outline_w_var.set(str(layer.get("outline_width", 0)))
            self.shape_frame.pack(anchor="w")
        else:
            self.image_frame.pack(anchor="w")
        self._loading = False

    def _sync_geometry_fields(self):
        layer = self._layer()
        if layer is None:
            return
        for key in ("x", "y", "w", "h", "rotation"):
            self.geo_vars[key].set(str(int(round(layer.get(key, 0)))))
        self.geo_vars["order"].set(str(self.selected + 1))

    @staticmethod
    def _paint_button(button, color):
        shown = color if color else "#2a2c33"
        button.config(bg=shown, activebackground=shown, text="" if color else "  —  ", fg=FG_MUTED)

    def _apply_geometry(self, _event=None):
        layer = self._layer()
        if layer is None or self._loading:
            return
        try:
            new = {key: int(round(float(self.geo_vars[key].get()))) for key in ("x", "y", "w", "h", "rotation")}
            order = int(float(self.geo_vars["order"].get()))
        except ValueError:
            self._sync_geometry_fields()
            return
        new["w"], new["h"] = max(MIN_SIZE, new["w"]), max(MIN_SIZE, new["h"])
        if layer["type"] == "video":
            new["rotation"] = 0  # o quadro de vídeo não gira
        old = {key: layer[key] for key in new}
        if self.keep_ratio_var.get() and old["h"]:
            if new["w"] != old["w"] and new["h"] == old["h"]:
                new["h"] = max(MIN_SIZE, int(round(new["w"] * old["h"] / old["w"])))
            elif new["h"] != old["h"] and new["w"] == old["w"]:
                new["w"] = max(MIN_SIZE, int(round(new["h"] * old["w"] / old["h"])))
        target = max(1, min(len(self.template["layers"]), order)) - 1
        if new == old and target == self.selected:
            self._sync_geometry_fields()
            return
        self._push_undo()
        layer.update(new)
        if target != self.selected:
            layers = self.template["layers"]
            layers.insert(target, layers.pop(self.selected))
            self.selected = target
            self._refresh_layers_list()
        self._sync_geometry_fields()
        self._schedule_render()

    def _on_slot_change(self, _event=None):
        layer = self._layer()
        if layer is None or self._loading:
            return
        wanted = int(self.slot_combo.get())
        if wanted == layer["slot"]:
            return
        self._push_undo()
        for other in self.template["layers"]:
            if other["type"] == "photo" and other is not layer and other["slot"] == wanted:
                other["slot"] = layer["slot"]
        layer["slot"] = wanted
        self._refresh_layers_list()
        self._schedule_render()

    def _on_text_change(self, _event=None):
        layer = self._layer()
        if layer is None or self._loading:
            return
        text = self.text_widget.get("1.0", "end-1c")
        if text == layer.get("text"):
            return
        self._push_undo(key=("text", self.selected))
        layer["text"] = text
        self._refresh_layers_list()
        self._schedule_render()

    def _on_text_prop(self, _event=None):
        layer = self._layer()
        if layer is None or self._loading:
            return
        try:
            size = max(4, int(float(self.size_var.get())))
            dist = max(0, int(float(self.shadow_dist_var.get())))
        except ValueError:
            self._sync_fields()
            return
        new = {"font": self.font_combo.get(), "size": size, "bold": self.bold_var.get(),
               "italic": self.italic_var.get(), "shadow_distance": dist}
        if all(layer.get(key) == value for key, value in new.items()):
            return
        self._push_undo()
        layer.update(new)
        self._schedule_render()

    def _on_shape_prop(self, _event=None):
        layer = self._layer()
        if layer is None or self._loading:
            return
        try:
            width = max(0, int(float(self.outline_w_var.get())))
        except ValueError:
            self._sync_fields()
            return
        if width != layer.get("outline_width"):
            self._push_undo()
            layer["outline_width"] = width
            self._schedule_render()

    def _pick_layer_color(self, key, allow_clear):
        layer = self._layer()
        if layer is None:
            return
        result = colorchooser.askcolor(color=layer.get(key) or "#ffffff", parent=self)
        if result and result[1]:
            self._push_undo()
            layer[key] = result[1]
            self._sync_fields()
            self._schedule_render()

    def _clear_layer_color(self, key):
        layer = self._layer()
        if layer is None or not layer.get(key):
            return
        self._push_undo()
        layer[key] = ""
        self._sync_fields()
        self._schedule_render()

    def _replace_image(self):
        layer = self._layer()
        if layer is None or layer["type"] != "image":
            return
        path = filedialog.askopenfilename(
            title="Escolher imagem", filetypes=[("Imagens", "*.png *.jpg *.jpeg"), ("Todos", "*.*")])
        if not path:
            return
        self._push_undo()
        layer["path"] = strip_templates.copy_asset(path)
        self._refresh_layers_list()
        self._schedule_render()

    # --- canvas: render, seleção e arraste -------------------------------------------

    def _schedule_render(self):
        if self._render_job is None:
            self._render_job = self.after(15, self._render)

    def _render(self):
        self._render_job = None
        if self.template is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 60 or ch < 60:
            cw, ch = 640, 440
        margin = 24
        t = self.template
        self._scale = max(0.01, min((cw - 2 * margin) / t["width"], (ch - 2 * margin) / t["height"]))
        image = strip_renderer.render_template(t, None, self._scale)
        self._photo_ref = ImageTk.PhotoImage(image)
        self._ox = (cw - image.width) // 2
        self._oy = (ch - image.height) // 2
        self.canvas.delete("all")
        self.canvas.create_image(self._ox, self._oy, anchor="nw", image=self._photo_ref)
        self._draw_selection()

    def _canvas_point(self, layer, local_x, local_y):
        """Ponto local da camada (relativo ao centro) -> coordenada do canvas."""
        dx, dy = _rotate(local_x, local_y, layer.get("rotation", 0))
        cx = layer["x"] + layer["w"] / 2
        cy = layer["y"] + layer["h"] / 2
        return self._ox + (cx + dx) * self._scale, self._oy + (cy + dy) * self._scale

    def _draw_selection(self):
        self.canvas.delete("sel")
        layer = self._layer()
        if layer is None:
            return
        hw, hh = layer["w"] / 2, layer["h"] / 2
        corners = [self._canvas_point(layer, sx * hw, sy * hh) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        self.canvas.create_polygon(*[c for point in corners for c in point], outline=ACCENT, fill="",
                                   width=2, tags="sel")
        for sx, sy in HANDLES.values():
            px, py = self._canvas_point(layer, sx * hw, sy * hh)
            self.canvas.create_rectangle(px - HANDLE_SIZE, py - HANDLE_SIZE, px + HANDLE_SIZE, py + HANDLE_SIZE,
                                         fill="#ffffff", outline=ACCENT, tags="sel")

    def _to_template(self, px, py):
        return (px - self._ox) / self._scale, (py - self._oy) / self._scale

    def _hit_handle(self, px, py):
        layer = self._layer()
        if layer is None:
            return None
        hw, hh = layer["w"] / 2, layer["h"] / 2
        for name, (sx, sy) in HANDLES.items():
            hx, hy = self._canvas_point(layer, sx * hw, sy * hh)
            if abs(px - hx) <= HANDLE_SIZE + 3 and abs(py - hy) <= HANDLE_SIZE + 3:
                return name
        return None

    def _hit_layer(self, px, py):
        tx, ty = self._to_template(px, py)
        for index in range(len(self.template["layers"]) - 1, -1, -1):
            layer = self.template["layers"][index]
            dx = tx - (layer["x"] + layer["w"] / 2)
            dy = ty - (layer["y"] + layer["h"] / 2)
            lx, ly = _rotate(dx, dy, -layer.get("rotation", 0))
            if abs(lx) <= layer["w"] / 2 and abs(ly) <= layer["h"] / 2:
                return index
        return None

    def _on_press(self, event):
        self.canvas.focus_set()
        handle = self._hit_handle(event.x, event.y)
        if handle:
            layer = self._layer()
            self._drag = {"mode": "resize", "handle": handle, "pushed": False,
                          "orig": {k: layer[k] for k in ("x", "y", "w", "h")}}
            return
        index = self._hit_layer(event.x, event.y)
        self.selected = index
        self._refresh_layers_list()
        self._sync_fields()
        self._draw_selection()
        if index is None:
            self._drag = None
            return
        layer = self._layer()
        start = self._to_template(event.x, event.y)
        self._drag = {"mode": "move", "pushed": False, "start": start, "orig": {"x": layer["x"], "y": layer["y"]}}

    def _on_motion(self, event):
        drag = self._drag
        layer = self._layer()
        if not drag or layer is None:
            return
        if not drag["pushed"]:
            self._push_undo()
            drag["pushed"] = True
            self._last_coalesce = None
        tx, ty = self._to_template(event.x, event.y)
        if drag["mode"] == "move":
            layer["x"] = int(round(drag["orig"]["x"] + tx - drag["start"][0]))
            layer["y"] = int(round(drag["orig"]["y"] + ty - drag["start"][1]))
        else:
            self._resize(layer, drag, tx, ty)
        self._sync_geometry_fields()
        self._schedule_render()

    def _resize(self, layer, drag, tx, ty):
        sx, sy = HANDLES[drag["handle"]]
        orig = drag["orig"]
        w0, h0 = orig["w"], orig["h"]
        cx0, cy0 = orig["x"] + w0 / 2, orig["y"] + h0 / 2
        rotation = layer.get("rotation", 0)
        # mouse no referencial local da camada (centro original, sem rotação)
        mx, my = _rotate(tx - cx0, ty - cy0, -rotation)
        fixed_x, fixed_y = -sx * w0 / 2, -sy * h0 / 2
        new_w = max(MIN_SIZE, sx * (mx - fixed_x)) if sx else w0
        new_h = max(MIN_SIZE, sy * (my - fixed_y)) if sy else h0
        if self.keep_ratio_var.get() and sx and sy:
            factor = max(new_w / w0, new_h / h0)
            new_w, new_h = max(MIN_SIZE, w0 * factor), max(MIN_SIZE, h0 * factor)
        local_cx = fixed_x + sx * new_w / 2 if sx else 0
        local_cy = fixed_y + sy * new_h / 2 if sy else 0
        off_x, off_y = _rotate(local_cx, local_cy, rotation)
        layer["w"], layer["h"] = int(round(new_w)), int(round(new_h))
        layer["x"] = int(round(cx0 + off_x - layer["w"] / 2))
        layer["y"] = int(round(cy0 + off_y - layer["h"] / 2))

    def _on_release(self, _event):
        self._drag = None

    def _nudge(self, dx, dy):
        layer = self._layer()
        if layer is None:
            return "break"
        self._push_undo(key=("nudge", self.selected))
        layer["x"] += dx
        layer["y"] += dy
        self._sync_geometry_fields()
        self._schedule_render()
        return "break"
