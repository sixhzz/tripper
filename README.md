# Tripper — navegação estilo Royal Enfield (PC + Android)

## Visão geral
- **PC** roda `tripper_gui.py` (visor gráfico estilo painel de moto).
- **Android** roda o APK: lê o GPS do celular e envia NMEA por TCP para o PC,
  e também permite escolher o destino e enviá-lo.

## Como usar

### 1. PC (servidor)
```powershell
ipconfig   # descubra o IP do PC, ex: 192.168.1.5
py tripper_gui.py
```
No modo padrão ("Celular conecta no PC"), o PC escuta na porta **8080**.

### 2. Android (app)
- Instale o APK gerado (veja "Build do APK" abaixo).
- Abra o app e digite o **IP do PC** e porta **8080**.
- Toque **Conectar**.
- Digite o **destino** e toque **Enviar destino**.
- O PC recebe o destino e começa a navegação usando o GPS do celular.

## Build do APK
O APK é compilado com Kivy + Buildozer.

### Via GitHub Actions (sem Linux local)
1. Suba esta pasta para um repositório GitHub.
2. Acesse **Actions → Build Tripper APK → Run workflow**.
3. Baixe o artefato `tripper-apk` (o `.apk`).

### Local (Linux)
```bash
cd android
pip install buildozer
buildozer android debug
# apk em android/bin/
```

## Arquivos
- `tripper_gui.py` — visor no PC (Tkinter).
- `tripper.py` — versão de terminal (OSRM + Nominatim).
- `android/main.py` — app Kivy/Android.
- `android/buildozer.spec` — config de build.
- `.github/workflows/build.yml` — build automático.