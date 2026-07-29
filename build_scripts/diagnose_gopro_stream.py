"""
Diagnostico rapido do stream Wi-Fi da GoPro - roda so quando o PC estiver
conectado na rede Wi-Fi da propria GoPro. Isola em qual camada esta
falhando: rede (nenhum pacote chega) vs. decodificacao (OpenCV/FFmpeg).
"""
import os
import socket
import time
import urllib.request

BASE_URL = "http://10.5.5.9"


def check_http():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/gp/gpControl/status", timeout=3) as resp:
            print(f"[OK] HTTP status respondeu: {resp.status}")
            return True
    except Exception as e:
        print(f"[FALHA] HTTP status: {e}")
        return False


def start_stream():
    url = f"{BASE_URL}/gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            print(f"[OK] Comando de start do stream respondeu: {resp.status}")
            return True
    except Exception as e:
        print(f"[FALHA] Comando de start do stream: {e}")
        return False


def check_raw_udp_packets(port=8554, seconds=6):
    """Escuta bruto na porta UDP, sem OpenCV/FFmpeg - só pra ver se ALGUM
    byte chega (isola problema de rede/firewall de problema de decodificação)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        sock.bind(("0.0.0.0", port))
    except Exception as e:
        print(f"[FALHA] Não conseguiu abrir a porta UDP {port}: {e}")
        return False
    print(f"Escutando bruto em UDP:{port} por {seconds}s...")
    total_bytes = 0
    packet_count = 0
    first_packet = None
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(65536)
            total_bytes += len(data)
            packet_count += 1
            if packet_count == 1:
                print(f"[OK] Primeiro pacote recebido de {addr}, {len(data)} bytes")
                first_packet = data
        except socket.timeout:
            continue
    sock.close()
    print(f"Total: {packet_count} pacotes, {total_bytes} bytes em {seconds}s")

    if first_packet:
        hexdump = first_packet[:32].hex(" ")
        print(f"Primeiros 32 bytes (hex): {hexdump}")
        if first_packet[0] == 0x47 and len(first_packet) >= 188 and first_packet[188] == 0x47:
            print("=> Cara de MPEG-TS (sync byte 0x47 a cada 188 bytes)")
        elif first_packet[:3] == b"\x00\x00\x01" or first_packet[:4] == b"\x00\x00\x00\x01":
            print("=> Cara de H.264 Annex-B cru (start code no início)")
        elif (first_packet[0] & 0xC0) == 0x80:
            print("=> Cara de cabeçalho RTP (version=2 no primeiro byte)")
        else:
            print("=> Formato não reconhecido pelos padrões óbvios (ver hexdump acima)")

    return packet_count > 0


def check_full_pipeline(seconds=45):
    """
    Testa o caminho real usado pelo Camera360: GoProWifiController de verdade
    (relay que tira o cabeçalho de 12 bytes + cv2.VideoCapture no TS
    limpo), não uma reimplementação paralela - assim o teste reflete
    exatamente o que o app vai fazer.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gopro_controller import GoProWifiController

    cam = GoProWifiController()
    if not cam.connect():
        print(f"[FALHA] connect(): {cam.last_connect_error}")
        return False
    cam.start_live_view(fps=10)

    ok_count = 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        frame = cam.get_frame()
        if frame is not None:
            ok_count += 1
            if ok_count == 1:
                print(f"[OK] Primeiro frame decodificado: {frame.shape}")
        time.sleep(0.2)
    print(f"último erro reportado: {cam.get_last_error()}")
    cam.disconnect()
    print(f"Total de frames obtidos em {seconds}s: {ok_count}")
    return ok_count > 0


if __name__ == "__main__":
    print("=== 1. HTTP (status) ===")
    if not check_http():
        print("\nA GoPro não está respondendo por HTTP - confirme que o PC está"
              " conectado na rede Wi-Fi da própria câmera antes de continuar.")
        raise SystemExit(1)

    print("\n=== 2. Comando de start do stream ===")
    start_stream()
    time.sleep(1.5)

    print("\n=== 3. Pacotes UDP brutos (sem OpenCV) ===")
    got_raw = check_raw_udp_packets()

    print("\n=== 4. Pipeline completo (relay + OpenCV, igual ao Camera360) ===")
    got_frames = check_full_pipeline()

    print("\n=== Resultado ===")
    if not got_raw:
        print("Nenhum pacote UDP chegou de forma alguma - problema de rede/firewall"
              " (ou a câmera não está realmente streamando).")
    elif not got_frames:
        print("Pacotes chegam, mas o pipeline completo não decodifica frame nenhum.")
    else:
        print("Funcionou! Pacotes chegam E o Camera360 decodifica frames de verdade.")
