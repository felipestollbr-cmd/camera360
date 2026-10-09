"""
Pós-produção do vídeo do giro 360: aplica o perfil de velocidade (trechos
mais rápidos/lentos, configurável em config.json) e mixa a música de fundo
fixa, tudo via ffmpeg/ffprobe (subprocess) - sem depender de moviepy/pydub,
no mesmo espírito de gopro_controller.py (que já chama o ffmpeg empacotado
como processo externo pro live view).
"""
import os
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

from ffmpeg_utils import find_ffmpeg, find_ffprobe

DEFAULT_SPEED_PROFILE = [
    {"start_pct": 0.0, "end_pct": 0.35, "speed": 1.0},
    {"start_pct": 0.35, "end_pct": 0.65, "speed": 0.35},
    {"start_pct": 0.65, "end_pct": 1.0, "speed": 1.0},
]

# Resolução de saída por formato de vídeo do evento - cobre os usos comuns
# (16:9 pra TV/download normal, 9:16 pra Stories/Reels, 1:1 pra feed).
ASPECT_RATIOS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


class VideoProcessingError(Exception):
    pass


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise VideoProcessingError(result.stderr.decode(errors="replace"))


def probe_duration(path):
    """Duração do vídeo em segundos, via ffprobe."""
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        raise VideoProcessingError("ffprobe não encontrado (bundle do ffmpeg incompleto)")
    cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise VideoProcessingError(result.stderr.decode(errors="replace"))
    return float(result.stdout.decode().strip())


def probe_dimensions(path):
    """Largura/altura (px) do vídeo, via ffprobe."""
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        raise VideoProcessingError("ffprobe não encontrado (bundle do ffmpeg incompleto)")
    cmd = [ffprobe_path, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise VideoProcessingError(result.stderr.decode(errors="replace"))
    width_str, height_str = result.stdout.decode().strip().split("x")
    return int(width_str), int(height_str)


def probe_fps(path, default=30.0):
    """FPS do vídeo (r_frame_rate do ffprobe, ex.: '30000/1001')."""
    ffprobe_path = find_ffprobe()
    if not ffprobe_path:
        return default
    cmd = [ffprobe_path, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path]
    result = subprocess.run(cmd, capture_output=True)
    try:
        num, _, den = result.stdout.decode().strip().partition("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return default
    return min(max(fps, 1.0), 120.0)


def apply_speed_profile(input_path, profile, output_path):
    """
    Corta o vídeo nos trechos definidos pelo perfil (frações 0-1 da duração
    total) e aplica `setpts=PTS/speed` em cada um (speed>1 acelera,
    speed<1 desacelera/câmera lenta), depois concatena tudo num único
    arquivo. Precisa re-codificar (setpts não é compatível com stream copy).
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise VideoProcessingError("ffmpeg não encontrado (bundle do ffmpeg incompleto)")

    duration = probe_duration(input_path)
    work_dir = tempfile.mkdtemp(prefix="camera360_speed_")
    segment_paths = []
    try:
        for i, seg in enumerate(profile):
            start_t = max(0.0, seg["start_pct"] * duration)
            end_t = min(duration, seg["end_pct"] * duration)
            seg_duration = end_t - start_t
            if seg_duration <= 0:
                continue
            speed = max(0.05, float(seg["speed"]))
            seg_path = os.path.join(work_dir, f"seg_{i}.mp4")
            # -ss/-t precisam vir ANTES do -i (opções de entrada): assim
            # delimitam o trecho lido do arquivo original antes do setpts
            # esticar/encolher os timestamps. Se -t viesse depois do -i,
            # ele limitaria a duração da SAÍDA (já esticada), cortando o
            # trecho errado do vídeo original (bem menos do que o pedido).
            _run([
                ffmpeg_path, "-y", "-loglevel", "error",
                "-ss", str(start_t), "-t", str(seg_duration), "-i", input_path,
                "-filter:v", f"setpts=PTS/{speed}", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                seg_path,
            ])
            segment_paths.append(seg_path)

        if not segment_paths:
            raise VideoProcessingError("Perfil de velocidade não gerou nenhum trecho válido")

        if len(segment_paths) == 1:
            os.replace(segment_paths[0], output_path)
            return output_path

        list_path = os.path.join(work_dir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for seg_path in segment_paths:
                escaped = seg_path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        _run([
            ffmpeg_path, "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", output_path,
        ])
        return output_path
    finally:
        for seg_path in segment_paths:
            if os.path.exists(seg_path) and seg_path != output_path:
                os.remove(seg_path)
        concat_list = os.path.join(work_dir, "concat.txt")
        if os.path.exists(concat_list):
            os.remove(concat_list)
        os.rmdir(work_dir)


def mix_background_music(video_path, music_path, output_path):
    """Mixa a trilha fixa sob o vídeo, em loop, cortada na duração do vídeo
    (-shortest com o vídeo primeiro garante que o corte é pelo vídeo, não
    pela música) - com um fade-out de 1s no final pra não cortar seco."""
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise VideoProcessingError("ffmpeg não encontrado (bundle do ffmpeg incompleto)")

    duration = probe_duration(video_path)
    fade_start = max(0.0, duration - 1.0)
    _run([
        ffmpeg_path, "-y", "-loglevel", "error",
        "-i", video_path, "-stream_loop", "-1", "-i", music_path,
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-af", f"afade=t=out:st={fade_start}:d=1",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        output_path,
    ])
    return output_path


def apply_aspect_ratio(input_path, aspect_ratio, output_path):
    """
    Ajusta o vídeo pro formato escolhido no evento (16:9/9:16/1:1),
    cortando o centro do frame original (o giro fica sempre com a pessoa
    centralizada, então cortar as laterais/topo-base mantém ela no quadro)
    e escalando pra uma resolução de saída padrão.
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise VideoProcessingError("ffmpeg não encontrado (bundle do ffmpeg incompleto)")

    target_w, target_h = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["16:9"])
    src_w, src_h = probe_dimensions(input_path)
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(target_ratio - src_ratio) < 0.01:
        vf = f"scale={target_w}:{target_h}"
    elif target_ratio < src_ratio:
        # saída mais estreita que a fonte (ex.: 16:9 -> 9:16) - corta os lados
        crop_w = int(src_h * target_ratio)
        vf = f"crop={crop_w}:{src_h}:(iw-{crop_w})/2:0,scale={target_w}:{target_h}"
    else:
        # saída mais larga que a fonte - corta topo/base
        crop_h = int(src_w / target_ratio)
        vf = f"crop={src_w}:{crop_h}:0:(ih-{crop_h})/2,scale={target_w}:{target_h}"

    _run([
        ffmpeg_path, "-y", "-loglevel", "error", "-i", input_path,
        "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        output_path,
    ])
    return output_path


def _load_font(size):
    for candidate in _FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def render_branding_overlay(event, size):
    """
    Gera uma imagem RGBA (mesmo tamanho do vídeo final) com o PNG e/ou o
    texto configurados no evento, pra sobrepor no vídeo com um único passo
    de overlay do ffmpeg. Retorna None se o evento não tem nenhuma marca
    configurada (nem texto nem PNG) - nesse caso não há o que sobrepor.
    """
    text = (event or {}).get("overlay_text") or ""
    png_path = (event or {}).get("overlay_png_path") or ""
    has_png = png_path and os.path.isfile(png_path)
    if not text and not has_png:
        return None

    w, h = size
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if has_png:
        logo = Image.open(png_path).convert("RGBA")
        # Logo ocupa no máximo 30% da largura do vídeo, ancorado no canto
        # superior esquerdo - funciona tanto pra um selo/logo pequeno
        # quanto (se o operador preferir) pra uma moldura maior.
        max_w = int(w * 0.3)
        if logo.width > max_w:
            ratio = max_w / logo.width
            logo = logo.resize((max_w, max(1, int(logo.height * ratio))), Image.Resampling.LANCZOS)
        canvas.paste(logo, (24, 24), logo)

    if text:
        draw = ImageDraw.Draw(canvas)
        font_size = max(18, int(h * 0.045))
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        band_h = text_h + 40
        # Faixa semi-opaca na base do vídeo pra garantir legibilidade do
        # texto em cima de qualquer fundo (mesmo raciocínio da régua do
        # protótipo original de medição, agora reaproveitado pra branding).
        draw.rectangle([0, h - band_h, w, h], fill=(0, 0, 0, 140))
        draw.text(((w - text_w) / 2, h - band_h + 20), text, font=font, fill=(255, 255, 255, 255))

    return canvas


def apply_event_branding(input_path, event, output_path):
    """Sobrepõe o PNG/texto do evento (se houver) no vídeo já ajustado ao
    formato escolhido. Sem nada configurado, só copia o arquivo adiante."""
    size = probe_dimensions(input_path)
    overlay_img = render_branding_overlay(event, size)
    if overlay_img is None:
        os.replace(input_path, output_path)
        return output_path

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise VideoProcessingError("ffmpeg não encontrado (bundle do ffmpeg incompleto)")

    work_dir = tempfile.mkdtemp(prefix="camera360_branding_")
    overlay_path = os.path.join(work_dir, "overlay.png")
    try:
        overlay_img.save(overlay_path)
        _run([
            ffmpeg_path, "-y", "-loglevel", "error",
            "-i", input_path, "-i", overlay_path,
            "-filter_complex", "overlay=0:0", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            output_path,
        ])
        return output_path
    finally:
        if os.path.exists(overlay_path):
            os.remove(overlay_path)
        os.rmdir(work_dir)


def apply_video_template(input_path, template, output_path):
    """
    Compõe o vídeo num template de vídeo (strip_templates.py, tipo "video"):
    escala o vídeo em "cover" pro quadro de vídeo, põe em cima do fundo do
    template e cobre com as camadas que ficam na frente - tudo num único
    ffmpeg. As imagens entram com o MESMO fps do vídeo (senão o ffmpeg
    reamostraria a câmera lenta pro fps padrão da imagem).
    """
    import strip_renderer  # import tardio: só quem usa template de vídeo precisa do Pillow aqui

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise VideoProcessingError("ffmpeg não encontrado (bundle do ffmpeg incompleto)")
    back, front, rect = strip_renderer.render_template_split(template, 1.0)
    if rect is None:
        raise VideoProcessingError("O template de vídeo não tem o quadro de vídeo")
    vx, vy, vw, vh = rect
    vw, vh = max(2, vw), max(2, vh)
    fps = probe_fps(input_path)

    work_dir = tempfile.mkdtemp(prefix="camera360_vtemplate_")
    back_path = os.path.join(work_dir, "back.png")
    front_path = os.path.join(work_dir, "front.png")
    try:
        back.save(back_path)
        front.save(front_path)
        graph = (
            f"[0:v]scale={vw}:{vh}:force_original_aspect_ratio=increase,crop={vw}:{vh}[v];"
            f"[1:v][v]overlay={vx}:{vy}:shortest=1[b];"
            f"[b][2:v]overlay=0:0:shortest=1[o];"
            f"[o]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[out]"
        )
        _run([
            ffmpeg_path, "-y", "-loglevel", "error", "-i", input_path,
            "-framerate", f"{fps:.3f}", "-loop", "1", "-i", back_path,
            "-framerate", f"{fps:.3f}", "-loop", "1", "-i", front_path,
            "-filter_complex", graph, "-map", "[out]", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", output_path,
        ])
        return output_path
    finally:
        for path in (back_path, front_path):
            if os.path.exists(path):
                os.remove(path)
        os.rmdir(work_dir)


def process_capture(raw_path, output_dir, speed_profile=None, music_path=None, event=None,
                    video_template=None):
    """
    Pipeline completo: velocidade -> template de vídeo (se houver) OU
    formato/marca simples do evento -> música (se configurada) -> retorna o
    caminho do arquivo final. Chamar de uma thread de worker (o
    processamento leva alguns segundos, não pode travar a UI do totem).
    """
    profile = speed_profile or DEFAULT_SPEED_PROFILE
    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())

    current_path = os.path.join(output_dir, f"spin_{timestamp}_sped.mp4")
    apply_speed_profile(raw_path, profile, current_path)

    if video_template is not None:
        templated_path = os.path.join(output_dir, f"spin_{timestamp}_tpl.mp4")
        apply_video_template(current_path, video_template, templated_path)
        os.remove(current_path)
        current_path = templated_path
    else:
        aspect_ratio = (event or {}).get("aspect_ratio")
        if aspect_ratio and aspect_ratio != "16:9":
            cropped_path = os.path.join(output_dir, f"spin_{timestamp}_crop.mp4")
            apply_aspect_ratio(current_path, aspect_ratio, cropped_path)
            os.remove(current_path)
            current_path = cropped_path

        if event and (event.get("overlay_text") or event.get("overlay_png_path")):
            branded_path = os.path.join(output_dir, f"spin_{timestamp}_branded.mp4")
            apply_event_branding(current_path, event, branded_path)
            if os.path.exists(current_path) and current_path != branded_path:
                os.remove(current_path)
            current_path = branded_path

    final_path = os.path.join(output_dir, f"spin_{timestamp}.mp4")
    if not music_path or not os.path.isfile(music_path):
        os.replace(current_path, final_path)
        return final_path

    mix_background_music(current_path, music_path, final_path)
    os.remove(current_path)
    return final_path
