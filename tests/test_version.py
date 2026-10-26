"""La versión va en cuatro sitios y tienen que decir lo mismo."""

import re
from pathlib import Path

import cifrarpdf

RAIZ = Path(__file__).resolve().parent.parent


def _leer(relativa):
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_la_version_coincide_en_todos_los_sitios():
    version = cifrarpdf.__version__
    cuatro = f"{version}.0"
    tupla = "(" + ", ".join(cuatro.split(".")) + ")"

    assert re.search(rf'^version = "{re.escape(version)}"$',
                     _leer("pyproject.toml"), re.M)
    assert f'#define MiVersion "{version}"' in _leer("empaquetar/CifrarPDF.iss")
    recurso = _leer("empaquetar/version.txt")
    assert f"filevers={tupla}" in recurso
    assert f"prodvers={tupla}" in recurso
    assert f'StringStruct("FileVersion", "{cuatro}")' in recurso
    assert f'StringStruct("ProductVersion", "{cuatro}")' in recurso
