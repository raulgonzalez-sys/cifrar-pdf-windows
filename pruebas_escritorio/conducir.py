"""TEMPORAL: conductor de la prueba de escritorio en Windows (no mergear)."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

SALIDA = Path(os.environ.get("SALIDA", "salida"))
SALIDA.mkdir(parents=True, exist_ok=True)
RESUMEN: list[str] = []


def anotar(texto: str) -> None:
    print(texto, flush=True)
    RESUMEN.append(texto)
    (SALIDA / "resumen.txt").write_text("\n".join(RESUMEN) + "\n", encoding="utf-8")


def captura(nombre: str):
    from PIL import ImageGrab, ImageStat
    imagen = ImageGrab.grab(all_screens=True)
    ruta = SALIDA / f"{nombre}.png"
    imagen.save(ruta)
    media = ImageStat.Stat(imagen.convert("L")).mean[0]
    extremos = imagen.convert("L").getextrema()
    anotar(f"captura {ruta.name}: {imagen.size}, luminancia media {media:.1f}, extremos {extremos}")
    return imagen


def sonda() -> int:
    anotar("== SONDA ==")
    anotar(f"usuario: {os.environ.get('USERNAME')}  sesion: "
           f"{os.environ.get('SESSIONNAME')}")
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    anotar(f"SessionId del proceso: {sid.value}")
    anotar("console session: " + str(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()))
    for orden in (["query", "session"], ["tasklist", "/v", "/fi", "imagename eq explorer.exe"],
                  ["tasklist", "/v", "/fi", "imagename eq Runner.Worker.exe"],
                  ["whoami", "/groups"]):
        try:
            r = subprocess.run(orden, capture_output=True, text=True, timeout=30)
            anotar(f"$ {' '.join(orden)}\n{r.stdout}{r.stderr}")
        except Exception as error:  # noqa: BLE001
            anotar(f"$ {' '.join(orden)} -> {error}")
    user32 = ctypes.windll.user32
    anotar(f"pantalla: {user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}")
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    anotar(f"Shell_TrayWnd: {hwnd}")
    captura("sonda_1_inicial")

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QLabel, QSystemTrayIcon
    app = QApplication(sys.argv)
    anotar(f"Qt plataforma: {app.platformName()}")
    anotar(f"isSystemTrayAvailable: {QSystemTrayIcon.isSystemTrayAvailable()}")
    anotar(f"supportsMessages: {QSystemTrayIcon.supportsMessages()}")
    etiqueta = QLabel("SONDA CIFRAR PDF — ventana Qt normal")
    etiqueta.setStyleSheet("font-size: 28px; background: yellow; padding: 30px")
    etiqueta.setWindowTitle("Sonda Cifrar PDF")
    etiqueta.move(100, 100)
    etiqueta.show()
    from PyQt6.QtGui import QIcon, QPixmap
    pix = QPixmap(32, 32)
    pix.fill()
    bandeja = QSystemTrayIcon(QIcon(pix))
    bandeja.show()
    resultado = {}

    def tomar() -> None:
        bandeja.showMessage("Sonda", "Globo de prueba de la sonda", QSystemTrayIcon.MessageIcon.Information, 8000)
        QTimer.singleShot(2500, lambda: (captura("sonda_2_ventana_qt"), app.quit()))

    QTimer.singleShot(1500, tomar)
    app.exec()
    hwnd = user32.FindWindowW(None, "Sonda Cifrar PDF")
    anotar(f"FindWindow sonda: {hwnd}; visible {user32.IsWindowVisible(hwnd) if hwnd else None}")
    try:
        from pywinauto import Desktop
        ventanas = [w.window_text() for w in Desktop(backend="uia").windows()]
        anotar(f"pywinauto uia ventanas de nivel superior: {ventanas[:30]}")
    except Exception as error:  # noqa: BLE001
        anotar(f"pywinauto: {error!r}")
    del resultado
    return 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "sonda"
    sys.exit({"sonda": sonda}[modo]())
