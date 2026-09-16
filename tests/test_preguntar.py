"""Modo «preguntar la contraseña cada vez».

Todo lo de aquí corre sin pantalla: el diálogo se sustituye por un atendedor de
mentira que contesta lo que diga cada test, igual que haría la persona.
"""

import time

import pytest

from cifrarpdf import cifrar, config, preguntar, secreto, vigilante

# Marca para el atendedor de mentira: «el diálogo se cerró solo».
CADUCA = object()


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
                respuesta = self.respuestas.pop(0)
                # CADUCA imita el diálogo que se cierra solo al agotarse su
                # plazo, que no es lo mismo que pulsar Cancelar.
                if respuesta is CADUCA:
                    peticion.caducada = True
                    peticion.resultado = None
                else:
                    peticion.resultado = respuesta
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
    assert preguntar.pedir_clave_confirmada("t", "x") == ("contraseña-larga", None)
    assert len(atendedor.vistas) == 2


def test_la_confirmacion_dice_que_es_una_confirmacion(atendedor):
    """El segundo cuadro tiene que explicar que es la repetición.

    Con el mismo texto las dos veces, parece que la primera no se ha
    registrado y se vuelve a escribir otra cosa.
    """
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga"]
    preguntar.pedir_clave_confirmada("t", "Contraseña para «x»:")
    assert atendedor.vistas[1] == ("pedir",
                                   "Escríbela otra vez para confirmarla.")


def test_si_no_coinciden_se_vuelve_a_preguntar(atendedor):
    atendedor.respuestas = ["contraseña-larga", "otra-distinta",
                            "contraseña-larga", "contraseña-larga"]
    assert preguntar.pedir_clave_confirmada("t", "x") == ("contraseña-larga", None)
    assert any(tipo == "avisar" and "no coincidían" in texto
               for tipo, texto in atendedor.vistas)


def test_contrasena_corta_no_se_acepta(atendedor):
    atendedor.respuestas = ["corta", "contraseña-larga", "contraseña-larga"]
    assert preguntar.pedir_clave_confirmada("t", "x") == ("contraseña-larga", None)
    assert any(tipo == "avisar" and "no válida" in texto
               for tipo, texto in atendedor.vistas)


def test_cancelar_devuelve_nada(atendedor):
    atendedor.respuestas = [None]
    assert preguntar.pedir_clave_confirmada("t", "x") == (None, preguntar.CANCELADO)


def test_caducar_no_es_lo_mismo_que_cancelar(atendedor):
    """Nadie delante ≠ alguien que dice que no: el aviso siguiente cambia."""
    atendedor.respuestas = [CADUCA]
    assert preguntar.pedir_clave_confirmada("t", "x") == (None, preguntar.CADUCADO)


def test_tres_veces_sin_coincidir_lo_dice_asi(atendedor):
    """Y NO «no has introducido ninguna contraseña», que era la mentira."""
    atendedor.respuestas = ["contraseña-larga", "otra-distinta"] * 3
    clave, motivo = preguntar.pedir_clave_confirmada("t", "x")
    assert clave is None
    assert motivo == preguntar.NO_COINCIDEN
    assert "no coincidían" in preguntar.texto_motivo(motivo)


def test_sin_atendedor_no_se_pregunta():
    preguntar.registrar_atendedor(None)
    assert not preguntar.hay_atendedor()
    assert preguntar.pedir_clave_confirmada("t", "x") == (None, preguntar.CANCELADO)


# --- Textos ------------------------------------------------------------------

def test_recortar_nombre_recorta_por_el_centro():
    largo = "informe-confidencial-de-seguimiento-del-itinerario-2026.pdf"
    corto = preguntar.recortar_nombre(largo, 24)
    assert len(corto) <= 24
    assert corto.startswith("informe-con")
    assert corto.endswith("2026.pdf"), "el final es lo que distingue el fichero"
    assert "…" in corto


def test_recortar_nombre_deja_en_paz_los_cortos():
    assert preguntar.recortar_nombre("informe.pdf") == "informe.pdf"


def test_lista_pendientes_nombra_tres_y_cuenta_el_resto(escritorio):
    rutas = [escritorio / f"{i}.pdf" for i in range(6)]
    texto = preguntar.lista_pendientes(rutas)
    assert texto.count("•") == 3
    assert "… y 3 más" in texto


def test_lista_pendientes_sin_resto(escritorio):
    texto = preguntar.lista_pendientes([escritorio / "uno.pdf"])
    assert texto == "  • uno.pdf"


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


def test_el_aviso_del_ultimo_intento_dice_la_verdad(atendedor, carpeta_preguntar):
    """Tres parejas que no coinciden no son «no has escrito ninguna».

    Era el mensaje que salía antes en los tres casos, y acusaba de no haber
    escrito nada a quien acababa de teclear seis veces.
    """
    fichero = pdf(carpeta_preguntar.ruta)
    atendedor.respuestas = ["contraseña-larga", "otra-distinta"] * 3 + [None]
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    avisos = [t for tipo, t in atendedor.vistas if tipo == "avisar"]
    assert any("no coincidían" in t and "última vez" in t for t in avisos)


def test_el_aviso_distingue_el_tiempo_agotado(atendedor, carpeta_preguntar):
    fichero = pdf(carpeta_preguntar.ruta)
    atendedor.respuestas = [CADUCA, None]
    vigilante._procesar_preguntando(fichero, carpeta_preguntar)
    avisos = [t for tipo, t in atendedor.vistas if tipo == "avisar"]
    assert any("sin respuesta" in t for t in avisos)


def test_el_dialogo_dice_la_carpeta_y_cuantos_hay(atendedor, carpeta_preguntar):
    pdf(carpeta_preguntar.ruta, "uno.pdf")
    pdf(carpeta_preguntar.ruta, "dos.pdf")
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga", False]
    vigilante._procesar_preguntando(
        carpeta_preguntar.ruta / "uno.pdf", carpeta_preguntar)
    primero = atendedor.vistas[0][1]
    assert "Informes" in primero, "la carpeta, no solo en el título de ventana"
    assert "uno.pdf" in primero
    assert "2 PDF sin proteger" in primero, "el recuento, ANTES de teclear"


def test_la_oferta_de_lote_nombra_los_pdf(atendedor, carpeta_preguntar):
    """«Hay 7 PDF sin cifrar» cuando solo has soltado uno desconcierta."""
    for nombre in ("uno.pdf", "dos.pdf", "tres.pdf"):
        pdf(carpeta_preguntar.ruta, nombre)
    atendedor.respuestas = ["contraseña-larga", "contraseña-larga", True]
    vigilante._procesar_preguntando(
        carpeta_preguntar.ruta / "uno.pdf", carpeta_preguntar)
    oferta = next(t for tipo, t in atendedor.vistas if tipo == "confirmar")
    for nombre in ("uno.pdf", "dos.pdf", "tres.pdf"):
        assert nombre in oferta
