"""Crea un PDF de prueba. Para comprobaciones a mano y para el CI.

    python herramientas/pdf_de_prueba.py ruta/al/fichero.pdf [paginas]
"""

import sys

import pikepdf


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    destino = sys.argv[1]
    paginas = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    with pikepdf.new() as pdf:
        for _ in range(paginas):
            pdf.add_blank_page(page_size=(595, 842))
        pdf.save(destino)
    print(f"Escrito {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
