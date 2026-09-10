"""Rutas, registro y carpetas conocidas.

En Windows —el sistema de producción de esta repo— la configuración vive en
«%APPDATA%\\FISAT\\CifrarPDF» (itinerante con el perfil) y el registro en
«%LOCALAPPDATA%\\FISAT\\CifrarPDF» (local, no tiene sentido sincronizarlo).

Las ramas POSIX existen solo para poder desarrollar y pasar los tests en Linux.
En los puestos Debian la herramienta que manda es el bash «fisat-cifrar-pdf»,
no este paquete.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

ES_WINDOWS = os.name == "nt"

ORG = "FISAT"
APP = "CifrarPDF"

# Servicio con el que se guardan las contraseñas en el Administrador de
# credenciales. Se conserva el nombre del backend Debian para que las dos
# implementaciones sean reconocibles como la misma herramienta.
SERVICIO = "fisat-cifrar-pdf"

MAX_LINEAS_LOG = 2000


def _de_entorno(nombre: str) -> Path | None:
    """Permite a los tests (y a una instalación portable) redirigir una ruta."""
    valor = os.environ.get(nombre)
    return Path(valor) if valor else None


def config_dir() -> Path:
    ruta = _de_entorno("CIFRARPDF_CONFIG_DIR")
    if ruta is None:
        if ES_WINDOWS:
            base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
            ruta = Path(base) / ORG / APP
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            ruta = Path(base) / "fisat" / "cifrar-pdf-win"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def carpetas_dir() -> Path:
    ruta = config_dir() / "carpetas.d"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def datos_dir() -> Path:
    ruta = _de_entorno("CIFRARPDF_DATOS_DIR")
    if ruta is None:
        if ES_WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            ruta = Path(base) / ORG / APP
        else:
            base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
            ruta = Path(base) / "fisat" / "cifrar-pdf-win"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def log_file() -> Path:
    return datos_dir() / "cifrar-pdf.log"


# --- Escritorio -------------------------------------------------------------
# Nunca «%USERPROFILE%\Escritorio»: el Escritorio puede estar redirigido
# (OneDrive, Drive para escritorio, perfiles de red) y hay que respetar dónde
# esté de verdad. La API de carpeta conocida es la única fuente fiable.

_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _escritorio_api() -> Path | None:
    """SHGetKnownFolderPath(FOLDERID_Desktop). None si el sistema no contesta."""
    import ctypes

    from . import _win

    try:
        guid = _win.GUID()
        _win.ole32.CLSIDFromString(_FOLDERID_DESKTOP, ctypes.byref(guid))
        puntero = ctypes.c_wchar_p()
        _win.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                          ctypes.byref(puntero))
        try:
            return Path(puntero.value) if puntero.value else None
        finally:
            _win.ole32.CoTaskMemFree(puntero)
    except OSError:
        # Los prototipos declaran HRESULT, así que un fallo llega como OSError.
        return None


def _escritorio_registro() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        clave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        with clave:
            valor, _ = winreg.QueryValueEx(clave, "Desktop")
        return Path(os.path.expandvars(valor))
    except OSError:
        return None


def escritorio() -> Path:
    """Carpeta del Escritorio del usuario actual, redirigida o no."""
    ruta = _de_entorno("CIFRARPDF_ESCRITORIO")
    if ruta is None and ES_WINDOWS:
        ruta = _escritorio_api() or _escritorio_registro()
        if ruta is None:
            ruta = Path.home() / "Desktop"
    if ruta is None:
        # POSIX (desarrollo): igual criterio que el bash de Debian.
        candidata = Path.home() / "Escritorio"
        ruta = candidata if candidata.is_dir() else Path.home() / "Desktop"
    return ruta


# --- Invocarse a sí mismo ---------------------------------------------------
# El programa se reparte como DOS ejecutables que comparten todo el código:
#
#   CifrarPDF.exe      sin consola  → la ventana de gestión y el vigilante
#                                     (icono en el área de notificación)
#   CifrarPDF-cli.exe  con consola  → los subcomandos --gui-* y --parar
#
# El motivo no es cosmético: en un ejecutable sin consola, PyQt6/PyInstaller
# dejan «sys.stdout» a None y todo lo que se imprima se descarta en silencio.
# Como la ventana habla con el backend LEYENDO SU SALIDA ESTÁNDAR, si el backend
# fuese el ejecutable sin consola no leería nada nunca — y encima sin error, que
# es la peor forma de fallar. El de consola se lanza siempre con
# CREATE_NO_WINDOW, así que no asoma ninguna ventana negra.

NOMBRE_GUI = "CifrarPDF.exe"
NOMBRE_CLI = "CifrarPDF-cli.exe"


def _congelado() -> bool:
    return bool(getattr(sys, "frozen", False))


def _dir_exe() -> Path:
    return Path(sys.executable).resolve().parent


def _raiz_desarrollo() -> Path:
    return Path(__file__).resolve().parent.parent


def comando_backend(*args: str) -> list[str]:
    """Cómo invocar los subcomandos --gui-* (hace falta salida estándar)."""
    if _congelado():
        return [str(_dir_exe() / NOMBRE_CLI), *args]
    return [sys.executable, "-m", "cifrarpdf", *args]


def comando_vigilante() -> list[str]:
    """Cómo arrancar el vigilante (sin consola: vive en la bandeja)."""
    if _congelado():
        return [str(_dir_exe() / NOMBRE_GUI), "--vigilante"]
    return [sys.executable, "-m", "cifrarpdf", "--vigilante"]


def comando_gui() -> list[str]:
    """Cómo abrir la ventana de gestión."""
    if _congelado():
        return [str(_dir_exe() / NOMBRE_GUI)]
    return [sys.executable, str(_raiz_desarrollo() / "gui.py")]


def linea_comando_vigilante() -> str:
    """El comando del vigilante como cadena citada (para el registro de Windows)."""
    partes = comando_vigilante()
    if ES_WINDOWS:
        return subprocess.list2cmdline(partes)
    return " ".join(partes)


# --- Registro ---------------------------------------------------------------

def log(mensaje: str) -> None:
    try:
        sello = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file(), "a", encoding="utf-8") as fh:
            fh.write(f"{sello} - {mensaje}\n")
    except OSError:
        pass


def rotar_log() -> None:
    """Recorta el registro a las últimas MAX_LINEAS_LOG líneas."""
    fichero = log_file()
    try:
        if not fichero.exists():
            return
        with open(fichero, encoding="utf-8", errors="replace") as fh:
            lineas = fh.readlines()
        if len(lineas) <= MAX_LINEAS_LOG:
            return
        temporal = fichero.with_suffix(".log.tmp")
        with open(temporal, "w", encoding="utf-8") as fh:
            fh.writelines(lineas[-MAX_LINEAS_LOG:])
        os.replace(temporal, fichero)
    except OSError:
        pass
