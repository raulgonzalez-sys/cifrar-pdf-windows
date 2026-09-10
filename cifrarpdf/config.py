"""Carpetas de cifrado configuradas: alta, baja, renombrado y lectura.

Una carpeta = un fichero «carpetas.d/<id>.json» con su nombre visible y su
ruta. El formato es JSON y no el «.conf + source» del bash: aquí no hay shell
que aprovechar, y JSON evita tener que reproducir el escapado de «printf %q».
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import rutas

# Caracteres que Windows no admite en un nombre de fichero o carpeta.
CARACTERES_INVALIDOS = '<>:"/\\|?*'

# Nombres de dispositivo reservados: una carpeta llamada así no se puede crear.
RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}

MAX_NOMBRE = 100


@dataclass(frozen=True)
class Carpeta:
    id: str
    nombre: str
    ruta: Path

    @property
    def existe(self) -> bool:
        return self.ruta.is_dir()


def validar_nombre(nombre: str) -> str | None:
    """Devuelve el texto del error, o None si el nombre es válido."""
    if not nombre or not nombre.strip():
        return "Escribe un nombre para la carpeta."
    if nombre != nombre.strip():
        return "El nombre no puede empezar ni acabar con espacios."
    if len(nombre) > MAX_NOMBRE:
        return f"El nombre es demasiado largo (máximo {MAX_NOMBRE} caracteres)."
    for caracter in nombre:
        if caracter in CARACTERES_INVALIDOS:
            return f"El nombre no puede contener «{caracter}»."
        if ord(caracter) < 32:
            return "El nombre contiene caracteres no imprimibles."
    if nombre.endswith("."):
        return "El nombre no puede acabar en punto."
    if nombre.upper() in RESERVADOS or nombre.upper().split(".")[0] in RESERVADOS:
        return f"«{nombre}» es un nombre reservado de Windows. Elige otro."
    return None


def slug(nombre: str) -> str:
    """Nombre legible → identificador seguro para nombre de fichero."""
    plano = unicodedata.normalize("NFKD", nombre)
    plano = plano.encode("ascii", "ignore").decode("ascii").lower()
    plano = re.sub(r"[^a-z0-9]+", "-", plano).strip("-")
    return plano or "carpeta"


def _fichero(cid: str) -> Path:
    return rutas.carpetas_dir() / f"{cid}.json"


def nuevo_id(nombre: str) -> str:
    base = slug(nombre)
    cid = base
    n = 2
    while _fichero(cid).exists():
        cid = f"{base}-{n}"
        n += 1
    return cid


def listar_ids() -> list[str]:
    try:
        return sorted(f.stem for f in rutas.carpetas_dir().glob("*.json"))
    except OSError:
        return []


def leer(cid: str) -> Carpeta | None:
    try:
        with open(_fichero(cid), encoding="utf-8") as fh:
            datos = json.load(fh)
        nombre = datos["nombre"]
        carpeta = datos["carpeta"]
    except (OSError, ValueError, KeyError):
        return None
    if not nombre or not carpeta:
        return None
    return Carpeta(id=cid, nombre=nombre, ruta=Path(carpeta))


def listar() -> list[Carpeta]:
    return [c for c in (leer(cid) for cid in listar_ids()) if c is not None]


def escribir(cid: str, nombre: str, carpeta: Path) -> None:
    """Escribe la configuración de una carpeta (atómico: temporal + replace)."""
    destino = _fichero(cid)
    temporal = destino.with_suffix(".json.tmp")
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump({"nombre": nombre, "carpeta": str(carpeta)}, fh,
                  ensure_ascii=False, indent=2)
    os.replace(temporal, destino)


def borrar(cid: str) -> None:
    try:
        _fichero(cid).unlink()
    except OSError:
        pass


def hay_carpetas() -> bool:
    return bool(listar_ids())


def ya_configurada(carpeta: Path) -> bool:
    """¿Hay ya una carpeta de cifrado apuntando a esta ruta?

    La comparación es insensible a mayúsculas en Windows, donde «Informes» y
    «informes» son la MISMA carpeta del disco (en Linux no lo serían).
    """
    objetivo = _clave_ruta(carpeta)
    return any(_clave_ruta(c.ruta) == objetivo for c in listar())


def _clave_ruta(carpeta: Path) -> str:
    texto = os.path.normpath(str(carpeta))
    return os.path.normcase(texto) if rutas.ES_WINDOWS else texto
