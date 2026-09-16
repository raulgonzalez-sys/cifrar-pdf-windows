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
        Qt, QEvent, QSize, QFileSystemWatcher, QSettings, QTimer,
        pyqtSignal,
    )
    from PyQt6.QtGui import (
        QAction, QFontDatabase, QFontInfo, QIcon, QKeySequence, QPainter,
        QPalette, QPixmap,
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

# Nombre técnico, sin espacios: en Debian es el WM_CLASS de X11 y el
# StartupWMClass del .desktop; en Windows, el identificador de modelo de
# aplicación con el que la barra de tareas agrupa la ventana con su acceso
# directo (ver _identificar_en_barra_de_tareas).
APP_NOMBRE = "fisat-cifrar-pdf"
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
    """QIcon del tema (Breeze) con alternativas por si falta un nombre.

    Se pregunta con hasThemeIcon() y no con isNull() sobre el resultado:
    QIcon.fromTheme() puede devolver un icono NO nulo pero vacío, con lo que
    la cadena de alternativas no llegaba a dispararse y quedaba el hueco.

    En Windows no hay tema de iconos, así que hasThemeIcon() dice que no a
    todo y se pasa siempre a los iconos estándar de Qt. A diferencia de la
    copia de Debian, aquí NO hay respaldo final con el logo: un nombre sin
    equivalente se queda sin icono a propósito (ver _ESTANDAR). El logo sí es
    el suelo del icono de carpeta, que es el único sitio donde un hueco
    descuadraría la fila.
    """
    for candidato in (nombre, *alternativos):
        if QIcon.hasThemeIcon(candidato):
            return QIcon.fromTheme(candidato)
    if ES_WINDOWS:
        for candidato in (nombre, *alternativos):
            ic = _icono_estandar(candidato)
            if not ic.isNull():
                return ic
        return QIcon()
    return QIcon.fromTheme(nombre)


def pixmap_nitido(widget, icono, lado):
    """QPixmap cuadrado del icono, nítido y siempre del tamaño pedido.

    Arregla dos cosas de «icono.pixmap(lado, lado)»: el pixmap que devuelve
    lleva devicePixelRatio 1, así que en una pantalla al 150 % —el escalado
    de fábrica de casi cualquier portátil que se compre hoy— Qt lo estira y
    se ve borroso, justo donde alguien ha subido el escalado por problemas de
    vista; y QIcon.pixmap() nunca AMPLÍA por encima del tamaño natural del
    fichero, de modo que un icono personalizado de 16x16 salía a 16 px y
    descuadraba la sangría de esa fila frente a las demás.
    """
    dpr = widget.devicePixelRatioF()
    fisico = max(1, round(lado * dpr))
    pm = icono.pixmap(QSize(fisico, fisico))
    if pm.isNull():
        return pm
    if pm.width() < fisico or pm.height() < fisico:
        pm = pm.scaled(fisico, fisico,
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


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
                # QIcon(ruta) NUNCA es nulo aunque el fichero no se pueda
                # decodificar: Qt lo carga en diferido, así que isNull() decía
                # que sí valía y luego pixmap() salía vacío. Quien decide es
                # el QPixmap.
                if not QPixmap(nombre).isNull():
                    return QIcon(nombre)
            elif QIcon.hasThemeIcon(nombre):
                return QIcon.fromTheme(nombre)
        return _con_respaldo(tema("folder"))
    return _con_respaldo(tema("folder-red", "folder"))


def _con_respaldo(icono):
    """El icono, o el logo de la aplicación si se quedó vacío.

    Solo para el icono de cada fila: un QLabel con pixmap nulo mide 0 px y
    descuadra la fila entera, así que aquí un hueco no es una opción.
    """
    return icono if not icono.isNull() else icono_app()


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


def texto_accesible(fila):
    """Frase que un lector de pantalla puede leer de una fila.

    Todo el contenido visible de la fila vive en un widget incrustado
    (setItemWidget) y los QLabel de dentro no se exponen como contenido del
    ítem: sin esto, el Narrador anuncia «lista, elemento 1 de 3» y nada más,
    así que no hay forma de saber qué carpeta se va a borrar antes de pulsar
    Supr.
    """
    partes = [fila["nombre"], fila["carpeta"]]
    n = fila.get("n", 0)
    if fila["existe"] and n > 0:
        partes.append(f"{n} PDF")
    if not fila["existe"]:
        partes.append("carpeta no encontrada")
    elif fila.get("modo") == "preguntar":
        partes.append("pregunta la contraseña cada vez")
    elif not fila["tiene_clave"]:
        partes.append("sin contraseña")
    else:
        partes.append("lista")
    return ", ".join(partes)


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


# ── Capa de color ──────────────────────────────────────────────────────
# Todo el color de la ventana pasa por aquí. Antes cada sitio decidía por su
# cuenta (un «palette(mid)», un hex suelto, el mismo «lightness() < 128»
# duplicado en dos funciones) y el resultado eran textos a 2:1 de contraste
# y colores que no se recalculaban al cambiar de tema.

def _luminancia(color):
    """Luminancia relativa WCAG de un QColor (0 = negro, 1 = blanco)."""
    def canal(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * canal(color.red())
            + 0.7152 * canal(color.green())
            + 0.0722 * canal(color.blue()))


def tema_oscuro(paleta):
    """True si el esquema de color es oscuro.

    Compara las LUMINANCIAS del fondo y del texto, en vez del antiguo
    «lightness() < 128»: ese umbral se equivoca con temas intermedios (un
    fondo gris medio cae justo en 128, elige la rama clara y deja el texto a
    1.3:1). Si el texto es más claro que su fondo, el tema es oscuro — da
    igual el gris del que se parta.
    """
    return (_luminancia(paleta.color(QPalette.ColorRole.WindowText))
            > _luminancia(paleta.color(QPalette.ColorRole.Window)))


# Colores semánticos, uno por tema. Salen de los roles Foreground* de los
# esquemas FISAT (FisatClaro/FisatOscuro.colors), oscurecidos en el tema
# claro para llegar a 4.5:1: los del esquema se quedan cortos sobre fondo
# blanco (ForegroundPositive 39,174,96 da 2.9:1).
_SEMANTICO_CLARO = {
    # 4.46:1 sobre el fondo de ventana con el verde de partida: justo por
    # debajo del 4.5 de WCAG AA, así que se oscurece un punto.
    "positivo": "#1a7340",
    "negativo": "#b02b38",
    "neutral":  "#8a4b00",
    "inactivo": "#5d6a75",
}
_SEMANTICO_OSCURO = {
    "positivo": "#7fd6a0",
    "negativo": "#f09a94",
    "neutral":  "#e0a76b",
    "inactivo": "#a1a9b1",
}


def semantico(widget, clave):
    """Color semántico (positivo/negativo/neutral/inactivo) del tema actual.

    Sustituye a «palette(mid)», que es un rol de SOMBREADO de marcos derivado
    del fondo, no un color de texto: daba unos 2:1 de contraste sobre la
    lista y era el motivo principal de que la ruta y el contador de PDF no se
    leyeran.
    """
    tabla = (_SEMANTICO_OSCURO if tema_oscuro(widget.palette())
             else _SEMANTICO_CLARO)
    return tabla[clave]


def escala_fuente(widget, factor):
    """Tamaño de fuente en pt, relativo al de la aplicación.

    Los tamaños fijos («9pt», «11pt») ignoraban la fuente del sistema: si
    alguien la subía por vista cansada, todo crecía MENOS la ruta y el
    contador, que es justo lo que peor se leía.
    """
    fuente = widget.font()
    base = fuente.pointSizeF()
    if base <= 0:                      # fuente definida en píxeles
        base = QFontInfo(fuente).pointSizeF() or 10.0
    return round(max(7.0, base * factor), 1)


# Colores de los «chips» de estado (claro/oscuro): cada entrada es (fondo,
# texto); en oscuro, fondos apagados con texto claro para que sean legibles.
# Todos los pares pasan de 4.5:1 (WCAG AA) sobre su propio fondo: «ok» y
# «nuevo» se quedaban en 4.21 y 4.44 en el tema claro.
_CHIP_CLARO = {
    "ok":    ("#d5f0dd", "#15693a"),
    "aviso": ("#fdecd9", "#a84300"),
    "error": ("#fbe3e0", "#b03a2e"),
    "nuevo": ("#fff3cd", "#6b5400"),
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


def estilo_pill(fondo, color):
    """Hoja de estilo de un «chip».

    Lleva BORDE además de fondo: en tema oscuro el fondo del chip informativo
    y el de la ventana tienen la misma luminancia (1.00:1), así que la píldora
    no se distinguía — se veía el texto suelto, sin forma que lo agrupara.
    """
    return (f"border-radius: 9px; padding: 2px 9px; font-weight: bold; "
            f"border: 1px solid {color}; background: {fondo}; color: {color};")


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
    def __init__(self, texto="", parent=None,
                 modo=Qt.TextElideMode.ElideMiddle):
        super().__init__(texto, parent)
        self._texto = texto
        self._modo = modo
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        # Mínimo en unidades de fuente, no 40 px fijos: con la fuente del
        # sistema subida, 40 px son cuatro caracteres y la ruta se quedaba
        # en un «…» que no informa de nada.
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 12)

    def setText(self, texto):
        self._texto = texto
        super().setText(texto)
        self.update()

    def paintEvent(self, _event):
        pintor = QPainter(self)
        # Pen explícito desde la paleta: al saltarse QLabel::paintEvent, el
        # color salía del pen por defecto de QPainter y dependía de que la
        # hoja de estilo hubiera volcado su «color:» en la paleta del widget.
        grupo = (QPalette.ColorGroup.Normal if self.isEnabled()
                 else QPalette.ColorGroup.Disabled)
        pintor.setPen(self.palette().color(grupo, self.foregroundRole()))
        elidido = self.fontMetrics().elidedText(
            self._texto, self._modo, self.width())
        pintor.drawText(
            self.rect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elidido)


# Indicador del estado del vigilante, en la barra de estado.
class IndicadorVigilante(QLabel):
    """Estado del vigilante: SIEMPRE con texto y con un glifo distinto por
    estado, nunca solo con color.

    Antes era un punto de color que únicamente se explicaba al pasar el ratón
    por encima, y fallaba por tres lados a la vez: el texto no se alcanzaba
    con el teclado ni lo leía un lector de pantalla; el punto medía unos
    pocos píxeles en una esquina; y «activo» (verde) y «detenido» (rojo) se
    convierten en el MISMO tono oliva bajo deuteranopía (1.0:1 entre sí) —
    justo el par que dice si tus PDF se están cifrando.
    """

    GLIFOS = {"activo": "✓", "detenido": "✕", "inactivo": "•"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName("Estado del vigilante")

    def set_estado(self, clave, texto, color, ayuda):
        self.setText(f"{self.GLIFOS.get(clave, '•')}  {texto}")
        self.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.setToolTip(ayuda)
        self.setAccessibleDescription(ayuda)


# Diálogo de contraseña (alta de carpeta o cambio de contraseña)
class DialogoContrasena(QDialog):
    """Contraseña de una carpeta, con el selector de modo: contraseña fija
    guardada, o preguntar cada vez que se suelte un PDF (entonces no se pide
    ni se guarda nada aquí; la pedirá el vigilante en el momento de cifrar)."""

    def __init__(self, parent=None, pedir_nombre=False,
                 nombre_def="Cifrar PDF", modo_actual="fija", carpeta=None):
        super().__init__(parent)
        self.pedir_nombre = pedir_nombre
        # Mientras nadie haya escrito, los mensajes son INSTRUCCIONES, no
        # errores: el constructor dispara la validación con los campos vacíos
        # y el diálogo se abría ya en rojo y con el botón apagado.
        self._tocado = False
        if pedir_nombre:
            titulo = "Nueva carpeta de cifrado"
        elif carpeta:
            titulo = f"Contraseña de «{carpeta}»"
        else:
            titulo = "Contraseña y modo"
        self.setWindowTitle(titulo)
        self.setWindowIcon(icono_app())
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        self.campo_nombre = None
        if pedir_nombre:
            form_nombre = QFormLayout()
            form_nombre.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self.campo_nombre = QLineEdit(nombre_def)
            self.campo_nombre.setClearButtonEnabled(True)
            self.campo_nombre.textChanged.connect(self._al_escribir)
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
        pista.setStyleSheet(f"color: {semantico(self, 'inactivo')};")
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
        self.pass1.textChanged.connect(self._al_escribir)

        self.pass2 = QLineEdit()
        self.pass2.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass2.setClearButtonEnabled(True)
        self.pass2.textChanged.connect(self._al_escribir)

        # Botón mostrar/ocultar contraseña. Es un botón solo-icono, así que
        # si no hay ninguno disponible (lo normal en Windows) se etiqueta con
        # texto en vez de dejar un cuadrado vacío junto al campo.
        self.ver = QToolButton()
        self.ver.setCheckable(True)
        self._ver_con_icono = not tema("view-visible", "visibility").isNull()
        self.ver.setToolTip("Mostrar u ocultar la contraseña")
        self.ver.setAccessibleName("Mostrar u ocultar la contraseña")
        self._pintar_ver(False)
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
        self.aviso.setStyleSheet(f"color: {semantico(self, 'inactivo')};")
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

    def _al_escribir(self):
        self._tocado = True
        self._validar()

    def _cambio_modo(self, _marcado=None):
        """Muestra u oculta los campos de contraseña según el modo elegido."""
        fija = self.radio_fija.isChecked()
        self.caja_pass.setVisible(fija)
        # «Guardar» chirriaba en un modo cuyo argumento de venta es que NO se
        # guarda nada.
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Guardar contraseña" if fija else "Aplicar")
        self._validar()
        # activate() antes de adjustSize(): con el aviso en dos líneas
        # (QLabel con wordWrap), el alto se calculaba mal y el texto podía
        # quedar recortado al volver de «preguntar» a «fija».
        self.layout().activate()
        self.adjustSize()

    def _pintar_ver(self, visible):
        if self._ver_con_icono:
            self.ver.setIcon(tema("view-hidden", "view-visible", "visibility")
                             if visible else tema("view-visible", "visibility"))
        else:
            self.ver.setText("Ocultar" if visible else "Ver")

    def _alternar_visible(self, visible):
        modo = (QLineEdit.EchoMode.Normal if visible
                else QLineEdit.EchoMode.Password)
        self.pass1.setEchoMode(modo)
        self.pass2.setEchoMode(modo)
        self._pintar_ver(visible)

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
            self.aviso.setStyleSheet(f"color: {semantico(self, 'positivo')};")
            return
        instruccion = False
        if not problema:
            if len(p1) < MIN_PASS:
                problema = f"La contraseña debe tener al menos {MIN_PASS} caracteres."
                instruccion = True
            elif p2 and p1 != p2:
                problema = "Las contraseñas no coinciden."
            elif not p2:
                problema = "Repite la contraseña para confirmarla."
                instruccion = True

        valido = not problema
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valido)
        if valido:
            self.aviso.setText("✓ Todo correcto.")
            self.aviso.setStyleSheet(f"color: {semantico(self, 'positivo')};")
        elif instruccion or not self._tocado:
            # «Debe tener al menos 8 caracteres» y «repite la contraseña» son
            # lo que hay que HACER, no algo que se haya hecho mal; y mientras
            # no se haya tocado nada, nada puede estar mal todavía. El rojo se
            # reserva para «las contraseñas no coinciden».
            self.aviso.setText(problema)
            self.aviso.setStyleSheet(f"color: {semantico(self, 'inactivo')};")
        else:
            self.aviso.setText(problema)
            self.aviso.setStyleSheet(f"color: {semantico(self, 'negativo')};")

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
        self._dimensionar()
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

    def _dimensionar(self):
        """Tamaño inicial y mínimo, en unidades de fuente y acotados a la
        pantalla disponible.

        Con 760×520 fijos la barra de herramientas no cabía (ocho acciones con
        texto suman bastante más) y Qt escondía las últimas tras el botón de
        desbordamiento. Y al revés: al 125-150 % de escalado en un 1366×768
        —los portátiles que más abundan en la fundación— unos píxeles fijos
        generosos dan una ventana más alta que el propio escritorio.
        """
        unidad = self.fontMetrics().height()
        ancho, alto = unidad * 52, unidad * 30
        min_ancho, min_alto = unidad * 38, unidad * 20
        pantalla = QApplication.primaryScreen()
        if pantalla is not None:
            libre = pantalla.availableGeometry()
            ancho = min(ancho, int(libre.width() * 0.9))
            alto = min(alto, int(libre.height() * 0.9))
            min_ancho = min(min_ancho, libre.width())
            min_alto = min(min_alto, libre.height())
        self.setMinimumSize(min_ancho, min_alto)
        self.resize(ancho, alto)

    def changeEvent(self, event):
        """Recalcula los colores cuando cambia el tema (o la fuente).

        Dependen de si el esquema es claro u oscuro y se resolvían una sola
        vez, al construir cada fila. Sin esto, cambiar el modo claro/oscuro de
        Windows con la ventana abierta dejaba los chips y el indicador con los
        colores del tema ANTERIOR —fondos claros sobre ventana oscura— hasta
        cerrarla y volver a abrirla: el QFileSystemWatcher vigila la
        configuración de las carpetas, no el tema del sistema.
        """
        if event.type() in (QEvent.Type.PaletteChange,
                            QEvent.Type.ApplicationPaletteChange,
                            QEvent.Type.FontChange):
            # Por el timer, para agrupar la ráfaga de eventos que llega al
            # cambiar de tema (y porque puede dispararse durante __init__).
            if getattr(self, "_timer_refresco", None) is not None:
                self._timer_refresco.start()
        super().changeEvent(event)

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
        # Con atajo y registrada en la ventana: es una acción DESTRUCTIVA que
        # no tenía ninguno, no estaba en el menú contextual y vive en la barra
        # (cuyos botones Qt crea sin foco), así que no había forma de llegar a
        # ella sin ratón.
        self._configurar_accion(
            self.act_quitar_todas, QKeySequence("Ctrl+Shift+Del"),
            "Quitar todas las carpetas de cifrado")
        self.addAction(self.act_quitar_todas)

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
        # Poner un tooltip propio pisa el automático de Qt, que habría añadido
        # el atajo entre paréntesis: sin esto los atajos solo se descubrían
        # abriendo el menú contextual, y ni el tooltip los decía.
        tecla = accion.shortcut().toString(
            QKeySequence.SequenceFormat.NativeText)
        accion.setToolTip(f"{ayuda} ({tecla})" if tecla else ayuda)
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

        # Las tres secundarias, solo icono: con texto, las ocho acciones
        # sumaban más ancho del que tenía la ventana y Qt escondía las
        # últimas tras el botón de desbordamiento «»» — lo primero que veía
        # la trabajadora era una barra amputada. Conservan tooltip, atajo y
        # nombre accesible (sale del texto de la acción).
        for accion in (self.act_quitar_todas, self.act_registro,
                       self.act_refrescar):
            boton = barra.widgetForAction(accion)
            if boton is not None:
                boton.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly)

        # QToolBar crea sus botones con Qt::NoFocus, así que la barra entera
        # quedaba fuera del recorrido del Tab: sin ratón solo se circulaba
        # entre la lista y el botón del estado vacío.
        for accion in barra.actions():
            boton = barra.widgetForAction(accion)
            if boton is not None:
                boton.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _crear_cuerpo(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Cabecera con icono y texto explicativo.
        cabecera = QHBoxLayout()
        icono = QLabel()
        icono.setPixmap(pixmap_nitido(self, icono_app(), 48))
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

        # Banda de aviso: aparece solo cuando el vigilante está parado y hay
        # carpetas, es decir, cuando los PDF que sueltes NO se van a cifrar.
        # Esa noticia no puede quedarse en un indicador de la barra de estado.
        self.banda = QLabel(
            "El vigilante no está en marcha: los PDF que sueltes ahora NO se "
            "cifrarán. Cierra la sesión y vuelve a entrar para reactivarlo.")
        self.banda.setWordWrap(True)
        self.banda.setVisible(False)
        layout.addWidget(self.banda)

        self.lista = ListaCarpetas()
        self.lista.setAlternatingRowColors(True)
        # Aire entre filas: el rayado alterno es un delta de luminancia
        # mínimo y, por sí solo, cinco o seis carpetas se leen como una única
        # mancha de texto de dos niveles.
        self.lista.setSpacing(3)
        # Sin barra horizontal: que el texto largo se elida, no que la lista
        # se desplace de lado (lo peor para recorrerla con la vista).
        self.lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        v_icono.setPixmap(
            pixmap_nitido(self, _con_respaldo(tema("folder",
                                                   "document-encrypt")), 64))
        vlay.addWidget(v_icono)

        v_texto = QLabel(
            "Aún no tienes ninguna carpeta de cifrado.\n"
            "Crea la primera y empieza a proteger tus PDF.")
        v_texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_texto.setStyleSheet(
            f"color: {semantico(self, 'inactivo')}; "
            f"font-size: {escala_fuente(self, 1.1)}pt;")
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
            item.setData(Qt.ItemDataRole.AccessibleTextRole,
                         texto_accesible(fila))
            self.lista.addItem(item)
            self.lista.setItemWidget(item, self._fila_widget(fila))
            # Solo el ALTO: fijando también el ancho, el nombre largo de
            # una carpeta obligaba a la lista a sacar barra horizontal en vez
            # de dejar que el texto se elidiera.
            item.setSizeHint(QSize(
                0, self.lista.itemWidget(item).sizeHint().height()))
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

        # Estado del vigilante (widget permanente, a la derecha): glifo +
        # texto + color, nunca el color a solas.
        _rc, estado, _err = backend(["--gui-estado"])
        if estado == "1":
            clave, texto = "activo", "Vigilante activo"
            color = semantico(self, "positivo")
            ayuda = ("El vigilante está en marcha: los PDF que sueltes en tus "
                     "carpetas se cifran automáticamente.")
        elif hay:
            clave, texto = "detenido", "Vigilante detenido"
            color = semantico(self, "negativo")
            ayuda = ("El vigilante no está en marcha, así que los PDF nuevos no "
                     "se cifrarán. Cierra la sesión y vuelve a entrar para "
                     "reactivarlo.")
        else:
            clave, texto = "inactivo", "Sin carpetas de cifrado"
            color = semantico(self, "inactivo")
            ayuda = ("Aún no hay carpetas de cifrado. Pulsa «Añadir carpeta» "
                     "para crear la primera y empezar a proteger tus PDF.")
        self.lbl_vigilante.set_estado(clave, texto, color, ayuda)
        self._mostrar_banda(clave == "detenido")

        self._actualizar_acciones()
        self._pintar_seleccion()
        self._actualizar_watches(filas)

    def _mostrar_banda(self, visible):
        """Pinta y muestra (u oculta) la banda de «vigilante detenido»."""
        if visible:
            fondo, color = colores_chip("error", tema_oscuro(self.palette()))
            self.banda.setStyleSheet(
                f"border: 1px solid {color}; border-radius: 4px; "
                f"padding: 8px; background: {fondo}; color: {color}; "
                f"font-weight: bold;")
        self.banda.setVisible(visible)

    # Color del texto según selección
    def _colorear_fila(self, widget, seleccionado):
        """Color del texto de una fila.

        En la fila seleccionada el texto pasa a «highlighted-text» para que
        contraste sobre el fondo de la selección, sea cual sea.

        Fuera de la selección, el texto secundario usa el color semántico
        «inactivo» en vez de «palette(mid)»: ese rol es un sombreado de marcos
        derivado del fondo y dejaba la ruta y el contador en unos 2:1.
        """
        if seleccionado:
            principal = secundario = "palette(highlighted-text)"
        else:
            principal = "palette(text)"
            secundario = semantico(self, "inactivo")
        pequena = escala_fuente(self, 0.9)
        widget._lbl_nombre.setStyleSheet(
            f"font-weight: bold; color: {principal};")
        widget._lbl_ruta.setStyleSheet(
            f"font-size: {pequena}pt; color: {secundario};")
        if widget._lbl_contador is not None:
            # El contador es un DATO (¿ha llegado ya mi PDF?), no un metadato:
            # va en color de texto normal y en negrita, no en el gris tenue de
            # la ruta, que es donde estaba y donde no se leía.
            widget._lbl_contador.setStyleSheet(
                f"font-size: {pequena}pt; font-weight: bold; "
                f"color: {principal};")

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
        # Con la tecla Menú (o Shift+F10) el evento NO trae la posición del
        # cursor —Qt usa el centro del widget—, así que itemAt() no encuentra
        # fila. Antes eso hacía una de dos cosas malas: o el menú no salía, o
        # salía y setCurrentItem MOVÍA la selección a la fila que hubiera en el
        # centro de la lista, con lo que el «Quitar» siguiente iba sobre otra
        # carpeta.
        item = self.lista.itemAt(pos)
        if item is not None:
            # Clic derecho sobre una fila: la selección sigue al clic.
            self.lista.setCurrentItem(item)
            punto = self.lista.viewport().mapToGlobal(pos)
        else:
            # Por teclado: se actúa sobre la fila ya seleccionada, sin moverla,
            # y el menú se ancla a esa fila en vez de a un punto arbitrario.
            item = self.lista.currentItem()
            if item is None:
                return
            rect = self.lista.visualItemRect(item)
            punto = self.lista.viewport().mapToGlobal(rect.bottomLeft())
        menu = QMenu(self)
        menu.addAction(self.act_abrir)
        menu.addAction(self.act_renombrar)
        menu.addAction(self.act_clave)
        menu.addSeparator()
        menu.addAction(self.act_quitar)
        menu.addAction(self.act_quitar_todas)
        menu.exec(punto)

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

    def _columna(self, ancho, etiqueta):
        """Mete una etiqueta en una columna de ancho fijo, pegada a la derecha.

        Contador y chip colgaban sueltos del layout y ambos eran opcionales,
        así que la posición del «3 PDF» cambiaba de una fila a otra según lo
        que llevara la de al lado: no quedaba ninguna vertical sobre la que
        apoyar la vista al recorrer la lista.
        """
        caja = QWidget()
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        if etiqueta is not None:
            lay.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignVCenter)
        caja.setFixedWidth(ancho)
        return caja

    def _fila_widget(self, fila):
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(6, 8, 6, 8)
        h.setSpacing(10)
        oscuro = tema_oscuro(self.palette())
        centrado = Qt.AlignmentFlag.AlignVCenter
        fm = self.fontMetrics()
        ancho_contador = fm.horizontalAdvance("8888 PDF") + 14
        ancho_chip = fm.horizontalAdvance("⚠  Carpeta no encontrada") + 34

        icono = QLabel()
        # Tamaño fijo y centrado: QIcon.pixmap() no AMPLÍA por encima del
        # tamaño natural del fichero, así que un icono personalizado de 16×16
        # salía a 16 px y descuadraba la sangría de esa fila respecto a las
        # demás.
        icono.setFixedSize(32, 32)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(pixmap_nitido(
            self, icono_carpeta(fila["carpeta"], fila["existe"]), 32))
        h.addWidget(icono, 0, centrado)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        # El nombre también se elide: lo teclea la trabajadora, y siendo un
        # QLabel normal su ancho íntegro entraba en el sizeHint de la fila y
        # empujaba el chip fuera de la ventana («⚠ Sin contras»).
        nombre = EtiquetaElidida(fila["nombre"],
                                 modo=Qt.TextElideMode.ElideRight)
        ruta = EtiquetaElidida(fila["carpeta"])
        textos.addWidget(nombre)
        textos.addWidget(ruta)
        h.addLayout(textos, 1)

        # Etiquetas cuyo color cambia según la fila esté seleccionada o no
        # (para que contrasten sobre el fondo de la selección).
        widget._lbl_nombre = nombre
        widget._lbl_ruta = ruta
        widget._lbl_contador = None

        # Contador de PDF (vacío si es 0, pero la columna se reserva igual);
        # si el número subió hace poco, se resalta como «chip» para avisar de
        # que hay un PDF más.
        n = fila.get("n", 0)
        contador = None
        if fila["existe"] and n > 0:
            contador = QLabel(f"{n} PDF")
            if fila.get("reciente"):
                contador.setText(f"▲ {n} PDF")
                fondo, color = colores_chip("nuevo", oscuro)
                contador.setStyleSheet(estilo_pill(fondo, color))
                contador.setToolTip("Se ha añadido un PDF recientemente")
            else:
                widget._lbl_contador = contador  # color según selección
        h.addWidget(self._columna(ancho_contador, contador), 0, centrado)

        # Chip de estado, SIEMPRE presente. Antes «todo bien» se comunicaba
        # por ausencia de chip, que es indistinguible de «aún no lo he
        # comprobado»; y error y aviso compartían el glifo ⚠, con lo que solo
        # los separaba el tono del pastel de fondo.
        texto_estado, clave = "✓  Lista", "ok"
        if fila.get("modo") == "preguntar":
            if not fila["existe"]:
                texto_estado, clave = "⚠  Carpeta no encontrada", "aviso"
            else:
                texto_estado, clave = "🔑  Pregunta cada vez", "info"
        elif not fila["tiene_clave"]:
            texto_estado, clave = "✕  Sin contraseña", "error"
        elif not fila["existe"]:
            texto_estado, clave = "⚠  Carpeta no encontrada", "aviso"
        fondo, color = colores_chip(clave, oscuro)
        estado = QLabel(texto_estado)
        estado.setStyleSheet(estilo_pill(fondo, color))
        if clave == "info":
            estado.setToolTip(
                "Esta carpeta no guarda contraseña: se te pedirá cada vez "
                "que sueltes un PDF en ella.")
        elif clave == "ok":
            estado.setToolTip(
                "La carpeta existe y tiene contraseña guardada: los PDF que "
                "sueltes aquí se cifran solos.")
        h.addWidget(self._columna(ancho_chip, estado), 0, centrado)

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
                                modo_actual=fila.get("modo", "fija"),
                                carpeta=fila.get("nombre"))
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


def _identificar_en_barra_de_tareas():
    """Declara el identificador de modelo de aplicación (Windows).

    Es el equivalente del WM_CLASS/StartupWMClass que la copia de Debian fija
    con setDesktopFileName: sin él, Windows deduce la identidad del proceso y
    la ventana de un ejecutable lanzado desde un acceso directo puede acabar
    en un botón de la barra de tareas SEPARADO del anclado, con el icono
    genérico. Con él, ventana y acceso directo se agrupan.

    Si falla no pasa nada: solo se pierde la agrupación.
    """
    if not ES_WINDOWS:
        return
    try:
        from cifrarpdf import _win
        _win.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"FISAT.{APP_NOMBRE}")
    except Exception:  # noqa: BLE001 — un detalle de barra de tareas no impide abrir
        pass


def main():
    _identificar_en_barra_de_tareas()
    app = QApplication(sys.argv)
    # El nombre de aplicación va SIN espacios: en Debian de él sale el
    # WM_CLASS de la ventana en X11. Lo que se ve escrito es el DisplayName,
    # que sí lleva el título bonito.
    app.setApplicationName(APP_NOMBRE)
    app.setApplicationDisplayName(APP_TITLE)
    if not ES_WINDOWS:
        # Asocia la ventana con su .desktop (fisat-cifrar-pdf.desktop): la barra
        # de tareas usa su icono (no uno genérico) y fija el WM_CLASS/app_id.
        app.setDesktopFileName(APP_NOMBRE)
    app.setWindowIcon(icono_app())
    ventana = Ventana()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
