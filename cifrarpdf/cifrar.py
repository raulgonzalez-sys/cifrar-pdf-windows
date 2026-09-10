"""Cifrado del PDF con pikepdf (AES-256).

pikepdf lleva qpdf dentro, así que el resultado es el mismo que produce el
backend Debian con «qpdf --encrypt … 256». La ventaja de hacerlo en proceso es
que la contraseña ya no viaja por la línea de órdenes ni por un argfile
temporal en el disco: se queda en memoria.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pikepdf

from . import rutas

SUFIJO_TEMP = "_temp.pdf"

# Reintentos del reemplazo final. En Windows el bloqueo de ficheros es real: si
# el PDF está abierto en un visor, os.replace falla (WinError 32) hasta que se
# cierre. En Linux esto no pasa nunca, así que es la diferencia de
# comportamiento más visible entre las dos versiones de la herramienta.
INTENTOS_REEMPLAZO = 10
ESPERA_REEMPLAZO = 1.0


class ErrorCifrado(Exception):
    """Fallo con mensaje ya redactado para la persona que usa el equipo."""


def es_temporal(nombre: str) -> bool:
    return nombre.endswith(SUFIJO_TEMP) or nombre.startswith(".")


def ya_cifrado(ruta: Path) -> bool:
    """¿El PDF ya está protegido con contraseña?

    Dos casos, y hay que cubrir los dos: si pide contraseña para abrirse,
    pikepdf lanza PasswordError; si abre sin contraseña pero está cifrado
    (contraseña de usuario vacía), hay que mirar «is_encrypted».
    """
    try:
        with pikepdf.open(ruta) as pdf:
            return bool(pdf.is_encrypted)
    except pikepdf.PasswordError:
        return True
    except pikepdf.PdfError as error:
        raise ErrorCifrado(f"No se pudo leer el PDF: {error}") from error


def _temporal_para(destino: Path) -> Path:
    return destino.with_name(f".{destino.stem}.{os.getpid()}{SUFIJO_TEMP}")


def reemplazar(origen: Path, destino: Path) -> None:
    """Mueve el temporal sobre el original, esperando a que se libere."""
    for intento in range(INTENTOS_REEMPLAZO):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == 0:
                rutas.log(f"El original está en uso, esperando para reemplazarlo: {destino.name}")
            time.sleep(ESPERA_REEMPLAZO)
        except OSError as error:
            raise ErrorCifrado(f"No se pudo reemplazar el original: {error}") from error
    raise ErrorCifrado(
        "El PDF está abierto en otro programa y no se ha podido sustituir por "
        "la versión protegida.\nCiérralo y vuelve a soltarlo en la carpeta."
    )


def cifrar_en_sitio(ruta: Path, clave: str) -> bool:
    """Cifra el PDF sobre sí mismo. Devuelve False si ya estaba cifrado."""
    if ya_cifrado(ruta):
        rutas.log(f"Ya cifrado, se omite: {ruta}")
        return False

    temporal = _temporal_para(ruta)
    try:
        with pikepdf.open(ruta) as pdf:
            pdf.save(
                temporal,
                encryption=pikepdf.Encryption(
                    user=clave, owner=clave, R=6, aes=True, metadata=True
                ),
            )
    except pikepdf.PdfError as error:
        _limpiar(temporal)
        raise ErrorCifrado(f"No se pudo cifrar «{ruta.name}»: {error}") from error
    except OSError as error:
        _limpiar(temporal)
        raise ErrorCifrado(f"No se pudo escribir el PDF protegido: {error}") from error

    # Mismo cinturón de seguridad que el bash: nunca dar por bueno un cifrado
    # sin comprobar que el resultado pide contraseña de verdad.
    if not _pide_contrasena(temporal):
        _limpiar(temporal)
        raise ErrorCifrado(f"El resultado no quedó protegido: {ruta.name}")

    try:
        reemplazar(temporal, ruta)
    except ErrorCifrado:
        _limpiar(temporal)
        raise
    rutas.log(f"Cifrado: {ruta}")
    return True


def _pide_contrasena(ruta: Path) -> bool:
    try:
        with pikepdf.open(ruta):
            return False
    except pikepdf.PasswordError:
        return True
    except pikepdf.PdfError:
        return False


def _limpiar(ruta: Path) -> None:
    try:
        ruta.unlink()
    except OSError:
        pass


def limpiar_temporales(carpeta: Path) -> None:
    """Borra restos de un cifrado interrumpido (corte de luz, cierre forzado)."""
    try:
        for entrada in carpeta.iterdir():
            if entrada.is_file() and entrada.name.endswith(SUFIJO_TEMP):
                _limpiar(entrada)
    except OSError:
        pass
