"""Control del vigilante: instancia única, parada y autorreparación."""

import time

from cifrarpdf import proceso


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
