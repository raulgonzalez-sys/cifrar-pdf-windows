"""Contraseña de cada carpeta.

Primera opción: el **Administrador de credenciales de Windows** vía keyring
(equivalente a KWallet en los puestos Debian; se desbloquea con el inicio de
sesión del usuario y queda protegido por DPAPI).

Si el Administrador de credenciales no está disponible, se guarda un fichero
cifrado con **DPAPI en ámbito de usuario** («<id>.dpapi»): solo lo puede
descifrar esa cuenta en ese equipo. Es un fallback mejor que el fichero en
claro con permisos 600 que usa el backend Debian, porque en Windows los
permisos heredados de %APPDATA% no son equivalentes a un chmod 600.
"""

from __future__ import annotations

from pathlib import Path

from . import rutas

MIN_CLAVE = 8


def validar_clave(clave: str) -> str | None:
    """Devuelve el texto del error, o None si la contraseña es aceptable.

    Mismo criterio que el backend Debian: 8 caracteres como mínimo. Endurecerlo
    aquí sin endurecerlo allí haría que la misma persona tuviera reglas
    distintas según el equipo en el que esté.
    """
    if len(clave) < MIN_CLAVE:
        return f"- Mínimo {MIN_CLAVE} caracteres (tiene {len(clave)})"
    return None


def _fichero_dpapi(cid: str) -> Path:
    return rutas.carpetas_dir() / f"{cid}.dpapi"


# --- Administrador de credenciales -----------------------------------------

def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    try:
        # Sin backend usable (p. ej. un Linux sin Secret Service) keyring
        # devuelve el backend «fail», que lanza al primer uso.
        from keyring.backends.fail import Keyring as KeyringFallido
        if isinstance(keyring.get_keyring(), KeyringFallido):
            return None
    except ImportError:
        pass
    return keyring


def _guardar_keyring(cid: str, clave: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(rutas.SERVICIO, cid, clave)
        return True
    except Exception:  # noqa: BLE001 — cualquier fallo del backend cae al fichero
        return False


def _leer_keyring(cid: str) -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(rutas.SERVICIO, cid) or None
    except Exception:  # noqa: BLE001
        return None


def _borrar_keyring(cid: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(rutas.SERVICIO, cid)
    except Exception:  # noqa: BLE001
        pass


# --- DPAPI (fallback) -------------------------------------------------------

def _dpapi(cifrar: bool, datos: bytes) -> bytes | None:
    """CryptProtectData / CryptUnprotectData en ámbito de usuario."""
    if not rutas.ES_WINDOWS:
        return None
    import ctypes

    from . import _win

    buffer_entrada = ctypes.create_string_buffer(datos, len(datos))
    entrada = _win.BLOB(len(datos),
                        ctypes.cast(buffer_entrada, ctypes.POINTER(ctypes.c_char)))
    salida = _win.BLOB()
    funcion = _win.crypt32.CryptProtectData if cifrar else _win.crypt32.CryptUnprotectData
    descripcion = "Cifrar PDF FISAT" if cifrar else None
    if not funcion(ctypes.byref(entrada), descripcion, None, None, None, 0,
                   ctypes.byref(salida)):
        return None
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        _win.kernel32.LocalFree(salida.pbData)


def _guardar_fichero(cid: str, clave: str) -> bool:
    fichero = _fichero_dpapi(cid)
    protegido = _dpapi(True, clave.encode("utf-8"))
    if protegido is None:
        if rutas.ES_WINDOWS:
            return False
        # POSIX: solo desarrollo/tests. En claro con permisos de solo-dueño.
        protegido = clave.encode("utf-8")
    try:
        with open(fichero, "wb") as fh:
            fh.write(protegido)
        if not rutas.ES_WINDOWS:
            fichero.chmod(0o600)
        return True
    except OSError:
        return False


def _leer_fichero(cid: str) -> str | None:
    try:
        datos = _fichero_dpapi(cid).read_bytes()
    except OSError:
        return None
    if not datos:
        return None
    if rutas.ES_WINDOWS:
        claro = _dpapi(False, datos)
        return claro.decode("utf-8", "replace") if claro else None
    return datos.decode("utf-8", "replace")


# --- API ---------------------------------------------------------------------

def guardar(cid: str, clave: str) -> bool:
    if _guardar_keyring(cid, clave):
        # Si quedaba un fallback de antes, deja de hacer falta.
        try:
            _fichero_dpapi(cid).unlink()
        except OSError:
            pass
        return True
    rutas.log(f"AVISO: sin Administrador de credenciales, se usa fichero DPAPI ({cid}).")
    return _guardar_fichero(cid, clave)


def leer(cid: str) -> str | None:
    return _leer_keyring(cid) or _leer_fichero(cid)


def borrar(cid: str) -> None:
    _borrar_keyring(cid)
    try:
        _fichero_dpapi(cid).unlink()
    except OSError:
        pass


def tiene_clave(cid: str) -> bool:
    return bool(leer(cid))
