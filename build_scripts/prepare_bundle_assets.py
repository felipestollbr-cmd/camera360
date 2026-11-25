"""Stage MSYS2 UCRT64 native files into a local folder PyInstaller can pick up.

Run this before `pyinstaller Product.spec (veja build_scripts/build_products.ps1)`. It copies:
  - libgphoto2/libgphoto2_port + their full transitive DLL closure -> dist_native/
  - camlibs/iolibs plugin DLLs -> dist_native/gphoto2_camlibs, dist_native/gphoto2_iolibs
    (matching the layout gphoto2/__init__.py already looks for at runtime)
  - tcl86.dll / tk86.dll + their script library folders -> dist_native/ and dist_native/tcl
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_native_deps import collect, UCRT64  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STAGE = PROJECT / "dist_native"
CAMLIBS_SRC = UCRT64 / "lib" / "libgphoto2" / "2.5.34"
IOLIBS_SRC = UCRT64 / "lib" / "libgphoto2_port" / "0.12.2"


def reset_stage():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    (STAGE / "gphoto2_camlibs").mkdir()
    (STAGE / "gphoto2_iolibs").mkdir()
    (STAGE / "tcl" / "tcl8.6").mkdir(parents=True)
    (STAGE / "tcl" / "tk8.6").mkdir(parents=True)


def copy_flat(paths, dest):
    for p in paths:
        shutil.copy2(p, dest / p.name)


def main():
    reset_stage()

    seeds = []
    seeds += list((PROJECT / "venv" / "lib" / "python3.14" / "site-packages" / "gphoto2").glob("*.pyd"))
    seeds += list(CAMLIBS_SRC.glob("*.dll"))
    seeds += list(IOLIBS_SRC.glob("*.dll"))
    seeds += [UCRT64 / "lib" / "python3.14" / "lib-dynload" / "_tkinter.cp314-mingw_x86_64_ucrt_gnu.pyd"]
    seeds += [UCRT64 / "bin" / "tcl86.dll", UCRT64 / "bin" / "tk86.dll"]

    extra_deps = collect(seeds)
    extra_deps |= {UCRT64 / "bin" / "libgphoto2-6.dll", UCRT64 / "bin" / "libgphoto2_port-12.dll"}
    extra_deps |= {UCRT64 / "bin" / "tcl86.dll", UCRT64 / "bin" / "tk86.dll"}

    copy_flat(extra_deps, STAGE)
    copy_flat(CAMLIBS_SRC.glob("*.dll"), STAGE / "gphoto2_camlibs")
    copy_flat(IOLIBS_SRC.glob("*.dll"), STAGE / "gphoto2_iolibs")

    shutil.copytree(UCRT64 / "lib" / "tcl8.6", STAGE / "tcl" / "tcl8.6", dirs_exist_ok=True)
    shutil.copytree(UCRT64 / "lib" / "tk8.6", STAGE / "tcl" / "tk8.6", dirs_exist_ok=True)

    print(f"Staged {sum(1 for _ in STAGE.rglob('*') if _.is_file())} files into {STAGE}")


if __name__ == "__main__":
    main()
