import re
import requests

BASE = "http://127.0.0.1:8000"


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

resp = admin_session.post(f"{BASE}/vendors/create/", data={
    "name": "Fotos do Fe E2E", "username": "vendedor_e2e", "password": "vendedor12345",
    "primary_color": "#ff6600", "csrfmiddlewaretoken": csrf,
}, headers={"Referer": f"{BASE}/"})
assert resp.status_code == 200
assert "Fotos do Fe E2E" in resp.text, "vendedor não apareceu na lista"
print("[OK] Super admin criou o vendedor")

# --- 2. vendedor loga, cria cliente, emite licença ---
vendor_session = requests.Session()
login(vendor_session, "vendedor_e2e", "vendedor12345")
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

print("\nTUDO OK - fluxo completo funcionando de ponta a ponta.")
