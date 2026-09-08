#!/usr/bin/env python3
"""Tripper GUI - navegacao turn-by-turn estilo Royal Enfield com janela grafica.

Mostra em tempo real: status da conexao com o celular, coordenadas GPS
recebidas, seta de manobra + distancia ate a proxima manobra, e um log
de eventos. Rota via OSRM (sem chave), geocoding via Nominatim.

Uso:
    py tripper_gui.py
"""
import json
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import tkinter as tk

OSRM = "https://router.project-osrm.org/route/v1/driving/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

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


class App:
    def __init__(self, root):
        self.root = root
        root.title("Tripper - Royal Enfield Style")
        root.configure(bg="#111")
        self.dest = None
        self.cur = None
        self.stop = threading.Event()

        f = dict(fg="#ccc", bg="#111", font=("Segoe UI", 10))
        self.status = tk.Label(root, text="Ocioso", bg="#111", fg="#999",
                               font=("Segoe UI", 12, "bold"))
        self.status.pack(pady=(10, 4))

        self.arrow = tk.Label(root, text="⬆", bg="#111", fg="#0e7",
                              font=("Segoe UI", 72, "bold"))
        self.arrow.pack(pady=4)

        self.dist = tk.Label(root, text="--", bg="#111", fg="#fff",
                             font=("Segoe UI", 30, "bold"))
        self.dist.pack()

        self.street = tk.Label(root, text="", bg="#111", fg="#aaa",
                               font=("Segoe UI", 12))
        self.street.pack()

        info = tk.Frame(root, bg="#111")
        info.pack(pady=6)
        self.pos = tk.Label(info, text="GPS: --", **f)
        self.pos.pack(side="left", padx=8)
        self.eta = tk.Label(info, text="Faltam: --", **f)
        self.eta.pack(side="left", padx=8)

        bar = tk.Frame(root, bg="#111")
        bar.pack(fill="x", padx=10, pady=6)
        tk.Label(bar, text="Destino:", **f).pack(side="left")
        self.entry = tk.Entry(bar, bg="#222", fg="#eee", insertbackground="#eee",
                              width=30)
        self.entry.pack(side="left", padx=6, fill="x", expand=True)
        self.go = tk.Button(bar, text="Iniciar", command=self.start,
                            bg="#0e7", fg="#000", activebackground="#0f8")
        self.go.pack(side="left")

        conn = tk.Frame(root, bg="#111")
        conn.pack(fill="x", padx=10, pady=6)
        tk.Label(conn, text="Tipo:", **f).pack(side="left")
        self.mode = tk.StringVar(value="cliente")
        tk.Radiobutton(conn, text="PC conecta no celular", variable=self.mode,
                       value="cliente", bg="#111", fg="#ccc", selectcolor="#222",
                       activebackground="#111",
                       command=self._mode).pack(side="left", padx=4)
        tk.Radiobutton(conn, text="Celular conecta no PC", variable=self.mode,
                       value="servidor", bg="#111", fg="#ccc", selectcolor="#222",
                       activebackground="#111",
                       command=self._mode).pack(side="left", padx=4)

        self.addr = tk.Frame(root, bg="#111")
        self.addr.pack(fill="x", padx=10, pady=4)
        tk.Label(self.addr, text="IP + porta (celular)", **f).pack(side="left")
        self.hostentry = tk.Entry(self.addr, bg="#222", fg="#eee",
                                  insertbackground="#eee", width=22)
        self.hostentry.insert(0, "192.168.1.18:8080")
        self.hostentry.pack(side="left", padx=6)

        self.log = tk.Text(root, height=10, bg="#000", fg="#6c6",
                           font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=8)

        self._mode()

    def _mode(self):
        for w in self.addr.winfo_children():
            w.pack_forget()
        self.addr.pack()
        if self.mode.get() == "cliente":
            tk.Label(self.addr, text="IP + porta do celular",
                     **dict(fg="#ccc", bg="#111")).pack(side="left")
            e = tk.Entry(self.addr, bg="#222", fg="#eee",
                         insertbackground="#eee", width=22)
            e.insert(0, "192.168.1.18:8080")
            e.pack(side="left", padx=6)
            self.hostentry = e
        else:
            tk.Label(self.addr, text="Porta p/ celular conectar",
                     **dict(fg="#ccc", bg="#111")).pack(side="left")
            e = tk.Entry(self.addr, bg="#222", fg="#eee",
                         insertbackground="#eee", width=10)
            e.insert(0, "8080")
            e.pack(side="left", padx=6)
            self.hostentry = e

    def logmsg(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, txt, color="#0e7"):
        self.status.configure(text=txt, fg=color)

    def start(self):
        dest = self.entry.get().strip()
        if not dest:
            self.logmsg("Digite um destino.")
            return
        self.logmsg(f"Geocodificando destino: {dest}")
        try:
            self.dest = geocode(dest)
        except Exception as e:
            self.logmsg(f"Erro geocoding: {e}")
            return
        self.logmsg(f"Destino resolvido: {self.dest[0]:.5f},{self.dest[1]:.5f}")
        self.stop.clear()
        self._spawn_gps()
        threading.Thread(target=self._loop, daemon=True).start()

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
        else:
            port = int(self.hostentry.get() or 8080)
            t = threading.Thread(target=self._server, args=(port,), daemon=True)
        t.start()

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
            time.sleep(1)
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
        self.arrow.configure(text=ARROWS.get(turn, "➡"))
        self.dist.configure(text=fmt_dist(d))
        self.street.configure(text=name[:30] if name else "")
        self.pos.configure(text=f"GPS: {self.cur[0]:.5f},{self.cur[1]:.5f}")
        self.eta.configure(text=f"Faltam: {fmt_dist(remaining)}")
        if turn == "arrive":
            self.set_status("Destino alcançado!", "#0e7")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()