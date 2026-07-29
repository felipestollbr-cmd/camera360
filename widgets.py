"""
Componentes visuais reutilizáveis pra dar ao Camera360 uma cara mais
profissional (inspirado no app desktop do Webex): botões em pílula com
ícone desenhado + texto, e painéis em formato de card com título.
Desenhados via Canvas (não dá pra fazer pílula/cantos arredondados de
verdade com ttk.Button no Windows).
"""
import tkinter as tk

BG_PANEL = "#17181c"
BG_CARD = "#1c1e24"
FG_TEXT = "#e8e8ea"
FG_MUTED = "#8a8d96"
ACCENT = "#00e0a0"
ACCENT_DARK = "#062018"
DANGER = "#ff4d4d"
BORDER = "#2a2c33"
GHOST_BG = "#22242b"
GHOST_BG_HOVER = "#2a2d35"


def _round_rect_points(x1, y1, x2, y2, radius):
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]


def draw_round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    return canvas.create_polygon(_round_rect_points(x1, y1, x2, y2, radius), smooth=True, **kwargs)


# --- Ícones: traços finos simples (mesma linguagem visual do HUD) -------

def _icon_camera(c, cx, cy, s, color):
    r = s * 0.55
    c.create_rectangle(cx - r, cy - r * 0.65, cx + r, cy + r * 0.75, outline=color, width=1.4)
    c.create_rectangle(cx - r * 0.35, cy - r * 1.15, cx + r * 0.1, cy - r * 0.65,
                        outline=color, width=1.4)
    c.create_oval(cx - r * 0.42, cy - r * 0.1, cx + r * 0.42, cy + r * 0.62, outline=color, width=1.4)


def _icon_video(c, cx, cy, s, color):
    r = s * 0.5
    c.create_rectangle(cx - r * 1.1, cy - r * 0.65, cx + r * 0.35, cy + r * 0.65,
                        outline=color, width=1.4)
    c.create_polygon(cx + r * 0.35, cy - r * 0.4, cx + r * 1.15, cy - r * 0.75,
                      cx + r * 1.15, cy + r * 0.75, cx + r * 0.35, cy + r * 0.4,
                      outline=color, fill="", width=1.4, joinstyle="round")


def _icon_hourglass(c, cx, cy, s, color):
    r = s * 0.5
    c.create_line(cx - r * 0.7, cy - r, cx + r * 0.7, cy - r, fill=color, width=1.4)
    c.create_line(cx - r * 0.7, cy + r, cx + r * 0.7, cy + r, fill=color, width=1.4)
    c.create_polygon(cx - r * 0.7, cy - r, cx + r * 0.7, cy - r, cx, cy,
                      outline=color, fill="", width=1.4, joinstyle="round")
    c.create_polygon(cx - r * 0.7, cy + r, cx + r * 0.7, cy + r, cx, cy,
                      outline=color, fill="", width=1.4, joinstyle="round")


def _icon_power(c, cx, cy, s, color):
    r = s * 0.5
    c.create_arc(cx - r, cy - r, cx + r, cy + r, start=55, extent=250,
                 style="arc", outline=color, width=1.5)
    c.create_line(cx, cy - r * 1.15, cx, cy - r * 0.15, fill=color, width=1.5)


def _icon_link(c, cx, cy, s, color):
    r = s * 0.42
    c.create_oval(cx - r * 1.5, cy - r * 0.65, cx - r * 0.3, cy + r * 0.65,
                  outline=color, width=1.4)
    c.create_oval(cx + r * 0.3, cy - r * 0.65, cx + r * 1.5, cy + r * 0.65,
                  outline=color, width=1.4)


def _icon_calendar(c, cx, cy, s, color):
    r = s * 0.5
    c.create_rectangle(cx - r, cy - r * 0.75, cx + r, cy + r, outline=color, width=1.4)
    c.create_line(cx - r, cy - r * 0.2, cx + r, cy - r * 0.2, fill=color, width=1.4)
    c.create_line(cx - r * 0.5, cy - r * 1.1, cx - r * 0.5, cy - r * 0.5, fill=color, width=1.4)
    c.create_line(cx + r * 0.5, cy - r * 1.1, cx + r * 0.5, cy - r * 0.5, fill=color, width=1.4)


def _icon_hangup(c, cx, cy, s, color):
    r = s * 0.55
    c.create_arc(cx - r, cy - r * 0.3, cx + r, cy + r * 1.4, start=30, extent=120,
                 style="arc", outline=color, width=1.6)
    c.create_line(cx - r * 0.55, cy + r * 0.05, cx, cy - r * 0.35, fill=color, width=1.6)
    c.create_line(cx + r * 0.55, cy + r * 0.05, cx, cy - r * 0.35, fill=color, width=1.6)


def _icon_pin(c, cx, cy, s, color):
    r = s * 0.5
    c.create_oval(cx - r * 0.65, cy - r, cx + r * 0.65, cy + r * 0.3, outline=color, width=1.4)
    c.create_polygon(cx - r * 0.35, cy + r * 0.05, cx + r * 0.35, cy + r * 0.05, cx, cy + r * 1.1,
                      outline=color, fill="", width=1.4, joinstyle="round")
    c.create_oval(cx - r * 0.2, cy - r * 0.5, cx + r * 0.2, cy - r * 0.1, outline=color, width=1.2)


def _icon_play(c, cx, cy, s, color):
    r = s * 0.55
    c.create_polygon(cx - r * 0.55, cy - r * 0.75, cx - r * 0.55, cy + r * 0.75,
                      cx + r * 0.75, cy, fill=color, outline="")


def _icon_person(c, cx, cy, s, color):
    r = s * 0.5
    c.create_oval(cx - r * 0.35, cy - r, cx + r * 0.35, cy - r * 0.3, outline=color, width=1.3)
    c.create_arc(cx - r * 0.75, cy - r * 0.05, cx + r * 0.75, cy + r * 1.15,
                 start=20, extent=140, style="arc", outline=color, width=1.3)


def _icon_refresh(c, cx, cy, s, color):
    r = s * 0.48
    c.create_arc(cx - r, cy - r, cx + r, cy + r, start=30, extent=280,
                 style="arc", outline=color, width=1.5)
    c.create_polygon(cx + r * 0.85, cy - r * 0.55, cx + r * 1.25, cy - r * 0.55,
                      cx + r * 1.05, cy - r * 0.1, fill=color, outline="")


def _icon_folder(c, cx, cy, s, color):
    r = s * 0.5
    c.create_polygon(cx - r, cy - r * 0.35, cx - r * 0.25, cy - r * 0.35,
                      cx - r * 0.05, cy - r * 0.65, cx + r * 0.35, cy - r * 0.65,
                      cx + r * 0.35, cy - r * 0.35,
                      outline=color, fill="", width=1.4, joinstyle="round")
    c.create_rectangle(cx - r, cy - r * 0.35, cx + r, cy + r * 0.55,
                        outline=color, width=1.4)


ICONS = {
    "camera": _icon_camera,
    "video": _icon_video,
    "hourglass": _icon_hourglass,
    "power": _icon_power,
    "link": _icon_link,
    "calendar": _icon_calendar,
    "hangup": _icon_hangup,
    "pin": _icon_pin,
    "refresh": _icon_refresh,
    "play": _icon_play,
    "person": _icon_person,
    "folder": _icon_folder,
}


class PillButton(tk.Canvas):
    """
    Botão em formato de pílula (cantos totalmente arredondados) com ícone
    desenhado + texto, em 4 variantes:
      - "primary": preenchido com a cor de destaque (ação principal)
      - "ghost":   fundo sutil, texto claro (ação secundária)
      - "ghost-active": como o ghost, mas com contorno/texto na cor de
        destaque (estado selecionado, ex.: modo ativo)
      - "danger":  contorno/texto vermelho (encerrar/sair)
    """

    def __init__(self, parent, text, command=None, icon=None, variant="ghost",
                 width=150, height=38, font=("Segoe UI", 10, "bold"), bg=BG_PANEL):
        super().__init__(parent, width=width, height=height, bg=bg,
                          highlightthickness=0, cursor="hand2")
        self.command = command
        self.text = text
        self.icon = icon
        self.variant = variant
        self.font = font
        self._hover = False
        self._disabled = False
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._redraw()

    def _palette(self):
        if self._disabled:
            return GHOST_BG, FG_MUTED, FG_MUTED
        if self.variant == "primary":
            fill = "#00c98f" if self._hover else ACCENT
            return fill, ACCENT_DARK, ACCENT_DARK
        if self.variant == "ghost-active":
            fill = GHOST_BG_HOVER if self._hover else GHOST_BG
            return fill, ACCENT, ACCENT
        if self.variant == "danger":
            fill = "#3a2226" if self._hover else "transparent"
            return fill, DANGER, DANGER
        fill = GHOST_BG_HOVER if self._hover else GHOST_BG
        return fill, FG_TEXT, FG_TEXT

    def _redraw(self):
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        fill, text_color, icon_color = self._palette()
        if fill == "transparent":
            draw_round_rect(self, 1, 1, w - 1, h - 1, h / 2, outline=DANGER, width=1.2, fill=self["bg"])
        else:
            draw_round_rect(self, 1, 1, w - 1, h - 1, h / 2, fill=fill, outline="")

        if not self.text and self.icon:
            # Botão só com ícone (ex.: "atualizar"): centraliza.
            ICONS[self.icon](self, w / 2, h / 2, h * 0.5, icon_color)
            return

        content_x = 18
        if self.icon:
            icon_size = h * 0.52
            icon_cx = content_x + icon_size * 0.55
            ICONS[self.icon](self, icon_cx, h / 2, icon_size, icon_color)
            content_x += icon_size * 1.3

        remaining_w = w - content_x - 14
        self.create_text(content_x + max(0, remaining_w) / 2, h / 2, text=self.text,
                          fill=text_color, font=self.font, anchor="c")

    def _on_click(self, _event):
        if self.command and not self._disabled:
            self.command()

    def _on_enter(self, _event):
        if self._disabled:
            return
        self._hover = True
        self._redraw()

    def _on_leave(self, _event):
        if self._disabled:
            return
        self._hover = False
        self._redraw()

    def set_text(self, text):
        self.text = text
        self._redraw()

    def set_variant(self, variant):
        self.variant = variant
        self._redraw()

    def set_state(self, state):
        """
        state: "normal" ou "disabled" (compatível com a chamada
        .config(state=...) do ttk). Usa cores esmaecidas em vez de
        stipple - combinar stipple com texto em Canvas quebra a
        renderização no Tk/Windows (aparecia uma caixa branca sólida por
        baixo do texto em vez de esmaecer).
        """
        self._disabled = (state == "disabled")
        self.config(cursor="arrow" if self._disabled else "hand2")
        self._redraw()

    # Compat com o código existente que chama .config(text=..., state=...)
    def config(self, **kwargs):
        if "text" in kwargs:
            self.set_text(kwargs.pop("text"))
        if "state" in kwargs:
            self.set_state(kwargs.pop("state"))
        if kwargs:
            super().config(**kwargs)


class Card(tk.Frame):
    """
    Painel em formato de card: fundo levemente diferente do painel ao
    redor, borda sutil e cantos arredondados (via Canvas de fundo).

    expand=False (padrão): o card "abraça" a altura do conteúdo (uso
    típico: seção de configurações/formulário).
    expand=True: o card ocupa toda a altura que o layout pai der a ele
    (uso típico: lista que precisa crescer/rolar, ex. reuniões agendadas).
    """

    def __init__(self, parent, bg_outer=BG_PANEL, padx=16, pady=14, expand=False):
        super().__init__(parent, bg=bg_outer)
        self._expand = expand
        self._canvas = tk.Canvas(self, bg=bg_outer, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self.body = tk.Frame(self._canvas, bg=BG_CARD)
        self._window = self._canvas.create_window(0, 0, window=self.body, anchor="nw")
        self._canvas.bind("<Configure>", self._on_resize)
        self.body.bind("<Configure>", self._on_body_resize)
        self._inner = tk.Frame(self.body, bg=BG_CARD)
        self._inner.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)

    def _on_resize(self, event):
        self._canvas.delete("bg")
        draw_round_rect(self._canvas, 1, 1, event.width - 1, max(event.height - 1, 2), 12,
                         fill=BG_CARD, outline=BORDER, width=1, tags="bg")
        self._canvas.tag_lower("bg")
        self._canvas.itemconfig(self._window, width=event.width)
        if self._expand:
            self._canvas.itemconfig(self._window, height=event.height)

    def _on_body_resize(self, _event):
        if not self._expand:
            self._canvas.config(height=self.body.winfo_reqheight())

    @property
    def content(self):
        return self._inner


class Pill(tk.Canvas):
    """
    Cápsula flutuante só de leitura (status/indicador), pra sobrepor no
    preview da câmera - ex.: "REC 00:12". Usa place() no widget pai, não
    pack/grid (é pra ficar por cima do vídeo, não empurrar layout).
    """

    def __init__(self, parent, text="", dot_color=None, bg="#1c1c1e",
                 fg=FG_TEXT, font=("Segoe UI", 10, "bold"), padx=14, pady=7):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent["bg"])
        self._text = text
        self._dot_color = dot_color
        self._bg = bg
        self._fg = fg
        self._font = font
        self._padx = padx
        self._pady = pady
        self._redraw()

    def _redraw(self):
        self.delete("all")
        import tkinter.font as tkfont
        measurer = tkfont.Font(font=self._font)
        text_w = measurer.measure(self._text)
        text_h = measurer.metrics("linespace")
        dot_w = 16 if self._dot_color else 0
        w = max(1, text_w + dot_w + self._padx * 2)
        h = text_h + self._pady * 2
        self.config(width=w, height=h)
        draw_round_rect(self, 1, 1, w - 1, h - 1, h / 2, fill=self._bg, outline="")
        x = self._padx
        if self._dot_color:
            cy = h / 2
            self.create_oval(x, cy - 4, x + 8, cy + 4, fill=self._dot_color, outline="")
            x += dot_w
        self.create_text(x, h / 2, anchor="w", text=self._text, fill=self._fg, font=self._font)

    def set_text(self, text, dot_color=None):
        self._text = text
        if dot_color is not None:
            self._dot_color = dot_color
        self._redraw()
