"""El contrato «--gui-*»: es lo que consume la interfaz gráfica.

Si algo de aquí cambia, la GUI se rompe — y hay que cambiarlo también en el
backend bash de los puestos Debian.
"""

import io

import pytest

from cifrarpdf import cli, config, proceso, secreto


@pytest.fixture(autouse=True)
def sin_vigilante(monkeypatch):
    """El backend no debe lanzar procesos de verdad durante los tests."""
    monkeypatch.setattr(proceso, "refrescar", lambda: None)
    monkeypatch.setattr(proceso, "asegurar", lambda: True)
    monkeypatch.setattr(proceso, "parar", lambda espera=10.0: True)


def entrada(monkeypatch, texto):
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


def test_add_crea_carpeta_y_guarda_clave(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    assert cli.main(["--gui-add", "Informes"]) == 0
    assert capsys.readouterr().out.strip() == "OK informes"
    assert (escritorio / "Informes").is_dir()
    assert secreto.leer("informes") == "contraseña-larga"


def test_add_quita_el_salto_final_de_la_contrasena(monkeypatch, sin_keyring):
    entrada(monkeypatch, "contraseña-larga\n")
    assert cli.main(["--gui-add", "Informes"]) == 0
    assert secreto.leer("informes") == "contraseña-larga"


def test_add_rechaza_contrasena_corta(capsys, monkeypatch, escritorio):
    entrada(monkeypatch, "corta")
    assert cli.main(["--gui-add", "Informes"]) == 1
    salida = capsys.readouterr().out
    assert salida.startswith("ERR ")
    assert "Mínimo 8" in salida
    assert not (escritorio / "Informes").exists()
    assert not config.hay_carpetas()


@pytest.mark.parametrize("nombre", ["con/barra", "CON", "", "acaba."])
def test_add_rechaza_nombres_imposibles(capsys, monkeypatch, nombre):
    entrada(monkeypatch, "contraseña-larga")
    assert cli.main(["--gui-add", nombre]) == 1
    assert capsys.readouterr().out.startswith("ERR ")


def test_add_rechaza_carpeta_repetida(capsys, monkeypatch, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    capsys.readouterr()
    entrada(monkeypatch, "otra-contraseña")
    assert cli.main(["--gui-add", "Informes"]) == 1
    assert "Ya hay una carpeta de cifrado" in capsys.readouterr().out


def test_listar_da_cinco_campos(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    capsys.readouterr()

    assert cli.main(["--gui-listar"]) == 0
    linea = capsys.readouterr().out.strip()
    campos = linea.split("\t")
    assert len(campos) == 5
    assert campos[0] == "informes"
    assert campos[1] == "Informes"
    assert campos[2] == str(escritorio / "Informes")
    assert campos[3] == "1"  # la carpeta existe
    assert campos[4] == "1"  # tiene contraseña


def test_listar_marca_carpeta_desaparecida(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    capsys.readouterr()
    (escritorio / "Informes").rmdir()

    cli.main(["--gui-listar"])
    campos = capsys.readouterr().out.strip().split("\t")
    assert campos[3] == "0"
    assert campos[4] == "1"


def test_estado(capsys, monkeypatch):
    monkeypatch.setattr(proceso, "activo", lambda: False)
    cli.main(["--gui-estado"])
    assert capsys.readouterr().out.strip() == "0"
    monkeypatch.setattr(proceso, "activo", lambda: True)
    cli.main(["--gui-estado"])
    assert capsys.readouterr().out.strip() == "1"


def test_rename_mueve_la_carpeta_de_verdad(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    (escritorio / "Informes" / "algo.pdf").write_bytes(b"%PDF-")
    capsys.readouterr()

    assert cli.main(["--gui-rename", "informes", "Confidencial"]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert not (escritorio / "Informes").exists()
    assert (escritorio / "Confidencial" / "algo.pdf").exists()
    assert config.leer("informes").nombre == "Confidencial"
    # El id NO cambia: la contraseña sigue siendo la de esa carpeta.
    assert secreto.leer("informes") == "contraseña-larga"


def test_rename_a_nombre_ocupado(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    (escritorio / "Ocupada").mkdir()
    capsys.readouterr()
    assert cli.main(["--gui-rename", "informes", "Ocupada"]) == 1
    assert "Ya existe algo con ese nombre" in capsys.readouterr().out


def test_rename_de_carpeta_inexistente(capsys):
    assert cli.main(["--gui-rename", "fantasma", "Otro"]) == 1
    assert "no encontrada" in capsys.readouterr().out


def test_set_pass(capsys, monkeypatch, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    capsys.readouterr()

    entrada(monkeypatch, "otra-contraseña-larga")
    assert cli.main(["--gui-set-pass", "informes"]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert secreto.leer("informes") == "otra-contraseña-larga"

    entrada(monkeypatch, "corta")
    assert cli.main(["--gui-set-pass", "informes"]) == 1
    assert secreto.leer("informes") == "otra-contraseña-larga", "no se pisa con una inválida"


def test_remove_deja_la_carpeta_por_defecto(capsys, monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    capsys.readouterr()

    assert cli.main(["--gui-remove", "informes"]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert (escritorio / "Informes").is_dir(), "sin --borrar-carpeta no se borra nada"
    assert not config.hay_carpetas()
    assert secreto.leer("informes") is None


def test_remove_con_borrado(monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    assert cli.main(["--gui-remove", "informes", "--borrar-carpeta"]) == 0
    assert not (escritorio / "Informes").exists()


def test_remove_all(capsys, monkeypatch, escritorio, sin_keyring):
    for nombre in ("Informes", "Nóminas"):
        entrada(monkeypatch, "contraseña-larga")
        cli.main(["--gui-add", nombre])
    capsys.readouterr()

    assert cli.main(["--gui-remove-all"]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert not config.hay_carpetas()
    assert (escritorio / "Informes").is_dir()
    assert (escritorio / "Nóminas").is_dir()


def test_remove_all_con_borrado(monkeypatch, escritorio, sin_keyring):
    entrada(monkeypatch, "contraseña-larga")
    cli.main(["--gui-add", "Informes"])
    assert cli.main(["--gui-remove-all", "--borrar-carpetas"]) == 0
    assert not (escritorio / "Informes").exists()


def test_opcion_desconocida(capsys):
    assert cli.main(["--inventada"]) == 1
    assert "Opción desconocida" in capsys.readouterr().err


def test_ayuda(capsys):
    assert cli.main(["--ayuda"]) == 0
    salida = capsys.readouterr().out
    assert "--gui-listar" in salida
    assert "Administrador de credenciales" in salida


def test_parar(capsys, monkeypatch):
    llamado = []
    monkeypatch.setattr(proceso, "parar", lambda espera=10.0: llamado.append(True))
    assert cli.main(["--parar"]) == 0
    assert capsys.readouterr().out.strip() == "OK"
    assert llamado, "el desinstalador necesita que esto pare el vigilante de verdad"
