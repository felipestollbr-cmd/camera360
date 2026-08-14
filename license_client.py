"""
Cliente da plataforma de licenciamento (camera360-licensing): identifica
essa máquina, ativa uma license_key uma vez e valida com o servidor
periodicamente. O Camera360 só roda com uma validação online recente e
positiva - sem cache offline (se a internet cair, o app trava até voltar).
"""
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid

STATE_PATH = "license.json"


def _get_hardware_id():
    """UUID de placa-mãe/produto via WMI (PowerShell) - mais difícil de
    falsificar do que só copiar o license.json pra outra máquina. Se falhar
    (VM sem WMI, permissão etc.), cai num UUID aleatório persistido local,
    que ainda cumpre o objetivo prático (identificar essa instalação de
    forma estável entre reinicializações)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        uuid_str = result.stdout.strip()
        if result.returncode == 0 and uuid_str and uuid_str.upper() != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
            return uuid_str
    except Exception:
        pass
    return None


def _load_state():
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_hardware_id():
    """Sempre retorna o mesmo id nessa máquina - grava a primeira vez que
    calcula (seja o UUID de hardware ou o fallback aleatório) pra nunca
    mudar depois, mesmo que o WMI comece a falhar num boot futuro."""
    state = _load_state()
    if state.get("hardware_id"):
        return state["hardware_id"]

    hardware_id = _get_hardware_id() or f"RANDOM-{uuid.uuid4()}"
    state["hardware_id"] = hardware_id
    _save_state(state)
    return hardware_id


def get_saved_license_key():
    return _load_state().get("license_key", "")


def _post(api_base_url, path, payload):
    url = api_base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"valid": False, "message": f"Erro HTTP {e.code}"}
        return body, e.code
    except urllib.error.URLError as e:
        return {"valid": False, "message": f"Sem conexão com o servidor de licenças ({e.reason})"}, 0


def activate(api_base_url, license_key):
    """Ativa a licença nessa máquina (primeira vez) e salva a chave
    localmente pras próximas validações não precisarem digitar de novo."""
    hardware_id = get_hardware_id()
    payload, status = _post(api_base_url, "/api/v1/license/activate",
                             {"license_key": license_key.strip().upper(), "hardware_id": hardware_id})
    if payload.get("valid") or status == 200:
        state = _load_state()
        state["license_key"] = license_key.strip().upper()
        _save_state(state)
    return payload


def validate(api_base_url):
    """Valida a licença salva localmente. Sem license_key salva ainda,
    retorna inválido sem nem tentar - a tela de ativação cuida disso."""
    license_key = get_saved_license_key()
    if not license_key:
        return {"valid": False, "message": "Nenhuma licença ativada nesta máquina"}
    hardware_id = get_hardware_id()
    payload, _status = _post(api_base_url, "/api/v1/license/validate",
                              {"license_key": license_key, "hardware_id": hardware_id})
    return payload
