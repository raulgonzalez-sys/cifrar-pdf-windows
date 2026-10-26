"""Control del vigilante: instancia única, parada limpia y arranque.

El backend Debian usa un fichero con el PID y lo mata por PID. En Windows eso
es frágil (los PID se reutilizan y se puede acabar matando a otro programa), así
que aquí se usan los mecanismos del sistema:

- un **mútex con nombre** para que solo haya un vigilante por usuario, y para
  poder preguntar «¿está en marcha?» sin leer ficheros;
- un **evento con nombre** para pedirle que se pare, de modo que termine él
  solo, ordenadamente, en vez de recibir un kill.

La rama POSIX (fichero PID + SIGTERM) existe solo para desarrollo y tests.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from . import autostart, config, rutas

NOMBRE_MUTEX = r"Local\FISAT-CifrarPDF-Vigilante"
NOMBRE_EVENTO = r"Local\FISAT-CifrarPDF-Parar"

# El evento de parada del vigilante de ESTE proceso (ver Vigilancia).
_evento = None


class YaEnMarcha(Exception):
    """Ya hay un vigilante de este usuario funcionando."""


def _pid_file() -> Path:
    return rutas.datos_dir() / "vigilante.pid"


# --- Instancia única --------------------------------------------------------

class Vigilancia:
    """Contexto que marca «yo soy el vigilante». Lanza YaEnMarcha si hay otro."""

    def __init__(self) -> None:
        self._mutex = None
        self._evento = None

    def __enter__(self) -> Vigilancia:
        global _evento
        if rutas.ES_WINDOWS:
            import ctypes

            from . import _win

            mutex = _win.kernel32.CreateMutexW(None, False, NOMBRE_MUTEX)
            # El código de error hay que leerlo INMEDIATAMENTE después de la
            # llamada: cualquier otra llamada por medio lo pisa.
            error = ctypes.get_last_error()
            if not mutex:
                raise OSError(f"No se pudo crear el mútex del vigilante (error {error}).")
            if error == _win.ERROR_ALREADY_EXISTS:
                _win.kernel32.CloseHandle(mutex)
                raise YaEnMarcha
            # Un objeto con nombre de Win32 muere al cerrarse su último handle:
            # el vigilante sujeta el evento de parada toda su vida para que
            # «pedir_parada» lo encuentre. Se pone a cero por si lo creó otro.
            evento = _win.kernel32.CreateEventW(None, True, False, NOMBRE_EVENTO)
            if not evento:
                error = ctypes.get_last_error()
                _win.kernel32.CloseHandle(mutex)
                raise OSError(f"No se pudo crear el evento de parada (error {error}).")
            _win.kernel32.ResetEvent(evento)
            self._mutex = mutex
            self._evento = evento
            _evento = evento
        else:
            if activo():
                raise YaEnMarcha
            _pid_file().write_text(str(os.getpid()), encoding="utf-8")
        return self

    def __exit__(self, *_excepcion: object) -> None:
        global _evento
        if rutas.ES_WINDOWS:
            from . import _win
            if self._evento:
                _win.kernel32.CloseHandle(self._evento)
                self._evento = None
                _evento = None
            if self._mutex:
                _win.kernel32.CloseHandle(self._mutex)
                self._mutex = None
        else:
            try:
                _pid_file().unlink()
            except OSError:
                pass


def activo() -> bool:
    """¿Hay un vigilante en marcha para este usuario?"""
    if rutas.ES_WINDOWS:
        from . import _win
        asa = _win.kernel32.OpenMutexW(_win.SYNCHRONIZE, False, NOMBRE_MUTEX)
        if asa:
            _win.kernel32.CloseHandle(asa)
            return True
        return False
    try:
        pid = int(_pid_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# --- Parada ordenada --------------------------------------------------------

def pedir_parada() -> None:
    if rutas.ES_WINDOWS:
        from . import _win
        asa = _win.kernel32.OpenEventW(_win.EVENT_MODIFY_STATE, False, NOMBRE_EVENTO)
        if not asa:
            # Nadie escuchando: no hay vigilante, nada que parar.
            return
        _win.kernel32.SetEvent(asa)
        _win.kernel32.CloseHandle(asa)
        return
    try:
        pid = int(_pid_file().read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass


def parada_pedida(espera_ms: int = 0) -> bool:
    """¿Nos han pedido parar? Espera hasta «espera_ms» milisegundos."""
    if rutas.ES_WINDOWS and _evento:
        from . import _win
        return _win.kernel32.WaitForSingleObject(_evento, espera_ms) == _win.WAIT_OBJECT_0
    # Sin evento propio se duerme igual: «_bucle_simple» no puede quedarse en
    # un bucle activo.
    time.sleep(espera_ms / 1000)
    return False


# --- Arranque / paro / refresco --------------------------------------------

def arrancar() -> bool:
    """Lanza el vigilante en segundo plano. True si quedó en marcha."""
    if activo():
        return True
    orden = rutas.comando_vigilante()
    try:
        if rutas.ES_WINDOWS:
            from . import _win
            subprocess.Popen(
                orden,
                creationflags=_win.DETACHED_PROCESS | _win.CREATE_NO_WINDOW,
                close_fds=True,
            )
        else:
            # Sin heredar las tuberías: quien lanza con «capture_output» no
            # recibiría nunca el fin de fichero y se colgaría.
            subprocess.Popen(orden, start_new_session=True, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except OSError as error:
        rutas.log(f"ERROR al arrancar el vigilante: {error}")
        return False
    # Se le da un momento a que tome el mútex, para informar del estado real.
    # Un False aquí NO significa que haya fallado: en un equipo lento el
    # ejecutable puede tardar más en registrarse, y se registrará solo. Por eso
    # quien llama no lo trata como error, y por eso parar() insiste (ver allí).
    for _ in range(20):
        if activo():
            return True
        time.sleep(0.25)
    rutas.log("El vigilante se lanzó pero aún no se había registrado; "
              "seguirá arrancando por su cuenta.")
    return False


# Veces seguidas que hay que ver el mútex libre para dar por parado al
# vigilante. Con una sola no basta (ver parar()).
LIBRE_SEGUIDAS = 4
INTERVALO_PARADA = 0.25


def parar(espera: float = 10.0) -> bool:
    """Pide la parada y espera a que el vigilante suelte el mútex.

    La parada se pide REPETIDAMENTE, y no una sola vez, por una carrera real: un
    vigilante recién lanzado tarda un par de segundos en registrarse (arrancar el
    ejecutable, importar Qt, leer las credenciales), y en ese hueco «activo()»
    devuelve False aunque el proceso exista ya. Si se diera por parado ahí, ese
    proceso terminaría de arrancar DESPUÉS y se quedaría huérfano, vigilando
    carpetas que puede que ya no existan.

    No es hipotético: pasó en el primer CI de la repo, que acabó con un
    «Terminate orphan process: CifrarPDF» tras dar de alta y quitar una carpeta
    seguidas. Como el proceso, al arrancar, pone el evento a cero, la única forma
    de ganarle la carrera es volver a pedirlo cada poco durante un rato.
    """
    limite = time.monotonic() + espera
    libres = 0
    while time.monotonic() < limite:
        pedir_parada()
        if activo():
            libres = 0
        else:
            libres += 1
            if libres >= LIBRE_SEGUIDAS:
                return True
        time.sleep(INTERVALO_PARADA)
    return not activo()


def pedir_barrido(cid: str) -> bool:
    """Pide al vigilante que barra la carpeta «cid», que acaba de recibir clave fija.

    Solo avisa: cifra el vigilante, para que dos procesos no cifren el mismo
    fichero a la vez. Si no hay vigilante, el que arranque la barre al empezar.
    Un id vacío, oculto o con separadores saldría de `barrer_dir`: se rechaza.
    """
    if not cid or cid.startswith(".") or "/" in cid or "\\" in cid:
        return False
    marcador = rutas.barrer_dir() / cid
    # Se borra y se vuelve a crear para que siempre haya un evento de creación.
    try:
        marcador.unlink(missing_ok=True)
        marcador.touch()
    except OSError as error:
        rutas.log(f"AVISO: no se pudo pedir el barrido de «{cid}»: {error}")
        return False
    return True


def refrescar() -> None:
    """Reaplica el estado tras añadir, renombrar o quitar carpetas.

    Mismo criterio que el backend Debian: si quedan carpetas, el vigilante
    queda en marcha con la lista al día y el autoarranque puesto; si no queda
    ninguna, se para y se quita el autoarranque — quien deja de usar la
    herramienta no se queda con nada arrancando en cada inicio de sesión.
    Cambiar la clave o el modo no lo necesita (el vigilante los lee al
    cifrar), salvo si la carpeta ya no está en el disco: solo se recrea al
    arrancar.
    """
    parar()
    if config.hay_carpetas():
        autostart.activar()
        arrancar()
    else:
        autostart.desactivar()


def asegurar() -> bool:
    """Autoarranque y autorreparación: si hay carpetas, que esté funcionando."""
    if not config.hay_carpetas():
        return True
    if activo():
        return True
    autostart.activar()
    return arrancar()
