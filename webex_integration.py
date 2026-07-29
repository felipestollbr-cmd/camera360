import datetime
import json
import os
import secrets
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

CONFIG_PATH = "webex_config.json"
# A conta logada aqui é só a "câmera": cria a reunião e entra nela pra
# transmitir o vídeo do Camera360. O organizador participa com uma conta Webex
# diferente (outro app/dispositivo) - por isso não precisa entrar pelo
# Camera360, e as duas sessões não colidem (identidades diferentes).
TOKEN_PATH = "webex_token.json"
AUTH_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
MEETINGS_URL = "https://webexapis.com/v1/meetings"
# spark:all/spark:kms sao exigidos pelo Meetings Widget para realmente
# entrar/participar de reunioes (nao so agenda-las) - ele precisa
# identificar o usuario logado via /v1/people/me e negociar as chaves
# de criptografia da reuniao (KMS), o que os escopos meeting:schedules_*
# sozinhos nao cobrem.
SCOPES = "meeting:schedules_read meeting:schedules_write spark:all spark:kms"


class WebexNotConfigured(Exception):
    pass


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        raise WebexNotConfigured(
            "webex_config.json não encontrado. Copie webex_config.example.json "
            "para webex_config.json e preencha client_id/client_secret "
            "(veja developer.webex.com/my-apps)."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("client_id") or "COLE_AQUI" in cfg.get("client_id", ""):
        raise WebexNotConfigured("Preencha client_id e client_secret em webex_config.json.")
    return cfg


def _load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_token(token):
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(token, f)


def _post_form(url, data):
    encoded = urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise Exception(f"Webex API error {e.code}: {body}")


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_state = params.get("state", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]
        self.server.auth_error_description = params.get("error_description", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.auth_error:
            html = (
                "<html><body style='font-family:sans-serif;text-align:center;padding-top:60px'>"
                "<h2>Falha ao conectar ao Webex.</h2>"
                f"<p>{self.server.auth_error}: {self.server.auth_error_description or ''}</p>"
                "<p>Pode fechar esta aba e voltar ao app.</p></body></html>"
            )
        else:
            html = (
                "<html><body style='font-family:sans-serif;text-align:center;padding-top:60px'>"
                "<h2>Camera360 conectado ao Webex.</h2><p>Pode fechar esta aba e voltar ao app.</p>"
                "</body></html>"
            )
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, fmt, *args):
        pass  # silencia o log de acesso HTTP no console


def _run_oauth_flow(cfg, timeout=120):
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": cfg["client_id"],
        "response_type": "code",
        "redirect_uri": cfg["redirect_uri"],
        "scope": SCOPES,
        "state": state,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"

    parsed_redirect = urlparse(cfg["redirect_uri"])
    port = parsed_redirect.port or 8765
    # "localhost" pode resolver para IPv6 (::1) dependendo da máquina; o
    # navegador podendo tentar um endereço diferente do que o server.py
    # escutou faz a resposta nunca chegar, sem erro nenhum aparecer. Usar o
    # IPv4 explícito evita essa ambiguidade.
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.auth_code = None
    server.auth_state = None
    server.auth_error = None
    server.auth_error_description = None
    server.timeout = 1

    webbrowser.open(url)

    deadline = time.time() + timeout
    while time.time() < deadline and server.auth_code is None and server.auth_error is None:
        server.handle_request()
    server.server_close()

    if server.auth_error:
        raise Exception(f"Webex recusou a autorização: {server.auth_error} - {server.auth_error_description}")

    if not server.auth_code:
        raise Exception("Login no Webex não completou a tempo. Tente de novo.")
    if server.auth_state != state:
        raise Exception("Resposta do Webex com 'state' inválido - tente de novo.")

    token = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": server.auth_code,
        "redirect_uri": cfg["redirect_uri"],
    })
    token["obtained_at"] = time.time()
    _save_token(token)
    return token


def _refresh_token(cfg, token):
    new_token = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": token["refresh_token"],
    })
    new_token["obtained_at"] = time.time()
    _save_token(new_token)
    return new_token


def get_access_token():
    """
    Retorna um access token válido. Se não houver login ainda, abre o
    navegador para o usuário autorizar o Camera360 (fluxo OAuth padrão do
    Webex); se o token expirou, renova com o refresh_token.
    """
    cfg = _load_config()
    token = _load_token()

    if token is None:
        return _run_oauth_flow(cfg)["access_token"]

    age = time.time() - token.get("obtained_at", 0)
    if age >= token.get("expires_in", 0) - 60:
        try:
            return _refresh_token(cfg, token)["access_token"]
        except Exception:
            return _run_oauth_flow(cfg)["access_token"]
    return token["access_token"]


def create_meeting(title, start_utc, end_utc, invitees=None):
    """
    Cria uma reunião Webex com título e horário (datetime UTC, naive)
    específicos. Retorna o dict da API (contém 'webLink', o link de
    acesso). A API do Webex Meetings só cria/gerencia a reunião - ela não
    injeta o vídeo da câmera na chamada; isso ainda dependeria de uma
    câmera virtual separada.

    invitees: lista de e-mails a convidar (o Webex manda o convite/notifica
    cada um). Só adiciona quem vai PARTICIPAR - não substitui a conta que
    o Camera360 usa pra transmitir a câmera.
    """
    access_token = get_access_token()
    payload = {
        "title": title,
        "start": start_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "end": end_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "timezone": "UTC",
    }
    if invitees:
        payload["invitees"] = [{"email": email} for email in invitees]
    body = json.dumps(payload).encode()

    req = urllib.request.Request(MEETINGS_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise Exception(f"Falha ao criar reunião Webex ({e.code}): {err_body}")


def create_instant_meeting(title="Camera360 - Sessão ao vivo", duration_minutes=60, invitees=None):
    """Agenda uma reunião Webex começando em ~1 minuto."""
    start = datetime.datetime.utcnow() + datetime.timedelta(minutes=1)
    end = start + datetime.timedelta(minutes=duration_minutes)
    return create_meeting(title, start, end, invitees=invitees)


def get_meeting_participants(meeting_id):
    """
    Lista quem está atualmente na reunião (id retornado por
    create_instant_meeting/create_meeting). Só retorna participantes depois
    que a reunião realmente começou no lado do Webex.
    """
    access_token = get_access_token()
    url = f"https://webexapis.com/v1/meetingParticipants?{urlencode({'meetingId': meeting_id})}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", [])
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise Exception(f"Falha ao listar participantes ({e.code}): {err_body}")


def list_upcoming_meetings(max_results=10):
    """
    Lista reuniões agendadas futuras. Retorna uma lista de dicts da API
    (cada um com 'title', 'start', 'end', 'webLink', etc.).
    """
    access_token = get_access_token()
    params = {
        "meetingType": "scheduledMeeting",
        "max": max_results,
        "from": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z",
    }
    url = f"{MEETINGS_URL}?{urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", [])
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise Exception(f"Falha ao listar reuniões Webex ({e.code}): {err_body}")
