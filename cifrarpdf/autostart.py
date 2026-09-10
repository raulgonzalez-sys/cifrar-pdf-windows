"""Autoarranque del vigilante en la sesión del usuario.

En Windows va por «HKCU\\...\\CurrentVersion\\Run»: es **por usuario**, así que
se conserva tal cual el modelo de los puestos Debian — el programa se instala
para todo el equipo, pero lo activa cada trabajador/a al crear su primera
carpeta, y quien no lo use no tiene nada corriendo.
"""

from __future__ import annotations

from pathlib import Path

from . import rutas

VALOR = "FISAT-CifrarPDF"
CLAVE = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _desktop_posix() -> Path:
    base = rutas.config_dir().parent / "autostart"
    return base / "fisat-cifrar-pdf-win.desktop"


def activar() -> bool:
    if not rutas.ES_WINDOWS:
        fichero = _desktop_posix()
        fichero.parent.mkdir(parents=True, exist_ok=True)
        fichero.write_text(
            "[Desktop Entry]\nType=Application\nName=Cifrar PDF (vigilante)\n"
            f"Exec={rutas.linea_comando_vigilante()}\n"
            "Terminal=false\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        return True
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CLAVE, 0,
                                winreg.KEY_SET_VALUE) as clave:
            winreg.SetValueEx(clave, VALOR, 0, winreg.REG_SZ,
                              rutas.linea_comando_vigilante())
        return True
    except OSError as error:
        rutas.log(f"ERROR al activar el autoarranque: {error}")
        return False


def desactivar() -> None:
    if not rutas.ES_WINDOWS:
        try:
            _desktop_posix().unlink()
        except OSError:
            pass
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE, 0,
                            winreg.KEY_SET_VALUE) as clave:
            winreg.DeleteValue(clave, VALOR)
    except OSError:
        pass


def activo() -> bool:
    if not rutas.ES_WINDOWS:
        return _desktop_posix().exists()
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE) as clave:
            valor, _ = winreg.QueryValueEx(clave, VALOR)
        return bool(valor)
    except OSError:
        return False
