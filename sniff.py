#!/usr/bin/env python3
"""Captura crua do que o app do celular envia na porta TCP."""
import socket
import time

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 8081))
sock.listen(1)
print("Aguardando conexao na 8081 ... (configure o app para esta porta)")
conn, addr = sock.accept()
print(f"conectado: {addr}")
conn.settimeout(0.5)
try:
    while True:
        try:
            data = conn.recv(2048)
        except socket.timeout:
            continue
        if not data:
            break
        print(repr(data.decode("utf-8", "replace")))
except KeyboardInterrupt:
    print("fim")