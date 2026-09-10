"""El vigilante: cifra los PDF que aparecen en las carpetas configuradas.

Un solo proceso por usuario vigila **todas** sus carpetas (igual que el único
inotifywait del backend Debian). Vive como icono en el área de notificación,
que es lo que además permite sacar los avisos como notificaciones de Windows y
lo que hace visible que la herramienta está funcionando — algo que en los
puestos Debian queda a oscuras.

Reparto de trabajo:

- watchdog avisa de los ficheros nuevos y los deja en una cola;
- un hilo trabajador espera a que cada PDF esté completo y lo cifra, para que
  un PDF grande no atasque la detección de los siguientes;
- el hilo principal es el de Qt (icono, menú y notificaciones) y comprueba cada
  medio segundo si alguien ha pedido la parada.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import cifrar, config, espera, notificar, proceso, rutas, secreto

COMPROBAR_PARADA_MS = 500
ESPERA_COLA = 0.5


class _Manejador(FileSystemEventHandler):
    """Mete en la cola los PDF nuevos (creados o movidos a la carpeta)."""

    def __init__(self, cola: queue.Queue[Path]) -> None:
        self.cola = cola

    def on_created(self, event) -> None:  # noqa: ANN001 — API de watchdog
        self._quizas(event.src_path, event.is_directory)

    def on_moved(self, event) -> None:  # noqa: ANN001
        self._quizas(event.dest_path, event.is_directory)

    def _quizas(self, ruta: str | bytes, es_directorio: bool) -> None:
        if es_directorio:
            return
        camino = Path(os.fsdecode(ruta))
        if camino.suffix.lower() != ".pdf" or cifrar.es_temporal(camino.name):
            return
        self.cola.put(camino)


def _clave(ruta: Path) -> str:
    texto = os.path.normpath(str(ruta))
    return os.path.normcase(texto) if rutas.ES_WINDOWS else texto


def _carpeta_de(ruta: Path, mapa: dict[str, config.Carpeta]) -> config.Carpeta | None:
    """¿A qué carpeta configurada pertenece este fichero?"""
    return mapa.get(_clave(ruta.parent))


def _procesar(ruta: Path, mapa: dict[str, config.Carpeta]) -> None:
    carpeta = _carpeta_de(ruta, mapa)
    if carpeta is None:
        return
    if not espera.esperar_archivo(ruta):
        notificar.error(
            "Cifrar PDF",
            f"«{ruta.name}» no terminó de copiarse (o sigue abierto en otro "
            "programa), así que no se ha cifrado.\nVuelve a soltarlo cuando esté listo.",
        )
        return
    clave = secreto.leer(carpeta.id)
    if not clave:
        notificar.error(
            "Cifrar PDF",
            f"La carpeta «{carpeta.nombre}» no tiene contraseña guardada, así que "
            f"«{ruta.name}» se ha quedado SIN cifrar.\nAbre «Cifrar PDF» y ponle una.",
        )
        return
    try:
        if cifrar.cifrar_en_sitio(ruta, clave):
            notificar.info("PDF protegido", f"Cifrado correctamente:\n{ruta.name}")
    except cifrar.ErrorCifrado as error:
        notificar.error("Error al cifrar PDF", str(error))


def _trabajador(cola: queue.Queue[Path], mapa: dict[str, config.Carpeta],
                parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            ruta = cola.get(timeout=ESPERA_COLA)
        except queue.Empty:
            continue
        try:
            _procesar(ruta, mapa)
        except Exception as error:  # noqa: BLE001 — el vigilante no se cae por un PDF
            notificar.error("Error al cifrar PDF",
                            f"Fallo inesperado con «{ruta.name}»: {error}")
        finally:
            cola.task_done()


def _preparar_carpetas() -> dict[str, config.Carpeta]:
    mapa: dict[str, config.Carpeta] = {}
    for carpeta in config.listar():
        try:
            carpeta.ruta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            notificar.error("Cifrar PDF",
                            f"No se pudo abrir la carpeta «{carpeta.nombre}»: {error}")
            continue
        cifrar.limpiar_temporales(carpeta.ruta)
        if not secreto.tiene_clave(carpeta.id):
            notificar.error(
                "Cifrar PDF — sin contraseña",
                f"La carpeta «{carpeta.nombre}» no tiene contraseña guardada.\n"
                "Abre «Cifrar PDF» y ponle una: hasta entonces sus PDF no se cifran.",
            )
        mapa[_clave(carpeta.ruta)] = carpeta
        rutas.log(f"Vigilando: {carpeta.nombre} → {carpeta.ruta}")
    return mapa


def _encolar_existentes(cola: queue.Queue[Path], mapa: dict[str, config.Carpeta]) -> None:
    """Barrido inicial: los PDF que ya estaban dentro también se cifran."""
    for carpeta in mapa.values():
        try:
            for entrada in sorted(carpeta.ruta.iterdir()):
                if (entrada.is_file() and entrada.suffix.lower() == ".pdf"
                        and not cifrar.es_temporal(entrada.name)):
                    cola.put(entrada)
        except OSError:
            continue


def _abrir_gestion() -> None:
    try:
        subprocess.Popen(rutas.comando_gui(), close_fds=True)
    except OSError as error:
        rutas.log(f"ERROR al abrir la ventana de gestión: {error}")


def _abrir_registro() -> None:
    fichero = rutas.log_file()
    try:
        if rutas.ES_WINDOWS:
            os.startfile(fichero)  # noqa: S606 — abre el registro con el visor del sistema
        else:
            subprocess.Popen(["xdg-open", str(fichero)], close_fds=True)
    except OSError as error:
        rutas.log(f"ERROR al abrir el registro: {error}")


def main() -> int:
    try:
        with proceso.Vigilancia():
            return _ejecutar()
    except proceso.YaEnMarcha:
        rutas.log("Ya hay un vigilante en marcha para este usuario. Saliendo.")
        return 0


def _ejecutar() -> int:
    rutas.rotar_log()
    if not config.hay_carpetas():
        rutas.log("No hay carpetas configuradas: el vigilante no arranca.")
        return 0

    rutas.log("Iniciando vigilancia (multi-carpeta).")
    mapa = _preparar_carpetas()
    if not mapa:
        rutas.log("Ninguna carpeta utilizable: saliendo.")
        return 0

    from PyQt6.QtCore import QObject, QTimer, pyqtSignal
    from PyQt6.QtGui import QAction, QIcon
    from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    class Puente(QObject):
        """Pasa los avisos del hilo trabajador al hilo de Qt."""

        aviso = pyqtSignal(str, str, bool)

    aplicacion = QApplication(sys.argv)
    aplicacion.setApplicationName("Cifrar PDF")
    aplicacion.setQuitOnLastWindowClosed(False)

    icono = QIcon(str(_ruta_icono()))
    bandeja = QSystemTrayIcon(icono)
    bandeja.setToolTip("Cifrar PDF — vigilando tus carpetas")
    menu = QMenu()
    accion_gestion = QAction("Gestionar carpetas…", menu)
    accion_gestion.triggered.connect(_abrir_gestion)
    accion_registro = QAction("Ver registro", menu)
    accion_registro.triggered.connect(_abrir_registro)
    accion_salir = QAction("Detener el vigilante", menu)
    accion_salir.triggered.connect(aplicacion.quit)
    menu.addAction(accion_gestion)
    menu.addAction(accion_registro)
    menu.addSeparator()
    menu.addAction(accion_salir)
    bandeja.setContextMenu(menu)
    bandeja.activated.connect(
        lambda motivo: _abrir_gestion()
        if motivo == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    if QSystemTrayIcon.isSystemTrayAvailable():
        bandeja.show()
    else:
        rutas.log("AVISO: no hay área de notificación; los avisos solo irán al registro.")

    puente = Puente()
    puente.aviso.connect(
        lambda titulo, texto, es_error: bandeja.showMessage(
            titulo, texto, QSystemTrayIcon.MessageIcon.Critical if es_error
            else QSystemTrayIcon.MessageIcon.Information, 8000)
    )
    notificar.registrar_emisor(
        lambda titulo, texto, es_error: puente.aviso.emit(titulo, texto, es_error)
    )

    cola: queue.Queue[Path] = queue.Queue()
    parar = threading.Event()
    hilo = threading.Thread(target=_trabajador, args=(cola, mapa, parar),
                            name="cifrador", daemon=True)
    hilo.start()

    observador = Observer()
    manejador = _Manejador(cola)
    for carpeta in mapa.values():
        observador.schedule(manejador, str(carpeta.ruta), recursive=False)
    observador.start()

    _encolar_existentes(cola, mapa)

    temporizador = QTimer()
    temporizador.setInterval(COMPROBAR_PARADA_MS)
    temporizador.timeout.connect(
        lambda: aplicacion.quit() if proceso.parada_pedida(0) else None
    )
    temporizador.start()

    codigo = aplicacion.exec()

    notificar.registrar_emisor(None)
    parar.set()
    observador.stop()
    observador.join(2)
    hilo.join(5)
    rutas.log("Vigilancia detenida.")
    return codigo


def _ruta_icono() -> Path:
    """El icono empaquetado (PyInstaller lo deja junto al ejecutable)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "recursos" / "cifrarpdf.png"
