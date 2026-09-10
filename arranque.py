"""Punto de entrada del ejecutable CifrarPDF.exe.

Un solo binario que hace de ventana y de backend según los argumentos, igual
que el script bash de los puestos Debian: sin argumentos abre la ventana de
gestión, y con «--vigilante» o «--gui-*» actúa de backend.

Es también el fichero que PyInstaller analiza, y por eso importa aquí «gui»:
así el módulo de la ventana entra en el paquete congelado.
"""

from __future__ import annotations

import sys


def main() -> int:
    argumentos = sys.argv[1:]
    if not argumentos or argumentos[0] == "--lanzar":
        import gui
        return gui.main()
    from cifrarpdf.cli import main as backend
    return backend(argumentos)


if __name__ == "__main__":
    sys.exit(main())
