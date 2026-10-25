"""Comprobación mínima de la ventana: que se construye y lista bien.

No prueba la interacción (para eso hace falta una persona delante), pero sí
detecta lo que más se rompe al portar: que la ventana ni siquiera abra, que la
lista no lea el backend, o que en Windows los botones se queden sin icono
porque el respaldo de iconos estándar no funciona.

Corre sin pantalla con QT_QPA_PLATFORM=offscreen.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def aplicacion():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_la_ventana_se_construye_vacia(aplicacion):
    import gui
    ventana = gui.Ventana()
    assert "Cifrar PDF" in ventana.windowTitle()
    assert ventana.lista.count() == 0
    ventana.close()


def test_en_windows_los_iconos_tienen_respaldo(aplicacion):
    """En Windows no hay tema de iconos: debe entrar el respaldo de Qt."""
    import gui
    if not gui.ES_WINDOWS:
        pytest.skip("en Debian los iconos vienen del tema Breeze")
    assert not gui.tema("list-add").isNull()
    assert not gui.tema("folder").isNull()
    assert not gui.icono_app().isNull()


def test_el_comando_del_backend_apunta_a_algo(aplicacion):
    import gui
    orden = gui.comando_backend()
    assert orden and isinstance(orden, list)


def test_el_dialogo_oculta_la_contrasena_al_preguntar(aplicacion):
    """El selector de modo es lo que decide si hay campos de contraseña.

    En «preguntar» no hay nada que escribir aquí, así que los campos se
    esconden y Guardar tiene que quedar habilitado igualmente.
    """
    from PyQt6.QtWidgets import QDialogButtonBox

    import gui
    dlg = gui.DialogoContrasena(pedir_nombre=True, nombre_def="Informes")
    aceptar = dlg.botones.button(QDialogButtonBox.StandardButton.Ok)

    assert dlg.modo() == "fija"
    assert dlg.caja_pass.isVisibleTo(dlg)
    assert not aceptar.isEnabled(), "en fija hace falta escribir la contraseña"

    dlg.radio_preguntar.setChecked(True)
    assert dlg.modo() == "preguntar"
    assert not dlg.caja_pass.isVisibleTo(dlg)
    assert aceptar.isEnabled()
    assert dlg.contrasena() == "", "no se manda contraseña en modo preguntar"
    dlg.close()


def test_el_dialogo_arranca_en_el_modo_de_la_carpeta(aplicacion):
    import gui
    dlg = gui.DialogoContrasena(pedir_nombre=False, modo_actual="preguntar")
    assert dlg.radio_preguntar.isChecked()
    dlg.close()


def test_texto_accesible_describe_la_fila(aplicacion):
    """Un lector de pantalla solo decía «elemento 1 de 3»: el contenido de la
    fila vive en un widget incrustado y no se expone como texto del ítem."""
    import gui
    base = {"nombre": "Informes", "carpeta": r"C:\\Escritorio\\Informes",
            "existe": True, "tiene_clave": True, "modo": "fija", "n": 3}
    texto = gui.texto_accesible(base)
    assert "Informes" in texto and "3 PDF" in texto and texto.endswith("lista")

    assert gui.texto_accesible({**base, "modo": "preguntar",
                                "tiene_clave": False}).endswith(
        "pregunta la contraseña cada vez")
    assert gui.texto_accesible({**base, "tiene_clave": False}).endswith(
        "sin contraseña")
    assert gui.texto_accesible({**base, "existe": False}).endswith(
        "carpeta no encontrada")


def test_el_tema_oscuro_se_detecta_por_luminancia(aplicacion):
    """Y no por «lightness() < 128», que se equivoca con grises medios."""
    from PyQt6.QtGui import QColor, QPalette

    import gui
    paleta = QPalette()
    paleta.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    paleta.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
    assert gui.tema_oscuro(paleta)
    paleta.setColor(QPalette.ColorRole.Window, QColor(250, 250, 250))
    paleta.setColor(QPalette.ColorRole.WindowText, QColor(20, 20, 20))
    assert not gui.tema_oscuro(paleta)


def test_los_chips_llegan_al_contraste_minimo(aplicacion):
    """4.5:1 (WCAG AA) entre el texto del chip y su propio fondo."""
    from PyQt6.QtGui import QColor

    import gui
    for tabla in (gui._CHIP_CLARO, gui._CHIP_OSCURO):
        for estado, (fondo, texto) in tabla.items():
            claro = gui._luminancia(QColor(fondo))
            oscuro = gui._luminancia(QColor(texto))
            if claro < oscuro:
                claro, oscuro = oscuro, claro
            ratio = (claro + 0.05) / (oscuro + 0.05)
            assert ratio >= 4.5, f"{estado}: {ratio:.2f}:1"


def test_el_dialogo_no_abre_ya_en_rojo(aplicacion):
    """Mientras nadie ha escrito, los mensajes son instrucciones, no errores."""
    import gui
    dlg = gui.DialogoContrasena(pedir_nombre=True, nombre_def="Informes")
    assert not dlg._tocado
    assert gui._SEMANTICO_CLARO["negativo"] not in dlg.aviso.styleSheet()
    assert gui._SEMANTICO_OSCURO["negativo"] not in dlg.aviso.styleSheet()
    dlg.close()


def test_texto_accesible_sigue_el_orden_de_casos_del_chip(aplicacion):
    """El lector de pantalla debe decir lo mismo que el chip de la fila."""
    import gui
    base = {"nombre": "Informes", "carpeta": r"C:\Escritorio\Informes",
            "existe": False, "tiene_clave": True, "modo": "fija", "n": 0}
    assert gui.texto_accesible({**base, "modo": "preguntar"}).endswith(
        "carpeta no encontrada")
    assert gui.texto_accesible({**base, "tiene_clave": False}).endswith(
        "sin contraseña")


def test_contar_pdf_cuenta_temp_visibles_y_no_ocultos(aplicacion, tmp_path):
    """Un «contrato_temp.pdf» del usuario es un PDF más; los temporales del
    backend son ocultos."""
    import gui
    for nombre in ("contrato_temp.pdf", ".x.123_temp.pdf", "INFORME.PDF"):
        (tmp_path / nombre).write_bytes(b"%PDF-")
    assert gui.contar_pdf(str(tmp_path)) == 2


@pytest.mark.parametrize("nombre", [".", ".."])
def test_el_dialogo_rechaza_los_nombres_punto(aplicacion, nombre):
    from PyQt6.QtWidgets import QDialogButtonBox

    import gui
    dlg = gui.DialogoContrasena(pedir_nombre=True, nombre_def="Informes")
    dlg.radio_preguntar.setChecked(True)
    dlg.campo_nombre.setText(nombre)
    assert dlg.aviso.text() == "El nombre no puede ser «.» ni «..»."
    aceptar = dlg.botones.button(QDialogButtonBox.StandardButton.Ok)
    assert not aceptar.isEnabled()
    dlg.close()


def _ventana_con_carpeta(monkeypatch, destino):
    import gui
    ventana = gui.Ventana()
    monkeypatch.setattr(ventana, "_carpetas", lambda: [
        {"id": "inf", "nombre": "Informes", "carpeta": str(destino)}])
    avisos = {"error": [], "aviso": [], "backend": []}
    monkeypatch.setattr(ventana, "_error", avisos["error"].append)
    monkeypatch.setattr(ventana, "_aviso", avisos["aviso"].append)
    monkeypatch.setattr(gui, "backend", avisos["backend"].append)
    return ventana, avisos


def test_soltar_un_pdf_oculto_avisa_y_no_lo_copia(
        aplicacion, tmp_path, monkeypatch):
    origen = tmp_path / "origen"
    destino = tmp_path / "destino"
    origen.mkdir()
    destino.mkdir()
    oculto = origen / ".secreto.pdf"
    oculto.write_bytes(b"%PDF-")
    ventana, avisos = _ventana_con_carpeta(monkeypatch, destino)

    ventana._soltar_pdfs("inf", [str(oculto)])

    assert list(destino.iterdir()) == []
    assert len(avisos["aviso"]) == 1 and ".secreto.pdf" in avisos["aviso"][0]
    assert avisos["backend"] == []
    ventana.close()


def test_soltar_con_fallo_de_copia_dice_cuantos_y_limpia_la_copia(
        aplicacion, tmp_path, monkeypatch):
    import shutil

    origen = tmp_path / "origen"
    destino = tmp_path / "destino"
    origen.mkdir()
    destino.mkdir()
    bueno = origen / "bueno.pdf"
    malo = origen / "malo.pdf"
    bueno.write_bytes(b"%PDF-")
    malo.write_bytes(b"%PDF-")
    ventana, avisos = _ventana_con_carpeta(monkeypatch, destino)
    copiar_real = shutil.copy2

    def copiar(origen_, destino_):
        if os.path.basename(origen_) == "malo.pdf":
            Path(destino_).write_bytes(b"%PD")  # copia a medias
            raise OSError(28, "No queda espacio en el dispositivo")
        return copiar_real(origen_, destino_)

    monkeypatch.setattr(shutil, "copy2", copiar)

    ventana._soltar_pdfs("inf", [str(bueno), str(malo)])

    assert sorted(p.name for p in destino.iterdir()) == ["bueno.pdf"]
    assert len(avisos["error"]) == 1
    assert "Copiados 1 de 2" in avisos["error"][0]
    assert "malo.pdf" in avisos["error"][0]
    assert avisos["backend"] == [["--gui-asegurar"]]
    ventana.close()


def test_los_separadores_de_la_barra_no_reciben_foco_con_tab(aplicacion):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QToolBar

    import gui
    ventana = gui.Ventana()
    barra = ventana.findChild(QToolBar)
    separadores = [a for a in barra.actions() if a.isSeparator()]
    assert separadores, "la barra debería tener separadores"
    for accion in separadores:
        widget = barra.widgetForAction(accion)
        assert widget.focusPolicy() == Qt.FocusPolicy.NoFocus
    for accion in barra.actions():
        if not accion.isSeparator():
            assert barra.widgetForAction(accion).focusPolicy() \
                == Qt.FocusPolicy.TabFocus
    ventana.close()


def test_los_titulos_no_repiten_el_nombre_de_la_aplicacion(
        aplicacion, tmp_path, monkeypatch):
    """Con setApplicationDisplayName, Qt añade « — Cifrar PDF — FISAT» a todo
    título que no termine así: los diálogos no deben llevar el nombre."""
    from PyQt6.QtWidgets import QMessageBox

    import gui
    titulos = []

    def espia(respuesta):
        def _f(_padre, titulo, *args, **kwargs):
            titulos.append(titulo)
            return respuesta
        return _f

    Si = QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", espia(Si))
    monkeypatch.setattr(QMessageBox, "warning", espia(Si))
    monkeypatch.setattr(QMessageBox, "critical", espia(None))
    monkeypatch.setattr(QMessageBox, "information", espia(None))
    monkeypatch.setattr(gui, "backend", lambda args: (0, "", ""))

    carpeta = tmp_path / "Informes"
    carpeta.mkdir()
    ventana = gui.Ventana()
    filas = [{"id": "inf", "nombre": "Informes", "carpeta": str(carpeta),
              "existe": True, "tiene_clave": True, "modo": "fija", "n": 0}]
    monkeypatch.setattr(ventana, "_carpetas", lambda: filas)
    monkeypatch.setattr(ventana, "fila_seleccionada", lambda: filas[0])
    monkeypatch.setattr(ventana, "refrescar", lambda: None)
    monkeypatch.setattr(ventana.lista, "count", lambda: 1)

    ventana.quitar()
    ventana.quitar_todas()
    ventana._error("x")
    ventana._aviso("x")
    monkeypatch.setattr(gui, "LOG_FILE", str(tmp_path / "registro.log"))
    registro = gui.DialogoRegistro(ventana)
    registro._limpiar()
    titulo_registro = registro.windowTitle()
    registro.close()
    ventana.close()

    assert len(titulos) == 7, titulos
    for titulo in titulos + [titulo_registro]:
        assert "Cifrar PDF" not in titulo, titulo


def test_el_traductor_pone_en_castellano_los_botones_estandar(aplicacion):
    """Sin qtbase_es, «Yes»/«No»/«OK» salen en inglés en Windows."""
    from PyQt6.QtCore import QCoreApplication

    import gui
    traductor = gui.instalar_traductor_qt(aplicacion)
    try:
        assert traductor is not None
        assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sí"
    finally:
        if traductor is not None:
            aplicacion.removeTranslator(traductor)
