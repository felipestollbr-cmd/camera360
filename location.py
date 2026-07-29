import json
import os
import subprocess
import sys
import tempfile

# Consulta o Windows Location Services (WinRT Geolocator) via PowerShell -
# nao ha binding Python direto instalado neste venv, e isso evita depender
# de um pacote extra (winsdk) que pode nao ter wheel para este Python do
# MSYS2. Sem custo, sem API key: so usa o que o Windows ja oferece.
_PS_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime

Function Await($WinRtTask, $ResultType) {
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
    $asTaskGeneric = $asTask.MakeGenericMethod($ResultType)
    $netTask = $asTaskGeneric.Invoke($null, @($WinRtTask))
    $netTask.Wait(15000) | Out-Null
    if (-not $netTask.IsCompleted) { throw "timeout" }
    $netTask.Result
}

try {
    [Windows.Devices.Geolocation.Geolocator,Windows.Devices.Geolocation,ContentType=WindowsRuntime] | Out-Null
    [Windows.Devices.Geolocation.Geoposition,Windows.Devices.Geolocation,ContentType=WindowsRuntime] | Out-Null
    [Windows.Devices.Geolocation.GeolocationAccessStatus,Windows.Devices.Geolocation,ContentType=WindowsRuntime] | Out-Null

    $access = Await ([Windows.Devices.Geolocation.Geolocator]::RequestAccessAsync()) ([Windows.Devices.Geolocation.GeolocationAccessStatus])
    if ($access -ne [Windows.Devices.Geolocation.GeolocationAccessStatus]::Allowed) {
        Write-Output (@{ok=$false; error="access_denied"} | ConvertTo-Json -Compress)
        exit 0
    }

    $geolocator = New-Object Windows.Devices.Geolocation.Geolocator
    $pos = Await ($geolocator.GetGeopositionAsync()) ([Windows.Devices.Geolocation.Geoposition])
    $result = @{
        ok = $true
        lat = $pos.Coordinate.Point.Position.Latitude
        lon = $pos.Coordinate.Point.Position.Longitude
        accuracy_m = $pos.Coordinate.Accuracy
    }
    Write-Output ($result | ConvertTo-Json -Compress)
} catch {
    Write-Output (@{ok=$false; error="$_"} | ConvertTo-Json -Compress)
}
"""


def get_current_location(timeout=20):
    """
    Retorna {"lat", "lon", "accuracy_m"} usando o Windows Location Services,
    ou None se indisponivel, sem permissao, sem sinal, ou fora do Windows.
    """
    if sys.platform != "win32":
        return None
    script_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(_PS_SCRIPT)
            script_path = f.name
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout.strip().splitlines()[-1])
        if not data.get("ok"):
            return None
        return {"lat": data["lat"], "lon": data["lon"], "accuracy_m": data.get("accuracy_m")}
    except Exception:
        return None
    finally:
        if script_path and os.path.exists(script_path):
            os.unlink(script_path)


def maps_url(lat, lon):
    return f"https://www.google.com/maps?q={lat},{lon}"


def write_sidecar(capture_path, location):
    """Grava um .location.txt ao lado do arquivo capturado com lat/lon e o link do Maps."""
    base, _ = os.path.splitext(capture_path)
    sidecar_path = base + ".location.txt"
    lat, lon = location["lat"], location["lon"]
    accuracy = location.get("accuracy_m")
    lines = [
        f"Latitude: {lat}",
        f"Longitude: {lon}",
    ]
    if accuracy is not None:
        lines.append(f"Precisão: ~{accuracy:.0f} m")
    lines.append(f"Google Maps: {maps_url(lat, lon)}")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return sidecar_path
