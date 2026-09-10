"""Aislamiento de los tests: nada toca la configuración real del usuario."""

import pytest

from cifrarpdf import rutas


@pytest.fixture(autouse=True)
def entorno_aislado(tmp_path, monkeypatch):
    """Redirige configuración, datos y Escritorio a un directorio temporal."""
    config = tmp_path / "config"
    datos = tmp_path / "datos"
    escritorio = tmp_path / "Escritorio"
    for carpeta in (config, datos, escritorio):
        carpeta.mkdir()
    monkeypatch.setenv("CIFRARPDF_CONFIG_DIR", str(config))
    monkeypatch.setenv("CIFRARPDF_DATOS_DIR", str(datos))
    monkeypatch.setenv("CIFRARPDF_ESCRITORIO", str(escritorio))
    return {"config": config, "datos": datos, "escritorio": escritorio}


@pytest.fixture
def sin_keyring(monkeypatch):
    """Fuerza el camino del fichero protegido (el fallback sin credenciales)."""
    from cifrarpdf import secreto
    monkeypatch.setattr(secreto, "_keyring", lambda: None)


@pytest.fixture
def escritorio(entorno_aislado):
    return entorno_aislado["escritorio"]


@pytest.fixture
def log(entorno_aislado):
    return rutas.log_file()
