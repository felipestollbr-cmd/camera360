"""
Webex embutido dentro do Camera360: serve uma pagina local (widget de reuniao
da Cisco) numa janela pywebview/WebView2, alimentando o video da reuniao
com os frames reais da camera do Camera360 via canvas.captureStream() - sem
precisar de driver de camera virtual.

IMPORTANTE: a pagina precisa ser servida por um servidor HTTP de verdade
(nao pelo carregamento de arquivo local do proprio pywebview) - servida
como file:// ou via o servidor interno do pywebview, o bundle React do
widget nao registra corretamente suas globais dentro do WebView2.
"""
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2

_WIDGET_CSS_URL = "https://cdn.jsdelivr.net/gh/WXSD-Sales/embeddable-meetings-widget/docs/webex-widgets.css"
_WIDGET_JS_URL = "https://cdn.jsdelivr.net/gh/WXSD-Sales/embeddable-meetings-widget/docs/bundle.js"

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Camera360 - Webex</title>
  <link href="{css_url}" rel="stylesheet"/>
  <script>
    // Canvas alimentado com os frames reais do Camera360 (via /frame.jpg) -
    // vira uma "camera" que o widget do Webex usa como se fosse de verdade.
    const canvas = document.createElement('canvas');
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#888';
    ctx.font = '24px sans-serif';
    ctx.fillText('Aguardando video do Camera360...', 40, 360);

    const img = new Image();
    let pending = false;
    function refreshFrame() {{
      if (pending) return;
      pending = true;
      const nextImg = new Image();
      nextImg.onload = () => {{
        if (nextImg.width && nextImg.height) {{
          canvas.width = nextImg.width;
          canvas.height = nextImg.height;
          ctx.drawImage(nextImg, 0, 0);
        }}
        pending = false;
      }};
      nextImg.onerror = () => {{ pending = false; }};
      nextImg.src = '/frame.jpg?t=' + Date.now();
    }}
    setInterval(refreshFrame, 100);

    const fakeStream = canvas.captureStream(10);
    navigator.mediaDevices.getUserMedia = async function() {{ return fakeStream; }};
    navigator.mediaDevices.enumerateDevices = async function() {{
      return [{{ deviceId: 'camera360-cam', kind: 'videoinput', label: 'Camera360', groupId: 'camera360' }}];
    }};
  </script>
  <script src="{js_url}"></script>
</head>
<body style="margin:0;background:#101114">
  <div id="embeddable-meetings-widget"></div>
  <script>
    window.addEventListener('load', () => {{
      webexMeetingsWidget({{
        accessToken: "{access_token}",
        meetingDestination: "{meeting_link}",
        theme: "dark",
        width: "{width}px",
        height: "{height}px",
        layout: "Grid",
        inMeetingControls: ['mute-audio', 'mute-video', 'share-screen', 'leave-meeting'],
        interstitialControls: ['mute-audio', 'mute-video', 'join-meeting'],
      }});
    }});
  </script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/frame.jpg":
            self._serve_frame()
        else:
            self._serve_widget_page()

    def _serve_widget_page(self):
        html = self.server.html_page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _serve_frame(self):
        frame = self.server.get_frame_callback()
        if frame is None:
            self.send_response(204)
            self.end_headers()
            return
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            self.send_response(500)
            self.end_headers()
            return
        data = buf.tobytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # silencia o log de acesso HTTP no console


class WebexEmbedServer:
    """Servidor HTTP local que serve a pagina do widget + os frames da camera."""

    def __init__(self, get_frame_callback, port=0):
        self.get_frame_callback = get_frame_callback
        self.httpd = HTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.get_frame_callback = get_frame_callback
        self.httpd.html_page = ""
        self.thread = None

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/widget.html"

    def set_meeting(self, access_token, meeting_link, width=900, height=600):
        self.httpd.html_page = _HTML_TEMPLATE.format(
            css_url=_WIDGET_CSS_URL,
            js_url=_WIDGET_JS_URL,
            access_token=access_token,
            meeting_link=meeting_link,
            width=width,
            height=height,
        )

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
