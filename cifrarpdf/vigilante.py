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

from . import cifrar, config, espera, notificar, preguntar, proceso, rutas, secreto

COMPROBAR_PARADA_MS = 500
ESPERA_COLA = 0.5

# Contraseñas de lote del modo «preguntar»: en memoria y con caducidad.
_lote = preguntar.Lote()


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
        # Los marcados «SIN-CIFRAR_» se ignoran: ese nombre se lo pusimos
        # nosotros, y el renombrado cuenta como fichero movido a la carpeta —
        # volveríamos a preguntar en bucle. Se recuperan en el lote del
        # próximo PDF que se suelte ahí.
        if preguntar.es_marcado(camino.name):
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
    # El modo se lee del disco en el momento de cifrar, no al arrancar: así
    # cambiarlo desde la ventana surte efecto sin reiniciar el vigilante.
    actual = config.leer(carpeta.id) or carpeta
    if actual.pregunta:
        _procesar_preguntando(ruta, actual)
        return
    clave = secreto.leer(carpeta.id)
    if not clave:
        notificar.error(
            "Cifrar PDF",
            f"La carpeta «{carpeta.nombre}» no tiene contraseña guardada, así que "
            f"«{ruta.name}» se ha quedado SIN cifrar.\nAbre «Cifrar PDF» y ponle una.",
        )
        return
    _cifrar_y_avisar(ruta, clave)


def _cifrar_y_avisar(ruta: Path, clave: str) -> bool:
    """Cifra un PDF y avisa del resultado. False si no se pudo."""
    try:
        if not cifrar.cifrar_en_sitio(ruta, clave):
            return True
    except cifrar.ErrorCifrado as error:
        notificar.error("Error al cifrar PDF", str(error))
        return False
    # Ya protegido: si venía marcado como sin cifrar, recupera su nombre limpio.
    final = preguntar.limpiar_prefijo(ruta)
    notificar.info("PDF protegido", f"Cifrado correctamente:\n{final.name}")
    return True


def _procesar_preguntando(ruta: Path, carpeta: config.Carpeta) -> None:
    """Modo «preguntar cada vez»: la contraseña se pide ahora, al cifrar."""
    # Guarda imprescindible ANTES de molestar a nadie: un PDF que ya está
    # cifrado no puede provocar un diálogo.
    try:
        if cifrar.ya_cifrado(ruta):
            rutas.log(f"Ya cifrado, se omite: {ruta}")
            return
    except cifrar.ErrorCifrado as error:
        # Ilegible: no tiene sentido pedir una contraseña para un PDF que
        # después no se va a poder cifrar igualmente.
        notificar.error("Error al cifrar PDF", str(error))
        return

    titulo = f"Cifrar PDF — {carpeta.nombre}"

    # Lote en curso: se reutiliza la contraseña sin volver a preguntar.
    clave = _lote.vigente(carpeta.id)
    if clave:
        _cifrar_y_avisar(ruta, clave)
        return

    if not preguntar.hay_atendedor():
        rutas.log("Sin interfaz para preguntar la contraseña: "
                  f"se marca sin cifrar {ruta.name}")
        _avisar_sin_cifrar(ruta, carpeta.nombre)
        return

    # Se mira cuántos hay antes de preguntar: si se soltaron varios de golpe,
    # ya están todos en el disco y se puede ofrecer una sola contraseña.
    pendientes = preguntar.pendientes_sin_cifrar(carpeta.ruta)

    # El texto del diálogo dice DÓNDE está el PDF y cuántos hay pendientes.
    # Antes la carpeta solo aparecía en el título de la ventana (que se trunca
    # y que mucha gente no lee) y el recuento del lote se mencionaba DESPUÉS de
    # teclear la contraseña dos veces, así que se decidía a ciegas.
    corto = preguntar.recortar_nombre(ruta.name)
    contexto = ""
    if len(pendientes) > 1:
        contexto = (f"\nEn esta carpeta hay {len(pendientes)} PDF sin proteger; "
                    "luego te pregunto si quieres usar la misma contraseña "
                    "para todos.")
    pedir = (f"Carpeta «{carpeta.nombre}».\n"
             f"Contraseña para proteger «{corto}» "
             f"(mínimo {secreto.MIN_CLAVE} caracteres).{contexto}")

    clave, motivo = preguntar.pedir_clave_confirmada(titulo, pedir)
    if not clave:
        preguntar.avisar(
            titulo,
            f"{preguntar.texto_motivo(motivo)}\n"
            "Vamos a intentarlo una última vez; si no, el PDF se quedará "
            "SIN proteger.")
        clave, _motivo = preguntar.pedir_clave_confirmada(
            titulo, f"{pedir}\n(Último intento.)")
    if not clave:
        _avisar_sin_cifrar(ruta, carpeta.nombre)
        return

    if len(pendientes) > 1 and preguntar.confirmar(
            titulo,
            f"En «{carpeta.nombre}» hay {len(pendientes)} PDF sin proteger:\n"
            f"{preguntar.lista_pendientes(pendientes)}\n"
            "¿Uso esta misma contraseña para todos?"):
        _lote.guardar(carpeta.id, clave)
        rutas.log(f"Lote de {len(pendientes)} PDF con una sola contraseña en "
                  f"«{carpeta.nombre}» (reuso {preguntar.REUSO_TTL:.0f} s).")
        for pendiente in pendientes:
            if pendiente.is_file():
                _cifrar_y_avisar(pendiente, clave)
        return

    _cifrar_y_avisar(ruta, clave)


def _avisar_sin_cifrar(ruta: Path, nombre_carpeta: str = "") -> None:
    """Deja constancia, en el nombre y en un aviso, de que NO se ha cifrado.

    El nombre del fichero se recorta y se dice UNA sola vez: antes salía
    entero y dos veces en el mismo aviso, que es lo que estiraba el cuadro.
    """
    corto = preguntar.recortar_nombre(ruta.name)
    if nombre_carpeta:
        donde = (f"Sigue en la carpeta «{nombre_carpeta}»: suelta ahí "
                 "cualquier PDF y te volveré a pedir la contraseña para "
                 "protegerlos todos, este incluido.")
    else:
        donde = ("Sigue en su carpeta: suelta ahí cualquier PDF y te volveré "
                 "a pedir la contraseña para protegerlos todos, este incluido.")

    if preguntar.es_marcado(ruta.name):
        notificar.error("PDF SIN CIFRAR",
                        f"«{corto}» sigue SIN proteger.\n{donde}")
        return
    destino = preguntar.marcar_sin_cifrar(ruta)
    if destino == ruta:
        notificar.error("PDF SIN CIFRAR",
                        f"«{corto}» NO está protegido.\n{donde}")
        return
    notificar.error(
        "PDF SIN CIFRAR",
        f"«{corto}» NO está protegido.\n"
        "Le he puesto delante «SIN-CIFRAR_» para que no se te pase.\n"
        f"{donde}")


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
        # En «preguntar» no hay contraseña guardada A PROPÓSITO: avisar de que
        # falta sería una falsa alarma.
        if not carpeta.pregunta and not secreto.tiene_clave(carpeta.id):
            notificar.error(
                "Cifrar PDF — sin contraseña",
                f"La carpeta «{carpeta.nombre}» no tiene contraseña guardada.\n"
                "Abre «Cifrar PDF» y ponle una: hasta entonces sus PDF no se cifran.",
            )
        mapa[_clave(carpeta.ruta)] = carpeta
        rutas.log(f"Vigilando: {carpeta.nombre} → {carpeta.ruta} "
                  f"(modo: {carpeta.modo})")
    return mapa


def _encolar_existentes(cola: queue.Queue[Path], mapa: dict[str, config.Carpeta]) -> None:
    """Barrido inicial: los PDF que ya estaban dentro también se cifran.

    Las carpetas en modo «preguntar» se saltan a propósito: nadie quiere que
    al iniciar sesión le salten diálogos de contraseña. Lo que quedara dentro
    se recupera en el lote del próximo PDF que se suelte ahí.
    """
    for carpeta in mapa.values():
        if carpeta.pregunta:
            rutas.log(f"Sin barrido inicial en «{carpeta.nombre}»: "
                      "no se pregunta hasta que se suelte un PDF.")
            continue
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

    try:
        codigo = _esperar_parada()
    finally:
        notificar.registrar_emisor(None)
        preguntar.registrar_atendedor(None)
        parar.set()
        observador.stop()
        observador.join(2)
        hilo.join(5)
        rutas.log("Vigilancia detenida.")
    return codigo


def _esperar_parada() -> int:
    """Se queda esperando hasta que alguien pida la parada.

    Con icono en el área de notificación si se puede, y sin él si no. **Cifrar no
    puede depender de que haya bandeja**: el icono es una comodidad (avisos y
    saber que está funcionando), no la función de la herramienta. Si montar la
    interfaz falla —una sesión sin escritorio, un perfil raro, Qt que no
    arranca—, se sigue vigilando igual y se deja dicho en el registro.

    Esto no es teórico: en el CI (que corre sin sesión de escritorio) el proceso
    se quedaba colgado montando la bandeja y sobrevivía a la petición de parada,
    apareciendo como «Terminate orphan process: CifrarPDF» al final del trabajo.
    """
    if os.environ.get("CIFRARPDF_SIN_BANDEJA") == "1":
        rutas.log("CIFRARPDF_SIN_BANDEJA=1: se vigila sin icono en la bandeja.")
        return _bucle_simple()
    try:
        return _bucle_con_bandeja()
    except Exception as error:  # noqa: BLE001 — cualquier fallo de Qt cae al bucle simple
        rutas.log(f"AVISO: no se pudo montar el icono del área de notificación "
                  f"({error}); se sigue vigilando sin él.")
        return _bucle_simple()


def _bucle_simple() -> int:
    """Espera la parada sin interfaz. Los avisos van solo al registro.

    Sin Qt no hay ventana que mostrar, así que tampoco se puede preguntar
    ninguna contraseña: las carpetas en modo «preguntar» dejarán sus PDF
    marcados «SIN-CIFRAR_». Queda dicho en el registro para que no parezca que
    la herramienta los ha perdido.
    """
    if any(c.pregunta for c in config.listar()):
        rutas.log("AVISO: sin interfaz gráfica no se puede preguntar la "
                  "contraseña; esas carpetas dejarán los PDF sin cifrar.")
    while not proceso.parada_pedida(COMPROBAR_PARADA_MS):
        pass
    return 0


def _bucle_con_bandeja() -> int:
    """Icono en el área de notificación, su menú y los avisos del sistema."""
    from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QAction, QIcon
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QSystemTrayIcon,
    )

    class Puente(QObject):
        """Pasa al hilo de Qt lo que el hilo trabajador no puede hacer.

        Qt solo construye ventanas en el hilo principal, así que tanto los
        avisos como los diálogos de contraseña del modo «preguntar» viajan por
        aquí. La conexión entre hilos es en cola, de modo que el cuerpo de los
        manejadores se ejecuta ya en el hilo de Qt.
        """

        aviso = pyqtSignal(str, str, bool)
        peticion = pyqtSignal(object)

    aplicacion = QApplication(sys.argv)
    aplicacion.setApplicationName("Cifrar PDF")
    aplicacion.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        # Sin área de notificación, la ventana de Qt no aporta nada: mejor el
        # bucle simple, que no depende de que haya un escritorio vivo.
        rutas.log("No hay área de notificación disponible: se vigila sin icono.")
        return _bucle_simple()

    icono = QIcon(str(_ruta_icono()))
    bandeja = QSystemTrayIcon(icono)
    bandeja.setToolTip("Cifrar PDF — vigilando tus carpetas")
    menu = QMenu()
    accion_gestion = QAction("Gestionar carpetas…", menu)
    accion_gestion.triggered.connect(_abrir_gestion)
    accion_registro = QAction("Ver registro", menu)
    accion_registro.triggered.connect(_abrir_registro)
    accion_salir = QAction("Detener el vigilante", menu)
    accion_salir.triggered.connect(lambda: salir())
    menu.addAction(accion_gestion)
    menu.addAction(accion_registro)
    menu.addSeparator()
    menu.addAction(accion_salir)
    bandeja.setContextMenu(menu)
    bandeja.activated.connect(
        lambda motivo: _abrir_gestion()
        if motivo == QSystemTrayIcon.ActivationReason.DoubleClick else None
    )
    bandeja.show()

    puente = Puente()
    puente.aviso.connect(
        lambda titulo, texto, es_error: bandeja.showMessage(
            titulo, texto, QSystemTrayIcon.MessageIcon.Critical if es_error
            else QSystemTrayIcon.MessageIcon.Information, 8000)
    )
    notificar.registrar_emisor(
        lambda titulo, texto, es_error: puente.aviso.emit(titulo, texto, es_error)
    )

    # Diálogos abiertos ahora mismo. Hacen falta porque «exec()» abre un bucle
    # de eventos ANIDADO: «quit()» solo termina el principal, así que con un
    # diálogo de contraseña delante «Detener el vigilante» no cerraría nada
    # hasta que alguien lo contestara (o pasaran sus 3 minutos).
    abiertos = []

    def salir() -> None:
        for dialogo in list(abiertos):
            dialogo.reject()
        aplicacion.quit()

    def _mostrar(dialogo):  # noqa: ANN001, ANN202 — QDialog
        abiertos.append(dialogo)
        try:
            return dialogo.exec()
        finally:
            abiertos.remove(dialogo)

    def atender(peticion) -> None:  # noqa: ANN001 — preguntar.Peticion
        """Muestra el diálogo que pide el hilo trabajador y guarda su respuesta.

        Los diálogos se cierran solos pasado su plazo: el vigilante es un
        proceso de fondo y un PDF soltado y olvidado no puede dejar la cola
        parada para siempre. Van «siempre encima» porque quien suelta el PDF
        está mirando otra ventana (el explorador, el visor) y un diálogo de una
        aplicación de la bandeja se queda detrás con facilidad.
        """
        def caducar(dialogo) -> None:  # noqa: ANN001 — QDialog
            # Se deja dicho ANTES de cerrar: quien espera necesita distinguir
            # «nadie estaba delante» de «han pulsado Cancelar», porque el
            # aviso siguiente le echa la culpa a uno o a otro.
            peticion.caducada = True
            dialogo.reject()

        try:
            if peticion.tipo == "pedir":
                dialogo = QInputDialog()
                dialogo.setWindowTitle(peticion.titulo)
                dialogo.setLabelText(peticion.texto)
                dialogo.setTextEchoMode(QLineEdit.EchoMode.Password)
                dialogo.setWindowIcon(icono)
                dialogo.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                # El texto lleva varias líneas (carpeta, fichero, cuántos hay
                # pendientes) y puede traer un nombre largo: sin wordWrap la
                # etiqueta estira el diálogo a lo ancho hasta salirse de la
                # pantalla, dejando los botones fuera.
                etiqueta = dialogo.findChild(QLabel)
                if etiqueta is not None:
                    etiqueta.setWordWrap(True)
                dialogo.setMinimumWidth(420)
                QTimer.singleShot(int(preguntar.ESPERA_PREGUNTA * 1000),
                                  lambda: caducar(dialogo))
                aceptado = _mostrar(dialogo) == QDialog.DialogCode.Accepted
                peticion.resultado = dialogo.textValue() if aceptado else None
            elif peticion.tipo == "confirmar":
                caja = QMessageBox(QMessageBox.Icon.Question, peticion.titulo,
                                   peticion.texto,
                                   QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
                caja.setWindowIcon(icono)
                caja.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                QTimer.singleShot(120_000, lambda: caducar(caja))
                peticion.resultado = (
                    _mostrar(caja) == QMessageBox.StandardButton.Yes)
            else:
                caja = QMessageBox(QMessageBox.Icon.Warning, peticion.titulo,
                                   peticion.texto,
                                   QMessageBox.StandardButton.Ok)
                caja.setWindowIcon(icono)
                caja.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                QTimer.singleShot(60_000, lambda: caducar(caja))
                _mostrar(caja)
                peticion.resultado = True
        finally:
            # Pase lo que pase, el hilo trabajador tiene que despertar: si no,
            # se quedaría esperando hasta agotar el plazo por nada.
            peticion.atendida.set()

    puente.peticion.connect(atender)
    preguntar.registrar_atendedor(puente.peticion.emit)

    temporizador = QTimer()
    temporizador.setInterval(COMPROBAR_PARADA_MS)
    temporizador.timeout.connect(
        lambda: salir() if proceso.parada_pedida(0) else None
    )
    temporizador.start()
    return aplicacion.exec()


def _ruta_icono() -> Path:
    """El icono empaquetado (PyInstaller lo deja junto al ejecutable)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "recursos" / "cifrarpdf.png"
