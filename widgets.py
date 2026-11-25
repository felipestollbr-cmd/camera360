"""
Componentes visuais reutilizáveis do Camera360 (estilo colorido e festivo):
botões em pílula com degradê e ícone desenhado, cartões com sombra suave,
pílula flutuante e um fundo festivo com confete animado.

Tkinter não tem cantos suaves/degradê/sombra de verdade, então as formas são
imagens geradas com Pillow (theme.py) desenhadas num Canvas. As cores vêm de
`theme` NA HORA de desenhar - `theme.apply(cor_da_marca)` antes de montar as
telas já vale pra tudo.
"""
import math
import random
import tkinter as tk

from PIL import ImageTk

import theme


def _w(size):
    """Espessura do traço dos ícones, proporcional ao tamanho."""
    return max(1.4, size / 11)


# --- Ícones: traços finos simples ---------------------------------------

def _icon_camera(c, cx, cy, s, color):
    r, w = s * 0.55, _w(s)
    c.create_rectangle(cx - r, cy - r * 0.65, cx + r, cy + r * 0.75, outline=color, width=w)
    c.create_rectangle(cx - r * 0.35, cy - r * 1.15, cx + r * 0.1, cy - r * 0.65, outline=color, width=w)
    c.create_oval(cx - r * 0.42, cy - r * 0.1, cx + r * 0.42, cy + r * 0.62, outline=color, width=w)


def _icon_video(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_rectangle(cx - r * 1.1, cy - r * 0.65, cx + r * 0.35, cy + r * 0.65, outline=color, width=w)
    c.create_polygon(cx + r * 0.35, cy - r * 0.4, cx + r * 1.15, cy - r * 0.75,
                     cx + r * 1.15, cy + r * 0.75, cx + r * 0.35, cy + r * 0.4,
                     outline=color, fill="", width=w, joinstyle="round")


def _icon_hourglass(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_line(cx - r * 0.7, cy - r, cx + r * 0.7, cy - r, fill=color, width=w)
    c.create_line(cx - r * 0.7, cy + r, cx + r * 0.7, cy + r, fill=color, width=w)
    c.create_polygon(cx - r * 0.7, cy - r, cx + r * 0.7, cy - r, cx, cy,
                     outline=color, fill="", width=w, joinstyle="round")
    c.create_polygon(cx - r * 0.7, cy + r, cx + r * 0.7, cy + r, cx, cy,
                     outline=color, fill="", width=w, joinstyle="round")


def _icon_power(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_arc(cx - r, cy - r, cx + r, cy + r, start=55, extent=250, style="arc", outline=color, width=w)
    c.create_line(cx, cy - r * 1.15, cx, cy - r * 0.15, fill=color, width=w)


def _icon_link(c, cx, cy, s, color):
    r, w = s * 0.42, _w(s)
    c.create_oval(cx - r * 1.5, cy - r * 0.65, cx - r * 0.3, cy + r * 0.65, outline=color, width=w)
    c.create_oval(cx + r * 0.3, cy - r * 0.65, cx + r * 1.5, cy + r * 0.65, outline=color, width=w)


def _icon_calendar(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_rectangle(cx - r, cy - r * 0.75, cx + r, cy + r, outline=color, width=w)
    c.create_line(cx - r, cy - r * 0.2, cx + r, cy - r * 0.2, fill=color, width=w)
    c.create_line(cx - r * 0.5, cy - r * 1.1, cx - r * 0.5, cy - r * 0.5, fill=color, width=w)
    c.create_line(cx + r * 0.5, cy - r * 1.1, cx + r * 0.5, cy - r * 0.5, fill=color, width=w)


def _icon_hangup(c, cx, cy, s, color):
    r, w = s * 0.55, _w(s)
    c.create_arc(cx - r, cy - r * 0.3, cx + r, cy + r * 1.4, start=30, extent=120, style="arc", outline=color, width=w)
    c.create_line(cx - r * 0.55, cy + r * 0.05, cx, cy - r * 0.35, fill=color, width=w)
    c.create_line(cx + r * 0.55, cy + r * 0.05, cx, cy - r * 0.35, fill=color, width=w)


def _icon_pin(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_oval(cx - r * 0.65, cy - r, cx + r * 0.65, cy + r * 0.3, outline=color, width=w)
    c.create_polygon(cx - r * 0.35, cy + r * 0.05, cx + r * 0.35, cy + r * 0.05, cx, cy + r * 1.1,
                     outline=color, fill="", width=w, joinstyle="round")
    c.create_oval(cx - r * 0.2, cy - r * 0.5, cx + r * 0.2, cy - r * 0.1, outline=color, width=w * 0.85)


def _icon_play(c, cx, cy, s, color):
    r = s * 0.55
    c.create_polygon(cx - r * 0.55, cy - r * 0.75, cx - r * 0.55, cy + r * 0.75, cx + r * 0.75, cy,
                     fill=color, outline="")


def _icon_person(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_oval(cx - r * 0.35, cy - r, cx + r * 0.35, cy - r * 0.3, outline=color, width=w)
    c.create_arc(cx - r * 0.75, cy - r * 0.05, cx + r * 0.75, cy + r * 1.15, start=20, extent=140,
                 style="arc", outline=color, width=w)


def _icon_refresh(c, cx, cy, s, color):
    r, w = s * 0.48, _w(s)
    c.create_arc(cx - r, cy - r, cx + r, cy + r, start=30, extent=280, style="arc", outline=color, width=w)
    c.create_polygon(cx + r * 0.85, cy - r * 0.55, cx + r * 1.25, cy - r * 0.55, cx + r * 1.05, cy - r * 0.1,
                     fill=color, outline="")


def _icon_folder(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_polygon(cx - r, cy - r * 0.35, cx - r * 0.25, cy - r * 0.35, cx - r * 0.05, cy - r * 0.65,
                     cx + r * 0.35, cy - r * 0.65, cx + r * 0.35, cy - r * 0.35,
                     outline=color, fill="", width=w, joinstyle="round")
    c.create_rectangle(cx - r, cy - r * 0.35, cx + r, cy + r * 0.55, outline=color, width=w)


def _icon_check(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s) * 1.3
    c.create_line(cx - r * 0.75, cy, cx - r * 0.2, cy + r * 0.6, cx + r * 0.8, cy - r * 0.55,
                  fill=color, width=w, capstyle="round", joinstyle="round")


def _icon_qr(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    for dx, dy in ((-1, -1), (0.15, -1), (-1, 0.15)):
        x, y = cx + dx * r, cy + dy * r
        c.create_rectangle(x, y, x + r * 0.85, y + r * 0.85, outline=color, width=w)
    c.create_rectangle(cx + r * 0.2, cy + r * 0.2, cx + r * 0.55, cy + r * 0.55, fill=color, outline="")
    c.create_rectangle(cx + r * 0.7, cy + r * 0.7, cx + r, cy + r, fill=color, outline="")


def _icon_gear(c, cx, cy, s, color):
    r, w = s * 0.42, _w(s)
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=w)
    c.create_oval(cx - r * 0.35, cy - r * 0.35, cx + r * 0.35, cy + r * 0.35, outline=color, width=w)
    for i in range(8):
        a = math.radians(i * 45)
        c.create_line(cx + math.cos(a) * r, cy + math.sin(a) * r,
                      cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35, fill=color, width=w * 1.4)


def _icon_template(c, cx, cy, s, color):
    r, w = s * 0.5, _w(s)
    c.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=color, width=w)
    c.create_rectangle(cx - r * 0.65, cy - r * 0.65, cx + r * 0.1, cy - r * 0.05, outline=color, width=w * 0.8)
    c.create_line(cx - r * 0.65, cy + r * 0.35, cx + r * 0.65, cy + r * 0.35, fill=color, width=w * 0.8)
    c.create_line(cx - r * 0.65, cy + r * 0.7, cx + r * 0.2, cy + r * 0.7, fill=color, width=w * 0.8)


def _icon_star(c, cx, cy, s, color):
    r = s * 0.55
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        rad = r if i % 2 == 0 else r * 0.45
        pts += [cx + math.cos(a) * rad, cy + math.sin(a) * rad]
    c.create_polygon(*pts, fill=color, outline="")


ICONS = {
    "camera": _icon_camera, "video": _icon_video, "hourglass": _icon_hourglass, "power": _icon_power,
    "link": _icon_link, "calendar": _icon_calendar, "hangup": _icon_hangup, "pin": _icon_pin,
    "refresh": _icon_refresh, "play": _icon_play, "person": _icon_person, "folder": _icon_folder,
    "check": _icon_check, "qr": _icon_qr, "gear": _icon_gear, "template": _icon_template, "star": _icon_star,
}


class PillButton(tk.Canvas):
    """
    Botão em pílula (cantos totalmente arredondados, com antialias) com ícone
    desenhado + texto. Variantes:
      - "primary":   degradê da marca (ação principal)
      - "secondary": degradê de apoio (segunda ação em destaque)
      - "ghost":     fundo sutil com borda fina (ação secundária)
      - "ghost-active": como o ghost, com contorno/texto na cor da marca (selecionado)
      - "danger":    contorno/texto vermelho (encerrar/sair)
    `start_pulse()` faz o botão "respirar" (chama atenção na tela inicial).
    """

    def __init__(self, parent, text, command=None, icon=None, variant="ghost",
                 width=150, height=38, font=None, bg=None, radius=None):
        super().__init__(parent, width=width, height=height, bg=bg or theme.BG_PANEL,
                         highlightthickness=0, cursor="hand2")
        self.command = command
        self.text = text
        self.icon = icon
        self.variant = variant
        self.font = font or theme.font(10, "bold")
        self.radius = radius
        self._hover = False
        self._disabled = False
        self._glow = 0.0
        self._pulse_job = None
        self._photo = None
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._redraw()

    def _style(self):
        """(preenchimento, contorno, espessura, cor do texto) do estado atual."""
        boost = (0.14 if self._hover else 0.0) + self._glow
        if self._disabled:
            return theme.GHOST_BG, None, 0, theme.FG_MUTED
        if self.variant == "primary":
            return tuple(theme.lighten(c, boost) for c in theme.GRADIENT), None, 0, theme.TEXT_ON_ACCENT
        if self.variant == "secondary":
            stops = (theme.ACCENT3, theme.ACCENT2)
            return tuple(theme.lighten(c, boost) for c in stops), None, 0, "#ffffff"
        if self.variant == "ghost-active":
            fill = theme.GHOST_HOVER if self._hover else theme.GHOST_BG
            return fill, theme.ACCENT, 2, theme.ACCENT
        if self.variant == "danger":
            fill = theme.mix(theme.BG_CARD, theme.DANGER, 0.22) if self._hover else None
            return fill, theme.DANGER, 2, theme.DANGER
        fill = theme.GHOST_HOVER if self._hover else theme.GHOST_BG
        return fill, theme.BORDER, 1, theme.FG_TEXT

    def _redraw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        fill, outline, outline_w, text_color = self._style()
        radius = self.radius if self.radius is not None else h // 2
        self._photo = ImageTk.PhotoImage(theme.rounded_image(w, h, radius, fill, outline, outline_w), master=self)
        self.create_image(0, 0, anchor="nw", image=self._photo)

        if not self.text and self.icon:
            ICONS[self.icon](self, w / 2, h / 2, h * 0.5, text_color)
            return

        pad = max(14, int(h * 0.42))
        content_x = pad
        if self.icon:
            icon_size = h * 0.46
            ICONS[self.icon](self, content_x + icon_size * 0.55, h / 2, icon_size, text_color)
            content_x += icon_size * 1.4
        remaining_w = w - content_x - pad * 0.8
        self.create_text(content_x + max(0, remaining_w) / 2, h / 2, text=self.text,
                         fill=text_color, font=self.font, anchor="c")

    def _on_click(self, _event):
        if self.command and not self._disabled:
            print(f"clique no botão: {self.text!r}", flush=True)
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
        """"normal" ou "disabled" (compatível com .config(state=...) do ttk)."""
        self._disabled = (state == "disabled")
        self.config(cursor="arrow" if self._disabled else "hand2")
        self._redraw()

    def start_pulse(self):
        if self._pulse_job is None:
            self._pulse_phase = 0.0
            self._pulse_step()

    def stop_pulse(self):
        if self._pulse_job is not None:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        if self._glow:
            self._glow = 0.0
            self._redraw()

    def _pulse_step(self):
        self._pulse_phase += 0.14
        glow = round((math.sin(self._pulse_phase) + 1) / 2 * 0.2 / 0.04) * 0.04  # degraus (cache de imagens)
        if glow != self._glow:
            self._glow = glow
            self._redraw()
        self._pulse_job = self.after(50, self._pulse_step)

    # Compat com o código existente que chama .config(text=..., state=...)
    def config(self, **kwargs):
        if "text" in kwargs:
            self.set_text(kwargs.pop("text"))
        if "state" in kwargs:
            self.set_state(kwargs.pop("state"))
        if kwargs:
            super().config(**kwargs)

    def destroy(self):
        self.stop_pulse()
        super().destroy()


class Card(tk.Frame):
    """
    Painel em formato de card: fundo e borda finos, cantos arredondados e
    sombra suave (imagem gerada pelo Pillow, desenhada atrás do conteúdo).

    expand=False (padrão): o card "abraça" a altura do conteúdo (formulário/
    configurações). expand=True: ocupa toda a altura que o layout pai der
    (listas que precisam crescer).
    """

    MARGIN = 10  # espaço pra sombra em volta

    def __init__(self, parent, bg_outer=None, padx=18, pady=16, expand=False):
        bg_outer = bg_outer or theme.BG_PANEL
        super().__init__(parent, bg=bg_outer)
        self._expand = expand
        self._inset = self.MARGIN + 2
        self._canvas = tk.Canvas(self, bg=bg_outer, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self.body = tk.Frame(self._canvas, bg=theme.BG_CARD)
        self._window = self._canvas.create_window(self._inset, self._inset, window=self.body, anchor="nw")
        self._bg_photo = None
        self._canvas.bind("<Configure>", self._on_resize)
        self.body.bind("<Configure>", self._on_body_resize)
        self._inner = tk.Frame(self.body, bg=theme.BG_CARD)
        self._inner.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)

    def _on_resize(self, event):
        self._canvas.delete("bg")
        self._bg_photo = ImageTk.PhotoImage(
            theme.card_image(event.width, max(event.height, 44), 22, self.MARGIN), master=self._canvas)
        self._canvas.create_image(0, 0, anchor="nw", image=self._bg_photo, tags="bg")
        self._canvas.tag_lower("bg")
        self._canvas.itemconfig(self._window, width=max(10, event.width - 2 * self._inset))
        if self._expand:
            self._canvas.itemconfig(self._window, height=max(10, event.height - 2 * self._inset - 2))

    def _on_body_resize(self, _event):
        if not self._expand:
            self._canvas.config(height=self.body.winfo_reqheight() + 2 * self._inset + 2)

    @property
    def content(self):
        return self._inner


class Pill(tk.Canvas):
    """
    Cápsula flutuante só de leitura (status/indicador), pra sobrepor no
    preview da câmera. Usa place() no widget pai, não pack/grid.
    """

    def __init__(self, parent, text="", dot_color=None, bg="#1c1c1e",
                 fg=None, font=None, padx=14, pady=7):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent["bg"])
        self._text = text
        self._dot_color = dot_color
        self._bg = bg
        self._fg = fg or theme.FG_TEXT
        self._font = font or theme.font(10, "bold")
        self._padx = padx
        self._pady = pady
        self._photo = None
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
        self._photo = ImageTk.PhotoImage(theme.rounded_image(w, h, h // 2, self._bg), master=self)
        self.create_image(0, 0, anchor="nw", image=self._photo)
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


class FestiveBackground(tk.Canvas):
    """
    Fundo de tela cheia em degradê escuro tingido pela marca, com luzes
    suaves e confete esparso. `start_confetti()` solta confete animado
    (caindo e balançando) - usado na tela do QR e no processamento.
    """

    def __init__(self, parent, static_confetti=True):
        super().__init__(parent, highlightthickness=0, bd=0, bg=theme.BG_ROOT)
        self._static_confetti = static_confetti
        self._bg_photo = None
        self._size = (0, 0)
        self._confetti = []
        self._anim_job = None
        self._tick = 0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        if event.width < 64 or event.height < 64:
            return
        if (event.width, event.height) != self._size:
            self._size = (event.width, event.height)
            image = theme.festive_background(event.width, event.height, theme.CURRENT_ACCENT,
                                             confetti=self._static_confetti)
            self._bg_photo = ImageTk.PhotoImage(image, master=self)
            self.delete("bgimg")
            self.create_image(0, 0, anchor="nw", image=self._bg_photo, tags="bgimg")
            self.tag_lower("confetti")
            self.tag_lower("bgimg")

    def start_confetti(self, count=36):
        self.stop_confetti()
        width = max(self.winfo_width(), 800)
        height = max(self.winfo_height(), 600)
        rng = random.Random()
        for _ in range(count):
            size = rng.randint(8, 18)
            x, y = rng.uniform(0, width), rng.uniform(-height, 0)
            color = rng.choice(theme.PARTY)
            if rng.random() < 0.5:
                item = self.create_rectangle(x, y, x + size, y + size * 0.55, fill=color, outline="", tags="confetti")
            else:
                item = self.create_oval(x, y, x + size * 0.7, y + size * 0.7, fill=color, outline="", tags="confetti")
            self._confetti.append({"id": item, "speed": rng.uniform(2.0, 5.0),
                                   "sway": rng.uniform(0.6, 2.2), "phase": rng.uniform(0, 6.28)})
        self.tag_lower("confetti")
        self.tag_lower("bgimg")
        self._anim_job = self.after(40, self._step)

    def stop_confetti(self):
        if self._anim_job is not None:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        self.delete("confetti")
        self._confetti = []

    def _step(self):
        self._tick += 1
        height = max(self.winfo_height(), 600)
        width = max(self.winfo_width(), 800)
        for piece in self._confetti:
            dx = math.sin(self._tick * 0.08 + piece["phase"]) * piece["sway"]
            self.move(piece["id"], dx, piece["speed"])
            _x1, y1, _x2, _y2 = self.coords(piece["id"])
            if y1 > height:
                x1 = random.uniform(0, width)
                x2_old = self.coords(piece["id"])
                self.move(piece["id"], x1 - x2_old[0], -(y1 + random.uniform(20, 200)))
        self._anim_job = self.after(40, self._step)

    def destroy(self):
        self.stop_confetti()
        super().destroy()


# Compat: telas ainda não migradas pro `theme` importam essa constante daqui.
BG_CARD = theme.BG_CARD
