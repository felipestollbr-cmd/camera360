"""
Controle de uma GoPro via Wi-Fi (protocolo gpControl, usado pelas HERO5 a
HERO7) - usado como alternativa quando a câmera não é uma DSLR PTP/USB
(gphoto2 não consegue fazer live view/captura numa GoPro, só reconhece o
modelo). Exige que o PC esteja conectado na mesma rede Wi-Fi da câmera
(a GoPro normalmente cria a própria rede, em 10.5.5.9).

Interface compatível com CameraController (connect/get_frame/capture_photo/
etc.) para o main.py poder usar qualquer uma das duas sem mudar o resto do
código.
"""
import glob
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import numpy as np

BASE_URL = "http://10.5.5.9"
MEDIA_BASE_URL = "http://10.5.5.9:8080"
GOPRO_IP = "10.5.5.9"
GOPRO_STREAM_PORT = 8554
# O demuxer de MPEG-TS do FFmpeg já sabe re-sincronizar sozinho procurando
# o sync byte (0x47) nos pacotes - o que faltava não era remover bytes na
# mão, era isso aqui: um "keep-alive" que o cliente precisa mandar pra
# câmera a cada ~2.5s (formato usado pela ferramenta comunitária
# KonradIT/GoProStream, testado e funcional). Sem ele o stream da câmera
# fica instável (nunca fecha um GOP decodificável de verdade).
KEEP_ALIVE_MSG = b"_GPHD_:0:0:2:0.000000\n"
KEEP_ALIVE_PERIOD = 2.5

# cv2.VideoCapture (o wrapper simplificado do OpenCV pro FFmpeg) nunca
# conseguiu ler os parâmetros do codec desse stream específico, mesmo com
# as mesmas opções que funcionam via linha de comando - por isso chamamos o
# FFmpeg de verdade como processo externo, do jeito que a ferramenta de
# referência (KonradIT/gopro-py-api) faz, e lemos o vídeo cru (sem
# container) direto do stdout dele.
#
# Duas pegadinhas resolvidas testando contra a câmera real:
# 1. `udp://@:8554` (qualquer interface) nunca recebe nada no Windows com
#    múltiplos adaptadores de rede ativos (Wi-Fi normal + Wi-Fi da GoPro) -
#    precisa do IP LOCAL específico do PC na rede da GoPro
#    (udp://<meu-ip>:8554), descoberto em tempo real (não dá pra fixar,
#    muda por máquina/lease de DHCP).
# 2. Precisa começar a escutar ANTES de mandar o comando de restart - a
#    câmera manda o SPS/PPS (informação essencial pra decodificar) logo no
#    início da resposta, e se o FFmpeg só liga depois, perde essa janela e
#    nunca fecha um frame decodificável.
FRAME_W, FRAME_H = 1280, 720
FRAME_SIZE = FRAME_W * FRAME_H * 3  # bgr24: 3 bytes por pixel

# Configurações de vídeo (gravação no cartão da própria câmera, não afeta o
# live view/preview que o Camera360 mostra) - valores confirmados direto no
# schema que a própria câmera retorna em GET /gp/gpControl (a doc estática
# do goprowifihack tinha o valor de "2.7K 4:3" errado: é 6, não 3).
VIDEO_RESOLUTIONS = {
    "4K": 1, "4K 4:3": 18, "2.7K": 4, "2.7K 4:3": 6,
    "1440p": 7, "1080p": 9, "960p": 10, "720p": 12,
}
VIDEO_FRAME_RATES = {
    "240fps": 0, "200fps": 13, "120fps": 1, "100fps": 2, "90fps": 3,
    "80fps": 4, "60fps": 5, "50fps": 6, "48fps": 7, "30fps": 8,
    "25fps": 9, "24fps": 10,
}
# Nem toda combinação resolução+fps é aceita pela câmera - confirmado na
# prática direto com a unidade real (não confiar cegamente na doc oficial:
# ela dizia que 4K aceitava até 60fps, mas essa câmera só aceita até
# 30fps mesmo). apply_video_settings() ainda confere com o status real da
# câmera depois de aplicar, como uma segunda camada de segurança.
VALID_FPS_FOR_RESOLUTION = {
    "4K": ["30fps", "25fps", "24fps"],
    "4K 4:3": ["30fps", "25fps", "24fps"],
    "2.7K": ["120fps", "100fps", "60fps", "50fps", "30fps", "25fps", "24fps"],
    "2.7K 4:3": ["60fps", "50fps", "30fps", "25fps", "24fps"],
    "1440p": ["120fps", "100fps", "60fps", "50fps", "30fps", "25fps", "24fps"],
    "1080p": ["240fps", "200fps", "120fps", "100fps", "60fps", "50fps", "30fps", "25fps", "24fps"],
    "960p": ["240fps", "200fps", "120fps", "100fps"],
    "720p": ["240fps", "200fps", "60fps", "50fps"],
}


def _find_ffmpeg():
    override = os.environ.get("CAMERA360_FFMPEG_PATH")
    if override and os.path.isfile(override):
        return override

    # Build "release essentials" da gyan.dev, extraído dentro da própria
    # pasta do projeto (ou ao lado do .exe empacotado) - assim funciona sem
    # precisar configurar PATH/variável de ambiente em outra máquina.
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    for candidate in glob.glob(os.path.join(base_dir, "ffmpeg-*", "bin", "ffmpeg.exe")):
        if os.path.isfile(candidate):
            return candidate

    return shutil.which("ffmpeg")


def _get_local_ip_for_gopro():
    """IP desse PC na mesma rede da GoPro - descoberto perguntando ao SO
    qual interface ele usaria pra alcançar a câmera (sem mandar nada de
    verdade; UDP "connect" só resolve a rota)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((GOPRO_IP, GOPRO_STREAM_PORT))
        return s.getsockname()[0]
    finally:
        s.close()


class GoProWifiController:
    def __init__(self):
        self.connected = False
        self.live_view_running = False
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.live_thread = None
        self.keepalive_thread = None
        self._keepalive_stop = threading.Event()
        self._ffmpeg_proc = None
        self.last_error = None
        self.last_connect_error = None

    def connect(self, retries=0, timeout=2.0):
        """
        Só confirma que dá pra falar com a câmera pela rede (GET rápido no
        status) - não há sessão PTP pra abrir/fechar como no USB.
        """
        try:
            with urllib.request.urlopen(f"{BASE_URL}/gp/gpControl/status", timeout=timeout):
                pass
            self.connected = True
            self.last_connect_error = None
            return True
        except Exception as e:
            self.last_connect_error = str(e)
            self.connected = False
            return False

    def is_usb_claim_conflict(self):
        return False  # não se aplica - conexão é por Wi-Fi, não USB

    def get_focus_confirmed(self):
        return None  # GoPro tem foco fixo, não há confirmação de AF pra checar

    def disconnect(self):
        self.stop_live_view()
        self.connected = False

    def start_live_view(self, fps=10):
        if self.live_view_running or not self.connected:
            return
        self.live_view_running = True
        self._keepalive_stop.clear()
        self.keepalive_thread = threading.Thread(target=self._keepalive_loop)
        self.keepalive_thread.daemon = True
        self.keepalive_thread.start()

        self.live_thread = threading.Thread(target=self._live_view_loop, args=(fps,))
        self.live_thread.daemon = True
        self.live_thread.start()

    def stop_live_view(self):
        self.live_view_running = False
        self._keepalive_stop.set()
        if self._ffmpeg_proc is not None:
            # Derruba o processo pra destravar uma leitura bloqueada no
            # pipe (stdout.read() não tem timeout embutido).
            try:
                self._ffmpeg_proc.terminate()
            except Exception:
                pass
        if self.live_thread:
            self.live_thread.join(timeout=2)
        if self.keepalive_thread:
            self.keepalive_thread.join(timeout=1)

    def _keepalive_loop(self):
        """Sem isso a câmera para de mandar o stream de forma saudável -
        ver o comentário em KEEP_ALIVE_MSG no topo do arquivo."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while not self._keepalive_stop.is_set():
                try:
                    sock.sendto(KEEP_ALIVE_MSG, (GOPRO_IP, GOPRO_STREAM_PORT))
                except Exception:
                    pass
                self._keepalive_stop.wait(KEEP_ALIVE_PERIOD)
        finally:
            sock.close()

    def _live_view_loop(self, fps):
        ffmpeg_path = _find_ffmpeg()
        if not ffmpeg_path:
            self.last_error = (
                "FFmpeg não encontrado - instale (ex.: gyan.dev/ffmpeg/builds) "
                "e garanta que o ffmpeg.exe esteja no PATH")
            self.live_view_running = False
            return

        # A largada é sujeita a corrida (perder o SPS/PPS inicial por uma
        # fração de segundo já visto acontecer na prática) - poucas
        # tentativas costumam resolver antes de reportar erro de verdade.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if not (self.live_view_running and self.connected):
                return
            got_any_frame = self._live_view_attempt(ffmpeg_path, fps)
            if got_any_frame or not (self.live_view_running and self.connected):
                return
            if attempt < max_attempts:
                time.sleep(1.0)

    def _live_view_attempt(self, ffmpeg_path, fps):
        """Uma tentativa de abrir+ler o stream. Retorna True se pelo menos
        um frame de verdade chegou a ser decodificado."""
        local_ip = _get_local_ip_for_gopro()
        # fifo_size maior dá mais folga pro nosso lado ler antes do buffer
        # de recepção do FFmpeg encher; overrun_nonfatal evita que um
        # estouro passageiro (Wi-Fi tem perda de pacote normal) derrube o
        # processo inteiro - sem isso, um "Circular buffer overrun" já
        # visto na prática matava o stream todo.
        stream_url = f"udp://{local_ip}:{GOPRO_STREAM_PORT}?fifo_size=5000000&overrun_nonfatal=1"
        cmd = [
            ffmpeg_path, "-loglevel", "error", "-fflags", "nobuffer",
            "-f", "mpegts", "-probesize", "8192", "-i", stream_url,
            "-vf", f"scale={FRAME_W}:{FRAME_H}",
            "-pix_fmt", "bgr24", "-f", "rawvideo", "-an", "-sn", "pipe:1",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._ffmpeg_proc = proc
        stderr_thread = threading.Thread(target=self._pump_stderr, args=(proc,))
        stderr_thread.daemon = True
        stderr_thread.start()

        # O FFmpeg já precisa estar escutando ANTES do restart: a câmera
        # manda o SPS/PPS (essencial pra decodificar) logo no início da
        # resposta, e escutar depois faz perder essa janela pra sempre.
        time.sleep(0.5)
        try:
            urllib.request.urlopen(
                f"{BASE_URL}/gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart",
                timeout=5)
        except Exception as e:
            self.last_error = f"Não foi possível iniciar o stream: {e}"
            self.live_view_running = False
            proc.terminate()
            self._ffmpeg_proc = None
            return False

        got_any_frame = False
        try:
            while self.live_view_running and self.connected:
                buf = self._read_exact(proc.stdout, FRAME_SIZE)
                if buf is None:
                    self.last_error = "Sem sinal do stream da GoPro"
                    break
                got_any_frame = True
                frame = np.frombuffer(buf, dtype=np.uint8).reshape((FRAME_H, FRAME_W, 3))
                with self.frame_lock:
                    self.current_frame = frame.copy()
                self.last_error = None
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            self._ffmpeg_proc = None
        return got_any_frame

    def _pump_stderr(self, proc):
        """
        Perda de pacote é normal num link Wi-Fi/UDP sem retransmissão - o
        decoder H.264 reclama disso o tempo todo (por macrobloco!) e isso
        sozinho lotaria o console em segundos. Só deixa passar linhas que
        não são esse ruído esperado.
        """
        noisy_markers = ("cabac decode", "error while decoding MB",
                          "concealing", "non-existing PPS", "no frame!",
                          "Decoding error", "Invalid data found")
        for line in iter(proc.stderr.readline, b""):
            text = line.decode(errors="replace").rstrip()
            if not any(marker in text for marker in noisy_markers):
                print(f"[ffmpeg] {text}")

    def _read_exact(self, stream, n):
        """Lê exatamente n bytes do pipe do FFmpeg (um frame bgr24 inteiro),
        ou None se o processo encerrou/o stream parou no meio."""
        buf = bytearray()
        while len(buf) < n:
            if not (self.live_view_running and self.connected):
                return None
            chunk = stream.read(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def get_last_error(self):
        return self.last_error

    def get_frame(self):
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def get_camera_model(self):
        return "GoPro (Wi-Fi)"

    def apply_video_settings(self, resolution_label, fps_label):
        """
        Aplica resolução+fps e confere de verdade com o status da câmera
        depois - ela responde HTTP 200 mesmo quando a combinação não é
        suportada, só que sem trocar o valor de verdade (confirmado na
        prática: a tabela "oficial" dizia que 4K aceitava 60fps, mas essa
        câmera não aceitou). Não confia em tabela estática, confia no que a
        câmera realmente relata depois.

        Retorna (ok, resolução_aplicada, fps_aplicado) - se ok for False,
        os dois últimos mostram o que a câmera manteve/aplicou de verdade.
        """
        import json
        resolution_value = VIDEO_RESOLUTIONS[resolution_label]
        fps_value = VIDEO_FRAME_RATES[fps_label]

        urllib.request.urlopen(f"{BASE_URL}/gp/gpControl/setting/2/{resolution_value}", timeout=5)
        time.sleep(0.3)
        urllib.request.urlopen(f"{BASE_URL}/gp/gpControl/setting/3/{fps_value}", timeout=5)
        time.sleep(0.5)

        with urllib.request.urlopen(f"{BASE_URL}/gp/gpControl/status", timeout=5) as resp:
            status = json.loads(resp.read().decode())
        settings = status.get("settings", {})
        actual_resolution_value = settings.get("2")
        actual_fps_value = settings.get("3")

        def _label_for(mapping, value):
            for key, val in mapping.items():
                if val == value:
                    return key
            return str(value)

        applied_resolution = _label_for(VIDEO_RESOLUTIONS, actual_resolution_value)
        applied_fps = _label_for(VIDEO_FRAME_RATES, actual_fps_value)
        ok = actual_resolution_value == resolution_value and actual_fps_value == fps_value
        return ok, applied_resolution, applied_fps

    def capture_photo(self):
        """
        Troca pro modo Foto, aciona o obturador, espera a câmera gravar no
        cartão e baixa o arquivo mais recente pela API de mídia (a foto em
        si não vem no stream de live view, que é baixa resolução).
        """
        if not self.connected:
            raise Exception("GoPro não conectada")

        def _get(url, timeout=5):
            try:
                return urllib.request.urlopen(url, timeout=timeout)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                raise Exception(f"{url} -> HTTP {e.code}: {body}") from None

        # Trocar de modo pra Foto enquanto o live view Wi-Fi (gpStream) está
        # ativo pode não ser aceito pela câmera (testar: pode precisar
        # parar o stream primeiro) - por isso cada passo tem sua própria
        # mensagem de erro, em vez de um "falhou" genérico.
        _get(f"{BASE_URL}/gp/gpControl/command/mode?p=1")
        _get(f"{BASE_URL}/gp/gpControl/command/sub_mode?mode=1&sub_mode=1")
        _get(f"{BASE_URL}/gp/gpControl/command/shutter?p=1")
        time.sleep(2.0)  # tempo pra processar e gravar no cartão

        with _get(f"{MEDIA_BASE_URL}/gp/gpMediaList", timeout=10) as resp:
            import json
            media = json.loads(resp.read().decode())

        newest = None
        for folder in media.get("media", []):
            for f in folder.get("fs", []):
                if not f["n"].upper().endswith(".JPG"):
                    continue
                if newest is None or int(f.get("cre", 0)) > int(newest[1].get("cre", 0)):
                    newest = (folder["d"], f)
        if newest is None:
            raise Exception("Foto capturada, mas não encontrada no cartão")
        folder_name, file_info = newest
        file_url = f"{MEDIA_BASE_URL}/videos/DCIM/{folder_name}/{file_info['n']}"
        with _get(file_url, timeout=15) as resp:
            return resp.read()
