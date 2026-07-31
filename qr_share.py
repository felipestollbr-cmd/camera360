"""
Compartilhamento do vídeo final via QR code: serve os vídeos processados por
um servidor HTTP local (mesma técnica já validada no extinto webex_embed.py,
com http.server puro) e gera o PNG do QR apontando pra lá. `ShareBackend` é
uma interface pequena pra poder plugar um backend de nuvem depois (upload +
link público) sem mexer no fluxo do totem em main.py - por enquanto só o
LocalShareBackend existe.
"""
import os
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import qrcode


def get_local_ip():
    """IP desse PC na rede local (do evento) - mesma técnica de "fake
    connect" UDP usada em gopro_controller._get_local_ip_for_gopro, mas sem
    mirar a rede da GoPro: aqui queremos a rede que o celular do convidado
    também alcança."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class ShareBackend:
    """Interface: publica um arquivo e devolve a URL pra colocar no QR."""

    def publish(self, file_path):
        raise NotImplementedError

    def stop(self):
        pass


class LocalShareBackend(ShareBackend):
    def __init__(self, serve_dir, port=8090):
        self.serve_dir = os.path.abspath(serve_dir)
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        if self._server is not None:
            return
        os.makedirs(self.serve_dir, exist_ok=True)
        serve_dir = self.serve_dir

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=serve_dir, **kwargs)

            def log_message(self, format, *args):
                pass  # silencioso - não precisa poluir o console do totem

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def publish(self, file_path):
        self.start()
        filename = os.path.basename(file_path)
        target = os.path.join(self.serve_dir, filename)
        if os.path.abspath(file_path) != os.path.abspath(target):
            with open(file_path, "rb") as src, open(target, "wb") as dst:
                dst.write(src.read())
        return f"http://{get_local_ip()}:{self.port}/{filename}"

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def generate_qr_image(url):
    """Retorna uma PIL.Image com o QR code pra url (o main.py só precisa
    envolver num ImageTk.PhotoImage pra mostrar no Tkinter, igual já faz
    com os frames de vídeo)."""
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")
