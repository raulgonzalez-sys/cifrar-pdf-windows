"""Genera el icono de la aplicación (candado sobre el rojo corporativo).

Windows no tiene tema de iconos, así que el icono se empaqueta con el programa
en lugar de pedirlo al sistema. Este script lo regenera para que no haya que
guardar un binario «mágico» que nadie sabe de dónde salió.

    python herramientas/generar_icono.py

Requiere Pillow (solo para generar; el programa no lo necesita en ejecución).
Rojo corporativo FISAT: RGB 246, 69, 91 — el mismo acento de los esquemas de
color FisatClaro/FisatOscuro de los puestos Debian.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROJO = (246, 69, 91, 255)
BLANCO = (255, 255, 255, 255)
LADO = 512
DESTINO = Path(__file__).resolve().parent.parent / "recursos"
TAMANOS = [16, 20, 24, 32, 48, 64, 128, 256]


def dibujar() -> Image.Image:
    imagen = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(imagen)

    # Fondo redondeado corporativo.
    lapiz.rounded_rectangle([0, 0, LADO - 1, LADO - 1], radius=int(LADO * 0.22), fill=ROJO)

    # Candado: arco (asa) + cuerpo.
    centro = LADO // 2
    grosor = int(LADO * 0.075)
    radio = int(LADO * 0.13)
    alto_asa = int(LADO * 0.30)
    lapiz.arc(
        [centro - radio, alto_asa - radio, centro + radio, alto_asa + radio],
        start=180, end=360, fill=BLANCO, width=grosor,
    )
    # Patas del asa hasta el cuerpo.
    for lado in (-1, 1):
        x = centro + lado * radio
        lapiz.line([x, alto_asa, x, int(LADO * 0.40)], fill=BLANCO, width=grosor)

    ancho_cuerpo = int(LADO * 0.44)
    lapiz.rounded_rectangle(
        [centro - ancho_cuerpo // 2, int(LADO * 0.38),
         centro + ancho_cuerpo // 2, int(LADO * 0.74)],
        radius=int(LADO * 0.055), fill=BLANCO,
    )
    # Ojo de la cerradura, en rojo sobre el cuerpo blanco.
    ojo = int(LADO * 0.045)
    lapiz.ellipse(
        [centro - ojo, int(LADO * 0.49) - ojo, centro + ojo, int(LADO * 0.49) + ojo],
        fill=ROJO,
    )
    lapiz.rounded_rectangle(
        [centro - ojo // 2, int(LADO * 0.49), centro + ojo // 2, int(LADO * 0.63)],
        radius=ojo // 2, fill=ROJO,
    )
    return imagen


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    imagen = dibujar()
    imagen.resize((256, 256), Image.LANCZOS).save(DESTINO / "cifrarpdf.png")
    imagen.save(DESTINO / "cifrarpdf.ico", sizes=[(n, n) for n in TAMANOS])
    print(f"Escritos {DESTINO / 'cifrarpdf.ico'} y {DESTINO / 'cifrarpdf.png'}")


if __name__ == "__main__":
    main()
