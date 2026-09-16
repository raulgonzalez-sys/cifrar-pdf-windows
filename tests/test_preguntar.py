"""Modo «preguntar la contraseña cada vez».

Todo lo de aquí corre sin pantalla: el diálogo se sustituye por un atendedor de
mentira que contesta lo que diga cada test, igual que haría la persona.
"""

import time

import pytest

from cifrarpdf import cifrar, config, preguntar, secreto, vigilante


@pytest.fixture(autouse=True)
def lote_limpio():
    """El lote es un global del vigilante y sobrevive entre tests.

    En producción es justo lo que se quiere (la contraseña vale para toda la
    tanda), pero aquí una carpeta con el mismo id heredaría la contraseña de
    otro test y no se preguntaría nada.
    """
    vigilante._lote = preguntar.Lote()


@pytest.fixture
def atendedor(monkeypatch):
    """Sustituye los diálogos por respuestas programadas.

    `respuestas` es la lista de lo que se va contestando, en orden: un texto
    para una contraseña, None para cancelar, True/False para las preguntas de
    sí o no. Deja constancia de cada petición en `vistas`.
    """
    class Falso:
        def __init__(self):
            self.respuestas = []
            self.vistas = []

        def __call__(self, peticion):
            self.vistas.append((peticion.tipo, peticion.texto))
            if peticion.tipo == "avisar":
                peticion.resultado = True
            elif self.respuestas:
                peticion.resultado = self.respuestas.pop(0)
            else:
                peticion.resultado = None
            peticion.atendida.set()

    falso = Falso()
    preguntar.registrar_atendedor(falso)
    yield falso
    preguntar.registrar_atendedor(None)


@pytest.fixture
def carpeta_preguntar(escritorio, sin_keyring):
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    return config.leer("informes")


def pdf(carpeta, nombre="informe.pdf"):
    """Un PDF de una página, sin cifrar."""
    import pikepdf
    destino = carpeta / nombre
    with pikepdf.new() as documento:
        documento.add_blank_page()
        documento.save(destino)
    return destino


def cifrado(ruta):
    return cifrar.ya_cifrado(ruta)


# --- Marcado de lo que se quedó sin cifrar -----------------------------------

def test_marcar_sin_cifrar(escritorio):
    fichero = escritorio / "informe.pdf"
    fichero.write_bytes(b"%PDF-")
    destino = preguntar.marcar_sin_cifrar(fichero)
    assert destino.name == "SIN-CIFRAR_informe.pdf"
    assert destino.exists() and not fichero.exists()


def test_no_se_marca_dos_veces(escritorio):
    fichero = escritorio / "SIN-CIFRAR_informe.pdf"
    fichero.write_bytes(b"%PDF-")
    assert preguntar.marcar_sin_cifrar(fichero) == fichero


def test_marcar_numera_si_el_nombre_esta_ocupado(escritorio):
    (escritorio / "SIN-CIFRAR_informe.pdf").write_bytes(b"%PDF-")
    fichero = escritorio / "informe.pdf"
    fichero.write_bytes(b"%PDF-")
    assert preguntar.marcar_sin_cifrar(fichero).name == "SIN-CIFRAR_2_informe.pdf"


@pytest.mark.parametrize(("marcado", "limpio"), [
    ("SIN-CIFRAR_informe.pdf", "informe.pdf"),
    ("SIN-CIFRAR_2_informe.pdf", "informe.pdf"),
    ("informe.pdf", "informe.pdf"),
])
def test_limpiar_prefijo(escritorio, marcado, limpio):
    fichero = escritorio / marcado
    fichero.write_bytes(b"%PDF-")
    assert preguntar.limpiar_prefijo(fichero).name == limpio


def test_limpiar_prefijo_no_pisa_un_fichero_existente(escritorio):
    (escritorio / "informe.pdf").write_bytes(b"otro")
    fichero = escritorio / "SIN-CIFRAR_informe.pdf"
    fichero.write_bytes(b"%PDF-")
    assert preguntar.limpiar_prefijo(fichero) == fichero


# --- Lote --------------------------------------------------------------------

def test_lote_caduca():
    lote = preguntar.Lote(ttl=0.05)
    lote.guardar("informes", "contraseña-larga")
    assert lote.vigente("informes") == "contraseña-larga"
    time.sleep(0.06)
    assert lote.vigente("informes") is None


def test_lote_es_por_carpeta():
    lote = preguntar.Lote()
    lote.guardar("informes", "contraseña-larga")
    assert lote.vigente("nominas") is None


# --- Pedir la contraseña -----------------------------------------------------

def test_pide_dos_veces_y_devuelve_la_contrasena(atendedor):
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga"]
    assert preguntar.pedir_clave_confirmada("t", "x") == "contraseña-larga"
    assert len(atendedor.vistas) == 2


def test_si_no_coinciden_se_vuelve_a_preguntar(atendedor):
    atendedor.respuestas = ["contraseña-larga", "otra-distinta",
                            "contraseña-larga", "contraseña-larga"]
    assert preguntar.pedir_clave_confirmada("t", "x") == "contraseña-larga"
    assert ("avisar", "Las contraseñas no coinciden. Inténtalo de nuevo.") \
        in atendedor.vistas


def test_contrasena_corta_no_se_acepta(atendedor):
    atendedor.respuestas = ["corta", "contraseña-larga", "contraseña-larga"]
    assert preguntar.pedir_clave_confirmada("t", "x") == "contraseña-larga"
    assert any(tipo == "avisar" and "no válida" in texto
               for tipo, texto in atendedor.vistas)


def test_cancelar_devuelve_nada(atendedor):
    atendedor.respuestas = [None]
    assert preguntar.pedir_clave_confirmada("t", "x") is None


def test_sin_atendedor_no_se_pregunta():
    preguntar.registrar_atendedor(None)
    assert not preguntar.hay_atendedor()
    assert preguntar.pedir_clave_confirmada("t", "x") is None


# --- El vigilante de punta a punta ------------------------------------------

def test_cifra_con_la_contrasena_que_se_escribe(atendedor, carpeta_preguntar):
    fichero = pdf(carpeta_preguntar.ruta)
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga"]
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    assert cifrado(fichero)
    assert secreto.leer("informes") is None, "no se guarda nada en modo preguntar"


def test_cancelar_deja_el_pdf_marcado(atendedor, carpeta_preguntar):
    fichero = pdf(carpeta_preguntar.ruta)
    atendedor.respuestas = [None, None]  # el primer intento y el último
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    marcado = carpeta_preguntar.ruta / "SIN-CIFRAR_informe.pdf"
    assert marcado.exists() and not fichero.exists()
    assert not cifrado(marcado), "sigue sin proteger, que es de lo que se avisa"


def test_un_pdf_ya_cifrado_no_pregunta_nada(atendedor, carpeta_preguntar):
    fichero = pdf(carpeta_preguntar.ruta)
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga"]
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    atendedor.vistas.clear()

    # Nuestro propio renombrado vuelve a traer el fichero por aquí: si esto
    # preguntase, se entraría en bucle.
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    assert atendedor.vistas == []


def test_lote_cifra_todos_con_una_sola_pregunta(atendedor, carpeta_preguntar):
    primero = pdf(carpeta_preguntar.ruta, "uno.pdf")
    segundo = pdf(carpeta_preguntar.ruta, "dos.pdf")
    tercero = pdf(carpeta_preguntar.ruta, "tres.pdf")
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga", True]

    vigilante._procesar_preguntando(primero, carpeta_preguntar)
    assert cifrado(primero) and cifrado(segundo) and cifrado(tercero)
    assert sum(1 for tipo, _ in atendedor.vistas if tipo == "pedir") == 2


def test_rechazar_el_lote_cifra_solo_el_suelto(atendedor, carpeta_preguntar):
    primero = pdf(carpeta_preguntar.ruta, "uno.pdf")
    segundo = pdf(carpeta_preguntar.ruta, "dos.pdf")
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga", False]

    vigilante._procesar_preguntando(primero, carpeta_preguntar)
    assert cifrado(primero)
    assert not cifrado(segundo)


def test_el_lote_recupera_un_pdf_marcado_y_su_nombre(atendedor, carpeta_preguntar):
    olvidado = pdf(carpeta_preguntar.ruta, "olvidado.pdf")
    atendedor.respuestas = [None, None]
    vigilante._procesar_preguntando(olvidado, carpeta_preguntar)
    marcado = carpeta_preguntar.ruta / "SIN-CIFRAR_olvidado.pdf"
    assert marcado.exists()

    # Al soltar otro PDF, el lote se lleva por delante también el marcado.
    nuevo = pdf(carpeta_preguntar.ruta, "nuevo.pdf")
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga", True]
    vigilante._procesar_preguntando(nuevo, carpeta_preguntar)

    recuperado = carpeta_preguntar.ruta / "olvidado.pdf"
    assert recuperado.exists() and cifrado(recuperado)
    assert not marcado.exists(), "al cifrarse bien recupera su nombre limpio"


def test_sin_barrido_inicial_en_modo_preguntar(carpeta_preguntar):
    """Al iniciar sesión no se le sueltan diálogos a nadie."""
    import queue
    pdf(carpeta_preguntar.ruta)
    cola = queue.Queue()
    vigilante._encolar_existentes(
        cola, {vigilante._clave(carpeta_preguntar.ruta): carpeta_preguntar})
    assert cola.empty()


def test_el_barrido_inicial_sigue_activo_en_modo_fija(escritorio):
    import queue
    ruta = escritorio / "Nóminas"
    ruta.mkdir()
    config.escribir("nominas", "Nóminas", ruta, "fija")
    carpeta = config.leer("nominas")
    pdf(ruta)
    cola = queue.Queue()
    vigilante._encolar_existentes(cola, {vigilante._clave(ruta): carpeta})
    assert cola.qsize() == 1


def test_el_vigilante_ignora_los_marcados(escritorio):
    """El renombrado a SIN-CIFRAR_ es un fichero movido a la carpeta: si el
    vigilante lo recogiera, volvería a preguntar en bucle."""
    import queue
    cola = queue.Queue()
    manejador = vigilante._Manejador(cola)
    manejador._quizas(str(escritorio / "SIN-CIFRAR_informe.pdf"), False)
    assert cola.empty()
    manejador._quizas(str(escritorio / "informe.pdf"), False)
    assert cola.qsize() == 1
