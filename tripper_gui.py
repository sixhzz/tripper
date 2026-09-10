#!/usr/bin/env python3
"""Tripper GUI - navegacao turn-by-turn estilo Royal Enfield com janela grafica.

Mostra em tempo real: status da conexao com o celular, coordenadas GPS
recebidas, seta de manobra + distancia ate a proxima manobra, e um log
de eventos. Rota via OSRM (sem chave), geocoding via Nominatim.

Uso:
    py tripper_gui.py
"""
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import tkinter as tk

OSRM = "https://router.project-osrm.org/route/v1/driving/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".tripper_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(a, b):
    key = f"{a[0]:.5f},{a[1]:.5f}_{b[0]:.5f},{b[1]:.5f}".replace(".", "").replace("-", "n")
    return os.path.join(CACHE_DIR, f"route_{key}.json")

ARROWS = {
    "left": "⬅", "slight left": "↖", "sharp left": "⤴",
    "right": "➡", "slight right": "↗", "sharp right": "⤵",
    "straight": "⬆", "uturn": "↩", "arrive": "🏁", "": "⬆",
}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tripper/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def geocode(query):
    q = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    data = _get(f"{NOMINATIM}?{q}")
    if not data:
        raise SystemExit(f"Nao encontrei: {query}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def route_calc(a, b):
    cache_file = _cache_path(a, b)
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data["steps"]
        except Exception:
            pass

    pts = f"{a[1]},{a[0]};{b[1]},{b[0]}"
    data = _get(OSRM + pts + "?overview=false&steps=true")
    if data.get("code") != "Ok":
        raise SystemExit(f"Rota indisponivel: {data.get('code')}")
    steps = []
    for leg in data["routes"][0]["legs"]:
        for s in leg["steps"]:
            if s.get("maneuver", {}).get("type") == "arrive":
                steps.append(("arrive", 0.0, s.get("name", "")))
                break
            steps.append((
                s.get("maneuver", {}).get("modifier", ""),
                s.get("distance", 0.0),
                s.get("name", "") or "continue",
            ))
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"steps": steps, "origin": a, "dest": b}, f)
    except Exception:
        pass
    return steps


def parse_nmea(line):
    if not line.startswith("$"):
        return None
    f = line.split(",")
    if f[0] in ("$GPGGA", "$GNGGA") and len(f) > 6 and f[2]:
        return _coord(f[2], f[3]), _coord(f[4], f[5])
    if f[0] in ("$GPRMC", "$GNRMC") and len(f) > 6 and f[3]:
        return _coord(f[3], f[4]), _coord(f[5], f[6])
    return None


def _coord(v, hemi):
    if not v:
        return None
    d = float(v[:3]) if hemi in "EW" else float(v[:2])
    m = float(v[3:]) if hemi in "EW" else float(v[2:])
    val = d + m / 60.0
    return -val if hemi in "SW" else val


def fmt_dist(m):
    if m >= 1000:
        return f"{m/1000:.1f} km"
    return f"{int(m)} m"


CANVAS_SIZE = 340
CANVAS_CENTER = CANVAS_SIZE // 2


class App:
    BG = "#0a0e14"
    CARD = "#151b24"
    ACCENT = "#00e5ff"
    TEXT = "#e6edf3"
    MUTED = "#6e7681"
    SUCCESS = "#00ff88"

    def __init__(self, root):
        self.root = root
        root.title("TRIPPER")
        root.configure(bg=self.BG)
        root.geometry("420x640")
        root.resizable(False, False)

        self.dest = None
        self.cur = None
        self.stop = threading.Event()

        self._build_gauge()
        self._build_info()
        self._build_controls()
        self._build_log()

        self._mode()

    def _build_gauge(self):
        frame = tk.Frame(self.root, bg=self.BG)
        frame.pack(pady=24)

        self.canvas = tk.Canvas(frame, width=CANVAS_SIZE, height=CANVAS_SIZE,
                                bg=self.BG, highlightthickness=0)
        self.canvas.pack()

        c = CANVAS_CENTER
        r1 = c - 12
        r2 = c - 26

        self.canvas.create_oval(c-r1, c-r1, c+r1, c+r1,
                                outline="#1a222e", width=6)
        self.canvas.create_oval(c-r2, c-r2, c+r2, c+r2,
                                outline=self.ACCENT, width=2)

        self.tick_els = []
        for a in range(0, 360, 30):
            rad = math.radians(a)
            x0 = c + (r1-8) * math.sin(rad)
            y0 = c - (r1-8) * math.cos(rad)
            x1 = c + (r1-18) * math.sin(rad)
            y1 = c - (r1-18) * math.cos(rad)
            self.tick_els.append(self.canvas.create_line(x0, y0, x1, y1,
                                                         fill="#222", width=3))

        self.arrow_text = self.canvas.create_text(c, c, text="⬆",
                                                  fill=self.ACCENT,
                                                  font=("Segoe UI", 64, "bold"))
        self.dist_text = self.canvas.create_text(c, c + 72, text="--",
                                                 fill="#ffffff",
                                                 font=("Segoe UI", 28, "bold"))
        self.unit_text = self.canvas.create_text(c, c + 110, text="",
                                                 fill="#555",
                                                 font=("Segoe UI", 12))

    def _build_info(self):
        frame = tk.Frame(self.root, bg=self.BG)
        frame.pack(fill="x", padx=24, pady=4)
        self.street = tk.Label(frame, text="Digite um destino para começar",
                               bg=self.BG, fg=self.TEXT,
                               font=("Segoe UI", 13),
                               anchor="w")
        self.street.pack(fill="x")

        row = tk.Frame(self.root, bg=self.BG)
        row.pack(fill="x", padx=24, pady=2)
        self.status = tk.Label(row, text="Pronto", bg=self.BG,
                               fg=self.MUTED, font=("Segoe UI", 10))
        self.status.pack(side="left")

        self.pos = tk.Label(row, text="GPS: --", bg=self.BG,
                            fg=self.MUTED, font=("Segoe UI", 10))
        self.pos.pack(side="right")

    def _build_controls(self):
        frame = tk.Frame(self.root, bg=self.BG)
        frame.pack(fill="x", padx=24, pady=14)

        self.entry = tk.Entry(frame, bg=self.CARD, fg=self.TEXT,
                              insertbackground=self.TEXT,
                              font=("Segoe UI", 12), relief="flat",
                              bd=8)
        self.entry.pack(fill="x", pady=6)
        self.entry.insert(0, "Digite o destino")
        self.entry.bind("<FocusIn>", lambda _: self.entry.delete(0, "end")
                        if self.entry.get() == "Digite o destino" else None)

        self.go = tk.Button(frame, text="INICIAR ROTA", command=self.start,
                            bg=self.ACCENT, fg="#000",
                            font=("Segoe UI", 11, "bold"),
                            relief="flat", pady=8, cursor="hand2",
                            activebackground="#33ddff")
        self.go.pack(fill="x", pady=4)

        mode_row = tk.Frame(self.root, bg=self.BG)
        mode_row.pack(pady=4)

        self.mode = tk.StringVar(value="pc")
        for m, label in [("pc", "GPS deste PC"),
                         ("cliente", "Celular → PC"),
                         ("servidor", "PC → Celular")]:
            tk.Radiobutton(mode_row, text=label, variable=self.mode, value=m,
                           bg=self.BG, fg=self.MUTED, selectcolor=self.BG,
                           activebackground=self.BG,
                           activeforeground=self.ACCENT,
                           font=("Segoe UI", 9),
                           command=self._mode).pack(side="left", padx=8)

        self.addr = tk.Frame(self.root, bg=self.BG)
        self.addr.pack(pady=6)

    def _build_log(self):
        frame = tk.Frame(self.root, bg=self.BG)
        frame.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        self.log = tk.Text(frame, height=5, bg=self.CARD, fg="#1a5560",
                           font=("Consolas", 8), state="disabled",
                           relief="flat", bd=6)
        self.log.pack(fill="both", expand=True)

    def _mode(self):
        for w in self.addr.winfo_children():
            w.destroy()
        mode = self.mode.get()
        if mode == "cliente":
            tk.Label(self.addr, text="IP + porta do celular:",
                     bg=self.BG, fg=self.MUTED,
                     font=("Segoe UI", 9)).pack(side="left")
            e = tk.Entry(self.addr, bg=self.CARD, fg=self.TEXT,
                         insertbackground=self.TEXT, width=22,
                         font=("Segoe UI", 10), relief="flat", bd=4)
            e.insert(0, "192.168.1.18:8080")
            e.pack(side="left", padx=6)
            self.hostentry = e
        elif mode == "servidor":
            tk.Label(self.addr, text="Porta p/ celular conectar:",
                     bg=self.BG, fg=self.MUTED,
                     font=("Segoe UI", 9)).pack(side="left")
            e = tk.Entry(self.addr, bg=self.CARD, fg=self.TEXT,
                         insertbackground=self.TEXT, width=8,
                         font=("Segoe UI", 10), relief="flat", bd=4)
            e.insert(0, "8080")
            e.pack(side="left", padx=6)
            self.hostentry = e

    def logmsg(self, msg):
        def _log():
            self.log.configure(state="normal")
            self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _log)

    def set_status(self, txt, color="#0e7"):
        self.root.after(0, lambda: self.status.configure(text=txt, fg=color))

    def start(self):
        dest_query = self.entry.get().strip()
        if not dest_query:
            self.logmsg("Digite um destino.")
            return
        self.stop.clear()
        self.go.configure(state="disabled")
        threading.Thread(target=self._start_async, args=(dest_query,), daemon=True).start()

    def _start_async(self, query):
        self.logmsg(f"Geocodificando destino: {query}")
        try:
            self.dest = geocode(query)
            self.logmsg(f"Destino resolvido: {self.dest[0]:.5f},{self.dest[1]:.5f}")
            self._spawn_gps()
            threading.Thread(target=self._loop, daemon=True).start()
        except Exception as e:
            self.logmsg(f"Erro geocoding: {e}")
        finally:
            self.root.after(0, lambda: self.go.configure(state="normal"))

    def _spawn_gps(self):
        if self.mode.get() == "cliente":
            hostport = self.hostentry.get().strip()
            host, _, port = hostport.partition(":")
            try:
                port = int(port or 8080)
            except ValueError:
                self.logmsg("Porta invalida.")
                return
            t = threading.Thread(target=self._client, args=(host, port),
                                 daemon=True)
        elif self.mode.get() == "servidor":
            port = int(self.hostentry.get() or 8080)
            t = threading.Thread(target=self._server, args=(port,), daemon=True)
        else:
            t = threading.Thread(target=self._pc_gps, daemon=True)
        t.start()

    def _pc_gps(self):
        import subprocess
        self.logmsg("Iniciando GPS nativo do Windows...")
        self.set_status("Aguardando GPS do PC...", "#e90")
        ps_script = (
            "Add-Type -AssemblyName System.Device; "
            "$w = New-Object System.Device.Location.GeoCoordinateWatcher('High'); "
            "$w.TryStart($false, [TimeSpan]::FromMilliseconds(100)); "
            "while ($true) { "
            "  if ($w.Status -eq 'Ready') { "
            "    $loc = $w.Position.Location; "
            "    if (-not $loc.IsUnknown -and $loc.HorizontalAccuracy -gt 0) { "
            "      [PSCustomObject]@{Lat=$loc.Latitude; Lon=$loc.Longitude; Acc=$loc.HorizontalAccuracy} | ConvertTo-Json -Compress "
            "    } "
            "  } "
            "  Start-Sleep -Seconds 2; "
            "}"
        )
        try:
            self.pc_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            while not self.stop.is_set():
                line = self.pc_proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if "Lat" in data and "Lon" in data:
                            lat, lon = float(data["Lat"]), float(data["Lon"])
                            acc = data.get("Acc", 0)
                            self.cur = (lat, lon)
                            if acc:
                                self.set_status(f"GPS PC (±{acc:.0f}m)", "#0e7")
                                self.logmsg(f"GPS PC: {lat:.5f},{lon:.5f} ±{acc:.0f}m")
                            else:
                                self.set_status("GPS do PC conectado", "#0e7")
                                self.logmsg(f"GPS PC: {lat:.5f}, {lon:.5f}")
                    except Exception:
                        pass
        except Exception as e:
            self.logmsg(f"Erro GPS PC: {e}")
        finally:
            try:
                if hasattr(self, 'pc_proc') and self.pc_proc:
                    self.pc_proc.terminate()
            except Exception:
                pass

    def _client(self, host, port):
        self.logmsg(f"Tentando conectar no celular {host}:{port} ...")
        self.set_status("Conectando no celular...", "#e90")
        while not self.stop.is_set():
            try:
                s = socket.create_connection((host, port), timeout=5)
                break
            except OSError as e:
                self.logmsg(f"Falha ao conectar: {e}. Retentando...")
                time.sleep(3)
        if self.stop.is_set():
            return
        self.logmsg("Conectado ao celular!")
        self.set_status("GPS conectado", "#0e7")
        buf = b""
        while not self.stop.is_set():
            try:
                s.settimeout(1)
                data = s.recv(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._feed(line)
        self.logmsg("Conexao com celular encerrada.")
        self.set_status("Desconectado", "#999")

    def _server(self, port):
        self.logmsg(f"Esperando celular conectar na porta {port} ...")
        self.set_status("Aguardando GPS...", "#e90")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            s.listen(1)
            conn, addr = s.accept()
        except OSError as e:
            self.logmsg(f"Erro bind: {e}")
            return
        self.logmsg(f"Conexao recebida de {addr[0]}")
        self.set_status("GPS conectado", "#0e7")
        buf = b""
        with conn:
            while not self.stop.is_set():
                try:
                    data = conn.recv(2048)
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._feed(line)

    def _feed(self, raw):
        try:
            txt = raw.decode("utf-8", "replace").strip()
        except Exception:
            return
        if not txt:
            return
        if txt.startswith("__DEST__"):
            dest = txt[len("__DEST__"):]
            self.logmsg(f"Destino recebido do celular: {dest}")
            self.root.after(0, lambda: self.entry.delete(0, "end") or
                            self.entry.insert(0, dest))
            self.root.after(0, self.start)
            return
        pos = parse_nmea(txt)
        if pos:
            self.cur = pos
            self.logmsg(f"GPS: {pos[0]:.5f},{pos[1]:.5f}")
        else:
            self.logmsg(f"recebido: {txt[:60]}")

    def _loop(self):
        while not self.stop.is_set():
            time.sleep(5)
            if self.dest is None or self.cur is None:
                self.set_status("Aguardando GPS...", "#e90")
                continue
            try:
                steps = route_calc(self.cur, self.dest)
            except Exception as e:
                self.logmsg(f"Erro rota: {e}")
                continue
            if not steps:
                continue
            turn, d, name = steps[0]
            remaining = sum(s[1] for s in steps[1:])
            self.root.after(0, self._update_view, turn, d, name, remaining)

    def _update_view(self, turn, d, name, remaining):
        arrow_sym = ARROWS.get(turn, "➡")
        self.canvas.itemconfig(self.arrow_text, text=arrow_sym)

        dist_val = fmt_dist(d)
        if " " in dist_val:
            val, unit = dist_val.split(" ", 1)
            self.canvas.itemconfig(self.dist_text, text=val)
            self.canvas.itemconfig(self.unit_text, text=unit.upper())
        else:
            self.canvas.itemconfig(self.dist_text, text=dist_val)
            self.canvas.itemconfig(self.unit_text, text="")

        self.street.configure(text=name[:35] if name else "Siga em frente")
        self.status.configure(text=f"Faltam {fmt_dist(remaining)}", fg=self.SUCCESS)
        if self.cur:
            self.pos.configure(text=f"GPS: {self.cur[0]:.5f}, {self.cur[1]:.5f}")

        if turn == "arrive":
            self.set_status("DESTINO ALCANÇADO!", self.SUCCESS)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()