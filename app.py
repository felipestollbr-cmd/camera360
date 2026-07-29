import io
import time
import threading
import subprocess
import cv2
import numpy as np
from flask import Flask, Response, render_template, request, jsonify
import os

app = Flask(__name__)

# --- Estado global ---
current_frame = None
frame_lock = threading.Lock()
live_view_running = False
live_thread = None
is_recording = False
video_frames = []
video_fps = 10
camera_connected = False

# --- Funções para controlar a câmera via gphoto2 (subprocess) ---

def capture_preview():
    """
    Captura o preview (live view) da câmera usando gphoto2 --capture-preview --stdout.
    Retorna um numpy array (imagem BGR) ou None em caso de erro.
    """
    try:
        result = subprocess.run(
            ['gphoto2', '--capture-preview', '--stdout'],
            capture_output=True,
            check=True,
            timeout=5
        )
        if result.stdout:
            img_array = np.frombuffer(result.stdout, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            return img
        else:
            return None
    except subprocess.CalledProcessError as e:
        print(f"Erro no gphoto2: {e.stderr.decode() if e.stderr else 'desconhecido'}")
        return None
    except Exception as e:
        print(f"Erro ao capturar preview: {e}")
        return None

def capture_photo():
    """
    Captura uma foto em alta resolução e salva no disco.
    Retorna o nome do arquivo ou None em caso de erro.
    """
    try:
        timestamp = int(time.time())
        filename = f"photo_{timestamp}.jpg"
        subprocess.run(
            ['gphoto2', '--capture-image', '--filename', filename],
            check=True,
            timeout=10
        )
        return filename
    except Exception as e:
        print(f"Erro ao capturar foto: {e}")
        return None

def check_camera():
    """Verifica se a câmera está conectada e acessível."""
    try:
        result = subprocess.run(
            ['gphoto2', '--auto-detect'],
            capture_output=True,
            check=True,
            timeout=5
        )
        output = result.stdout.decode()
        # Se houver alguma linha com "usb" ou "ptp", considera conectada
        if 'usb' in output or 'ptp' in output:
            return True
        return False
    except:
        return False

# --- Loop de captura do live view ---

def live_view_loop():
    global current_frame, live_view_running
    while live_view_running:
        img = capture_preview()
        if img is not None:
            with frame_lock:
                current_frame = img
        else:
            # Se falhar, espera um pouco e tenta novamente
            time.sleep(0.2)
        time.sleep(1.0 / video_fps)

def start_live_view():
    global live_view_running, live_thread
    if live_view_running:
        return
    live_view_running = True
    live_thread = threading.Thread(target=live_view_loop)
    live_thread.daemon = True
    live_thread.start()

def stop_live_view():
    global live_view_running
    live_view_running = False
    if live_thread:
        live_thread.join(timeout=1)

# --- Funções de overlay (grade + régua com zero central) ---

def draw_overlay(frame):
    """
    Aplica grade e régua sobre o frame (modifica o frame original).
    Retorna o frame com overlay.
    """
    if frame is None:
        # Cria um frame preto com mensagem
        h, w = 480, 640
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(img, "Sem sinal da câmera", (w//2-100, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    else:
        img = frame.copy()
        h, w = img.shape[:2]

    # --- Grade (regra dos terços) ---
    color = (255, 255, 255)  # branco
    thickness = 1
    # Linhas verticais
    cv2.line(img, (w//3, 0), (w//3, h), color, thickness)
    cv2.line(img, (2*w//3, 0), (2*w//3, h), color, thickness)
    # Linhas horizontais
    cv2.line(img, (0, h//3), (w, h//3), color, thickness)
    cv2.line(img, (0, 2*h//3), (w, 2*h//3), color, thickness)

    # Círculo de foco central
    cx, cy = w//2, h//2
    cv2.circle(img, (cx, cy), 60, color, thickness)
    cv2.circle(img, (cx, cy), 24, color, thickness)
    cv2.line(img, (cx-8, cy), (cx+8, cy), color, thickness)
    cv2.line(img, (cx, cy-8), (cx, cy+8), color, thickness)

    # Retângulos nos pontos de terço
    pts = [(w//3, h//3), (w//3, 2*h//3), (2*w//3, h//3), (2*w//3, 2*h//3)]
    for (px, py) in pts:
        cv2.rectangle(img, (px-12, py-8), (px+12, py+8), color, thickness)
        cv2.rectangle(img, (px-8, py-12), (px+8, py+12), color, thickness)

    # Escala de exposição (simulada)
    scale_values = [-3, -2, -1, 0, 1, 2, 3]
    scale_y = 40
    scale_width = 180
    start_x = w//2 - scale_width//2
    step = scale_width // (len(scale_values)-1)
    cv2.line(img, (start_x, scale_y), (start_x+scale_width, scale_y), color, 1)
    for i, val in enumerate(scale_values):
        x = start_x + i*step
        cv2.line(img, (x, scale_y-5), (x, scale_y+5), color, 1)
        label = f"+{val}" if val > 0 else str(val)
        cv2.putText(img, label, (x, scale_y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    # Indicador central
    cv2.line(img, (w//2, scale_y-10), (w//2-4, scale_y-2), (0, 255, 255), 2)
    cv2.line(img, (w//2, scale_y-10), (w//2+4, scale_y-2), (0, 255, 255), 2)

    # --- Régua com zero central (sem sinais negativos) ---
    ruler_height = max(130, int(h * 0.15))
    ruler_y = h - ruler_height

    # Fundo escuro transparente
    overlay_region = img[ruler_y:h, 0:w].copy()
    img[ruler_y:h, 0:w] = cv2.addWeighted(overlay_region, 0.7, np.zeros_like(overlay_region), 0.3, 0)

    # Linha superior da régua
    cv2.line(img, (0, ruler_y), (w, ruler_y), (200, 200, 200), 1)

    center_x = w // 2
    cm_to_show = 20
    px_per_cm = (w / 2) / cm_to_show
    px_per_mm = px_per_cm / 10

    for side in [-1, 1]:
        for mm in range(cm_to_show * 10 + 1):
            x = int(center_x + (side * mm * px_per_mm))
            if x < 0 or x >= w:
                continue
            is_cm = (mm % 10 == 0)
            is_5mm = (mm % 5 == 0 and not is_cm)
            tick_height = int(ruler_height * 0.20)
            if is_5mm:
                tick_height = int(ruler_height * 0.35)
            if is_cm:
                tick_height = int(ruler_height * 0.55)

            cv2.line(img, (x, ruler_y + ruler_height - 2),
                     (x, ruler_y + ruler_height - tick_height),
                     (255, 255, 255), 2)

            if is_cm and mm > 0:
                cm_val = mm // 10
                label = str(cm_val)  # sem sinal
                font_scale = max(0.5, w / 1500)
                tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)[0][0]
                tx = x - tw // 2
                if tx < 4:
                    tx = 4
                if tx + tw > w - 4:
                    tx = w - tw - 4
                cv2.putText(img, label, (tx, ruler_y + ruler_height - tick_height - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 2)

    # Zero central (destacado)
    cv2.putText(img, "0", (center_x, ruler_y + ruler_height - 8),
                cv2.FONT_HERSHEY_SIMPLEX, max(0.7, w / 1200), (0, 255, 255), 2)

    # Textos adicionais (FONT_HERSHEY_SCRIPT_SIMPLEX para itálico)
    cv2.putText(img, "tilibra", (w - 100, ruler_y + ruler_height - 10),
                cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 0.6, (200, 200, 200), 1)
    cv2.putText(img, "mm", (10, ruler_y + ruler_height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.putText(img, "cm", (10, ruler_y + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Traços laterais
    cv2.line(img, (0, ruler_y + ruler_height - 2), (4, ruler_y + ruler_height - 10),
             (255, 255, 255), 2)
    cv2.line(img, (w-1, ruler_y + ruler_height - 2), (w-5, ruler_y + ruler_height - 10),
             (255, 255, 255), 2)

    return img

# --- Geração do stream MJPEG ---

def generate_frames():
    while True:
        with frame_lock:
            if current_frame is None:
                # Frame preto com mensagem de espera
                black = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(black, "Aguardando câmera...", (200, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                frame_with_overlay = draw_overlay(black)
            else:
                frame_with_overlay = draw_overlay(current_frame.copy())

        if frame_with_overlay is None:
            continue

        # Codifica como JPEG
        ret, jpeg = cv2.imencode('.jpg', frame_with_overlay, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue
        frame_bytes = jpeg.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n\r\n')
        time.sleep(1.0 / video_fps)

# --- Rotas Flask ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture_photo_route():
    """Rota para capturar foto em alta resolução."""
    global camera_connected
    if not camera_connected:
        return jsonify({'error': 'Câmera não conectada'}), 500
    filename = capture_photo()
    if filename:
        return jsonify({'success': True, 'filename': filename})
    else:
        return jsonify({'error': 'Falha ao capturar foto'}), 500

@app.route('/start_recording', methods=['POST'])
def start_recording():
    global is_recording, video_frames
    if is_recording:
        return jsonify({'error': 'Já gravando'}), 400
    is_recording = True
    video_frames = []
    return jsonify({'success': True})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    global is_recording, video_frames
    if not is_recording:
        return jsonify({'error': 'Não está gravando'}), 400
    is_recording = False
    if not video_frames:
        return jsonify({'error': 'Nenhum frame gravado'}), 500
    # Salva vídeo com OpenCV
    timestamp = int(time.time())
    filename = f"video_{timestamp}.mp4"
    h, w = video_frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, video_fps, (w, h))
    for frame in video_frames:
        out.write(frame)
    out.release()
    video_frames = []
    return jsonify({'success': True, 'filename': filename})

@app.route('/record_frame', methods=['POST'])
def record_frame():
    """Rota para acumular frames durante a gravação."""
    global is_recording, video_frames
    if not is_recording:
        return jsonify({'error': 'Não está gravando'}), 400
    with frame_lock:
        if current_frame is not None:
            video_frames.append(current_frame.copy())
            return jsonify({'success': True})
    return jsonify({'error': 'Sem frame'}), 400

@app.route('/status')
def status():
    """Retorna o status da câmera (conectada ou não)."""
    return jsonify({'connected': camera_connected})

# --- Inicialização ---

if __name__ == '__main__':
    # Verifica se a câmera está conectada
    camera_connected = check_camera()
    if camera_connected:
        print("Câmera detectada. Iniciando live view...")
        start_live_view()
    else:
        print("Câmera NÃO detectada. Rodando em modo simulação (sem câmera).")

    # Cria a pasta templates/ se não existir
    if not os.path.exists('templates'):
        os.makedirs('templates')

    # Executa o servidor Flask
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)