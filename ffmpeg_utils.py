"""
Localiza o executável do ffmpeg empacotado com o projeto (build "release
essentials" da gyan.dev, extraído dentro da pasta do projeto ou ao lado do
.exe empacotado - ver ffmpeg-*/ no .gitignore). Compartilhado entre
gopro_controller.py (stream ao vivo) e video_processor.py (pós-produção),
já que os dois precisam do mesmo binário.
"""
import glob
import os
import shutil
import sys


def _find_binary(exe_name, env_var):
    override = os.environ.get(env_var)
    if override and os.path.isfile(override):
        return override

    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    for candidate in glob.glob(os.path.join(base_dir, "ffmpeg-*", "bin", exe_name)):
        if os.path.isfile(candidate):
            return candidate

    return shutil.which(exe_name.replace(".exe", ""))


def find_ffmpeg():
    return _find_binary("ffmpeg.exe", "CAMERA360_FFMPEG_PATH")


def find_ffprobe():
    return _find_binary("ffprobe.exe", "CAMERA360_FFPROBE_PATH")
