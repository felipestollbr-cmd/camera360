import sys
import os
import glob

if sys.platform == "win32":
    # Este projeto usa o Python do MSYS2 UCRT64 (venv --system-site-packages).
    # libgphoto2-6.dll / libgphoto2_port-12.dll vivem em <base_prefix>/bin, mas o
    # Windows não procura mais dependências de .pyd no PATH (Python 3.8+), então
    # precisamos registrar o diretório explicitamente e apontar CAMLIBS/IOLIBS
    # para os plugins de câmera e de porta (USB/PTP), senão gp.Camera().init()
    # falha com "[-4] Error loading a library".
    _ucrt64_root = sys.base_prefix
    _dll_dir = os.path.join(_ucrt64_root, "bin")
    if os.path.isdir(_dll_dir):
        os.add_dll_directory(_dll_dir)

        if not os.environ.get("CAMLIBS"):
            _camlibs = glob.glob(os.path.join(_ucrt64_root, "lib", "libgphoto2", "*"))
            _camlibs = [d for d in _camlibs if os.path.isdir(d)]
            if _camlibs:
                os.environ["CAMLIBS"] = _camlibs[0]

        if not os.environ.get("IOLIBS"):
            _iolibs = glob.glob(os.path.join(_ucrt64_root, "lib", "libgphoto2_port", "*"))
            _iolibs = [d for d in _iolibs if os.path.isdir(d)]
            if _iolibs:
                os.environ["IOLIBS"] = _iolibs[0]

import gphoto2 as gp
import numpy as np
import cv2
import threading
import time

class CameraController:
    def __init__(self):
        self.camera = None
        self.context = None
        self.connected = False
        self.live_view_running = False
        self.current_frame = None
        self.frame_lock = threading.Lock()
        # gp.Camera não é thread-safe: o live view (thread própria) e chamadas
        # vindas da UI (capturar foto, ler modelo, etc.) disputam a mesma
        # conexão USB/PTP. Sem serializar, a câmera responde "[-110] I/O in
        # progress" quando duas chamadas se sobrepõem.
        self.camera_lock = threading.Lock()
        self.live_thread = None
        self.last_error = None
        self.last_connect_error = None
        # None = sem dado ainda (nenhum autofoco tentado, ou câmera sem
        # confirmação disponível, ex.: Nikon); True/False = confirmado pela
        # própria câmera (via "focusinfo") depois da última tentativa de AF.
        self.last_focus_confirmed = None

    def connect(self, retries=1):
        """
        Tenta conectar à câmera via USB. Logo após uma sessão PTP anterior
        fechar, a câmera pode recusar a próxima conexão por um instante
        (ex.: "[-105] Unknown model") - uma nova tentativa curta depois
        costuma resolver, então tentamos de novo antes de desistir.
        """
        for attempt in range(retries + 1):
            try:
                self.context = gp.Context()
                self.camera = gp.Camera()
                with self.camera_lock:
                    self._bind_detected_camera(self.camera, self.context)
                    self.camera.init(self.context)
                    self._drain_events()
                self.connected = True
                self.last_connect_error = None
                return True
            except Exception as e:
                self.last_connect_error = str(e)
                if attempt < retries:
                    print(f"Erro ao conectar (tentativa {attempt + 1}): {e} - tentando de novo...")
                    time.sleep(2)
                else:
                    print(f"Erro ao conectar: {e}")
        return False

    def _bind_detected_camera(self, camera, context):
        """
        `camera.init()` sozinho (sem abilities/porta explícitas) pode falhar
        com "[-105] Unknown model" mesmo quando gp.Camera.autodetect() já
        enxerga a câmera direitinho - um problema conhecido dessa
        combinação de libgphoto2/binding no Windows. Resolvendo o modelo e a
        porta detectados manualmente antes do init() evita essa ambiguidade.
        """
        detected = list(gp.Camera.autodetect(context))
        if not detected:
            return  # deixa o init() padrão tentar/falhar normalmente
        model, port = detected[0]

        abilities_list = gp.CameraAbilitiesList()
        abilities_list.load(context)
        idx = abilities_list.lookup_model(model)
        camera.set_abilities(abilities_list[idx])

        port_info_list = gp.PortInfoList()
        port_info_list.load()
        port_idx = port_info_list.lookup_path(port)
        camera.set_port_info(port_info_list[port_idx])

    def is_usb_claim_conflict(self):
        """
        `[-53] Could not claim the USB device` acontece quando o driver WPD
        (Windows Portable Devices) do próprio Windows já está segurando a
        câmera - comum assim que ela é conectada, já que o Windows a
        reconhece automaticamente como um dispositivo de mídia/foto.
        """
        return bool(self.last_connect_error) and "claim" in self.last_connect_error.lower()

    def _drain_events(self, max_events=10, timeout_ms=300):
        """
        Processa eventos PTP pendentes da câmera (ex.: uma foto tirada numa
        sessão anterior que a câmera acha que ainda não foi confirmada/
        baixada). Sem isso, ela pode ficar "presa" recusando o live view
        com erros como "Pending unretrieved SDRAM image" até ser desligada
        e religada na mão - isso costuma acontecer quando o app fecha de
        forma abrupta (crash, kill do processo) logo após uma captura.
        Chame sempre dentro de um `with self.camera_lock`.
        """
        for _ in range(max_events):
            try:
                evtype, _ = self.camera.wait_for_event(timeout_ms, self.context)
            except Exception:
                break
            if evtype == gp.GP_EVENT_TIMEOUT:
                break

    def disconnect(self):
        """Desconecta a câmera."""
        if self.connected:
            self.stop_live_view()
            with self.camera_lock:
                self.camera.exit(self.context)
            self.connected = False

    def start_live_view(self, fps=10):
        """Inicia o loop de captura do live view em thread separada."""
        if self.live_view_running or not self.connected:
            return
        self.live_view_running = True
        self.live_thread = threading.Thread(target=self._live_view_loop, args=(fps,))
        self.live_thread.daemon = True
        self.live_thread.start()

    def stop_live_view(self):
        """Para o loop do live view."""
        self.live_view_running = False
        if self.live_thread:
            self.live_thread.join(timeout=1)

    def _live_view_loop(self, fps):
        """Loop interno que captura frames continuamente."""
        while self.live_view_running and self.connected:
            try:
                # Captura preview (JPEG)
                with self.camera_lock:
                    preview = self.camera.capture_preview()
                    data = bytes(preview.get_data_and_size())
                # Converte para array numpy (BGR)
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                with self.frame_lock:
                    self.current_frame = img
                self.last_error = None
            except Exception as e:
                error_msg = self._describe_live_view_error(str(e))
                if error_msg != self.last_error:
                    print(f"Erro no live view: {error_msg}")
                    self.last_error = error_msg
                time.sleep(0.5)
            time.sleep(1.0 / fps)

    def _describe_live_view_error(self, raw_error):
        """
        Traduz um erro genérico de capture_preview (ex.: "[-1] Unspecified
        error") checando se a própria câmera está recusando o live view por
        um motivo conhecido (bateria fraca, tampa da lente, etc.) - a Nikon
        expõe isso no widget 'liveviewprohibit', mas o erro do capture_preview
        em si não diz o motivo.
        """
        try:
            with self.camera_lock:
                config = self.camera.get_config(self.context)
                widget = config.get_child_by_name("liveviewprohibit")
                reason = widget.get_value()
            if reason and reason.strip().lower() not in ("none", "0", ""):
                return f"Live view indisponível: {reason}"
        except Exception:
            pass
        return raw_error

    def get_last_error(self):
        """Retorna a última mensagem de erro do live view, se houver."""
        return self.last_error

    def get_frame(self):
        """Retorna o último frame capturado (cópia)."""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def _trigger_autofocus(self):
        """
        Aciona o autofoco da câmera antes de capturar. Sem isso, capture()
        tira a foto na distância de foco que já estava (geralmente
        desfocada) - comandar a captura via PTP não focaliza sozinho no
        modo AF-S. Chame sempre dentro de um `with self.camera_lock`.

        Nikon e Canon expõem mecanismos diferentes pra isso:
        - Canon (EOS) usa "eosremoterelease", simulando o meio-clique do
          disparador ("Press Half AF" aciona o AF, "Release Half" solta) -
          testado e confirmado visualmente contra uma Canon EOS Rebel T7:
          "autofocusdrive" sozinho não focaliza nada nela.
        - Nikon usa o widget "autofocusdrive" direto (valor 1 aciona o
          drive do AF-S).
        """
        try:
            config = self.camera.get_config(self.context)
            eos_release = config.get_child_by_name("eosremoterelease")
        except Exception:
            eos_release = None

        try:
            if eos_release is not None:
                eos_release.set_value("Press Half AF")
                self.camera.set_config(config, self.context)
                time.sleep(1.0)
                self._drain_events()
                config = self.camera.get_config(self.context)
                config.get_child_by_name("eosremoterelease").set_value("Release Half")
                self.camera.set_config(config, self.context)
                self._drain_events()
                # A própria câmera confirma se achou foco: o "focusinfo"
                # (Canon) fica vazio ("{}") até um AF bem-sucedido, e passa
                # a trazer os pontos de foco detectados depois.
                try:
                    focusinfo = self.camera.get_config(self.context).get_child_by_name(
                        "focusinfo").get_value()
                    self.last_focus_confirmed = bool(focusinfo) and focusinfo.strip() != "{}"
                except Exception:
                    self.last_focus_confirmed = None
            else:
                widget = config.get_child_by_name("autofocusdrive")
                widget.set_value(1)
                self.camera.set_config(config, self.context)
                time.sleep(1.0)
                self._drain_events()
                self.last_focus_confirmed = None  # sem confirmação disponível (Nikon)
        except Exception as e:
            print(f"Aviso: não foi possível acionar o autofoco: {e}")
            self.last_focus_confirmed = None

    def get_focus_confirmed(self):
        """Retorna True/False (confirmado pela câmera) ou None (sem dado)."""
        return self.last_focus_confirmed

    def capture_photo(self):
        """Captura uma foto em alta resolução e retorna os dados JPEG."""
        if not self.connected:
            raise Exception("Câmera não conectada")
        try:
            with self.camera_lock:
                self._trigger_autofocus()
                file_path = self.camera.capture(gp.GP_CAPTURE_IMAGE)
                camera_file = self.camera.file_get(
                    file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
                data = bytes(camera_file.get_data_and_size())
                self._drain_events()
            return data  # bytes JPEG
        except Exception as e:
            raise Exception(f"Erro ao capturar foto: {e}")

    def get_camera_model(self):
        """Retorna o modelo da câmera."""
        if self.connected:
            with self.camera_lock:
                abilities = self.camera.get_abilities()
            return abilities.model or "Desconhecida"
        return "Desconhecida"