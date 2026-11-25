# Gera os executaveis (PyInstaller) e os instaladores (Inno Setup) dos produtos.
#
#   .\build_scripts\build_products.ps1                    # Giro360 + FotoCabine
#   .\build_scripts\build_products.ps1 -Product giro360   # so um deles
#   .\build_scripts\build_products.ps1 -SkipInstaller     # so o executavel (dist\)
#
# Saidas: dist\Giro360\Giro360.exe, dist\FotoCabine\FotoCabine.exe e
# Output\Giro360-Setup.exe, Output\FotoCabine-Setup.exe
param(
    [ValidateSet("all", "giro360", "fotocabine")][string]$Product = "all",
    [switch]$SkipInstaller
)
# comandos nativos escrevem avisos no stderr (ex.: pip); o PS 5.1 trataria isso como erro, entao so o ExitCode vale
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = Join-Path $root "venv\bin\python.exe"
if (-not (Test-Path $py)) { throw "venv nao encontrado em $py (veja o README)" }

$names = @{ giro360 = "Giro360"; fotocabine = "FotoCabine" }
$products = if ($Product -eq "all") { @("giro360", "fotocabine") } else { @($Product) }

& $py -m pip install --quiet --disable-pip-version-check pyinstaller
if ($LASTEXITCODE -ne 0) { throw "falha ao instalar o PyInstaller" }

Write-Host "== Icones" -ForegroundColor Cyan
& $py build_scripts\make_icons.py
if ($LASTEXITCODE -ne 0) { throw "falha ao gerar os icones" }

if (-not (Test-Path "dist_native")) {
    Write-Host "== Dependencias nativas (MSYS2 UCRT64)" -ForegroundColor Cyan
    & $py build_scripts\prepare_bundle_assets.py
    if ($LASTEXITCODE -ne 0) { throw "falha ao reunir as dependencias nativas" }
}

if (-not (Get-ChildItem -Directory -Filter "ffmpeg-*" -ErrorAction SilentlyContinue)) {
    # sem a pasta ffmpeg-* (build essentials da gyan.dev), reaproveita o ffmpeg/ffprobe do PATH
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $fp = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($ff -and $fp) {
        Write-Host "== ffmpeg: copiando de $($ff.Source) para ffmpeg-bundled\bin" -ForegroundColor Cyan
        New-Item -ItemType Directory -Force "ffmpeg-bundled\bin" | Out-Null
        Copy-Item $ff.Source "ffmpeg-bundled\bin\ffmpeg.exe" -Force
        Copy-Item $fp.Source "ffmpeg-bundled\bin\ffprobe.exe" -Force
    } else {
        Write-Warning "ffmpeg nao encontrado (pasta ffmpeg-* ou PATH): sem ele o video e o live view da GoPro nao funcionam no instalador."
    }
}

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

foreach ($p in $products) {
    $name = $names[$p]
    Write-Host "== $name : executavel" -ForegroundColor Cyan
    $env:CAMERA_PRODUCT = $p
    & $py -m PyInstaller Product.spec --noconfirm --distpath dist --workpath "build\$p"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou para $name" }

    if (-not $SkipInstaller) {
        if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) nao encontrado" }
        Write-Host "== $name : instalador" -ForegroundColor Cyan
        # compila numa pasta temporaria e move: o antivirus as vezes trava o Setup.exe recem-gravado
        # em Output\ ("EndUpdateResource failed") e isso derruba o build sem motivo real
        $tmpOut = Join-Path $env:TEMP "camera360-iss-$p"
        New-Item -ItemType Directory -Force $tmpOut | Out-Null
        & $iscc "/DProduct=$p" "/O$tmpOut" /Q Installer.iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou para $name" }
        New-Item -ItemType Directory -Force Output | Out-Null
        Move-Item (Join-Path $tmpOut "$name-Setup.exe") "Output\$name-Setup.exe" -Force
    }
}
Remove-Item Env:\CAMERA_PRODUCT -ErrorAction SilentlyContinue
Write-Host "Pronto." -ForegroundColor Green
