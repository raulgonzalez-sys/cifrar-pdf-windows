"""Esperar a que un fichero esté completamente escrito antes de tocarlo.

El backend Debian usa «lsof». En Windows no hace falta: el bloqueo de ficheros
es obligatorio, así que si otro proceso sigue escribiendo, un intento de
apertura en modo escritura falla — más fiable que preguntar por la lista de
descriptores abiertos.

Aun así se comprueba también que el tamaño se haya estabilizado, porque hay
programas que escriben por trozos cerrando el fichero entre medias (Chrome al
descargar, los clientes de sincronización en la nube): en ese hueco el fichero
no está bloqueado pero tampoco está completo.

Con todo, esto no es infalible y conviene saber por qué: el «open» de Python no
pide acceso exclusivo, así que solo se detecta al que escribe si ÉL abrió el
fichero denegando escritura a los demás (lo habitual en un programa que lo está
generando). Para el resto, la red de seguridad es el tamaño estable.
"""

from __future__ import annotations

import time
from pathlib import Path

ESPERA_MAX = 60.0
INTERVALO = 1.0
# Lecturas consecutivas con el mismo tamaño para dar el fichero por terminado.
# Con una sola bastaba para colarse: un programa que escriba a ráfagas y pause
# entre trozos más de lo que dura un intervalo parecería acabado en la pausa.
# Con dos hacen falta ~2 s sin crecer, que ninguna pausa de escritura normal
# alcanza, y solo retrasa el cifrado un segundo más.
LECTURAS_ESTABLES = 2


def bloqueado(ruta: Path) -> bool:
    """¿Lo tiene abierto otro proceso en modo exclusivo?"""
    try:
        with open(ruta, "rb+"):
            return False
    except PermissionError:
        return True
    except OSError:
        # No existe todavía, o desapareció: quien llama lo trata como «no listo».
        return True


def esperar_archivo(ruta: Path, espera_max: float = ESPERA_MAX) -> bool:
    """True si el fichero acabó de escribirse; False si se agotó la espera."""
    limite = time.monotonic() + espera_max

    # 1) Que exista y tenga contenido.
    while time.monotonic() < limite:
        try:
            if ruta.stat().st_size > 0:
                break
        except OSError:
            pass
        time.sleep(INTERVALO)
    else:
        return False

    # 2) Que nadie lo tenga abierto y que el tamaño lleve varias lecturas igual.
    anterior = -1
    estables = 0
    while time.monotonic() < limite:
        try:
            actual = ruta.stat().st_size
        except OSError:
            return False
        if actual > 0 and actual == anterior:
            estables += 1
            if estables >= LECTURAS_ESTABLES and not bloqueado(ruta):
                return True
        else:
            estables = 0
        anterior = actual
        time.sleep(INTERVALO)
    return False
