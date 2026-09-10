"""Autoarranque en la sesión del usuario."""

from cifrarpdf import autostart, rutas


def test_activar_y_desactivar():
    assert not autostart.activo()
    assert autostart.activar()
    assert autostart.activo()
    autostart.desactivar()
    assert not autostart.activo()


def test_desactivar_dos_veces_no_falla():
    autostart.desactivar()
    autostart.desactivar()


def test_la_orden_incluye_el_vigilante():
    assert "--vigilante" in rutas.linea_comando_vigilante()
