"""Compara «gui.py» con la interfaz de los puestos Debian.

`gui.py` deriva de `archivos/fisat-cifrar-pdf-gui` de debian13-fisat, pero es un
**fork**: la copia de Debian no lleva las ramas `ES_WINDOWS`. Esta herramienta
solo sirve para VER las diferencias cuando hay que portar un cambio de un lado
al otro:

    python herramientas/comparar_gui.py /ruta/a/debian13-fisat

No copia nada, y es deliberado: copiar el fichero entero de una copia a la otra
se llevaría por delante las ramas de plataforma del destino. Los cambios se
portan a mano, mirando este diff.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
GUI = RAIZ / "gui.py"
CANONICA = Path("archivos") / "fisat-cifrar-pdf-gui"


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def main() -> int:
    partes = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    partes.add_argument("checkout", help="ruta a un checkout de debian13-fisat")
    args = partes.parse_args()

    otra = Path(args.checkout).expanduser().resolve() / CANONICA
    if not otra.is_file():
        print(f"No encuentro {otra}. ¿Es un checkout de debian13-fisat?", file=sys.stderr)
        return 2

    print(f"Windows : {GUI}  ({sha256(GUI)[:12]}…)")
    print(f"Debian  : {otra}  ({sha256(otra)[:12]}…)")
    if sha256(otra) == sha256(GUI):
        print("\nSon idénticas (no es lo habitual: son forks).")
        return 0

    print("\nDiferencias (Debian → Windows):\n")
    sys.stdout.writelines(difflib.unified_diff(
        otra.read_text(encoding="utf-8").splitlines(keepends=True),
        GUI.read_text(encoding="utf-8").splitlines(keepends=True),
        fromfile="debian13-fisat/archivos/fisat-cifrar-pdf-gui",
        tofile="cifrar-pdf-windows/gui.py",
    ))
    print("\nRecuerda: los cambios se portan A MANO. Copiar el fichero entero "
          "rompería las ramas de plataforma del destino.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
