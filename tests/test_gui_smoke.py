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
