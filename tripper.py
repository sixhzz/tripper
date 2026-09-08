#!/usr/bin/env python3
"""Tripper - navegacao turn-by-turn estilo Royal Enfield, em terminal.

Modo GPS em tempo real: o celular transmite a propria posicao via Wi-Fi
(NMEA over TCP) e o PC mostra no terminal a seta de direcao + distancia
ate a proxima manobra, igual ao display do Tripper POD.

Rota: OSRM publico (sem chave). Geocoding: Nominatim (OSM).

Como usar:
    1. No Android, instale um app que transmita GPS por TCP, ex.
       "Share GPS" / "GPS over TCP" (envia NMEA pela porta).
       Configure o IP do PC e a porta 10110.
    2. Rode o servidor no PC:
           py tripper.py --serve 0.0.0.0 10110 "destino"
    3. O visor atualiza sozinho conforme o GPS se move.

Tambem aceita coordenadas manuais para teste:
    py tripper.py --demo "destino"          (posicao simulada movendo-se)
    py tripper.py "origem" "destino"        (modo original, sem GPS)
"""
import json
import math
import socket
import sys
import time
import threading
import urllib.parse
import urllib.request

OSRM = "https://router.project-osrm.org/route/v1/driving/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

CUR = {"lat": None, "lon": None, "ts": 0.0}


# --- rede / GPS ------------------------------------------------------------

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


def route(a, b):
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
    """Extrai lat/lon de sentencas NMEA GGA ou RMC."""
    if not line.startswith("$"):
        return None
    fields = line.split(",")
    if fields[0] in ("$GPGGA", "$GNGGA") and len(fields) > 6 and fields[2]:
        lat = _nmea_coord(fields[2], fields[3])
        lon = _nmea_coord(fields[4], fields[5])
        return lat, lon
    if fields[0] in ("$GPRMC", "$GNRMC") and len(fields) > 6 and fields[3]:
        lat = _nmea_coord(fields[3], fields[4])
        lon = _nmea_coord(fields[5], fields[6])
        return lat, lon
    return None


def _nmea_coord(v, hemi):
    if not v:
        return None
    deg = float(v[:2]) if hemi in "NS" else float(v[:3])
    if hemi in "NS":
        deg = float(v[:2])
        minutes = float(v[2:])
    else:
        deg = float(v[:3])
        minutes = float(v[3:])
    val = deg + minutes / 60.0
    if hemi in "SW":
        val = -val
    return val


def gps_server(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(1)
    print(f"Aguardando GPS do celular em {host}:{port} ...")
    conn, addr = sock.accept()
    print(f"GPS conectado: {addr[0]}")
    buf = b""
    with conn:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    txt = line.decode("ascii", "ignore").strip()
                except Exception:
                    continue
                pos = parse_nmea(txt)
                if pos:
                    CUR["lat"], CUR["lon"], CUR["ts"] = pos[0], pos[1], time.time()


# --- display ---------------------------------------------------------------

ARROWS = {
    "left": "  <-  ", "slight left": "  ~<- ", "sharp left": " <<-  ",
    "right": "  ->  ", "slight right": " ->~  ", "sharp right": "  ->> ",
    "straight": "  ^   ", "uturn": " ...U ", "arrive": "  (•) ", "": "  ^   ",
}


def arrow(t):
    return ARROWS.get(t, "  >   ")


def fmt_dist(m):
    if m >= 1000:
        return f"{m/1000:.1f} km"
    return f"{int(m)} m"


def render(turn, dist, name, remaining, total):
    line = "=" * 18
    pct = int((total - remaining) / total * 100) if total else 100
    print("\033[2J\033[H", end="")
    print(line)
    print("      TRIPPER      ")
    print(line)
    print(f"   {arrow(turn)}")
    print()
    print(f"      {fmt_dist(dist):>8}")
    print()
    if turn == "arrive":
        print("   Destino!")
    elif name:
        print(f"   {name[:16]}")
    print()
    print(line)
    print(f" chegar  {fmt_dist(remaining):>7}")
    print(f" total   {fmt_dist(total):>7}")
    print(f"         [{pct:>3d}%]")
    print(line)


# --- modos -----------------------------------------------------------------

def run_live(dest_name):
    dest = geocode(dest_name)
    print(f"Destino: {dest_name}")
    threading.Thread(target=gps_server, args=(HOST, PORT), daemon=True).start()

    steps = None
    while True:
        if CUR["lat"] is None:
            print("\r[1] Aguardando GPS... conecte o app do celular.", end="")
            time.sleep(1)
            continue
        now = CUR["ts"]
        if time.time() - now > 10:
            print("\r[Atencao] GPS desatualizado (>10s). Aguardando sinal...", end="")
            time.sleep(1)
            continue
        here = (CUR["lat"], CUR["lon"])
        steps = route(here, dest)
        dist0 = steps[0][1] if steps else 0
        if dist0 < 30 and len(steps) == 1:
            render("arrive", 0, "", 0, 30)
            time.sleep(1)
            continue
        turn, d, name = steps[0]
        remaining = sum(s[1] for s in steps)
        total = remaining + dist0
        render(turn, d, name, remaining, total)
        time.sleep(1)


def run_demo(dest_name):
    dest = geocode(dest_name)
    here = list(dest)
    here[0] -= 0.05
    while True:
        steps = route(tuple(here), dest)
        if not steps:
            break
        turn, d, name = steps[0]
        remaining = sum(s[1] for s in steps)
        total = remaining + d
        render(turn, d, name, remaining, total)
        if d < 1:
            print("\nChegou!")
            break
        here[0] += 0.002
        time.sleep(1)


def run_static(a, b):
    ca, cb = geocode(a), geocode(b)
    steps = route(ca, cb)
    idx = 0
    while idx < len(steps):
        turn, d, name = steps[idx]
        remaining = sum(s[1] for s in steps[idx:])
        total = sum(s[1] for s in steps)
        render(turn, d, name, remaining, total)
        time.sleep(2)
        idx += 1
    print("\nViagem concluida. Boa estrada!")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--serve":
        global HOST, PORT
        HOST = args[1] if len(args) > 1 else "0.0.0.0"
        PORT = int(args[2]) if len(args) > 2 else 10110
        dest = args[3] if len(args) > 3 else sys.exit("Informe o destino.")
        run_live(dest)
    elif args and args[0] == "--demo":
        dest = args[1] if len(args) > 1 else sys.exit("Informe o destino.")
        run_demo(dest)
    elif len(args) >= 2:
        run_static(args[0], args[1])
    else:
        sys.exit(__doc__)


HOST = "0.0.0.0"
PORT = 10110

if __name__ == "__main__":
    main()