"""El vigilante: qué recoge, los avisos de barrido y el lote."""

import queue

import pytest

from cifrarpdf import cifrar, config, espera, preguntar, proceso, rutas, secreto, vigilante


@pytest.fixture
def cola():
    return queue.Queue()


def nombres_en(cola):
    """Nombres de lo encolado, sea un PDF suelto o uno de un barrido."""
    vistos = []
    while not cola.empty():
        elemento = cola.get_nowait()
        vistos.append(getattr(elemento, "ruta", elemento).name)
    return vistos


def atender_todo(cola, mapa):
    while not cola.empty():
        vigilante._atender(cola.get_nowait(), cola, mapa)


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
    vigilante._avisados_lote.clear()
    yield
    preguntar.registrar_atendedor(None)
    vigilante._lote = preguntar.Lote()
    vigilante._avisados_lote.clear()


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
    assert f"Lote: se omite, en uso por otro programa: {copiando}" in log.read_text(encoding="utf-8")


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
    assert "de momento no se ha cifrado" in avisos[0]
    assert "si en un minuto no ves «PDF protegido»" in avisos[0]


def test_el_omitido_del_lote_no_se_avisa_otra_vez_por_su_evento(
        escritorio, sin_keyring, atendedor, monkeypatch, log):
    """Su propio evento seguía en la cola: a los 60 s no puede llegar un segundo
    aviso, «no terminó de copiarse», del mismo PDF."""
    from cifrarpdf import notificar
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    mapa = {vigilante._clave(ruta): carpeta}
    soltado = pdf(ruta, "uno.pdf")
    abierto = pdf(ruta, "dos.pdf")
    monkeypatch.setattr(espera, "bloqueado", lambda r: r.name == "dos.pdf")
    monkeypatch.setattr(espera, "esperar_archivo", lambda r, *a, **k: False)
    errores = []
    monkeypatch.setattr(notificar, "error", lambda t, x: errores.append((t, x)))

    vigilante._procesar_preguntando(soltado, carpeta)
    vigilante._procesar(abierto, mapa)

    avisos = [x for _t, x in errores if "«dos.pdf»" in x]
    assert len(avisos) == 1, errores
    assert f"ya avisado en el lote: {abierto}" in log.read_text(encoding="utf-8")

    # Avisado una vez, no para siempre: la próxima vez que falle se avisa.
    vigilante._procesar(abierto, mapa)
    assert len([x for _t, x in errores if "«dos.pdf»" in x]) == 2


def test_la_marca_de_ya_avisado_en_el_lote_caduca(
        escritorio, sin_keyring, atendedor, monkeypatch, log):
    """La marca cubre el evento de la misma tanda, que espera como mucho
    ESPERA_MAX. Si nadie la consume, un fallo de horas después no puede
    quedarse sin aviso."""
    import time

    from cifrarpdf import notificar
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    mapa = {vigilante._clave(ruta): carpeta}
    soltado = pdf(ruta, "uno.pdf")
    abierto = pdf(ruta, "dos.pdf")
    monkeypatch.setattr(espera, "bloqueado", lambda r: r.name == "dos.pdf")
    monkeypatch.setattr(espera, "esperar_archivo", lambda r, *a, **k: False)
    errores = []
    monkeypatch.setattr(notificar, "error", lambda t, x: errores.append((t, x)))

    vigilante._procesar_preguntando(soltado, carpeta)
    real = time.monotonic
    with monkeypatch.context() as m:
        m.setattr(time, "monotonic", lambda: real() + preguntar.REUSO_TTL + 1)
        vigilante._procesar(abierto, mapa)

    assert len([x for _t, x in errores if "«dos.pdf»" in x]) == 2, errores
    assert "ya avisado en el lote" not in log.read_text(encoding="utf-8")


def test_un_aviso_que_llega_mientras_lee_las_carpetas_no_se_pierde(
        escritorio, sin_keyring, monkeypatch, log):
    """El paso a fija llega justo cuando el vigilante ya leyó la carpeta en
    «preguntar»: su aviso tiene que sobrevivir al arranque."""
    ruta = escritorio / "P"
    ruta.mkdir()
    config.escribir("p", "P", ruta, "preguntar")
    pdf(ruta, "SIN-CIFRAR_a.pdf")
    original = vigilante._preparar_carpetas

    def leer_y_pasar_a_fija():
        mapa = original()
        secreto.guardar("p", "contraseña-larga")
        config.escribir("p", "P", ruta, "fija")
        proceso.pedir_barrido("p")
        return mapa

    monkeypatch.setattr(vigilante, "_preparar_carpetas", leer_y_pasar_a_fija)
    monkeypatch.setattr(vigilante, "_procesar", lambda ruta, mapa: None)
    monkeypatch.setattr(vigilante, "_esperar_parada", lambda: 0)

    assert vigilante._ejecutar() == 0
    assert "Barrido a petición en «P»." in log.read_text(encoding="utf-8")


def test_lo_ya_cifrado_no_espera_a_estar_completo(nominas, monkeypatch):
    """Un barrido recorre carpetas llenas de PDF ya protegidos: esperar ~2 s
    por cada uno retendría la cola minutos."""
    carpeta, mapa = nominas
    protegido = pdf(carpeta.ruta, "uno.pdf")
    assert cifrar.cifrar_en_sitio(protegido, "contraseña-larga")
    esperas = []
    monkeypatch.setattr(espera, "esperar_archivo",
                        lambda ruta, *a, **k: esperas.append(ruta) or True)

    vigilante._procesar(protegido, mapa)

    assert esperas == []


def test_el_evento_de_un_pdf_ya_cifrado_queda_en_el_registro(nominas, log):
    """Como «procesar_pdf» del bash; el barrido, como «barrer_carpeta», calla."""
    carpeta, mapa = nominas
    protegido = pdf(carpeta.ruta, "uno.pdf")
    assert cifrar.cifrar_en_sitio(protegido, "contraseña-larga")

    vigilante._procesar_de_barrido(vigilante._DeBarrido(protegido, avisar=True), mapa)
    assert "Ya cifrado" not in log.read_text(encoding="utf-8")

    vigilante._procesar(protegido, mapa)
    assert f"Ya cifrado, se omite: {protegido}" in log.read_text(encoding="utf-8")


# --- Barrido con PDF en uso: no se espera, como el bash ----------------------

@pytest.fixture
def en_uso(monkeypatch):
    """Todo PDF está abierto en otro programa; anota esperas y avisos."""
    from cifrarpdf import notificar
    registro = {"esperas": [], "errores": []}
    monkeypatch.setattr(espera, "bloqueado", lambda ruta: True)
    monkeypatch.setattr(espera, "esperar_archivo",
                        lambda ruta, *a, **k: registro["esperas"].append(ruta) or False)
    monkeypatch.setattr(notificar, "error",
                        lambda t, x: registro["errores"].append((t, x)))
    return registro


def test_el_barrido_inicial_no_espera_al_pdf_en_uso_y_avisa(nominas, cola, en_uso, log):
    carpeta, mapa = nominas
    abierto = pdf(carpeta.ruta, "uno.pdf")

    vigilante._encolar_existentes(cola, mapa)
    atender_todo(cola, mapa)

    assert en_uso["esperas"] == [], "un PDF en uso no puede retener la cola 60 s"
    assert not cifrar.ya_cifrado(abierto)
    assert (f"Barrido: se omite, en uso por otro programa: {abierto}"
            in log.read_text(encoding="utf-8"))
    avisos = [x for _t, x in en_uso["errores"] if "«uno.pdf»" in x]
    assert len(avisos) == 1, en_uso["errores"]
    assert "próximo inicio de sesión" in avisos[0]


def test_el_barrido_a_peticion_no_espera_y_avisa_del_pdf_en_uso(
        nominas, cola, en_uso, log):
    """Al poner contraseña fija, el PDF abierto en un visor no puede quedarse
    en claro sin decirlo: después no llega ningún evento que lo recoja."""
    carpeta, mapa = nominas
    abierto = pdf(carpeta.ruta, "uno.pdf")
    proceso.pedir_barrido("nominas")

    vigilante._atender(rutas.barrer_dir() / "nominas", cola, mapa)
    atender_todo(cola, mapa)

    assert en_uso["esperas"] == []
    assert not cifrar.ya_cifrado(abierto)
    assert (f"Barrido: se omite, en uso por otro programa: {abierto}"
            in log.read_text(encoding="utf-8"))
    avisos = [x for _t, x in en_uso["errores"] if "«uno.pdf»" in x]
    assert len(avisos) == 1, en_uso["errores"]
    assert "próximo inicio de sesión" in avisos[0]


def test_lo_ya_cifrado_y_abierto_en_un_visor_no_espera(nominas, en_uso):
    """Leer está permitido aunque otro lo tenga abierto: no hace falta esperar
    para saber que ya está protegido."""
    carpeta, mapa = nominas
    protegido = pdf(carpeta.ruta, "uno.pdf")
    assert cifrar.cifrar_en_sitio(protegido, "contraseña-larga")

    vigilante._procesar(protegido, mapa)

    assert en_uso["esperas"] == []
    assert en_uso["errores"] == []


# --- Interfaz del vigilante ---------------------------------------------------

def test_los_botones_estandar_salen_en_castellano():
    """En KDE los traduce plasma-integration; en Windows nadie, aunque el
    sistema esté en español."""
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtCore import QCoreApplication
    app = widgets.QApplication.instance() or widgets.QApplication([])
    traductor = vigilante._instalar_traductor(app)
    try:
        assert traductor is not None
        assert QCoreApplication.translate("QPlatformTheme", "&Yes") == "&Sí"
        assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancelar"
    finally:
        if traductor is not None:
            QCoreApplication.removeTranslator(traductor)


def test_la_etiqueta_del_dialogo_es_ancha_con_segoe_ui(monkeypatch):
    """Con Segoe UI 9 pt al 100 % (windows-latest) la letra media es estrecha
    frente a la altura de línea: medir en caracteres dejaba el diálogo en
    unos 322 px, aunque en Linux con DejaVu saliera ancho."""
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])  # noqa: F841 — que no la recoja el GC

    class MetricasSegoe:
        def height(self) -> int:
            return 16

        def averageCharWidth(self) -> int:  # noqa: N802 — API de Qt
            return 6

    etiqueta = widgets.QLabel("Carpeta: Nóminas\nPDF: contrato.pdf")
    monkeypatch.setattr(widgets.QLabel, "fontMetrics",
                        lambda self: MetricasSegoe())
    vigilante._ensanchar_etiqueta(etiqueta)

    assert etiqueta.wordWrap()
    # ANCHO_MINIMO de pruebas_escritorio/conducir.py es la ventana entera;
    # la etiqueta sola ya tiene que llegar.
    assert etiqueta.minimumWidth() >= 400


# --- Avisos pensados para el globo de Windows ---------------------------------

@pytest.fixture
def avisos(monkeypatch):
    from cifrarpdf import notificar
    vistos = []
    monkeypatch.setattr(notificar, "info", lambda t, x: vistos.append(("info", t, x)))
    monkeypatch.setattr(notificar, "error", lambda t, x: vistos.append(("error", t, x)))
    return vistos


def test_el_aviso_sin_cifrar_dice_que_hacer_en_la_segunda_linea(escritorio, avisos):
    """El globo de Windows solo enseña las primeras líneas."""
    carpeta = escritorio / "Informes"
    carpeta.mkdir()
    fichero = pdf(carpeta, "uno.pdf")

    vigilante._avisar_sin_cifrar(fichero, "Informes")

    (_tipo, _titulo, texto), = avisos
    lineas = texto.split("\n")
    assert lineas[0] == "«uno.pdf» NO está protegido."
    assert lineas[1].startswith("Sigue en la carpeta «Informes»: suelta ahí")
    assert "SIN-CIFRAR_" in lineas[-1]


def test_el_lote_da_un_solo_aviso_de_protegidos(
        escritorio, sin_keyring, atendedor, avisos, log):
    """Windows enseña los avisos de uno en uno: tres «PDF protegido» seguidos
    dejaban detrás de la cola un error posterior."""
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    soltado = pdf(ruta, "uno.pdf")
    pdf(ruta, "dos.pdf")
    pdf(ruta, "tres.pdf")

    vigilante._procesar_preguntando(soltado, carpeta)

    assert avisos == [("info", "PDF protegidos", "Protegidos 3 PDF en «Informes».")]
    registro = log.read_text(encoding="utf-8")
    for nombre in ("uno.pdf", "dos.pdf", "tres.pdf"):
        assert f"PDF protegido — Cifrado correctamente: {nombre}" in registro


def test_el_lote_avisa_de_cada_error(
        escritorio, sin_keyring, atendedor, avisos, monkeypatch):
    ruta = escritorio / "Informes"
    ruta.mkdir()
    config.escribir("informes", "Informes", ruta, "preguntar")
    carpeta = config.leer("informes")
    soltado = pdf(ruta, "uno.pdf")
    pdf(ruta, "dos.pdf")
    original = cifrar.cifrar_en_sitio

    def falla_dos(r, clave):
        if r.name == "dos.pdf":
            raise cifrar.ErrorCifrado("No se pudo cifrar «dos.pdf»: roto")
        return original(r, clave)

    monkeypatch.setattr(cifrar, "cifrar_en_sitio", falla_dos)

    vigilante._procesar_preguntando(soltado, carpeta)

    assert ("error", "Error al cifrar PDF", "No se pudo cifrar «dos.pdf»: roto") in avisos
    assert ("info", "PDF protegidos", "Protegido 1 PDF en «Informes».") in avisos
