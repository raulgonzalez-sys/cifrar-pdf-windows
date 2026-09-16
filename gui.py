#!/usr/bin/env python3
# fisat-cifrar-pdf-gui — interfaz gráfica (PyQt6) para gestionar las carpetas
# de cifrado de «Cifrar PDF».
#
# Es SOLO un frontend: toda la lógica (KWallet, vigilante, slugificado,
# autostart…) vive en el script bash fisat-cifrar-pdf, al que esta ventana
# llama por subcomandos «--gui-*». La contraseña va por stdin, nunca como
# argumento visible en «ps» — así no se duplica nada y hay una sola fuente
# de verdad.
#
# Si PyQt6 no está disponible, el bash (--lanzar) ni la invoca: cae a kdialog
# o a la TUI por su cuenta.
#
# Esta versión DERIVA de archivos/fisat-cifrar-pdf-gui de la repo
# debian13-fisat, pero es un FORK: allí la interfaz no lleva las ramas
# ES_WINDOWS de más abajo. Una mejora de interfaz hay que hacerla en las dos
# copias, a mano; ver GUI_SYNC.md y herramientas/comparar_gui.py.

import os
import shutil
import subprocess
import sys

try:
    from PyQt6.QtCore import (
        Qt, QSize, QFileSystemWatcher, QSettings, QTimer, pyqtSignal,
    )
    from PyQt6.QtGui import (
        QAction, QFontDatabase, QIcon, QKeySequence, QPainter, QPalette,
    )
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame,
        QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
        QPushButton, QRadioButton, QSizePolicy, QStyle, QToolBar, QToolButton,
        QVBoxLayout, QWidget,
    )
except ImportError:
    sys.stderr.write(
        "fisat-cifrar-pdf-gui: falta PyQt6 (paquete python3-pyqt6).\n"
    )
    sys.exit(1)

ES_WINDOWS = sys.platform.startswith("win")

APP_TITLE = "Cifrar PDF — FISAT"
MIN_PASS = 8

# Único punto del fichero que decide sistema: en Debian el backend es el script
# bash del PATH; en Windows, el propio ejecutable (o «python -m cifrarpdf» al
# desarrollar), que atiende exactamente los mismos subcomandos --gui-*.
if ES_WINDOWS:
    from cifrarpdf import rutas as _rutas

    def comando_backend():
        return _rutas.comando_backend()

    LOG_FILE = str(_rutas.log_file())
    CARPETAS_DIR = str(_rutas.carpetas_dir())
    ICONO_APP = os.path.join(
        getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
        "recursos", "cifrarpdf.png")
else:
    def comando_backend():
        return ["fisat-cifrar-pdf"]

    _cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    LOG_FILE = os.path.join(_cfg, "fisat", "cifrar-pdf.log")
    CARPETAS_DIR = os.path.join(_cfg, "fisat", "cifrar-pdf.d")
    ICONO_APP = None

# En Windows, sin este indicador cada llamada al backend abriría y cerraría una
# consola: un parpadeo negro en pantalla en cada refresco de la lista.
_SIN_CONSOLA = {"creationflags": 0x08000000} if ES_WINDOWS else {}


# Windows no trae tema de iconos, así que QIcon.fromTheme devuelve vacío. Se
# cae a los iconos estándar de Qt (los del propio sistema) por equivalencia de
# nombre. Los que no tienen equivalente razonable se quedan SIN icono a
# propósito: la barra de herramientas muestra siempre el texto de la acción, así
# que un botón sin icono se entiende igual, y eso es mejor que colar un icono
# que no pega.
_ESTANDAR = {
    "list-add": "SP_FileDialogNewFolder",
    "list-remove": "SP_DialogDiscardButton",
    "edit-delete-shred": "SP_TrashIcon",
    "trash-empty": "SP_TrashIcon",
    "folder": "SP_DirIcon",
    "folder-open": "SP_DirOpenIcon",
    "folder-red": "SP_MessageBoxWarning",
    "view-refresh": "SP_BrowserReload",
    "view-list-text": "SP_FileDialogContentsView",
    "dialog-close": "SP_DialogCloseButton",
    "edit-clear-history": "SP_DialogResetButton",
    "object-locked": "SP_VistaShield",
    "dialog-password": "SP_VistaShield",
}


def _icono_estandar(nombre):
    clave = _ESTANDAR.get(nombre)
    app = QApplication.instance()
    if not clave or app is None:
        return QIcon()
    estandar = getattr(QStyle.StandardPixmap, clave, None)
    return app.style().standardIcon(estandar) if estandar is not None else QIcon()


def tema(nombre, *alternativos):
    """QIcon del tema (Breeze) con alternativas por si falta un nombre."""
    ic = QIcon.fromTheme(nombre)
    for alt in alternativos:
        if ic.isNull():
            ic = QIcon.fromTheme(alt)
    if ic.isNull() and ES_WINDOWS:
        for candidato in (nombre, *alternativos):
            ic = _icono_estandar(candidato)
            if not ic.isNull():
                break
    return ic


def icono_app():
    """Icono de la aplicación: el empaquetado en Windows, el del tema en KDE."""
    if ICONO_APP and os.path.exists(ICONO_APP):
        ic = QIcon(ICONO_APP)
        if not ic.isNull():
            return ic
    return tema("object-locked", "lock", "document-encrypt")


def icono_carpeta(ruta, existe):
    """Icono real de la carpeta.

    Si el usuario le puso un icono personalizado en Dolphin, KDE lo guarda en
    «<carpeta>/.directory» bajo [Desktop Entry] → Icon=. El valor puede ser un
    nombre de icono del tema (p. ej. «folder-documents») o una ruta absoluta a
    una imagen. Si no hay icono propio, se cae al genérico (rojo si la carpeta
    ya no existe en el disco).
    """
    if existe:
        nombre = _icono_de_directory(ruta)
        if nombre:
            if os.path.isabs(nombre) and os.path.exists(nombre):
                ic = QIcon(nombre)
                if not ic.isNull():
                    return ic
            else:
                ic = QIcon.fromTheme(nombre)
                if not ic.isNull():
                    return ic
        return tema("folder")
    return tema("folder-red", "folder")


def _icono_de_directory(ruta):
    """Lee Icon= de la sección [Desktop Entry] de <ruta>/.directory."""
    archivo = os.path.join(ruta, ".directory")
    try:
        with open(archivo, encoding="utf-8", errors="replace") as fh:
            seccion = ""
            for linea in fh:
                linea = linea.strip()
                if linea.startswith("[") and linea.endswith("]"):
                    seccion = linea
                elif seccion == "[Desktop Entry]" and linea.startswith("Icon="):
                    valor = linea[len("Icon="):].strip()
                    return valor or None
    except OSError:
        pass
    return None


def contar_pdf(carpeta):
    """Cuenta los PDF de una carpeta, omitiendo los temporales del backend
    (*_temp.pdf y los ocultos «.<algo>»). Devuelve 0 ante cualquier error."""
    n = 0
    try:
        with os.scandir(carpeta) as it:
            for entrada in it:
                nombre = entrada.name
                if nombre.startswith("."):
                    continue
                if nombre.endswith("_temp.pdf"):
                    continue
                if nombre.lower().endswith(".pdf") and entrada.is_file():
                    n += 1
    except OSError:
        return 0
    return n


# Colores de los «chips» de estado (claro/oscuro): cada entrada es (fondo,
# texto); en oscuro, fondos apagados con texto claro para que sean legibles.
_CHIP_CLARO = {
    "ok":    ("#d5f0dd", "#1e7e44"),
    "aviso": ("#fdecd9", "#a84300"),
    "error": ("#fbe3e0", "#b03a2e"),
    "nuevo": ("#fff3cd", "#8a6d00"),
    "info":  ("#dce7f7", "#1f4f8f"),
}
_CHIP_OSCURO = {
    "ok":    ("#1f3d2a", "#7fd6a0"),
    "aviso": ("#3d3019", "#e0a76b"),
    "error": ("#3d2422", "#e08a80"),
    "nuevo": ("#3d3410", "#f0c869"),
    "info":  ("#1e2e45", "#8ab4e8"),
}


def colores_chip(estado, oscuro):
    """(fondo, texto) del chip de estado, adaptado a tema claro u oscuro."""
    tabla = _CHIP_OSCURO if oscuro else _CHIP_CLARO
    return tabla.get(estado, tabla["ok"])


def backend(args, entrada=None):
    """Llama al script bash. Devuelve (codigo, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [*comando_backend(), *args],
            input=entrada,
            capture_output=True,
            text=True,
            **_SIN_CONSOLA,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "No se encontró el backend de Cifrar PDF."


def mensaje_backend(salida, por_defecto):
    """Extrae el texto tras «ERR » que devuelve el backend."""
    if salida.startswith("ERR "):
        return salida[4:].strip()
    return salida.strip() or por_defecto


# Etiqueta que recorta («elide») su texto si no cabe, en vez de ensanchar la
# fila. Se usa para la ruta de cada carpeta, así el contador y el chip de
# estado quedan siempre visibles.
class EtiquetaElidida(QLabel):
    def __init__(self, texto="", parent=None):
        super().__init__(texto, parent)
        self._texto = texto
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, texto):
        self._texto = texto
        super().setText(texto)
        self.update()

    def paintEvent(self, _event):
        pintor = QPainter(self)
        elidido = self.fontMetrics().elidedText(
            self._texto, Qt.TextElideMode.ElideMiddle, self.width())
        pintor.drawText(
            self.rect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elidido)


# Indicador del estado del vigilante: por defecto solo un punto de color; al
# pasar el ratón se expande mostrando el texto y, tras la pausa habitual,
# aparece el tooltip explicativo.
class IndicadorVigilante(QLabel):
    def __init__(self, parent=None):
        super().__init__("●", parent)
        self._texto = ""
        self._color = "palette(mid)"
        # Alineado a la derecha: el punto queda fijo y, al expandirse, el
        # texto crece hacia la izquierda, así el cursor sigue sobre el punto
        # (sin parpadeo del hover).
        self.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)

    def set_estado(self, texto, color, ayuda):
        self._texto = texto
        self._color = color
        self.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.setToolTip(ayuda)
        self._contraer()

    def _contraer(self):
        self.setText("●")  # contraído: solo el punto

    def enterEvent(self, event):
        # Expandido: texto a la izquierda y el punto al final (sigue bajo el
        # cursor, que estaba sobre el punto contraído).
        self.setText(f"{self._texto}  ●")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._contraer()
        super().leaveEvent(event)


# Diálogo de contraseña (alta de carpeta o cambio de contraseña)
class DialogoContrasena(QDialog):
    """Contraseña de una carpeta, con el selector de modo: contraseña fija
    guardada, o preguntar cada vez que se suelte un PDF (entonces no se pide
    ni se guarda nada aquí; la pedirá el vigilante en el momento de cifrar)."""

    def __init__(self, parent=None, pedir_nombre=False,
                 nombre_def="Cifrar PDF", modo_actual="fija"):
        super().__init__(parent)
        self.pedir_nombre = pedir_nombre
        self.setWindowTitle("Nueva carpeta de cifrado" if pedir_nombre
                            else "Contraseña y modo")
        self.setWindowIcon(icono_app())
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        self.campo_nombre = None
        if pedir_nombre:
            form_nombre = QFormLayout()
            form_nombre.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self.campo_nombre = QLineEdit(nombre_def)
            self.campo_nombre.setClearButtonEnabled(True)
            self.campo_nombre.textChanged.connect(self._validar)
            form_nombre.addRow("Nombre de la carpeta:", self.campo_nombre)
            layout.addLayout(form_nombre)

        # Selector radial del modo: es lo que decide si abajo hay que escribir
        # una contraseña o no.
        grupo = QGroupBox("¿Cómo quieres la contraseña?")
        vgrupo = QVBoxLayout(grupo)
        self.radio_fija = QRadioButton("Usar siempre esta contraseña")
        self.radio_fija.setToolTip(
            "Se guarda una sola vez (en el Administrador de credenciales de "
            "Windows) y se aplica sola a cada PDF que sueltes en la carpeta.")
        self.radio_preguntar = QRadioButton(
            "Preguntar cada vez que suelte un PDF")
        self.radio_preguntar.setToolTip(
            "No se guarda ninguna contraseña: se pide en el momento de cifrar. "
            "Si sueltas varios PDF de golpe, se pregunta una sola vez.")
        vgrupo.addWidget(self.radio_fija)
        vgrupo.addWidget(self.radio_preguntar)
        pista = QLabel(
            "Con «preguntar cada vez» no queda ninguna contraseña guardada en "
            "el equipo y cada PDF puede llevar la suya.")
        pista.setWordWrap(True)
        pista.setStyleSheet("color: palette(mid);")
        vgrupo.addWidget(pista)
        layout.addWidget(grupo)

        if modo_actual == "preguntar":
            self.radio_preguntar.setChecked(True)
        else:
            self.radio_fija.setChecked(True)

        # Los campos de contraseña van en su propia caja para poder ocultarlos
        # enteros (etiquetas incluidas) en el modo «preguntar».
        self.caja_pass = QWidget()
        form = QFormLayout(self.caja_pass)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.pass1 = QLineEdit()
        self.pass1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass1.setClearButtonEnabled(True)
        self.pass1.textChanged.connect(self._validar)

        self.pass2 = QLineEdit()
        self.pass2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass2.setClearButtonEnabled(True)
        self.pass2.textChanged.connect(self._validar)

        # Botón mostrar/ocultar contraseña.
        self.ver = QToolButton()
        self.ver.setCheckable(True)
        self.ver.setIcon(tema("view-visible", "visibility"))
        if self.ver.icon().isNull():
            # Sin icono (Windows) el botón se quedaría vacío: se etiqueta.
            self.ver.setText("Ver")
        self.ver.setToolTip("Mostrar u ocultar la contraseña")
        self.ver.toggled.connect(self._alternar_visible)

        fila_pass = QHBoxLayout()
        fila_pass.addWidget(self.pass1)
        fila_pass.addWidget(self.ver)
        cont_pass = QWidget()
        cont_pass.setLayout(fila_pass)
        fila_pass.setContentsMargins(0, 0, 0, 0)

        form.addRow("Contraseña:", cont_pass)
        form.addRow("Repite la contraseña:", self.pass2)
        layout.addWidget(self.caja_pass)

        self.aviso = QLabel(f"La contraseña debe tener al menos {MIN_PASS} caracteres.")
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.aviso)

        self.botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar")
        self.botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        layout.addWidget(self.botones)

        self.radio_fija.toggled.connect(self._cambio_modo)
        self._cambio_modo()
        (self.campo_nombre or self.pass1).setFocus()

    def _cambio_modo(self, _marcado=None):
        """Muestra u oculta los campos de contraseña según el modo elegido."""
        fija = self.radio_fija.isChecked()
        self.caja_pass.setVisible(fija)
        self._validar()
        self.adjustSize()

    def _alternar_visible(self, visible):
        modo = (QLineEdit.EchoMode.Normal if visible
                else QLineEdit.EchoMode.Password)
        self.pass1.setEchoMode(modo)
        self.pass2.setEchoMode(modo)
        self.ver.setIcon(tema("view-hidden", "view-visible", "visibility")
                         if visible else tema("view-visible", "visibility"))
        if self.ver.icon().isNull():
            self.ver.setText("Ocultar" if visible else "Ver")

    def _validar(self):
        p1 = self.pass1.text()
        p2 = self.pass2.text()
        problema = ""
        if self.campo_nombre is not None:
            nombre = self.campo_nombre.text().strip()
            if not nombre:
                problema = "Escribe un nombre para la carpeta."
            elif "/" in nombre:
                problema = "El nombre no puede contener «/»."
        if not problema and self.modo() == "preguntar":
            # No hay contraseña que validar: se pedirá al cifrar.
            self.botones.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            self.aviso.setText(
                "Se te pedirá la contraseña cada vez que sueltes un PDF.")
            self.aviso.setStyleSheet("color: palette(link);")
            return
        if not problema:
            if len(p1) < MIN_PASS:
                problema = f"La contraseña debe tener al menos {MIN_PASS} caracteres."
            elif p2 and p1 != p2:
                problema = "Las contraseñas no coinciden."
            elif not p2:
                problema = "Repite la contraseña para confirmarla."

        valido = not problema
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valido)
        if valido:
            self.aviso.setText("✓ Todo correcto.")
            self.aviso.setStyleSheet("color: palette(link);")
        else:
            self.aviso.setText(problema)
            self.aviso.setStyleSheet("color: #c0392b;")

    def nombre(self):
        return self.campo_nombre.text().strip() if self.campo_nombre else ""

    def modo(self):
        return "fija" if self.radio_fija.isChecked() else "preguntar"

    def contrasena(self):
        return self.pass1.text() if self.modo() == "fija" else ""


class DialogoRegistro(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registro — Cifrar PDF")
        self.setWindowIcon(tema("view-list-text", "text-x-generic"))
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.texto)

        fila = QHBoxLayout()
        fila.addStretch(1)
        btn_limpiar = QPushButton(tema("edit-clear-history", "edit-clear"),
                                  "Limpiar registro")
        btn_limpiar.clicked.connect(self._limpiar)
        btn_cerrar = QPushButton(tema("dialog-close", "window-close"), "Cerrar")
        btn_cerrar.clicked.connect(self.accept)
        fila.addWidget(btn_limpiar)
        fila.addWidget(btn_cerrar)
        layout.addLayout(fila)

        self._cargar()

    def _cargar(self):
        try:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
                self.texto.setPlainText(fh.read())
        except OSError:
            self.texto.setPlainText("No hay registro todavía.")
        self.texto.verticalScrollBar().setValue(
            self.texto.verticalScrollBar().maximum())

    def _limpiar(self):
        if QMessageBox.question(self, "Cifrar PDF",
                                "¿Limpiar todo el registro?") \
                == QMessageBox.StandardButton.Yes:
            try:
                open(LOG_FILE, "w").close()
            except OSError:
                pass
            self._cargar()


# Lista de carpetas con soporte de arrastrar y soltar PDF
class ListaCarpetas(QListWidget):
    """QListWidget que acepta soltar PDF sobre una fila. Emite
    pdfs_soltados(id_carpeta, [rutas]) para que la ventana los copie."""

    pdfs_soltados = pyqtSignal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _pdfs_del_evento(event):
        rutas = []
        for url in event.mimeData().urls():
            ruta = url.toLocalFile()
            if ruta and ruta.lower().endswith(".pdf"):
                rutas.append(ruta)
        return rutas

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._pdfs_del_evento(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and self._pdfs_del_evento(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        rutas = self._pdfs_del_evento(event)
        if not rutas:
            event.ignore()
            return
        item = self.itemAt(event.position().toPoint())
        if item is None:
            # Sin fila bajo el cursor: si solo hay una carpeta, usarla.
            if self.count() == 1:
                item = self.item(0)
            else:
                event.ignore()
                return
        id_carpeta = item.data(Qt.ItemDataRole.UserRole)
        event.acceptProposedAction()
        self.pdfs_soltados.emit(id_carpeta, rutas)


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(icono_app())
        self.resize(760, 520)
        self.setMinimumSize(620, 360)
        self.ajustes = QSettings("FISAT", "Cifrar PDF")

        self._crear_acciones()
        self._crear_barra()
        self._crear_cuerpo()
        # Estado del vigilante como widget permanente (derecha): no pisa la
        # zona temporal donde van los statusTip de las acciones.
        self.lbl_vigilante = IndicadorVigilante()
        self.statusBar().addPermanentWidget(self.lbl_vigilante)

        # Vigilancia en vivo: cambios en carpetas, iconos (.directory) o
        # config refrescan la lista sin reabrir la ventana; el timer agrupa
        # ráfagas de eventos (debounce) para no refrescar varias veces seguidas.
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_cambio_fs)
        self.watcher.fileChanged.connect(self._on_cambio_fs)
        self._timer_refresco = QTimer(self)
        self._timer_refresco.setSingleShot(True)
        self._timer_refresco.setInterval(400)
        self._timer_refresco.timeout.connect(self.refrescar)

        # Conteo de PDF por carpeta y marca «reciente» (cuando el número sube):
        # la carpeta se resalta unos segundos para avisar de que hay un PDF más.
        self._conteos = {}
        self._recientes = {}
        self._timer_reciente = QTimer(self)
        self._timer_reciente.setSingleShot(True)
        self._timer_reciente.setInterval(8000)
        self._timer_reciente.timeout.connect(self._limpiar_recientes)

        # Restaura el tamaño/posición de la última vez, si se guardó.
        geometria = self.ajustes.value("geometria")
        if geometria is not None:
            self.restoreGeometry(geometria)

        # Asegura que el vigilante esté en marcha si ya hay carpetas.
        backend(["--gui-asegurar"])
        self.refrescar()

    def closeEvent(self, event):
        self.ajustes.setValue("geometria", self.saveGeometry())
        super().closeEvent(event)

    # Construcción de la interfaz
    def _crear_acciones(self):
        # (acción, atajo, tooltip/statusTip)
        self.act_anadir = QAction(tema("list-add"), "Añadir carpeta", self)
        self.act_anadir.triggered.connect(self.anadir)
        self._configurar_accion(
            self.act_anadir, QKeySequence(Qt.Key.Key_Insert),
            "Crear una carpeta nueva y elegir cómo va su contraseña")

        self.act_renombrar = QAction(
            tema("edit-rename", "document-edit"), "Renombrar", self)
        self.act_renombrar.triggered.connect(self.renombrar)
        self._configurar_accion(
            self.act_renombrar, QKeySequence(Qt.Key.Key_F2),
            "Cambiar el nombre de la carpeta seleccionada")

        self.act_clave = QAction(
            tema("dialog-password", "security-high", "object-locked"),
            "Contraseña", self)
        self.act_clave.triggered.connect(self.cambiar_clave)
        self._configurar_accion(
            self.act_clave, QKeySequence("Ctrl+P"),
            "Cambiar la contraseña de la carpeta seleccionada, o pasar a "
            "que se pregunte cada vez")

        self.act_abrir = QAction(
            tema("folder-open", "document-open-folder"), "Abrir carpeta", self)
        self.act_abrir.triggered.connect(self.abrir_carpeta)
        self._configurar_accion(
            self.act_abrir, QKeySequence("Ctrl+O"),
            "Abrir la carpeta en el gestor de archivos")

        self.act_quitar = QAction(
            tema("list-remove", "edit-delete"), "Quitar", self)
        self.act_quitar.triggered.connect(self.quitar)
        self._configurar_accion(
            self.act_quitar, QKeySequence(Qt.Key.Key_Delete),
            "Quitar la carpeta de la lista de cifrado")

        self.act_quitar_todas = QAction(
            tema("edit-delete-shred", "edit-clear-all", "trash-empty"),
            "Quitar todas", self)
        self.act_quitar_todas.triggered.connect(self.quitar_todas)
        self._configurar_accion(
            self.act_quitar_todas, None,
            "Quitar todas las carpetas de cifrado")

        self.act_registro = QAction(
            tema("view-list-text", "text-x-generic", "document-open-recent"),
            "Registro", self)
        self.act_registro.triggered.connect(self.ver_registro)
        self._configurar_accion(
            self.act_registro, QKeySequence("Ctrl+L"),
            "Ver el registro de actividad")

        self.act_refrescar = QAction(
            tema("view-refresh"), "Refrescar", self)
        self.act_refrescar.triggered.connect(self.refrescar)
        self._configurar_accion(
            self.act_refrescar, QKeySequence(Qt.Key.Key_F5),
            "Actualizar la lista de carpetas")
        self.addAction(self.act_refrescar)

    def _configurar_accion(self, accion, atajo, ayuda):
        if atajo is not None:
            accion.setShortcut(atajo)
        accion.setToolTip(ayuda)
        accion.setStatusTip(ayuda)

    def _crear_barra(self):
        barra = QToolBar("Acciones")
        barra.setMovable(False)
        barra.setIconSize(QSize(22, 22))
        barra.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        barra.addAction(self.act_anadir)
        barra.addSeparator()
        barra.addAction(self.act_renombrar)
        barra.addAction(self.act_clave)
        barra.addAction(self.act_abrir)
        barra.addAction(self.act_quitar)
        barra.addSeparator()
        barra.addAction(self.act_quitar_todas)
        barra.addAction(self.act_registro)
        barra.addAction(self.act_refrescar)
        self.addToolBar(barra)

    def _crear_cuerpo(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Cabecera con icono y texto explicativo.
        cabecera = QHBoxLayout()
        icono = QLabel()
        icono.setPixmap(
            tema("object-locked", "lock", "document-encrypt").pixmap(48, 48))
        cabecera.addWidget(icono)
        texto = QLabel(
            "<b>Cifra tus PDF automáticamente</b><br>"
            "Suelta un PDF en cualquiera de estas carpetas del Escritorio "
            "y se protegerá solo con su contraseña.")
        texto.setWordWrap(True)
        cabecera.addWidget(texto, 1)
        layout.addLayout(cabecera)

        linea = QFrame()
        linea.setFrameShape(QFrame.Shape.HLine)
        linea.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(linea)

        self.lista = ListaCarpetas()
        self.lista.setIconSize(QSize(32, 32))
        self.lista.setAlternatingRowColors(True)
        self.lista.itemSelectionChanged.connect(self._actualizar_acciones)
        self.lista.itemSelectionChanged.connect(self._pintar_seleccion)
        self.lista.itemDoubleClicked.connect(lambda _i: self.abrir_carpeta())
        self.lista.pdfs_soltados.connect(self._soltar_pdfs)
        self.lista.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_contextual)
        self.lista.setToolTip(
            "Arrastra aquí un PDF para cifrarlo en esa carpeta")
        layout.addWidget(self.lista, 1)

        # Estado vacío: icono, texto y un botón «Añadir carpeta» centrados,
        # ocupando la misma zona que el listado.
        self.vacio = QWidget()
        vlay = QVBoxLayout(self.vacio)
        vlay.addStretch(1)

        v_icono = QLabel()
        v_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_icono.setPixmap(tema("folder", "document-encrypt").pixmap(64, 64))
        vlay.addWidget(v_icono)

        v_texto = QLabel(
            "Aún no tienes ninguna carpeta de cifrado.\n"
            "Crea la primera y empieza a proteger tus PDF.")
        v_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_texto.setStyleSheet("color: palette(mid); font-size: 11pt;")
        vlay.addWidget(v_texto)

        fila_btn = QHBoxLayout()
        fila_btn.addStretch(1)
        v_boton = QPushButton(tema("list-add"), "Añadir carpeta")
        v_boton.clicked.connect(self.anadir)
        fila_btn.addWidget(v_boton)
        fila_btn.addStretch(1)
        vlay.addLayout(fila_btn)

        vlay.addStretch(1)
        layout.addWidget(self.vacio, 1)

        self.setCentralWidget(central)

    # Carga de datos
    def _carpetas(self):
        _rc, salida, _err = backend(["--gui-listar"])
        filas = []
        for linea in salida.splitlines():
            partes = linea.split("\t")
            if len(partes) >= 5:
                filas.append({
                    "id": partes[0],
                    "nombre": partes[1],
                    "carpeta": partes[2],
                    "existe": partes[3] == "1",
                    "tiene_clave": partes[4] == "1",
                    # 6º campo: lo añadió el selector de modo. Si faltara
                    # (backend antiguo), «fija» es el comportamiento de siempre.
                    "modo": partes[5] if len(partes) >= 6 else "fija",
                })
        return filas

    def refrescar(self):
        seleccion = self.id_seleccionado()
        self.lista.clear()
        filas = self._carpetas()

        hay = bool(filas)
        self.lista.setVisible(hay)
        self.vacio.setVisible(not hay)

        ids_actuales = set()
        marca_nueva = False
        for fila in filas:
            fid = fila["id"]
            ids_actuales.add(fid)
            n = contar_pdf(fila["carpeta"]) if fila["existe"] else 0
            anterior = self._conteos.get(fid)
            if anterior is not None and n > anterior:
                self._recientes[fid] = True
                marca_nueva = True
            self._conteos[fid] = n
            fila["n"] = n
            fila["reciente"] = fid in self._recientes

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, fid)
            self.lista.addItem(item)
            self.lista.setItemWidget(item, self._fila_widget(fila))
            item.setSizeHint(self.lista.itemWidget(item).sizeHint())
            if fid == seleccion:
                self.lista.setCurrentItem(item)

        # Olvida conteos/marcas de carpetas que ya no están.
        for fid in list(self._conteos):
            if fid not in ids_actuales:
                self._conteos.pop(fid, None)
                self._recientes.pop(fid, None)

        if marca_nueva:
            self._timer_reciente.start()

        if seleccion is None and self.lista.count():
            self.lista.setCurrentRow(0)

        # Estado del vigilante (widget permanente, a la derecha) con color:
        # verde = activo, rojo = detenido (hay carpetas), gris = sin carpetas.
        oscuro = self.palette().color(
            QPalette.ColorRole.Window).lightness() < 128
        _rc, estado, _err = backend(["--gui-estado"])
        if estado == "1":
            texto = "Vigilante activo"
            color = "#7fd6a0" if oscuro else "#1e7e44"
            ayuda = ("El vigilante está en marcha: los PDF que sueltes en tus "
                     "carpetas se cifran automáticamente.")
        elif hay:
            texto = "Vigilante detenido"
            color = "#e08a80" if oscuro else "#b03a2e"
            ayuda = ("El vigilante no está en marcha, así que los PDF nuevos no "
                     "se cifrarán. Cierra la sesión y vuelve a entrar para "
                     "reactivarlo.")
        else:
            texto = "Sin carpetas de cifrado"
            color = "palette(mid)"
            ayuda = ("Aún no hay carpetas de cifrado. Pulsa «Añadir carpeta» "
                     "para crear la primera y empezar a proteger tus PDF.")
        self.lbl_vigilante.set_estado(texto, color, ayuda)

        self._actualizar_acciones()
        self._pintar_seleccion()
        self._actualizar_watches(filas)

    # Color del texto según selección
    def _colorear_fila(self, widget, seleccionado):
        """En la fila seleccionada (fondo azul) el texto secundario pasa a
        «highlighted-text» (blanco) para que contraste; si no, gris discreto."""
        if seleccionado:
            principal = secundario = "palette(highlighted-text)"
        else:
            principal, secundario = "palette(text)", "palette(mid)"
        widget._lbl_nombre.setStyleSheet(f"font-weight: bold; color: {principal};")
        widget._lbl_ruta.setStyleSheet(f"font-size: 9pt; color: {secundario};")
        if widget._lbl_contador is not None:
            widget._lbl_contador.setStyleSheet(
                f"font-size: 9pt; color: {secundario};")

    def _pintar_seleccion(self):
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            widget = self.lista.itemWidget(item)
            if widget is not None:
                self._colorear_fila(widget, item.isSelected())

    # Vigilancia del sistema de ficheros
    def _actualizar_watches(self, filas):
        """Recalcula qué rutas vigilar: la carpeta de configuración, cada
        carpeta de cifrado y su carpeta padre (altas/bajas/renombrados) y su
        .directory (cambios de icono)."""
        rutas = set()
        if os.path.isdir(CARPETAS_DIR):
            rutas.add(CARPETAS_DIR)
        for fila in filas:
            carpeta = fila["carpeta"]
            padre = os.path.dirname(carpeta)
            if os.path.isdir(padre):
                rutas.add(padre)
            if os.path.isdir(carpeta):
                rutas.add(carpeta)
                directory = os.path.join(carpeta, ".directory")
                if os.path.isfile(directory):
                    rutas.add(directory)

        actuales = set(self.watcher.directories()) | set(self.watcher.files())
        sobran = list(actuales - rutas)
        if sobran:
            self.watcher.removePaths(sobran)
        faltan = list(rutas - actuales)
        if faltan:
            self.watcher.addPaths(faltan)

    def _on_cambio_fs(self, _ruta):
        # Reinicia el debounce: tras la última ráfaga, refresca una sola vez.
        self._timer_refresco.start()

    def _limpiar_recientes(self):
        # Pasados unos segundos, quita el resaltado de «PDF nuevo».
        if self._recientes:
            self._recientes.clear()
            self.refrescar()

    # Menú contextual y arrastrar/soltar
    def _menu_contextual(self, pos):
        item = self.lista.itemAt(pos)
        if item is None:
            return
        self.lista.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(self.act_abrir)
        menu.addAction(self.act_renombrar)
        menu.addAction(self.act_clave)
        menu.addSeparator()
        menu.addAction(self.act_quitar)
        menu.exec(self.lista.mapToGlobal(pos))

    def _soltar_pdfs(self, id_carpeta, rutas):
        carpeta = None
        for fila in self._carpetas():
            if fila["id"] == id_carpeta:
                carpeta = fila["carpeta"]
                nombre = fila["nombre"]
                break
        if carpeta is None or not os.path.isdir(carpeta):
            self._error("La carpeta de destino ya no existe.")
            return

        copiados = 0
        for ruta in rutas:
            if not ruta.lower().endswith(".pdf") or not os.path.isfile(ruta):
                continue
            destino = os.path.join(carpeta, os.path.basename(ruta))
            if os.path.abspath(ruta) == os.path.abspath(destino):
                continue  # ya está en la carpeta
            destino = _ruta_unica(destino)
            try:
                shutil.copy2(ruta, destino)
                copiados += 1
            except OSError:
                pass

        if copiados:
            backend(["--gui-asegurar"])
            s = "s" if copiados > 1 else ""
            self.statusBar().showMessage(
                f"Copiado{s} {copiados} PDF a «{nombre}» — "
                f"se cifrará{'n' if copiados > 1 else ''} en breve.", 6000)
        else:
            self.statusBar().showMessage("No se copió ningún PDF.", 4000)

    def _fila_widget(self, fila):
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(10)
        oscuro = self.palette().color(
            QPalette.ColorRole.Window).lightness() < 128
        pill = "border-radius: 9px; padding: 2px 9px; font-weight: bold;"

        icono = QLabel()
        icono.setPixmap(icono_carpeta(fila["carpeta"], fila["existe"]).pixmap(32, 32))
        h.addWidget(icono)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        nombre = QLabel(fila["nombre"])
        ruta = EtiquetaElidida(fila["carpeta"])
        textos.addWidget(nombre)
        textos.addWidget(ruta)
        h.addLayout(textos, 1)

        # Etiquetas cuyo color cambia según la fila esté seleccionada o no
        # (para que contrasten sobre el azul de la selección).
        widget._lbl_nombre = nombre
        widget._lbl_ruta = ruta
        widget._lbl_contador = None

        # Contador de PDF (oculto si es 0); si el número subió hace poco, se
        # resalta como «chip» para avisar de que hay un PDF más.
        n = fila.get("n", 0)
        if fila["existe"] and n > 0:
            contador = QLabel(f"{n} PDF")
            if fila.get("reciente"):
                contador.setText(f"▲ {n} PDF")
                fondo, color = colores_chip("nuevo", oscuro)
                contador.setStyleSheet(f"{pill} background: {fondo}; color: {color};")
                contador.setToolTip("Se ha añadido un PDF recientemente")
            else:
                widget._lbl_contador = contador  # color según selección
            h.addWidget(contador)

        # Chip de estado. Solo se avisa si hay un PROBLEMA (sin contraseña o
        # carpeta no encontrada); si todo está bien no se muestra nada — la
        # ausencia de aviso ya indica que está lista. La excepción es el modo
        # «preguntar»: ahí no hay contraseña guardada A PROPÓSITO, así que se
        # muestra como información y nunca como error.
        texto_estado = clave = None
        if fila.get("modo") == "preguntar":
            if not fila["existe"]:
                texto_estado, clave = "⚠  Carpeta no encontrada", "aviso"
            else:
                texto_estado, clave = "🔑  Pregunta cada vez", "info"
        elif not fila["tiene_clave"]:
            texto_estado, clave = "⚠  Sin contraseña", "error"
        elif not fila["existe"]:
            texto_estado, clave = "⚠  Carpeta no encontrada", "aviso"
        if texto_estado:
            fondo, color = colores_chip(clave, oscuro)
            estado = QLabel(texto_estado)
            estado.setStyleSheet(f"{pill} background: {fondo}; color: {color};")
            if clave == "info":
                estado.setToolTip(
                    "Esta carpeta no guarda contraseña: se te pedirá cada vez "
                    "que sueltes un PDF en ella.")
            h.addWidget(estado)

        widget.setToolTip(fila["carpeta"])
        self._colorear_fila(widget, False)
        return widget

    # Selección
    def id_seleccionado(self):
        item = self.lista.currentItem()
        if item is not None and item.isSelected():
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def fila_seleccionada(self):
        sid = self.id_seleccionado()
        if sid is None:
            return None
        for fila in self._carpetas():
            if fila["id"] == sid:
                return fila
        return None

    def _actualizar_acciones(self):
        hay_sel = self.id_seleccionado() is not None
        for act in (self.act_renombrar, self.act_clave,
                    self.act_abrir, self.act_quitar):
            act.setEnabled(hay_sel)
        self.act_quitar_todas.setEnabled(self.lista.count() > 0)

    # Acciones
    def anadir(self):
        dlg = DialogoContrasena(self, pedir_nombre=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rc, salida, err = backend(
            ["--gui-add", dlg.nombre(), "--modo", dlg.modo()],
            entrada=dlg.contrasena())
        if rc != 0:
            self._error(mensaje_backend(salida or err,
                                        "No se pudo crear la carpeta."))
            return
        self.refrescar()
        if dlg.modo() == "preguntar":
            self._aviso(f"Carpeta «{dlg.nombre()}» lista y vigilándose.\n"
                        "Se te pedirá la contraseña cada vez que sueltes "
                        "un PDF en ella.")
        else:
            self._aviso(f"Carpeta «{dlg.nombre()}» lista y vigilándose.")

    def renombrar(self):
        fila = self.fila_seleccionada()
        if fila is None:
            return
        nuevo, ok = QInputDialog.getText(
            self, "Renombrar carpeta",
            "Nuevo nombre (se renombra también en el Escritorio):",
            text=fila["nombre"])
        if not ok:
            return
        nuevo = nuevo.strip()
        if not nuevo or nuevo == fila["nombre"]:
            return
        rc, salida, err = backend(["--gui-rename", fila["id"], nuevo])
        if rc != 0:
            self._error(mensaje_backend(salida or err,
                                        "No se pudo renombrar."))
            return
        self.refrescar()

    def cambiar_clave(self):
        fila = self.fila_seleccionada()
        if fila is None:
            return
        dlg = DialogoContrasena(self, pedir_nombre=False,
                                modo_actual=fila.get("modo", "fija"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rc, salida, err = backend(
            ["--gui-set-pass", fila["id"], "--modo", dlg.modo()],
            entrada=dlg.contrasena())
        if rc != 0:
            self._error(mensaje_backend(salida or err,
                                        "No se pudo cambiar la contraseña."))
            return
        self.refrescar()
        if dlg.modo() == "preguntar":
            self._aviso(f"«{fila['nombre']}» pedirá la contraseña cada vez "
                        "que sueltes un PDF.\n"
                        "No queda ninguna contraseña guardada.")
        else:
            self._aviso(f"Contraseña actualizada para «{fila['nombre']}».\n"
                        "Se aplicará al próximo PDF que cifres en esa carpeta.")

    def abrir_carpeta(self):
        fila = self.fila_seleccionada()
        if fila is None:
            return
        if not os.path.isdir(fila["carpeta"]):
            self._error("La carpeta ya no existe en el disco.")
            return
        if ES_WINDOWS:
            os.startfile(fila["carpeta"])
        else:
            subprocess.Popen(["xdg-open", fila["carpeta"]])

    def quitar(self):
        fila = self.fila_seleccionada()
        if fila is None:
            return
        if QMessageBox.warning(
                self, "Cifrar PDF",
                f"¿Quitar la carpeta de cifrado «{fila['nombre']}»?\n\n"
                "Se quitará de la lista y se borrará su contraseña guardada.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        args = ["--gui-remove", fila["id"]]
        if os.path.isdir(fila["carpeta"]):
            resp = QMessageBox.question(
                self, "Cifrar PDF",
                f"¿Borrar también la carpeta «{fila['nombre']}» y todo su "
                f"contenido del disco?\n\n{fila['carpeta']}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if resp == QMessageBox.StandardButton.Yes:
                args.append("--borrar-carpeta")

        rc, salida, err = backend(args)
        if rc != 0:
            self._error(mensaje_backend(salida or err, "No se pudo quitar."))
            return
        self.refrescar()

    def quitar_todas(self):
        if self.lista.count() == 0:
            return
        if QMessageBox.warning(
                self, "Cifrar PDF — Quitar todas",
                "¿Quitar TODAS las carpetas de cifrado?\n\n"
                "Se dejarán de cifrar y se borrarán sus contraseñas guardadas.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        args = ["--gui-remove-all"]
        if any(os.path.isdir(f["carpeta"]) for f in self._carpetas()):
            resp = QMessageBox.question(
                self, "Cifrar PDF",
                "¿Borrar también las carpetas del Escritorio y todo su "
                "contenido?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if resp == QMessageBox.StandardButton.Yes:
                args.append("--borrar-carpetas")

        rc, salida, err = backend(args)
        if rc != 0:
            self._error(mensaje_backend(salida or err, "No se pudo completar."))
            return
        self.refrescar()

    def ver_registro(self):
        DialogoRegistro(self).exec()

    # Mensajes
    def _error(self, texto):
        QMessageBox.critical(self, "Cifrar PDF", texto)

    def _aviso(self, texto):
        QMessageBox.information(self, "Cifrar PDF", texto)


def _ruta_unica(destino):
    """Devuelve una ruta libre: si «destino» existe, prueba «nombre (2).pdf»…"""
    if not os.path.exists(destino):
        return destino
    base, ext = os.path.splitext(destino)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Cifrar PDF")
    app.setApplicationDisplayName(APP_TITLE)
    if not ES_WINDOWS:
        # Asocia la ventana con su .desktop (fisat-cifrar-pdf.desktop): la barra
        # de tareas usa su icono (no uno genérico) y fija el WM_CLASS/app_id.
        app.setDesktopFileName("fisat-cifrar-pdf")
    app.setWindowIcon(icono_app())
    ventana = Ventana()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
