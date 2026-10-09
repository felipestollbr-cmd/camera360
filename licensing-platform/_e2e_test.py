import re
import time

import requests

BASE = "http://127.0.0.1:8000"
SUFFIX = str(int(time.time()))  # nomes únicos a cada execução (o teste pode rodar várias vezes)


def get_csrf(session, url):
    resp = session.get(url)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', resp.text)
    return match.group(1), resp


def login(session, username, password):
    csrf, _ = get_csrf(session, f"{BASE}/accounts/login/")
    resp = session.post(f"{BASE}/accounts/login/", data={
        "username": username, "password": password, "csrfmiddlewaretoken": csrf,
    }, headers={"Referer": f"{BASE}/accounts/login/"})
    assert resp.status_code == 200, f"login falhou: {resp.status_code}"
    assert "login" not in resp.url, f"login parece ter falhado, ainda em {resp.url}"
    return resp


# --- 1. super admin cria um vendedor ---
admin_session = requests.Session()
login(admin_session, "admin", "admin12345")
csrf, resp = get_csrf(admin_session, f"{BASE}/")
assert "Criar vendedor" in resp.text, "dashboard do super admin não carregou direito"

VENDOR_NAME = f"Fotos do Fe E2E {SUFFIX}"
VENDOR_USER = f"vendedor_e2e_{SUFFIX}"
resp = admin_session.post(f"{BASE}/vendors/create/", data={
    "name": VENDOR_NAME, "username": VENDOR_USER, "password": "vendedor12345",
    "primary_color": "#ff6600", "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/"})
assert resp.status_code == 200
assert VENDOR_NAME in resp.text, "vendedor não apareceu na lista"
print("[OK] Super admin criou o vendedor")

# --- 2. vendedor loga, cria cliente, emite licença ---
vendor_session = requests.Session()
login(vendor_session, VENDOR_USER, "vendedor12345")
csrf, resp = get_csrf(vendor_session, f"{BASE}/")
assert "Criar cliente" in resp.text

resp = vendor_session.post(f"{BASE}/customers/create/", data={
    "name": "Casamento Ana e Joao E2E", "email": "ana@example.com", "phone": "11999999999",
    "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/"})
assert "Casamento Ana e Joao E2E" in resp.text
print("[OK] Vendedor criou o cliente")

match = re.search(r'/customers/(\d+)/', resp.text)
customer_id = match.group(1)

csrf, resp = get_csrf(vendor_session, f"{BASE}/customers/{customer_id}/")
resp = vendor_session.post(f"{BASE}/customers/{customer_id}/licenses/create/", data={
    "plan_type": "month", "amount": "99.90", "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/customers/{customer_id}/"})
match = re.search(r'<code>(CAM3-[A-Z0-9-]+)</code>', resp.text)
assert match, "licença não apareceu na lista"
license_key = match.group(1)
print(f"[OK] Vendedor emitiu a licença {license_key}")

# --- 3. marca a venda como paga ---
sale_match = re.search(r'/sales/(\d+)/mark-paid/', resp.text)
sale_id = sale_match.group(1)
csrf, _ = get_csrf(vendor_session, f"{BASE}/customers/{customer_id}/")
resp = vendor_session.post(f"{BASE}/sales/{sale_id}/mark-paid/", data={
    "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/customers/{customer_id}/"})
assert "Paga" in resp.text
print("[OK] Venda marcada como paga")

# --- 4. Camera360 ativa a licença (API pública) ---
resp = requests.post(f"{BASE}/api/v1/license/activate", json={
    "license_key": license_key, "hardware_id": "HW-E2E-TEST",
})
data = resp.json()
assert data["valid"] is True, data
assert data["plan_type"] == "month"
# vendedor sem restrição + licença sem o campo "modules" no POST -> libera os dois
assert data["modules"] == ["video360", "photobooth"], data
print(f"[OK] /activate: {data}")

# ativar de novo com o MESMO hardware -> ok (idempotente)
resp = requests.post(f"{BASE}/api/v1/license/activate", json={
    "license_key": license_key, "hardware_id": "HW-E2E-TEST",
})
assert resp.json()["valid"] is True
print("[OK] /activate de novo na mesma máquina não quebra")

# ativar com OUTRA máquina -> deve recusar
resp = requests.post(f"{BASE}/api/v1/license/activate", json={
    "license_key": license_key, "hardware_id": "HW-OUTRA-MAQUINA",
})
assert resp.json()["valid"] is False, "deveria ter recusado hardware diferente"
print("[OK] /activate recusa corretamente outra máquina")

# --- 5. Camera360 valida a licença periodicamente ---
resp = requests.post(f"{BASE}/api/v1/license/validate", json={
    "license_key": license_key, "hardware_id": "HW-E2E-TEST",
})
data = resp.json()
assert data["valid"] is True, data
print(f"[OK] /validate: {data}")

# licença inexistente
resp = requests.post(f"{BASE}/api/v1/license/validate", json={
    "license_key": "CAM3-0000-0000-0000", "hardware_id": "HW-E2E-TEST",
})
assert resp.json()["valid"] is False
print("[OK] /validate recusa chave inexistente")

# --- 6. módulos: o vendedor só licencia o que o super admin liberou ---
PB_NAME = f"Revenda Photobooth {SUFFIX}"
PB_USER = f"vend_pb_{SUFFIX}"
csrf, _ = get_csrf(admin_session, f"{BASE}/")
admin_session.post(f"{BASE}/vendors/create/", data={
    "name": PB_NAME, "username": PB_USER, "password": "vendedor12345", "primary_color": "#3366ff",
    "modules_form": "1", "sells_photobooth": "on",  # sells_360 desmarcado
    "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/"})
dash = admin_session.get(f"{BASE}/")
assert PB_NAME in dash.text
pb_vendor_id = re.search(r"/vendors/(\d+)/modules/", dash.text).group(1)  # o mais novo vem primeiro
print(f"[OK] Super admin criou a revenda só Photobooth (id {pb_vendor_id})")

pb_session = requests.Session()
login(pb_session, PB_USER, "vendedor12345")
csrf, resp = get_csrf(pb_session, f"{BASE}/")
resp = pb_session.post(f"{BASE}/customers/create/", data={
    "name": "Cliente Photobooth", "csrfmiddlewaretoken": csrf}, headers={"Referer": f"{BASE}/"})
pb_customer = re.search(r"/customers/(\d+)/", resp.text).group(1)


def issue(session, customer_id, modules):
    csrf, _ = get_csrf(session, f"{BASE}/customers/{customer_id}/")
    resp = session.post(f"{BASE}/customers/{customer_id}/licenses/create/", data={
        "modules": modules, "plan_type": "lifetime", "amount": "10", "csrfmiddlewaretoken": csrf,
    }, headers={"Referer": f"{BASE}/customers/{customer_id}/"})
    return resp


resp = issue(pb_session, pb_customer, "360")
assert "permissão" in resp.text and "CAM3-" not in resp.text, "deveria recusar 360 pra revenda só Photobooth"
print("[OK] Revenda só Photobooth NÃO consegue emitir licença 360")

resp = issue(pb_session, pb_customer, "photobooth")
pb_key = re.search(r"<code>(CAM3-[A-Z0-9-]+)</code>", resp.text).group(1)
data = requests.post(f"{BASE}/api/v1/license/activate", json={
    "license_key": pb_key, "hardware_id": "HW-PB-TEST"}).json()
assert data["valid"] is True and data["modules"] == ["photobooth"], data
data = requests.post(f"{BASE}/api/v1/license/validate", json={
    "license_key": pb_key, "hardware_id": "HW-PB-TEST"}).json()
assert data["valid"] is True and data["modules"] == ["photobooth"], data
print(f"[OK] Licença Photobooth: modules = {data['modules']}")

# super admin troca os módulos da revenda pra só 360: a licença já vendida não muda
csrf, _ = get_csrf(admin_session, f"{BASE}/")
admin_session.post(f"{BASE}/vendors/{pb_vendor_id}/modules/", data={
    "sells_360": "on", "csrfmiddlewaretoken": csrf}, headers={"Referer": f"{BASE}/"})
data = requests.post(f"{BASE}/api/v1/license/validate", json={
    "license_key": pb_key, "hardware_id": "HW-PB-TEST"}).json()
assert data["valid"] is True and data["modules"] == ["photobooth"], "licença já vendida não pode mudar"
resp = issue(pb_session, pb_customer, "photobooth")
assert "permissão" in resp.text, "agora a revenda não pode mais emitir Photobooth"
resp = issue(pb_session, pb_customer, "360")
key_360 = re.findall(r"<code>(CAM3-[A-Z0-9-]+)</code>", resp.text)
assert len(key_360) == 2, "a licença 360 deveria ter sido emitida"
print("[OK] Troca de módulos vale só pras novas emissões; licença já vendida intacta")

print("\nTUDO OK - fluxo completo funcionando de ponta a ponta.")
