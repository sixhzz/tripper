#!/usr/bin/env python3
"""Tripper Android - captura GPS do celular e envia para o PC via TCP.

O PC roda o servidor (tripper_gui.py na porta 8080) que recebe NMEA
e mostra a navegacao. Este app Kivy roda no Android, le a localizacao
via plyer e transmite sentencas NMEA GGA/RMC por TCP.

Tambem envia o destino digitado para o PC via um prefixo de mensagem.
"""
import socket
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

try:
    from plyer import gps
    HAS_GPS = True
except Exception:
    HAS_GPS = False

try:
    from jnius import autoclass  # noqa: F401
    IS_ANDROID = True
except Exception:
    IS_ANDROID = False


def nmea_gprmc(lat, lon, ts):
    lat_hemi = "N" if lat >= 0 else "S"
    lon_hemi = "E" if lon >= 0 else "W"
    alat, alon = abs(lat), abs(lon)
    lat_deg = int(alat)
    lat_min = (alat - lat_deg) * 60
    lon_deg = int(alon)
    lon_min = (alon - lon_deg) * 60
    t = time.strftime("%H%M%S", time.gmtime(ts))
    return (f"$GPRMC,{t},A,{lat_deg:02d}{lat_min:07.4f},{lat_hemi},"
            f"{lon_deg:03d}{lon_min:07.4f},{lon_hemi},0.0,0.0,"
            f"{time.strftime('%d%m%y')},,,A*00\r\n")


class Net:
    def __init__(self, app):
        self.app = app
        self.sock = None
        self.running = False

    def send(self, msg):
        if self.sock is None:
            return False
        try:
            self.sock.sendall(msg.encode())
            return True
        except OSError:
            return False

    def connect(self, host, port):
        try:
            self.sock = socket.create_connection((host, port), timeout=5)
            return True
        except OSError:
            self.sock = None
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None


class Main(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=10, spacing=8, **kw)
        self.net = Net(self)
        self.cur = (None, None)
        self.ts = time.time()

        self.add_widget(Label(text="Tripper Android", font_size=24, bold=True,
                              size_hint_y=None, height=44))

        self.st = Label(text="Desconectado", size_hint_y=None, height=28)
        self.add_widget(self.st)

        self.host = TextInput(text="192.168.1.5", hint_text="IP do PC",
                              multiline=False, size_hint_y=None, height=44)
        self.add_widget(self.host)
        self.port = TextInput(text="8080", hint_text="Porta", multiline=False,
                              size_hint_y=None, height=44)
        self.add_widget(self.port)

        self.dest = TextInput(text="", hint_text="Destino (endereco)",
                              multiline=False, size_hint_y=None, height=44)
        self.add_widget(self.dest)

        self.btn_conn = Button(text="Conectar", size_hint_y=None, height=50)
        self.btn_conn.bind(on_press=self.toggle_conn)
        self.add_widget(self.btn_conn)

        self.btn_dest = Button(text="Enviar destino", size_hint_y=None, height=50)
        self.btn_dest.bind(on_press=self.send_dest)
        self.add_widget(self.btn_dest)

        self.gps_label = Label(text="GPS: --", size_hint_y=None, height=28)
        self.add_widget(self.gps_label)

        sv = ScrollView(size_hint=(1, 1))
        self.log = Label(text="", size_hint_y=None, valign="top", text_size=(None, None))
        self.log.bind(texture_size=lambda *a: self._resize_log())
        sv.add_widget(self.log)
        self.add_widget(sv)

        self._lines = []
        self._start_gps()

    def _resize_log(self):
        self.log.height = self.log.texture_size[1]
        self.log.text_size = (self.log.width, None)

    def _start_gps(self):
        if HAS_GPS:
            try:
                gps.configure(on_location=self._on_gps, on_status=self._on_status)
                gps.start(minTime=1000, minDistance=1)
                self.logline("GPS iniciado")
            except Exception as e:
                self.logline(f"Erro GPS: {e}")
        else:
            self.logline("plyer ausente; sem GPS")

    def _on_gps(self, **kw):
        self.cur = (kw.get("lat"), kw.get("lon"))
        self.ts = time.time()
        self.gps_label.text = f"GPS: {self.cur[0]:.5f},{self.cur[1]:.5f}"
        if self.net.sock:
            self.net.send(nmea_gprmc(self.cur[0], self.cur[1], self.ts))

    def _on_status(self, status, **kw):
        self.logline(f"GPS status: {status}")

    def toggle_conn(self, *a):
        if self.net.sock:
            self.net.close()
            self.btn_conn.text = "Conectar"
            self.st.text = "Desconectado"
        else:
            host = self.host.text.strip()
            port = int(self.port.text.strip() or 8080)
            if self.net.connect(host, port):
                self.btn_conn.text = "Desconectar"
                self.st.text = f"Conectado em {host}:{port}"
                self.logline(f"Conectado em {host}:{port}")
                self._send_cur()
            else:
                self.logline(f"Falha ao conectar {host}:{port}")

    def _send_cur(self):
        if self.net.sock and self.cur[0] is not None:
            self.net.send(nmea_gprmc(self.cur[0], self.cur[1], self.ts))

    def send_dest(self, *a):
        d = self.dest.text.strip()
        if not d:
            self.logline("Digite um destino.")
            return
        ok = self.net.send(f"__DEST__{d}\r\n")
        self.logline(("Destino enviado: " if ok else "Falha ao enviar ") + d)

    def logline(self, m):
        self._lines.append(time.strftime("[%H:%M:%S] ") + m)
        if len(self._lines) > 60:
            self._lines = self._lines[-60:]
        self.log.text = "\n".join(self._lines)


class TripperApp(App):
    def build(self):
        return Main()


if __name__ == "__main__":
    TripperApp().run()