"""
Aciona o braço giratório do totem 360 via porta serial (Arduino/ESP32), com
fallback silencioso pra quando o rig usa controlador próprio (botão físico,
app do fabricante etc.) e o software não deve mandar comando nenhum pro
motor - só disparar a gravação. Nesse caso trigger_spin() vira um no-op.

Config esperada (ver config.json, seção "motor"):
    {"enabled": true, "port": "COM5", "baud_rate": 9600, "start_command": "SPIN\\n"}
"""
import time

try:
    import serial
except ImportError:
    serial = None


class MotorController:
    def __init__(self, config):
        self.enabled = bool(config.get("enabled")) and serial is not None
        self.port = config.get("port", "")
        self.baud_rate = int(config.get("baud_rate", 9600))
        self.start_command = config.get("start_command", "SPIN\n")
        self._conn = None
        self.last_error = None

    def connect(self):
        """
        Abre a porta serial se o motor estiver habilitado na config. Falha
        de conexão não derruba o totem - só desativa o acionamento do motor
        pra essa sessão (a gravação continua funcionando normalmente,
        como se o rig fosse de controlador próprio).
        """
        if not self.enabled:
            return False
        if serial is None:
            self.last_error = "pacote 'pyserial' não instalado"
            self.enabled = False
            return False
        try:
            self._conn = serial.Serial(self.port, self.baud_rate, timeout=2)
            time.sleep(2)  # boards Arduino/ESP32 reiniciam ao abrir a porta serial
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = str(e)
            self.enabled = False
            self._conn = None
            return False

    def is_available(self):
        return self.enabled and self._conn is not None

    def trigger_spin(self):
        """Manda o comando de início de giro. Não faz nada se o motor não
        estiver habilitado/conectado (rig com controlador próprio)."""
        if not self.is_available():
            return
        try:
            payload = self.start_command
            if isinstance(payload, str):
                payload = payload.encode("ascii")
            self._conn.write(payload)
        except Exception as e:
            self.last_error = str(e)

    def disconnect(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
