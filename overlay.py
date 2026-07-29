import cv2
import numpy as np

HUD_COLOR = (255, 255, 255)
REC_COLOR = (60, 60, 255)
FOCUS_OK_COLOR = (160, 224, 0)
FOCUS_FAIL_COLOR = (60, 60, 255)
SHADOW_COLOR = (0, 0, 0)
AA = cv2.LINE_AA


def _text(img, text, org, font_scale, color, thickness=1):
    """Texto com contorno escuro por baixo, para ler em qualquer fundo."""
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale, SHADOW_COLOR,
                thickness + 2, AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale, color,
                thickness, AA)


def _line(img, p1, p2, color, thickness=1):
    cv2.line(img, p1, p2, color, thickness, AA)


def _thirds_and_center_grid(img, w, h, color):
    """Regra dos terços + linha vertical central (guia de nivelamento), bem sutil."""
    thickness = 1
    grid_color = tuple(int(c * 0.75) for c in color)
    _line(img, (w // 3, 0), (w // 3, h), grid_color, thickness)
    _line(img, (2 * w // 3, 0), (2 * w // 3, h), grid_color, thickness)
    _line(img, (0, h // 3), (w, h // 3), grid_color, thickness)
    _line(img, (0, 2 * h // 3), (w, 2 * h // 3), grid_color, thickness)
    _line(img, (w // 2, 0), (w // 2, h), grid_color, thickness)


def _af_reticle(img, w, h, color, focus_state=None):
    """
    Mira de foco central: cantos em bracket + linha horizontal curta. A cor
    reflete a confirmação real da câmera após a última tentativa de
    autofoco (focus_state: True = focou, False = não confirmou, None =
    sem tentativa ainda) - não é uma posição exata do ponto de AF (a Canon
    não documenta publicamente a escala de coordenadas do "focusinfo"), só
    um indicador de "focou" ou não.
    """
    if focus_state is True:
        color = FOCUS_OK_COLOR
    elif focus_state is False:
        color = FOCUS_FAIL_COLOR
    cx, cy = w // 2, h // 2
    half = int(min(w, h) * 0.055)
    bracket = int(half * 0.6)
    thickness = 2
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        x = cx + dx * half
        y = cy + dy * half
        _line(img, (x, y), (x - dx * bracket, y), color, thickness)
        _line(img, (x, y), (x, y - dy * bracket), color, thickness)
    _line(img, (cx - int(half * 1.3), cy), (cx + int(half * 1.3), cy), color, 1)


def _ruler_height(h):
    return max(90, int(h * 0.13))


def _rec_indicator(img, w, h, recording):
    """Ponto REC, canto superior esquerdo."""
    x, y = int(w * 0.03), int(h * 0.05)
    r = max(4, int(h * 0.012))
    dot_color = REC_COLOR if recording else (150, 150, 150)
    cv2.circle(img, (x + r, y + r), r, SHADOW_COLOR, -1, AA)
    cv2.circle(img, (x + r, y + r), r, dot_color, -1, AA)


def _ruler_band(img, w, h, color):
    """
    Faixa de regua opaca em mm/cm na base do quadro (funcao de medicao do
    Camera360): zero centralizado, com a escala se abrindo para a esquerda e
    para a direita - facilita alinhar o centro da regua sobre o ponto a
    medir (ex.: uma lesao) e ler o tamanho para os dois lados.
    """
    ruler_height = _ruler_height(h)
    ruler_y = h - ruler_height
    overlay = img[ruler_y:h, 0:w].copy()
    img[ruler_y:h, 0:w] = cv2.addWeighted(overlay, 0.45, np.zeros_like(overlay), 0.55, 0)

    center_x = w // 2
    cm_each_side = 10
    px_per_cm = (w / 2) / cm_each_side
    px_per_mm = px_per_cm / 10

    for side in (-1, 1):
        for mm in range(cm_each_side * 10 + 1):
            x = int(center_x + side * mm * px_per_mm)
            if x < 0 or x >= w:
                continue
            is_cm = (mm % 10 == 0)
            is_5mm = (mm % 5 == 0 and not is_cm)
            tick_height = int(ruler_height * 0.20)
            if is_5mm:
                tick_height = int(ruler_height * 0.34)
            if is_cm:
                tick_height = int(ruler_height * 0.5)
            _line(img, (x, ruler_y + ruler_height - 2),
                  (x, ruler_y + ruler_height - tick_height), color, 1)

            if is_cm and mm > 0:
                cm_val = mm // 10
                label = str(cm_val)
                font_scale = max(0.4, w / 1700)
                tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)[0][0]
                tx = max(4, min(x - tw // 2, w - tw - 4))
                _text(img, label, (tx, ruler_y + ruler_height - tick_height - 4), font_scale, color)

    zero_font_scale = max(0.45, w / 1500)
    tw = cv2.getTextSize("0", cv2.FONT_HERSHEY_SIMPLEX, zero_font_scale, 1)[0][0]
    _text(img, "0", (center_x - tw // 2, ruler_y + int(ruler_height * 0.5) - 8),
          zero_font_scale, color, thickness=2)
    return ruler_y


def draw_overlay(frame, show_grid=True, show_ruler=True, cam_info=None):
    """
    Desenha o HUD da camera (cantos, terços, mira de foco, indicadores) e a
    regua mm/cm (zero central) sobre o frame. Retorna o frame modificado.
    """
    if frame is None:
        return None
    img = frame.copy()
    h, w = img.shape[:2]
    info = cam_info or {}

    if show_grid:
        _thirds_and_center_grid(img, w, h, HUD_COLOR)
        _af_reticle(img, w, h, HUD_COLOR, focus_state=info.get("focus_confirmed"))
        _rec_indicator(img, w, h, recording=info.get("recording", False))

    if show_ruler:
        _ruler_band(img, w, h, HUD_COLOR)

    return img
