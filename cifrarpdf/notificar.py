"""Avisos a la persona que usa el equipo.

Todo aviso va **siempre** al registro. Además, si quien está ejecutando puede
mostrar notificaciones del sistema (el vigilante, que vive como icono en el
área de notificación), registra aquí su emisor y los avisos salen también como
notificación de Windows.

Así los subcomandos «--gui-*», que corren sin ventana y contestan por texto, no
intentan sacar globos por su cuenta.
"""

from __future__ import annotations

from collections.abc import Callable

from . import rutas

_emisor: Callable[[str, str, bool], None] | None = None


def registrar_emisor(emisor: Callable[[str, str, bool], None] | None) -> None:
    global _emisor
    _emisor = emisor


def _enviar(titulo: str, texto: str, es_error: bool) -> None:
    rutas.log(("ERROR: " if es_error else "") + f"{titulo} — {texto}".replace("\n", " "))
    if _emisor is None:
        return
    try:
        _emisor(titulo, texto, es_error)
    except Exception as error:  # noqa: BLE001 — un aviso nunca debe tumbar el vigilante
        rutas.log(f"AVISO: no se pudo mostrar la notificación: {error}")


def info(titulo: str, texto: str) -> None:
    _enviar(titulo, texto, False)


def error(titulo: str, texto: str) -> None:
    _enviar(titulo, texto, True)
