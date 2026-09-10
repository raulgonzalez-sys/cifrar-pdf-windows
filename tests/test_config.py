"""Nombres, identificadores y persistencia de las carpetas configuradas."""

import pytest

from cifrarpdf import config, rutas


@pytest.mark.parametrize("nombre", ["Informes", "Cifrar PDF", "Nóminas 2026", "a"])
def test_nombres_validos(nombre):
    assert config.validar_nombre(nombre) is None


@pytest.mark.parametrize("nombre", [
    "", "   ", " Informes", "Informes ", "con/barra", "con\\barra", "dos:puntos",
    "aste*risco", "inter?rogante", "may|or", 'con"comillas', "acaba.", "CON", "NUL.txt",
    "x" * 101,
])
def test_nombres_invalidos(nombre):
    assert config.validar_nombre(nombre) is not None


def test_nombres_invalidos_de_windows_tambien_en_linux():
    """La validación es la MISMA en los dos sistemas.

    Si en Linux se dejara crear «CON» o «a|b», ese perfil no se podría llevar a
    un equipo Windows. Se valida siempre con el criterio más estricto.
    """
    assert "reservado" in config.validar_nombre("COM1")
    assert config.validar_nombre("a|b") is not None


@pytest.mark.parametrize(("nombre", "esperado"), [
    ("Informes", "informes"),
    ("Nóminas 2026", "nominas-2026"),
    ("  Doble  espacio ", "doble-espacio"),
    ("¡¿!", "carpeta"),
    ("ÁÉÍÓÚ ñ", "aeiou-n"),
])
def test_slug(nombre, esperado):
    assert config.slug(nombre) == esperado


def test_ids_no_colisionan():
    config.escribir("informes", "Informes", rutas.escritorio() / "Informes")
    assert config.nuevo_id("Informes") == "informes-2"
    config.escribir("informes-2", "Informes", rutas.escritorio() / "Informes2")
    assert config.nuevo_id("Informes") == "informes-3"


def test_escribir_y_leer():
    ruta = rutas.escritorio() / "Informes"
    config.escribir("informes", "Informes", ruta)
    leida = config.leer("informes")
    assert leida is not None
    assert (leida.id, leida.nombre, leida.ruta) == ("informes", "Informes", ruta)
    assert not leida.existe
    ruta.mkdir()
    assert config.leer("informes").existe


def test_leer_configuracion_corrupta_no_revienta():
    (rutas.carpetas_dir() / "roto.json").write_text("{no es json", encoding="utf-8")
    assert config.leer("roto") is None
    assert config.listar() == []


def test_ya_configurada():
    ruta = rutas.escritorio() / "Informes"
    config.escribir("informes", "Informes", ruta)
    assert config.ya_configurada(ruta)
    assert config.ya_configurada(rutas.escritorio() / "Informes" / ".")
    assert not config.ya_configurada(rutas.escritorio() / "Otra")


def test_hay_carpetas_y_borrar():
    assert not config.hay_carpetas()
    config.escribir("informes", "Informes", rutas.escritorio() / "Informes")
    assert config.hay_carpetas()
    config.borrar("informes")
    assert not config.hay_carpetas()
