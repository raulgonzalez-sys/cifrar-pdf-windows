"""El vigilante: qué recoge, los avisos de barrido y el lote."""

import queue

import pytest

from cifrarpdf import cifrar, config, espera, preguntar, proceso, rutas, secreto, vigilante


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


# --- Avisos de barrido (pasar a contraseña fija sin reiniciar) ---------------

def pdf(carpeta, nombre):
    import pikepdf
    destino = carpeta / nombre
    with pikepdf.new() as documento:
        documento.add_blank_page()
        documento.save(destino)
    return destino


@pytest.fixture
def nominas(escritorio, sin_keyring):
    ruta = escritorio / "Nóminas"
    ruta.mkdir()
    config.escribir("nominas", "Nóminas", ruta, "fija")
    secreto.guardar("nominas", "contraseña-larga")
    carpeta = config.leer("nominas")
    return carpeta, {vigilante._clave(ruta): carpeta}


def test_el_manejador_de_barrido_encola_el_marcador(cola):
    proceso.pedir_barrido("nominas")
    marcador = rutas.barrer_dir() / "nominas"

    class Evento:
        src_path = str(marcador)
        is_directory = False

    vigilante._ManejadorBarrido(cola).on_created(Evento())
    assert cola.get_nowait() == marcador


def test_un_marcador_barre_la_carpeta_fija_y_se_borra(nominas, cola, log):
    carpeta, mapa = nominas
    pdf(carpeta.ruta, "uno.pdf")
    pdf(carpeta.ruta, "DOS.PDF")
    pdf(carpeta.ruta, ".oculto.pdf")
    proceso.pedir_barrido("nominas")
    marcador = rutas.barrer_dir() / "nominas"

    vigilante._atender(marcador, cola, mapa)

    assert sorted(nombres_en(cola)) == ["DOS.PDF", "uno.pdf"]
    assert not marcador.exists()
    assert "Barrido a petición en «Nóminas»." in log.read_text(encoding="utf-8")


def test_un_marcador_de_una_carpeta_en_preguntar_se_ignora(nominas, cola):
    carpeta, mapa = nominas
    pdf(carpeta.ruta, "uno.pdf")
    # El modo se lee del disco: el mapa aún dice «fija».
    config.escribir("nominas", "Nóminas", carpeta.ruta, "preguntar")
    proceso.pedir_barrido("nominas")
    marcador = rutas.barrer_dir() / "nominas"

    vigilante._atender(marcador, cola, mapa)

    assert cola.empty()
    assert not marcador.exists()


def test_un_marcador_de_una_carpeta_desconocida_se_ignora(nominas, cola):
    _carpeta, mapa = nominas
    proceso.pedir_barrido("fantasma")
    marcador = rutas.barrer_dir() / "fantasma"
    vigilante._atender(marcador, cola, mapa)
    assert cola.empty()
    assert not marcador.exists()


def test_el_arranque_borra_los_marcadores(nominas, monkeypatch, log):
    """El barrido inicial ya cubre lo que pedían: no se barre dos veces."""
    carpeta, _mapa = nominas
    pdf(carpeta.ruta, "uno.pdf")
    proceso.pedir_barrido("nominas")
    monkeypatch.setattr(vigilante, "_procesar", lambda ruta, mapa: None)
    monkeypatch.setattr(vigilante, "_esperar_parada", lambda: 0)

    assert vigilante._ejecutar() == 0

    assert list(rutas.barrer_dir().iterdir()) == []
    assert "Barrido a petición" not in log.read_text(encoding="utf-8")


def test_el_arranque_atiende_los_marcadores_que_llegan_mientras_arranca(
        nominas, monkeypatch, log):
    """Igual que el bucle «Avisos que llegaron mientras arrancaba» del bash."""
    original = vigilante._encolar_existentes

    def barrido_y_aviso(cola, mapa):
        original(cola, mapa)
        proceso.pedir_barrido("nominas")

    monkeypatch.setattr(vigilante, "_encolar_existentes", barrido_y_aviso)
    monkeypatch.setattr(vigilante, "_procesar", lambda ruta, mapa: None)
    monkeypatch.setattr(vigilante, "_esperar_parada", lambda: 0)

    assert vigilante._ejecutar() == 0

    assert list(rutas.barrer_dir().iterdir()) == []
    assert "Barrido a petición en «Nóminas»." in log.read_text(encoding="utf-8")


# --- Lote del modo «preguntar» -----------------------------------------------

@pytest.fixture
def atendedor():
    respuestas = ["contraseña-larga", "contraseña-larga", True]

    def contestar(peticion):
        peticion.resultado = True if peticion.tipo == "avisar" else respuestas.pop(0)
        peticion.atendida.set()

    preguntar.registrar_atendedor(contestar)
    vigilante._lote = preguntar.Lote()
    yield
    preguntar.registrar_atendedor(None)
    vigilante._lote = preguntar.Lote()


def test_el_lote_salta_el_pendiente_que_aun_se_escribe(
        escritorio, sin_keyring, atendedor, monkeypatch, log):
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    soltado = pdf(ruta, "uno.pdf")
    copiando = pdf(ruta, "dos.pdf")
    listo = pdf(ruta, "tres.pdf")
    monkeypatch.setattr(espera, "bloqueado",
                        lambda r: r.name in ("uno.pdf", "dos.pdf"))

    vigilante._procesar_preguntando(soltado, carpeta)

    assert cifrar.ya_cifrado(soltado), "el que disparó el diálogo se cifra"
    assert cifrar.ya_cifrado(listo)
    assert not cifrar.ya_cifrado(copiando), "lo cifrará su propio evento"
    assert f"Lote: se omite, aún se escribe: {copiando}" in log.read_text(encoding="utf-8")


def test_el_pendiente_omitido_del_lote_se_avisa(
        escritorio, sin_keyring, atendedor, monkeypatch, log):
    """Un PDF abierto en un visor no genera evento: si no se avisa, queda en claro."""
    from cifrarpdf import notificar
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    soltado = pdf(ruta, "uno.pdf")
    abierto = pdf(ruta, "dos.pdf")
    pdf(ruta, "tres.pdf")
    monkeypatch.setattr(espera, "bloqueado", lambda r: r.name == "dos.pdf")
    errores = []
    monkeypatch.setattr(notificar, "error", lambda t, x: errores.append((t, x)))

    vigilante._procesar_preguntando(soltado, carpeta)

    assert not cifrar.ya_cifrado(abierto)
    avisos = [x for _t, x in errores if "«dos.pdf»" in x]
    assert len(avisos) == 1, errores
    assert "no se ha cifrado" in avisos[0]
    assert "Ciérralo y vuelve a soltarlo" in avisos[0]
