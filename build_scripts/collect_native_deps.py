"""Resolve the closure of MSYS2 UCRT64 DLLs needed to run the Camera360 products standalone.

Walks the PE import table of a set of seed files (gphoto2 native libs/plugins,
tkinter) via `objdump -p` and follows every dependency that resolves to a file
under the MSYS2 UCRT64 tree, recursively, so the PyInstaller build can bundle
the whole closure instead of guessing DLL names by hand.
"""
import subprocess
import sys
from pathlib import Path

UCRT64 = Path(r"C:\msys64\ucrt64")
OBJDUMP = UCRT64 / "bin" / "objdump.exe"


def imported_dll_names(path: Path):
    out = subprocess.run([str(OBJDUMP), "-p", str(path)], capture_output=True, text=True)
    names = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("DLL Name:"):
            names.append(line.split(":", 1)[1].strip())
    return names


def resolve_under_ucrt64(name: str):
    candidate = UCRT64 / "bin" / name
    if candidate.exists():
        return candidate
    # case-insensitive fallback
    for f in (UCRT64 / "bin").iterdir():
        if f.name.lower() == name.lower():
            return f
    return None


def collect(seeds):
    visited_files = set()
    extra_deps = set()
    queue = list(seeds)

    while queue:
        current = queue.pop()
        key = str(current).lower()
        if key in visited_files:
            continue
        visited_files.add(key)

        for name in imported_dll_names(current):
            resolved = resolve_under_ucrt64(name)
            if resolved is None:
                continue  # Windows system DLL, OS provides it
            rkey = str(resolved).lower()
            if rkey not in visited_files:
                extra_deps.add(resolved)
                queue.append(resolved)

    return extra_deps


if __name__ == "__main__":
    project = Path(__file__).resolve().parent.parent
    venv_site = project / "venv" / "lib" / "python3.14" / "site-packages"

    gphoto2_pkg = venv_site / "gphoto2"
    camlibs_dir = UCRT64 / "lib" / "libgphoto2" / "2.5.34"
    iolibs_dir = UCRT64 / "lib" / "libgphoto2_port" / "0.12.2"

    seeds = []
    seeds += list(gphoto2_pkg.glob("*.pyd"))
    seeds += list(camlibs_dir.glob("*.dll"))
    seeds += list(iolibs_dir.glob("*.dll"))
    seeds += [UCRT64 / "lib" / "python3.14" / "lib-dynload" / "_tkinter.cp314-mingw_x86_64_ucrt_gnu.pyd"]
    seeds += [UCRT64 / "bin" / "tcl86.dll", UCRT64 / "bin" / "tk86.dll"]

    deps = collect(seeds)
    for d in sorted(deps):
        print(d)
