"""Modo «preguntar la contraseña cada vez»: lo que hace el vigilante.

En este modo no se guarda ninguna contraseña en el equipo: se pide en el
momento de cifrar. Aquí vive todo lo que eso necesita y no depende de Qt —
pedir la contraseña dos veces, el lote de un solo diálogo para varios PDF, y el
marcado «SIN-CIFRAR_» de lo que se quedó sin proteger—, para poder probarlo sin
pantalla.

**Cómo se pregunta en Windows, y por qué no como en Debian.** El bash lanza un
diálogo externo (kdialog, zenity, la propia GUI con «--pedir-pass») y recoge la
contraseña por la salida estándar del hijo. Aquí ese camino no vale: los dos
ejecutables sin consola tienen `sys.stdout` a None y el `print` se descarta sin
error (ver `rutas.py`), así que la contraseña nunca llegaría de vuelta. Además
Qt solo construye ventanas en el hilo principal, que en el vigilante es el del
icono del área de notificación. Así que el diálogo lo muestra **ese mismo
proceso**, en su hilo de Qt: el hilo que cifra registra aquí su petición y
espera la respuesta. La contraseña no sale de la memoria del vigilante — ni
tubería, ni fichero temporal, ni línea de órdenes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import cifrar, rutas, secreto

# Prefijo del PDF que se quedó sin cifrar porque nadie escribió la contraseña.
# Se ve a simple vista en el Escritorio, que es justo lo que se busca.
PREFIJO_SIN_CIFRAR = "SIN-CIFRAR_"

# Segundos que se deja abierto cada diálogo. Un PDF soltado y olvidado no puede
# dejar al vigilante esperando para siempre: el resto de PDF no se cifrarían.
ESPERA_PREGUNTA = 180.0

# Vida de la contraseña de lote. Vive SOLO en memoria del vigilante y caduca;
# nunca toca el disco — es la diferencia con el modo «fija».
REUSO_TTL = 120.0

# Vueltas antes de rendirse cuando la contraseña no vale o no coinciden.
INTENTOS = 3


# --- Diálogos ----------------------------------------------------------------

@dataclass
class Peticion:
    """Un diálogo pendiente de atender por el hilo de Qt."""

    tipo: str  # "pedir" | "avisar" | "confirmar"
    titulo: str
    texto: str
    resultado: object = None
    atendida: threading.Event = field(default_factory=threading.Event)


# Lo registra el vigilante cuando consigue montar su interfaz de Qt. Sin él no
# hay a quién preguntar (sesión sin escritorio, Qt que no arranca) y el PDF
# acaba marcado: mejor eso que dejarlo sin proteger y sin avisar.
_atendedor = None


def registrar_atendedor(atendedor) -> None:  # noqa: ANN001 — callable o None
    global _atendedor
    _atendedor = atendedor


def hay_atendedor() -> bool:
    return _atendedor is not None


def _preguntar(tipo: str, titulo: str, texto: str, espera: float):
    if _atendedor is None:
        return None
    peticion = Peticion(tipo=tipo, titulo=titulo, texto=texto)
    try:
        _atendedor(peticion)
    except Exception as error:  # noqa: BLE001 — un diálogo no tumba el vigilante
        rutas.log(f"AVISO: no se pudo mostrar el diálogo de contraseña: {error}")
        return None
    if not peticion.atendida.wait(espera):
        rutas.log("Diálogo de contraseña sin respuesta a tiempo.")
        return None
    return peticion.resultado


def pedir_clave(titulo: str, texto: str) -> str | None:
    """Un diálogo de contraseña. None si se cancela o no se contesta."""
    respuesta = _preguntar("pedir", titulo, texto, ESPERA_PREGUNTA)
    return respuesta or None


def avisar(titulo: str, texto: str) -> None:
    """Aviso modal entre dos intentos (contraseña corta, no coinciden)."""
    if _preguntar("avisar", titulo, texto, 60.0) is None:
        rutas.log(f"AVISO: {titulo} — {texto}")


def confirmar(titulo: str, texto: str) -> bool:
    return _preguntar("confirmar", titulo, texto, 120.0) is True


def pedir_clave_confirmada(titulo: str, texto: str) -> str | None:
    """Contraseña + confirmación, igual que al crear la carpeta.

    Se pide dos veces a propósito: el original se sustituye por la versión
    cifrada, así que una errata dejaría un PDF que no se puede abrir nunca.
    """
    for _ in range(INTENTOS):
        primera = pedir_clave(titulo, texto)
        if not primera:
            return None
        problema = secreto.validar_clave(primera)
        if problema:
            avisar(titulo, f"Contraseña no válida:\n{problema}")
            continue
        segunda = pedir_clave(titulo, "Repite la contraseña para confirmarla:")
        if segunda is None:
            return None
        if primera == segunda:
            return primera
        avisar(titulo, "Las contraseñas no coinciden. Inténtalo de nuevo.")
    return None


# --- Lote --------------------------------------------------------------------

class Lote:
    """Contraseña compartida por los PDF que se sueltan de golpe.

    Solo en memoria y con caducidad: pasados `REUSO_TTL` segundos se vuelve a
    preguntar. Nunca se escribe en ningún sitio.
    """

    def __init__(self, ttl: float = REUSO_TTL) -> None:
        self._ttl = ttl
        self._claves: dict[str, tuple[str, float]] = {}
        self._cerrojo = threading.Lock()

    def guardar(self, cid: str, clave: str) -> None:
        with self._cerrojo:
            self._claves[cid] = (clave, time.monotonic() + self._ttl)

    def vigente(self, cid: str) -> str | None:
        with self._cerrojo:
            guardado = self._claves.get(cid)
            if guardado is None:
                return None
            clave, caduca = guardado
            if time.monotonic() >= caduca:
                del self._claves[cid]
                return None
            return clave

    def olvidar(self, cid: str) -> None:
        with self._cerrojo:
            self._claves.pop(cid, None)


# --- PDF pendientes y marcado ------------------------------------------------

def es_marcado(nombre: str) -> bool:
    return nombre.startswith(PREFIJO_SIN_CIFRAR)


def pendientes_sin_cifrar(carpeta: Path) -> list[Path]:
    """PDF sin cifrar que hay AHORA MISMO en la carpeta.

    Sirve para preguntar una sola vez cuando se sueltan varios PDF de golpe:
    cuando llega el aviso del primero, los demás ya están escritos en el disco,
    así que mirarlo aquí es más fiable que espiar la cola de eventos.

    Incluye a propósito los marcados «SIN-CIFRAR_»: estaban desprotegidos, y
    que el lote se los lleve por delante es justo lo que se quiere.
    """
    encontrados: list[Path] = []
    try:
        entradas = sorted(carpeta.iterdir())
    except OSError:
        return encontrados
    for entrada in entradas:
        if not entrada.is_file() or entrada.suffix.lower() != ".pdf":
            continue
        if cifrar.es_temporal(entrada.name):
            continue
        try:
            if cifrar.ya_cifrado(entrada):
                continue
        except cifrar.ErrorCifrado:
            # Ilegible: no es «pendiente», es un problema aparte. Se deja para
            # que lo cuente el intento de cifrado de ese fichero en concreto.
            continue
        encontrados.append(entrada)
    return encontrados


def marcar_sin_cifrar(ruta: Path) -> Path:
    """Renombra a «SIN-CIFRAR_…» el PDF que se quedó sin proteger.

    Nunca se marca dos veces (el prefijo se apilaría), y si el nombre marcado
    ya está ocupado se numera. Devuelve la ruta resultante.
    """
    if es_marcado(ruta.name):
        return ruta
    destino = ruta.with_name(f"{PREFIJO_SIN_CIFRAR}{ruta.name}")
    numero = 2
    while destino.exists():
        destino = ruta.with_name(f"{PREFIJO_SIN_CIFRAR}{numero}_{ruta.name}")
        numero += 1
    try:
        ruta.rename(destino)
    except OSError as error:
        rutas.log(f"No se pudo marcar como sin cifrar «{ruta.name}»: {error}")
        return ruta
    return destino


def limpiar_prefijo(ruta: Path) -> Path:
    """Devuelve su nombre limpio a un PDF marcado que ya se ha cifrado bien.

    Si el nombre limpio está ocupado se deja como está: renombrar encima
    borraría el fichero de otra persona.
    """
    if not es_marcado(ruta.name):
        return ruta
    limpio = ruta.name[len(PREFIJO_SIN_CIFRAR):]
    # El sufijo numérico que añade marcar_sin_cifrar ante una colisión.
    partes = limpio.split("_", 1)
    if len(partes) == 2 and partes[0].isdigit():
        limpio = partes[1]
    if not limpio:
        return ruta
    destino = ruta.with_name(limpio)
    if destino.exists():
        return ruta
    try:
        ruta.rename(destino)
    except OSError:
        return ruta
    return destino
