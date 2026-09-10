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

class YaEnMarcha(Exception):
    """Ya hay un vigilante de este usuario funcionando."""


def _pid_file() -> Path:
    return rutas.datos_dir() / "vigilante.pid"


# --- Instancia única --------------------------------------------------------

class Vigilancia:
    """Contexto que marca «yo soy el vigilante». Lanza YaEnMarcha si hay otro."""

    def __init__(self) -> None:
        self._mutex = None

    def __enter__(self) -> Vigilancia:
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
            self._mutex = mutex
        else:
            if activo():
                raise YaEnMarcha
            _pid_file().write_text(str(os.getpid()), encoding="utf-8")
        limpiar_parada()
        return self

    def __exit__(self, *_excepcion: object) -> None:
        if rutas.ES_WINDOWS:
            if self._mutex:
                from . import _win
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


def limpiar_parada() -> None:
    """Deja el evento de parada a cero (lo llama el vigilante al arrancar)."""
    if not rutas.ES_WINDOWS:
        return
    from . import _win
    asa = _win.kernel32.CreateEventW(None, True, False, NOMBRE_EVENTO)
    if asa:
        _win.kernel32.ResetEvent(asa)
        _win.kernel32.CloseHandle(asa)


def parada_pedida(espera_ms: int = 0) -> bool:
    """¿Nos han pedido parar? Espera hasta «espera_ms» milisegundos."""
    if not rutas.ES_WINDOWS:
        time.sleep(espera_ms / 1000)
        return False
    from . import _win
    asa = _win.kernel32.CreateEventW(None, True, False, NOMBRE_EVENTO)
    if not asa:
        return False
    try:
        return _win.kernel32.WaitForSingleObject(asa, espera_ms) == _win.WAIT_OBJECT_0
    finally:
        _win.kernel32.CloseHandle(asa)


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
            subprocess.Popen(orden, start_new_session=True, close_fds=True)
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


def refrescar() -> None:
    """Reaplica el estado tras un cambio de carpetas.

    Mismo criterio que el backend Debian: si quedan carpetas, el vigilante
    queda en marcha con la lista al día y el autoarranque puesto; si no queda
    ninguna, se para y se quita el autoarranque — quien deja de usar la
    herramienta no se queda con nada arrancando en cada inicio de sesión.
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
