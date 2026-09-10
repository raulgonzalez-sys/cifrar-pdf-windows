"""Espera a que el PDF esté completo antes de tocarlo."""

import threading
import time

from cifrarpdf import espera


def test_espera_a_que_deje_de_crecer(tmp_path, monkeypatch):
    monkeypatch.setattr(espera, "INTERVALO", 0.05)
    ruta = tmp_path / "grande.pdf"
    ruta.write_bytes(b"%PDF-")

    escribiendo = threading.Event()

    def escribir():
        # Escritura continua (pausas más cortas que el intervalo de muestreo):
        # mientras dure, esperar_archivo no puede dar el fichero por terminado.
        for _ in range(15):
            with open(ruta, "ab") as fh:
                fh.write(b"x" * 1024)
            time.sleep(0.02)
        escribiendo.set()

    hilo = threading.Thread(target=escribir)
    hilo.start()
    assert espera.esperar_archivo(ruta, espera_max=5.0) is True
    assert escribiendo.is_set(), "no debe darlo por listo mientras crecía"
    hilo.join()


def test_no_se_cuela_en_una_pausa_de_escritura(tmp_path, monkeypatch):
    """Una sola lectura estable no basta: hacen falten varias seguidas."""
    monkeypatch.setattr(espera, "INTERVALO", 0.05)
    assert espera.LECTURAS_ESTABLES >= 2
    ruta = tmp_path / "a-rafagas.pdf"
    ruta.write_bytes(b"%PDF-")

    listo = threading.Event()

    def escribir():
        # Pausa MAYOR que el intervalo: entre trozo y trozo el tamaño no cambia.
        for _ in range(3):
            time.sleep(0.08)
            with open(ruta, "ab") as fh:
                fh.write(b"x" * 512)
        listo.set()

    hilo = threading.Thread(target=escribir)
    hilo.start()
    assert espera.esperar_archivo(ruta, espera_max=5.0) is True
    assert listo.is_set(), "no debe darlo por listo en una pausa entre trozos"
    hilo.join()


def test_fichero_que_no_aparece(tmp_path, monkeypatch):
    monkeypatch.setattr(espera, "INTERVALO", 0.05)
    assert espera.esperar_archivo(tmp_path / "fantasma.pdf", espera_max=0.3) is False


def test_fichero_vacio_no_esta_listo(tmp_path, monkeypatch):
    monkeypatch.setattr(espera, "INTERVALO", 0.05)
    ruta = tmp_path / "vacio.pdf"
    ruta.touch()
    assert espera.esperar_archivo(ruta, espera_max=0.3) is False


def test_bloqueado_con_fichero_inexistente(tmp_path):
    assert espera.bloqueado(tmp_path / "no-existe.pdf") is True
