"""El vigilante: cifra los PDF que aparecen en las carpetas configuradas.

Un solo proceso por usuario vigila **todas** sus carpetas (igual que el único
inotifywait del backend Debian). Vive como icono en el área de notificación,
que es lo que además permite sacar los avisos como notificaciones de Windows y
lo que hace visible que la herramienta está funcionando — algo que en los
puestos Debian queda a oscuras.

Reparto de trabajo:

- watchdog avisa de los ficheros nuevos y los deja en una cola, junto con los
  avisos de barrido de `proceso.pedir_barrido`;
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
from typing import NamedTuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import cifrar, config, espera, notificar, preguntar, proceso, rutas, secreto

COMPROBAR_PARADA_MS = 500
ESPERA_COLA = 0.5

# Contraseñas de lote del modo «preguntar»: en memoria y con caducidad.
_lote = preguntar.Lote()

# PDF que el lote omitió por estar en uso y de los que ya se avisó (por
# `_clave`). Su propio evento sigue en la cola: si falla, no se avisa otra vez.
_avisados_lote: set[str] = set()


class _DeBarrido(NamedTuple):
    """Un PDF que encontró un barrido, no un evento.

    Si está en uso no se le espera: no hay evento que lo vuelva a traer, y un
    PDF abierto en un visor retendría 60 s la cola entera. Con «avisar» se
    dice que se ha quedado sin cifrar.
    """

    ruta: Path
    avisar: bool


class _Manejador(FileSystemEventHandler):
    """Mete en la cola los PDF nuevos (creados o movidos a la carpeta)."""

    def __init__(self, cola: queue.Queue) -> None:
        self.cola = cola

    def on_created(self, event) -> None:  # noqa: ANN001 — API de watchdog
        self._quizas(event.src_path, event.is_directory)

    def on_moved(self, event) -> None:  # noqa: ANN001
        self._quizas(event.dest_path, event.is_directory)

    def _quizas(self, ruta: str | bytes, es_directorio: bool) -> None:
        if es_directorio:
            return
        camino = Path(os.fsdecode(ruta))
        if camino.suffix.lower() != ".pdf" or cifrar.es_oculto(camino.name):
            return
        # Los marcados «SIN-CIFRAR_» se ignoran: ese nombre se lo pusimos
        # nosotros, y el renombrado cuenta como fichero movido a la carpeta —
        # volveríamos a preguntar en bucle. Se recuperan en el lote del
        # próximo PDF que se suelte ahí.
        if preguntar.es_marcado(camino.name):
            return
        self.cola.put(camino)


class _ManejadorBarrido(FileSystemEventHandler):
    """Mete en la misma cola los avisos de barrido (`proceso.pedir_barrido`).

    Van a la cola de los PDF para que solo cifre el hilo trabajador.
    """

    def __init__(self, cola: queue.Queue) -> None:
        self.cola = cola

    def on_created(self, event) -> None:  # noqa: ANN001 — API de watchdog
        if not event.is_directory:
            self.cola.put(Path(os.fsdecode(event.src_path)))


def _clave(ruta: Path) -> str:
    texto = os.path.normpath(str(ruta))
    return os.path.normcase(texto) if rutas.ES_WINDOWS else texto


def _carpeta_de(ruta: Path, mapa: dict[str, config.Carpeta]) -> config.Carpeta | None:
    """¿A qué carpeta configurada pertenece este fichero?"""
    return mapa.get(_clave(ruta.parent))


def _atender(elemento: Path | _DeBarrido, cola: queue.Queue,
             mapa: dict[str, config.Carpeta]) -> None:
    """Lo que saca de la cola el hilo trabajador: un PDF, un PDF de un barrido
    o un aviso de barrido."""
    if isinstance(elemento, _DeBarrido):
        _procesar_de_barrido(elemento, mapa)
    elif _clave(elemento.parent) == _clave(rutas.barrer_dir()):
        _barrer_por_aviso(elemento.name, cola, mapa)
    else:
        _procesar(elemento, mapa)


def _barrer_por_aviso(cid: str, cola: queue.Queue,
                      mapa: dict[str, config.Carpeta]) -> None:
    """Aviso de barrido de la carpeta «cid»: encola sus PDF si sigue en «fija».

    Borrar el marcador hace de turno: si el aviso llega dos veces (el evento y
    el repaso del arranque), el segundo ya no lo encuentra y no barre. Si no
    se puede borrar, se barre igual: barrer de más no hace daño.
    """
    try:
        (rutas.barrer_dir() / cid).unlink()
    except FileNotFoundError:
        return
    except OSError:
        pass
    for carpeta in mapa.values():
        if carpeta.id != cid:
            continue
        actual = config.leer(cid)
        if actual is None or actual.pregunta:
            return
        rutas.log(f"Barrido a petición en «{carpeta.nombre}».")
        # El bash no avisa aquí, pero en Linux nada bloquea el PDF. En Windows
        # un visor sí, y después no llega ningún evento que lo recoja: sin
        # aviso quedaría en claro sin decirlo.
        for entrada in _pdfs_visibles(carpeta.ruta):
            cola.put(_DeBarrido(entrada, avisar=True))
        return


def _pdfs_visibles(carpeta: Path) -> list[Path]:
    """Los PDF de la carpeta, sin distinguir mayúsculas y sin los ocultos."""
    try:
        entradas = sorted(carpeta.iterdir())
    except OSError:
        return []
    return [e for e in entradas
            if e.is_file() and e.suffix.lower() == ".pdf"
            and not cifrar.es_oculto(e.name)]


def _ya_cifrado(ruta: Path) -> bool:
    """Como `cifrar.ya_cifrado`, pero un PDF ilegible cuenta como «no»: ese
    caso lo cuenta el intento de cifrado."""
    try:
        return cifrar.ya_cifrado(ruta)
    except cifrar.ErrorCifrado:
        return False


def _procesar_de_barrido(pendiente: _DeBarrido,
                         mapa: dict[str, config.Carpeta]) -> None:
    """Paridad con «barrer_carpeta» del bash: lo cifrado fuera, y lo que esté en
    uso se omite sin esperar (avisando si el barrido lo pide)."""
    ruta = pendiente.ruta
    if _carpeta_de(ruta, mapa) is None or not ruta.is_file() or _ya_cifrado(ruta):
        return
    if espera.bloqueado(ruta):
        rutas.log(f"Barrido: se omite, en uso por otro programa: {ruta}")
        if pendiente.avisar:
            notificar.error(
                "PDF SIN CIFRAR",
                f"No se cifró «{preguntar.recortar_nombre(ruta.name)}» porque "
                "estaba abierto en otro programa (o aún se copiaba).\n"
                "Se cifrará en el próximo inicio de sesión, o vuelve a soltarlo "
                "en la carpeta.")
        return
    _procesar(ruta, mapa)


def _procesar(ruta: Path, mapa: dict[str, config.Carpeta]) -> None:
    carpeta = _carpeta_de(ruta, mapa)
    if carpeta is None:
        return
    # Lo ya cifrado se descarta antes de esperar (~2 s por fichero), como el
    # bash, que mira «qpdf --is-encrypted» antes que lsof. Leer se puede aunque
    # otro lo tenga abierto, así que un PDF protegido abierto en un visor
    # tampoco espera.
    if _ya_cifrado(ruta):
        return
    if not espera.esperar_archivo(ruta):
        if _clave(ruta) in _avisados_lote:
            _avisados_lote.discard(_clave(ruta))
            rutas.log(f"Sigue en uso, ya avisado en el lote: {ruta}")
            return
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


def _cifrar_y_avisar(ruta: Path, clave: str, avisar: bool = True) -> bool:
    """Cifra un PDF y avisa del resultado. True si lo ha cifrado ahora.

    Los errores se avisan siempre; el éxito, solo con «avisar» (el lote da
    uno solo al final).
    """
    try:
        if not cifrar.cifrar_en_sitio(ruta, clave):
            return False
    except cifrar.ErrorCifrado as error:
        notificar.error("Error al cifrar PDF", str(error))
        return False
    _avisados_lote.discard(_clave(ruta))
    # Ya protegido: si venía marcado como sin cifrar, recupera su nombre limpio.
    final = preguntar.limpiar_prefijo(ruta)
    if avisar:
        notificar.info("PDF protegido", f"Cifrado correctamente:\n{final.name}")
    else:
        rutas.log(f"PDF protegido — Cifrado correctamente: {final.name}")
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

    # El texto del diálogo dice dónde está el PDF y cuántos hay pendientes, antes
    # de pedir nada: el título de la ventana se trunca.
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
        omitidos: list[Path] = []
        cifrados = 0
        for pendiente in pendientes:
            if not pendiente.is_file():
                continue
            # Bloqueado por otro proceso: si aún se copia, lo cifra su propio
            # evento; si lo tiene abierto un visor, solo habrá evento si llegó
            # en esta misma tanda.
            if (os.path.normcase(pendiente.name) != os.path.normcase(ruta.name)
                    and espera.bloqueado(pendiente)):
                rutas.log(f"Lote: se omite, en uso por otro programa: {pendiente}")
                omitidos.append(pendiente)
                continue
            cifrados += _cifrar_y_avisar(pendiente, clave, avisar=False)
        # Un solo aviso de éxito para todo el lote: Windows enseña los avisos de
        # uno en uno, unos 5 s cada uno, y un error posterior quedaba detrás de
        # la cola de «PDF protegido».
        if cifrados:
            plural = "s" if cifrados != 1 else ""
            notificar.info("PDF protegidos",
                           f"Protegido{plural} {cifrados} PDF en «{carpeta.nombre}».")
        # En Windows un visor bloquea el PDF y no se distingue de una copia en
        # curso: mejor un aviso de más que un PDF en claro sin decirlo.
        for omitido in omitidos:
            if omitido.is_file():
                _avisados_lote.add(_clave(omitido))
                notificar.error(
                    "Cifrar PDF",
                    f"«{preguntar.recortar_nombre(omitido.name)}» sigue abierto "
                    "en otro programa (o aún se copia) y de momento no se ha "
                    "cifrado.\nCiérralo: si en un minuto no ves «PDF protegido», "
                    "vuelve a soltarlo en la carpeta.")
        return

    _cifrar_y_avisar(ruta, clave)


def _avisar_sin_cifrar(ruta: Path, nombre_carpeta: str = "") -> None:
    """Deja constancia, en el nombre y en un aviso, de que NO se ha cifrado.

    El nombre se recorta y se dice una sola vez: entero y repetido estiraba el
    cuadro.
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
    # Orden distinto del bash: el globo de Windows solo enseña las primeras
    # líneas, así que lo que hay que hacer va antes que el porqué del prefijo.
    notificar.error(
        "PDF SIN CIFRAR",
        f"«{corto}» NO está protegido.\n{donde}\n"
        "Le he puesto delante «SIN-CIFRAR_» para que no se te pase.")


def _trabajador(cola: queue.Queue, mapa: dict[str, config.Carpeta],
                parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            elemento = cola.get(timeout=ESPERA_COLA)
        except queue.Empty:
            continue
        try:
            _atender(elemento, cola, mapa)
        except Exception as error:  # noqa: BLE001 — el vigilante no se cae por un PDF
            ruta = elemento.ruta if isinstance(elemento, _DeBarrido) else elemento
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


def _encolar_existentes(cola: queue.Queue, mapa: dict[str, config.Carpeta]) -> None:
    """Barrido inicial: los PDF que ya estaban dentro también se cifran.

    Las carpetas en modo «preguntar» se saltan a propósito: nadie quiere que
    al iniciar sesión le salten diálogos de contraseña. Lo que quedara dentro
    se recupera en el lote del próximo PDF que se suelte ahí.

    Una carpeta fija sin contraseña se vigila igual pero no se barre: se barre
    cuando se la pongan, por aviso (`proceso.pedir_barrido`).
    """
    for carpeta in mapa.values():
        if carpeta.pregunta:
            rutas.log(f"Sin barrido inicial en «{carpeta.nombre}»: "
                      "no se pregunta hasta que se suelte un PDF.")
            continue
        if not secreto.tiene_clave(carpeta.id):
            rutas.log(f"Sin barrido inicial en «{carpeta.nombre}»: "
                      "no tiene contraseña guardada.")
            continue
        for entrada in _pdfs_visibles(carpeta.ruta):
            cola.put(_DeBarrido(entrada, avisar=True))


def _borrar_marcadores() -> None:
    try:
        marcadores = list(rutas.barrer_dir().iterdir())
    except OSError:
        return
    for marcador in marcadores:
        try:
            marcador.unlink()
        except OSError:
            pass


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
    # Los avisos de barrido pendientes los cubre el barrido inicial. Se borran
    # ANTES de leer las carpetas: uno que llegue después se atiende abajo.
    _borrar_marcadores()
    mapa = _preparar_carpetas()
    if not mapa:
        rutas.log("Ninguna carpeta utilizable: saliendo.")
        return 0

    cola: queue.Queue = queue.Queue()
    parar = threading.Event()
    hilo = threading.Thread(target=_trabajador, args=(cola, mapa, parar),
                            name="cifrador", daemon=True)
    hilo.start()

    observador = Observer()
    manejador = _Manejador(cola)
    for carpeta in mapa.values():
        observador.schedule(manejador, str(carpeta.ruta), recursive=False)
    barrer = rutas.barrer_dir()
    observador.schedule(_ManejadorBarrido(cola), str(barrer), recursive=False)
    observador.start()

    _encolar_existentes(cola, mapa)

    # Avisos que llegaron mientras arrancaba, antes de que vigilara el observador.
    try:
        pendientes = sorted(barrer.iterdir())
    except OSError:
        pendientes = []
    for marcador in pendientes:
        _barrer_por_aviso(marcador.name, cola, mapa)

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
    _instalar_traductor(aplicacion)
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
        # Primero se da de baja quien atiende diálogos y avisos: lo siguiente
        # que pida el hilo cifrador iría a un bucle que ya no despacha y el
        # proceso saldría con el PDF en claro, sin marcar.
        preguntar.registrar_atendedor(None)
        notificar.registrar_emisor(None)
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
                    _ensanchar_etiqueta(etiqueta)
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


def _ensanchar_etiqueta(etiqueta) -> None:  # noqa: ANN001 — QLabel
    """Ajusta la etiqueta del diálogo de contraseña: varias líneas y ancho mínimo.

    El ancho va en la etiqueta: el del diálogo lo pisa su layout
    (SetMinAndMaxSize) al mostrarse. Se mide en alturas de línea, como
    `_dimensionar` de gui.py, y no en caracteres: la letra media de Segoe UI
    es estrecha y 50 caracteres dejaban el diálogo en 322 px en Windows,
    aunque con DejaVu en Linux salieran 422.
    """
    etiqueta.setWordWrap(True)
    etiqueta.setMinimumWidth(etiqueta.fontMetrics().height() * 26)


def _instalar_traductor(aplicacion):  # noqa: ANN001, ANN202 — QApplication → QTranslator | None
    """Botones estándar de Qt («Aceptar», «Sí»…) en castellano.

    En KDE los traduce plasma-integration; en Windows nadie. Se fuerza el
    español aunque Windows esté en inglés: toda la interfaz está en castellano.
    Primero donde dice Qt y luego donde lo deja PyInstaller.
    """
    import PyQt6
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    traductor = QTranslator(aplicacion)
    espanol = QLocale(QLocale.Language.Spanish, QLocale.Country.Spain)
    for directorio in (QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
                       str(Path(PyQt6.__file__).parent / "Qt6" / "translations")):
        if traductor.load(espanol, "qtbase", "_", directorio):
            aplicacion.installTranslator(traductor)
            return traductor
    rutas.log("AVISO: no se encontró la traducción de Qt; "
              "los botones estándar saldrán en inglés.")
    return None


def _ruta_icono() -> Path:
    """El icono empaquetado (PyInstaller lo deja junto al ejecutable)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "recursos" / "cifrarpdf.png"
