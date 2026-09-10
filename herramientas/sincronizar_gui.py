"""Regla de sincronía de «gui.py» con la repo debian13-fisat.

«gui.py» de esta repo y «archivos/fisat-cifrar-pdf-gui» de debian13-fisat son
el MISMO fichero: byte a byte idénticos, con todo lo específico de cada sistema
detrás de ES_WINDOWS. Es duplicidad consciente (la misma clase que los heredocs
de instalar-cifrar-pdf.sh o el CRT_B64 de rotar_certificado_flota.sh), y como
esas, se mantiene a mano — pero con red de seguridad:

    python herramientas/sincronizar_gui.py --comprobar-sello
        Falla si gui.py ha cambiado y no se ha resellado. Esto es lo que corre
        el CI: obliga a pasar por aquí y, con ello, a acordarse de la otra copia.

    python herramientas/sincronizar_gui.py --diff RUTA_A_debian13-fisat
        Enseña en qué se diferencian las dos copias.

    python herramientas/sincronizar_gui.py --traer RUTA_A_debian13-fisat
        Copia la versión de debian13-fisat aquí y resella.

    python herramientas/sincronizar_gui.py --llevar RUTA_A_debian13-fisat
        Lo contrario: copia esta versión a debian13-fisat (mantiene el modo
        ejecutable del destino) y resella.

    python herramientas/sincronizar_gui.py --sellar
        Solo actualiza el sello con el gui.py actual.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
GUI = RAIZ / "gui.py"
SELLO = RAIZ / "GUI_SYNC.md"
CANONICO = Path("archivos") / "fisat-cifrar-pdf-gui"
PATRON_SELLO = re.compile(r"^sha256\s*=\s*([0-9a-f]{64})\s*$", re.MULTILINE)


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def sello_guardado() -> str | None:
    if not SELLO.exists():
        return None
    encontrado = PATRON_SELLO.search(SELLO.read_text(encoding="utf-8"))
    return encontrado.group(1) if encontrado else None


def sellar() -> int:
    actual = sha256(GUI)
    texto = SELLO.read_text(encoding="utf-8")
    if PATRON_SELLO.search(texto):
        texto = PATRON_SELLO.sub(f"sha256 = {actual}", texto, count=1)
    else:
        texto += f"\nsha256 = {actual}\n"
    SELLO.write_text(texto, encoding="utf-8")
    print(f"Sello actualizado: {actual}")
    return 0


def comprobar_sello() -> int:
    guardado = sello_guardado()
    actual = sha256(GUI)
    if guardado == actual:
        print(f"gui.py coincide con su sello ({actual[:12]}…).")
        return 0
    print("gui.py ha cambiado y el sello no se ha actualizado.\n", file=sys.stderr)
    print(f"  sello:  {guardado}\n  actual: {actual}\n", file=sys.stderr)
    print("Sincroniza la copia de debian13-fisat (archivos/fisat-cifrar-pdf-gui)\n"
          "y después resella:\n"
          "  python herramientas/sincronizar_gui.py --llevar /ruta/a/debian13-fisat\n"
          "  python herramientas/sincronizar_gui.py --sellar", file=sys.stderr)
    return 1


def _canonico(checkout: str) -> Path:
    ruta = Path(checkout).expanduser().resolve() / CANONICO
    if not ruta.is_file():
        raise SystemExit(f"No encuentro {ruta}. ¿Es un checkout de debian13-fisat?")
    return ruta


def diff(checkout: str) -> int:
    otro = _canonico(checkout)
    if sha256(otro) == sha256(GUI):
        print("Las dos copias son idénticas.")
        return 0
    lineas = difflib.unified_diff(
        otro.read_text(encoding="utf-8").splitlines(keepends=True),
        GUI.read_text(encoding="utf-8").splitlines(keepends=True),
        fromfile=str(otro), tofile=str(GUI),
    )
    sys.stdout.writelines(lineas)
    return 1


def traer(checkout: str) -> int:
    otro = _canonico(checkout)
    shutil.copyfile(otro, GUI)
    print(f"Traído {otro} → {GUI}")
    return sellar()


def llevar(checkout: str) -> int:
    otro = _canonico(checkout)
    modo = otro.stat().st_mode
    shutil.copyfile(GUI, otro)
    otro.chmod(modo)  # en Debian se instala con 755: no perder el bit ejecutable
    print(f"Llevado {GUI} → {otro}")
    return sellar()


def main() -> int:
    partes = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = partes.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--comprobar-sello", action="store_true")
    grupo.add_argument("--sellar", action="store_true")
    grupo.add_argument("--diff", metavar="RUTA")
    grupo.add_argument("--traer", metavar="RUTA")
    grupo.add_argument("--llevar", metavar="RUTA")
    args = partes.parse_args()

    if args.comprobar_sello:
        return comprobar_sello()
    if args.sellar:
        return sellar()
    if args.diff:
        return diff(args.diff)
    if args.traer:
        return traer(args.traer)
    return llevar(args.llevar)


if __name__ == "__main__":
    sys.exit(main())
