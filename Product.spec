# -*- mode: python ; coding: utf-8 -*-
# Spec do PyInstaller parametrizado por produto (veja product.py).
#   CAMERA_PRODUCT=giro360     pyinstaller Product.spec   -> dist/Giro360/Giro360.exe
#   CAMERA_PRODUCT=fotocabine  pyinstaller Product.spec   -> dist/FotoCabine/FotoCabine.exe
# O script build_scripts/build_products.ps1 faz isso (e o instalador) pros dois.
import os
from pathlib import Path

project = Path.cwd()
sys_path_backup = list(__import__("sys").path)
__import__("sys").path.insert(0, str(project))
import product  # noqa: E402

info = product.select(os.environ.get("CAMERA_PRODUCT", product.DEFAULT_PRODUCT))
entry = f"{info['id']}.py"
exe_name = info["exe"]
icon_path = project / "assets" / f"{info['id']}.ico"
native = project / "dist_native"

# Flat native DLLs (libgphoto2, libusb, libexif, tcl/tk runtime dlls, etc.)
# land at the app root so add_dll_directory(sys._MEIPASS)/exe-dir picks them up.
flat_dlls = [(str(p), ".") for p in native.glob("*.dll")]

# camlibs/iolibs go where gphoto2/__init__.py already looks for them
# (gphoto2/libgphoto2/camlibs, gphoto2/libgphoto2/iolibs).
camlibs = [(str(p), "gphoto2/libgphoto2/camlibs") for p in (native / "gphoto2_camlibs").glob("*.dll")]
iolibs = [(str(p), "gphoto2/libgphoto2/iolibs") for p in (native / "gphoto2_iolibs").glob("*.dll")]

# Ícones/logos do produto (usados na splash).
assets = [(str(p), "assets") for p in (project / "assets").glob(f"{info['id']}*")]

# FFmpeg "release essentials" (extraído dentro da pasta do projeto, ver
# gopro_controller.py) - precisa dele de verdade pro live view Wi-Fi da GoPro e
# pro processamento do vídeo 360°. gopro_controller._find_ffmpeg() procura
# "ffmpeg-*/bin/ffmpeg.exe" ao lado do .exe, então o Tree() abaixo preserva
# esse mesmo nome de pasta no bundle.
ffmpeg_dirs = list(project.glob("ffmpeg-*"))

a = Analysis(
    [entry],
    pathex=[str(project)],
    binaries=flat_dlls,
    datas=camlibs + iolibs + assets,
    hiddenimports=["gphoto2", "serial", "main", "kiosk_app", "product"],
    hookspath=[],
    excludes=[],
    noarchive=False,
)

# Bundle Tcl/Tk data dirs verbatim (they contain many small .tcl files, not binaries)
a.datas += Tree(str(native / "tcl" / "tcl8.6"), prefix="tcl/tcl8.6")
a.datas += Tree(str(native / "tcl" / "tk8.6"), prefix="tcl/tk8.6")

for ffmpeg_dir in ffmpeg_dirs:
    a.datas += Tree(str(ffmpeg_dir), prefix=ffmpeg_dir.name)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=exe_name,
    console=False,
    icon=str(icon_path) if icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=exe_name,
)
