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

from ffmpeg_utils import find_ffmpeg, find_ffprobe

DEFAULT_SPEED_PROFILE = [
    {"start_pct": 0.0, "end_pct": 0.35, "speed": 1.0},
    {"start_pct": 0.35, "end_pct": 0.65, "speed": 0.35},
    {"start_pct": 0.65, "end_pct": 1.0, "speed": 1.0},
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


def process_capture(raw_path, output_dir, speed_profile=None, music_path=None):
    """
    Pipeline completo: velocidade -> música (se configurada) -> retorna o
    caminho do arquivo final. Chamar de uma thread de worker (o
    processamento leva alguns segundos, não pode travar a UI do totem).
    """
    profile = speed_profile or DEFAULT_SPEED_PROFILE
    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())

    sped_path = os.path.join(output_dir, f"spin_{timestamp}_sped.mp4")
    apply_speed_profile(raw_path, profile, sped_path)

    if not music_path or not os.path.isfile(music_path):
        final_path = os.path.join(output_dir, f"spin_{timestamp}.mp4")
        os.replace(sped_path, final_path)
        return final_path

    final_path = os.path.join(output_dir, f"spin_{timestamp}.mp4")
    mix_background_music(sped_path, music_path, final_path)
    os.remove(sped_path)
    return final_path
