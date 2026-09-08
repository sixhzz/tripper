#!/usr/bin/env python3
"""Simulador de celular para teste: envia NMEA por TCP como um app de GPS."""
import socket
import time
import sys

HOST = "127.0.0.1"
PORT = 10110


def nmea_gprmc(lat, lon):
    lat_hemi = "N" if lat >= 0 else "S"
    lon_hemi = "E" if lon >= 0 else "W"
    alat = abs(lat)
    alon = abs(lon)
    lat_deg = int(alat)
    lat_min = (alat - lat_deg) * 60
    lon_deg = int(alon)
    lon_min = (alon - lon_deg) * 60
    return (f"$GPRMC,120000,A,{lat_deg:02d}{lat_min:07.4f},{lat_hemi},"
            f"{lon_deg:03d}{lon_min:07.4f},{lon_hemi},0.0,0.0,010123,,,A*00\r\n")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    lat = -23.60
    lon = -46.65
    print("enviando GPS simulado...")
    try:
        while True:
            sock.sendall(nmea_gprmc(lat, lon).encode())
            lat += 0.0005
            lon += 0.0003
            time.sleep(1)
    except KeyboardInterrupt:
        sock.close()
        print("\nfim")


if __name__ == "__main__":
    main()