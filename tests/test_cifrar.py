"""Cifrado real de PDF: el corazón de la herramienta."""

import pikepdf
import pytest

from cifrarpdf import cifrar

CLAVE = "contraseña-larga-1"


def pdf_de_prueba(ruta, paginas=2):
    with pikepdf.new() as pdf:
        for _ in range(paginas):
            pdf.add_blank_page(page_size=(595, 842))
        pdf.save(ruta)
    return ruta


def test_cifra_y_queda_protegido(tmp_path):
    ruta = pdf_de_prueba(tmp_path / "informe.pdf")
    assert not cifrar.ya_cifrado(ruta)

    assert cifrar.cifrar_en_sitio(ruta, CLAVE) is True

    assert cifrar.ya_cifrado(ruta)
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(ruta)
    # Con la contraseña se abre y el contenido sigue ahí.
    with pikepdf.open(ruta, password=CLAVE) as pdf:
        assert len(pdf.pages) == 2
        assert pdf.is_encrypted
        assert pdf.encryption.R == 6  # AES-256


def test_no_recifra_lo_ya_cifrado(tmp_path):
    ruta = pdf_de_prueba(tmp_path / "informe.pdf")
    cifrar.cifrar_en_sitio(ruta, CLAVE)
    antes = ruta.read_bytes()
    assert cifrar.cifrar_en_sitio(ruta, "otra-contraseña") is False
    assert ruta.read_bytes() == antes, "un PDF ya cifrado no se toca"


def test_no_deja_temporales(tmp_path):
    carpeta = tmp_path / "vigilada"
    carpeta.mkdir()
    ruta = pdf_de_prueba(carpeta / "informe.pdf")
    cifrar.cifrar_en_sitio(ruta, CLAVE)
    assert [f.name for f in carpeta.iterdir()] == ["informe.pdf"]


def test_un_no_pdf_da_error_claro(tmp_path):
    ruta = tmp_path / "falso.pdf"
    ruta.write_text("esto no es un PDF", encoding="utf-8")
    with pytest.raises(cifrar.ErrorCifrado):
        cifrar.cifrar_en_sitio(ruta, CLAVE)


def test_limpiar_temporales(tmp_path):
    carpeta = tmp_path / "vigilada"
    carpeta.mkdir()
    (carpeta / ".informe.123_temp.pdf").write_bytes(b"basura")
    (carpeta / "informe.pdf").write_bytes(b"%PDF-")
    cifrar.limpiar_temporales(carpeta)
    assert [f.name for f in carpeta.iterdir()] == ["informe.pdf"]


@pytest.mark.parametrize(("nombre", "temporal"), [
    (".informe.99_temp.pdf", True),
    ("informe_temp.pdf", True),
    (".oculto.pdf", True),
    ("informe.pdf", False),
])
def test_deteccion_de_temporales(nombre, temporal):
    assert cifrar.es_temporal(nombre) is temporal
