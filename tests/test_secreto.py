"""Guardado de la contraseña (credenciales del sistema o fichero protegido)."""

import pytest

from cifrarpdf import secreto


@pytest.mark.parametrize(("clave", "valida"), [
    ("12345678", True),
    ("contraseña larga", True),
    ("1234567", False),
    ("", False),
])
def test_validacion(clave, valida):
    assert (secreto.validar_clave(clave) is None) is valida


def test_ida_y_vuelta(sin_keyring):
    assert secreto.guardar("informes", "contraseña-larga")
    assert secreto.leer("informes") == "contraseña-larga"
    assert secreto.tiene_clave("informes")


def test_acentos_y_simbolos(sin_keyring):
    clave = "ñandú-€uro «cita» 12"
    secreto.guardar("informes", clave)
    assert secreto.leer("informes") == clave


def test_borrar(sin_keyring):
    secreto.guardar("informes", "contraseña-larga")
    secreto.borrar("informes")
    assert secreto.leer("informes") is None
    assert not secreto.tiene_clave("informes")


def test_sin_clave_guardada(sin_keyring):
    assert secreto.leer("nunca-existio") is None


def test_el_fichero_no_guarda_la_clave_en_claro(sin_keyring):
    """En Windows el fallback va cifrado con DPAPI; en Linux es solo desarrollo."""
    secreto.guardar("informes", "contraseña-larga")
    datos = secreto._fichero_dpapi("informes").read_bytes()
    if secreto.rutas.ES_WINDOWS:
        assert b"contrase" not in datos
    else:
        pytest.skip("DPAPI solo existe en Windows")
