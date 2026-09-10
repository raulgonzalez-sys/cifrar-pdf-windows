"""Sale con 0 si el PDF está protegido con contraseña, con 1 si no.

Para comprobar a mano o desde el CI que el vigilante ha hecho su trabajo:

    python herramientas/es_cifrado.py Escritorio/Informes/informe.pdf
"""

import sys
from pathlib import Path

from cifrarpdf import cifrar


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    ruta = Path(sys.argv[1])
    if not ruta.is_file():
        print(f"No existe: {ruta}", file=sys.stderr)
        return 1
    try:
        protegido = cifrar.ya_cifrado(ruta)
    except cifrar.ErrorCifrado as error:
        print(f"No se pudo leer: {error}", file=sys.stderr)
        return 1
    print("protegido" if protegido else "sin proteger")
    return 0 if protegido else 1


if __name__ == "__main__":
    sys.exit(main())
