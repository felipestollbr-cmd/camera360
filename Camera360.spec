# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path.cwd()
native = project / "dist_native"

# Flat native DLLs (libgphoto2, libusb, libexif, tcl/tk runtime dlls, etc.)
# land at the app root so add_dll_directory(sys._MEIPASS)/exe-dir picks them up.
flat_dlls = [(str(p), ".") for p in native.glob("*.dll")]

# camlibs/iolibs go where gphoto2/__init__.py already looks for them
# (gphoto2/libgphoto2/camlibs, gphoto2/libgphoto2/iolibs).
camlibs = [(str(p), "gphoto2/libgphoto2/camlibs") for p in (native / "gphoto2_camlibs").glob("*.dll")]
iolibs = [(str(p), "gphoto2/libgphoto2/iolibs") for p in (native / "gphoto2_iolibs").glob("*.dll")]

# Tcl/Tk script libraries (init.tcl etc.) needed at runtime by Tcl_Init/Tk_Init.
tcl_data = [(str(native / "tcl" / "tcl8.6"), "tcl/tcl8.6"), (str(native / "tcl" / "tk8.6"), "tcl/tk8.6")]

# FFmpeg "release essentials" (extraído dentro da pasta do projeto, ver
# gopro_controller.py) - precisa dele de verdade (não só das libs que o
# opencv-python já embute) pro live view Wi-Fi da GoPro funcionar.
# gopro_controller._find_ffmpeg() procura "ffmpeg-*/bin/ffmpeg.exe" ao lado
# do .exe, então o Tree() abaixo preserva esse mesmo nome de pasta no bundle.
ffmpeg_dirs = list(project.glob("ffmpeg-*"))

a = Analysis(
    ["main.py"],
    pathex=[str(project)],
    binaries=flat_dlls,
    datas=camlibs + iolibs,
    hiddenimports=["gphoto2", "webview", "webview.platforms.edgechromium"],
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
    name="Camera360",
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Camera360",
)
