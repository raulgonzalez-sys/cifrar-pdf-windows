"""El vigilante: qué recoge, los avisos de barrido y el lote."""

import queue

import pytest

from cifrarpdf import vigilante


@pytest.fixture
def cola():
    return queue.Queue()


def nombres_en(cola):
    vistos = []
    while not cola.empty():
        vistos.append(cola.get_nowait().name)
    return vistos


def test_el_manejador_acepta_mayusculas_y_temp_del_usuario(escritorio, cola):
    manejador = vigilante._Manejador(cola)
    for nombre in ("INFORME.PDF", "contrato_temp.pdf"):
        manejador._quizas(str(escritorio / nombre), False)
    assert nombres_en(cola) == ["INFORME.PDF", "contrato_temp.pdf"]


def test_el_manejador_ignora_los_ocultos(escritorio, cola):
    manejador = vigilante._Manejador(cola)
    for nombre in (".x.pdf", ".INFORME.123_temp.PDF"):
        manejador._quizas(str(escritorio / nombre), False)
    assert cola.empty()
