"""Línea de órdenes del backend.

Los subcomandos «--gui-*» son el **contrato con la interfaz gráfica** y son
idénticos, uno a uno, a los del backend bash de los puestos Debian: misma
sintaxis, misma salida («OK [dato]» / «ERR mensaje»), mismo código de salida y
la contraseña siempre por la entrada estándar, nunca como argumento (en un
argumento sería visible en la lista de procesos).

Cambiar esta salida rompe la GUI. Si hay que cambiarla, se cambia en las dos
implementaciones a la vez.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import autostart, config, proceso, rutas, secreto

AYUDA = """Cifrar PDF (FISAT) — cifra con contraseña los PDF que sueltas en tus carpetas.

Uso:
  CifrarPDF                      Abre la ventana de gestión.
  CifrarPDF --lanzar             Igual que sin argumentos.
  CifrarPDF --vigilante          Arranca el vigilante (lo usa el autoarranque).
  CifrarPDF --parar              Detiene el vigilante (lo usa el desinstalador).
  CifrarPDF --ayuda              Muestra esta ayuda.

Subcomandos para la interfaz gráfica (no interactivos, contraseña por stdin):
  --gui-listar                   id, nombre, ruta, ¿existe?, ¿tiene contraseña?, modo
  --gui-estado                   1 si el vigilante está activo, 0 si no
  --gui-asegurar                 Arranca el vigilante si hace falta
  --gui-add NOMBRE [--modo fija|preguntar]   Crea la carpeta en el Escritorio
  --gui-rename ID NUEVO          Renombra la carpeta (también en el disco)
  --gui-set-pass ID [--modo fija|preguntar]  Cambia la contraseña o el modo
  --gui-remove ID [--borrar-carpeta]
  --gui-remove-all [--borrar-carpetas]

Cada carpeta tiene su modo de contraseña. En «fija», la contraseña se guarda
en el Administrador de credenciales de Windows y se aplica sola. En
«preguntar» no se guarda nada y la pide el vigilante al cifrar (no lee stdin).

Un PDF ya cifrado no se vuelve a cifrar. Nada de esto se puede deshacer sin la
contraseña: si se pierde, el PDF no se recupera.
"""


def _leer_clave() -> str:
    """Contraseña por stdin.

    Se quita un único salto de línea final (el que añaden las tuberías y las
    consolas). El bash hace lo propio con «$(cat)», que se come los saltos
    finales, así que una contraseña que acabe en salto de línea no es posible
    en ninguna de las dos versiones.
    """
    datos = sys.stdin.read()
    if datos.endswith("\r\n"):
        return datos[:-2]
    if datos.endswith("\n"):
        return datos[:-1]
    return datos


def _err(mensaje: str) -> int:
    print(f"ERR {mensaje}")
    return 1


def _partir_modo(argumentos: tuple[str, ...],
                 por_defecto: str | None = None) -> tuple[list[str], str | None]:
    """Separa «--modo VALOR» del resto de argumentos.

    Se admite en cualquier posición, igual que en el bash, para que la GUI no
    tenga que preocuparse del orden.
    """
    sueltos: list[str] = []
    modo = por_defecto
    resto = list(argumentos)
    while resto:
        actual = resto.pop(0)
        if actual == "--modo":
            modo = config.normalizar_modo(resto.pop(0) if resto else "")
        else:
            sueltos.append(actual)
    return sueltos, modo


# --- Subcomandos de la GUI --------------------------------------------------

def gui_listar() -> int:
    for carpeta in config.listar():
        existe = 1 if carpeta.existe else 0
        # En modo «preguntar» no hay contraseña guardada por diseño, así que no
        # se consulta el Administrador de credenciales: la GUI tampoco muestra
        # ahí el aviso de «sin contraseña».
        clave = 0
        if not carpeta.pregunta and secreto.tiene_clave(carpeta.id):
            clave = 1
        print(f"{carpeta.id}\t{carpeta.nombre}\t{carpeta.ruta}\t{existe}"
              f"\t{clave}\t{carpeta.modo}")
    return 0


def gui_estado() -> int:
    print("1" if proceso.activo() else "0")
    return 0


def gui_asegurar() -> int:
    proceso.asegurar()
    return 0


def gui_add(*argumentos: str) -> int:
    sueltos, modo = _partir_modo(argumentos, config.MODO_FIJA)
    nombre = sueltos[0] if sueltos else ""
    problema = config.validar_nombre(nombre)
    if problema:
        return _err(problema)

    # En «preguntar» no hay contraseña que guardar, así que no se lee stdin: la
    # GUI no manda nada y esperar aquí colgaría la llamada.
    clave = ""
    if modo == config.MODO_FIJA:
        clave = _leer_clave()
        problema = secreto.validar_clave(clave)
        if problema:
            return _err(f"Contraseña inválida: {problema}")

    carpeta = rutas.escritorio() / nombre
    if config.ya_configurada(carpeta):
        return _err(f"Ya hay una carpeta de cifrado en: {carpeta}")
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _err(f"No se pudo crear la carpeta: {carpeta} ({error})")

    cid = config.nuevo_id(nombre)
    config.escribir(cid, nombre, carpeta, modo)
    if modo == config.MODO_FIJA and not secreto.guardar(cid, clave):
        config.borrar(cid)
        return _err("No se pudo guardar la contraseña. La carpeta no se ha añadido.")
    rutas.log(f"Carpeta añadida: {nombre} → {carpeta} (modo: {modo})")
    proceso.refrescar()
    print(f"OK {cid}")
    return 0


def gui_rename(cid: str = "", nuevo: str = "") -> int:
    carpeta = config.leer(cid)
    if carpeta is None:
        return _err("Carpeta no encontrada.")
    problema = config.validar_nombre(nuevo)
    if problema:
        return _err(problema)
    if nuevo == carpeta.nombre:
        print("OK")
        return 0

    destino = carpeta.ruta.parent / nuevo
    if destino.exists():
        return _err(f"Ya existe algo con ese nombre: {destino}")
    try:
        if carpeta.ruta.is_dir():
            carpeta.ruta.rename(destino)
        else:
            destino.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _err(f"No se pudo renombrar la carpeta a: {destino} ({error})")

    config.escribir(cid, nuevo, destino, carpeta.modo)
    rutas.log(f"Carpeta renombrada: {carpeta.nombre} → {nuevo} ({destino})")
    proceso.refrescar()
    print("OK")
    return 0


def gui_set_pass(*argumentos: str) -> int:
    sueltos, modo = _partir_modo(argumentos)
    cid = sueltos[0] if sueltos else ""
    carpeta = config.leer(cid)
    if carpeta is None:
        return _err("Carpeta no encontrada.")
    if modo is None:
        modo = carpeta.modo

    # Pasar a «preguntar» no es solo cambiar el modo: hay que BORRAR lo que
    # hubiera guardado, o quedaría una contraseña en el Administrador de
    # credenciales que ya nadie usa. Y se refresca el vigilante en los dos
    # casos, porque al arrancar decide por modo qué hace con cada carpeta.
    if modo == config.MODO_PREGUNTAR:
        config.escribir(cid, carpeta.nombre, carpeta.ruta, modo)
        secreto.borrar(cid)
        rutas.log(f"Modo «preguntar cada vez» activado: {carpeta.nombre}")
        proceso.refrescar()
        print("OK")
        return 0

    clave = _leer_clave()
    problema = secreto.validar_clave(clave)
    if problema:
        return _err(f"Contraseña inválida: {problema}")
    if not secreto.guardar(cid, clave):
        return _err("No se pudo guardar la contraseña.")
    config.escribir(cid, carpeta.nombre, carpeta.ruta, config.MODO_FIJA)
    rutas.log(f"Contraseña actualizada: {carpeta.nombre}")
    proceso.refrescar()
    print("OK")
    return 0


def gui_remove(cid: str = "", *opciones: str) -> int:
    carpeta = config.leer(cid)
    if carpeta is None:
        return _err("Carpeta no encontrada.")
    secreto.borrar(cid)
    config.borrar(cid)
    if "--borrar-carpeta" in opciones and carpeta.ruta.is_dir():
        shutil.rmtree(carpeta.ruta, ignore_errors=True)
    rutas.log(f"Carpeta eliminada: {carpeta.nombre}")
    proceso.refrescar()
    print("OK")
    return 0


def gui_remove_all(*opciones: str) -> int:
    carpetas = config.listar()
    proceso.parar()
    for carpeta in carpetas:
        secreto.borrar(carpeta.id)
        config.borrar(carpeta.id)
    if "--borrar-carpetas" in opciones:
        for carpeta in carpetas:
            if carpeta.ruta.is_dir():
                shutil.rmtree(carpeta.ruta, ignore_errors=True)
    autostart.desactivar()
    try:
        rutas.log_file().unlink()
    except OSError:
        pass
    print("OK")
    return 0


def parar() -> int:
    """Detiene el vigilante. La usa el desinstalador antes de borrar ficheros."""
    proceso.parar()
    print("OK")
    return 0


# --- Entrada ----------------------------------------------------------------

def _abrir_gui() -> int:
    """Abre la ventana de gestión (gui.py, junto a este paquete o congelado)."""
    if getattr(sys, "frozen", False):
        # Desde el ejecutable de consola se abre el SIN consola, que es el que
        # tiene que quedarse con la ventana (y con el icono en la barra).
        try:
            subprocess.Popen(rutas.comando_gui(), close_fds=True)
        except OSError as error:
            print(f"No se pudo abrir la ventana: {error}", file=sys.stderr)
            return 1
        return 0
    guion = Path(__file__).resolve().parent.parent / "gui.py"
    if not guion.exists():
        print("No se encontró gui.py junto al paquete.", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(guion)])


ORDENES_GUI = {
    "--gui-listar": gui_listar,
    "--gui-estado": gui_estado,
    "--gui-asegurar": gui_asegurar,
    "--gui-add": gui_add,
    "--gui-rename": gui_rename,
    "--gui-set-pass": gui_set_pass,
    "--gui-remove": gui_remove,
    "--gui-remove-all": gui_remove_all,
}


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    if not argumentos or argumentos[0] == "--lanzar":
        return _abrir_gui()

    orden, *resto = argumentos
    if orden == "--vigilante":
        from . import vigilante
        return vigilante.main()
    if orden == "--parar":
        return parar()
    if orden in ("-h", "--ayuda", "--help"):
        print(AYUDA)
        return 0
    if orden in ORDENES_GUI:
        try:
            return ORDENES_GUI[orden](*resto)
        except TypeError:
            return _err(f"Argumentos incorrectos para {orden}.")
    print(f"Opción desconocida: {orden}", file=sys.stderr)
    print(AYUDA, file=sys.stderr)
    return 1
