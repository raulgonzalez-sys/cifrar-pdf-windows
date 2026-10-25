"""Control del vigilante: instancia única, parada y autorreparación."""

import time

import pytest

from cifrarpdf import proceso, rutas


def test_sin_vigilante_no_esta_activo():
    assert proceso.activo() is False


def test_parar_sin_vigilante_no_se_queda_esperando():
    """Sin nadie a quien parar, no debe agotar el plazo de espera entero."""
    inicio = time.monotonic()
    assert proceso.parar(espera=10.0) is True
    assert time.monotonic() - inicio < 4.0


def test_asegurar_sin_carpetas_no_lanza_nada(monkeypatch):
    """Sin carpetas configuradas no hay nada que vigilar: no se arranca."""
    lanzados = []
    monkeypatch.setattr(proceso, "arrancar", lambda: lanzados.append(True))
    assert proceso.asegurar() is True
    assert not lanzados


def test_pedir_parada_sin_nadie_escuchando_no_falla():
    proceso.pedir_parada()


@pytest.mark.skipif(not rutas.ES_WINDOWS, reason="evento con nombre de Win32")
def test_la_parada_llega_al_vigilante_en_marcha():
    """El evento tiene que existir mientras viva el vigilante: si solo existiera
    durante cada consulta, «pedir_parada» no lo encontraría casi nunca."""
    with proceso.Vigilancia():
        assert proceso.parada_pedida(0) is False
        proceso.pedir_parada()
        assert proceso.parada_pedida(0) is True


def test_pedir_barrido_crea_el_marcador():
    from cifrarpdf import rutas
    marcador = rutas.barrer_dir() / "informes"
    marcador.write_text("viejo", encoding="utf-8")
    assert proceso.pedir_barrido("informes") is True
    assert marcador.is_file()
    assert marcador.read_bytes() == b""


@pytest.mark.parametrize("cid", ["", ".", "..", ".oculto", "a/b", "a\\b", "../fuera"])
def test_pedir_barrido_rechaza_ids_malos(cid):
    from cifrarpdf import rutas
    assert proceso.pedir_barrido(cid) is False
    assert list(rutas.barrer_dir().iterdir()) == []


@pytest.mark.skipif(rutas.ES_WINDOWS, reason="rama POSIX; en Windows tocaría el Run real")
def test_quien_lanza_el_vigilante_con_tuberias_recibe_el_final(escritorio, monkeypatch):
    """La ventana lanza «--gui-asegurar» capturando su salida: si el vigilante
    heredara esas tuberías, nunca llegaría el fin de fichero y se colgaría."""
    import subprocess
    import sys
    from pathlib import Path

    from cifrarpdf import config
    monkeypatch.setenv("CIFRARPDF_SIN_BANDEJA", "1")
    config.escribir("informes", "Informes", escritorio / "Informes", "preguntar")
    try:
        resultado = subprocess.run(
            [sys.executable, "-m", "cifrarpdf", "--gui-asegurar"],
            capture_output=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert resultado.returncode == 0, resultado.stderr
    finally:
        assert proceso.parar()
