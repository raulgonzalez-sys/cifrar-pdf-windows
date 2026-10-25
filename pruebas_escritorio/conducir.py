"""Prueba de escritorio: el CifrarPDF.exe empaquetado, con bandeja y diálogos de verdad.

Corre en el escritorio interactivo de `windows-latest` (ver
`.github/workflows/escritorio.yml`): lanza el vigilante con su icono en la
bandeja, suelta PDF en carpetas del modo «preguntar» y contesta los diálogos
con pywinauto (UIA), como lo haría una trabajadora. Cubre lo que los tests no
ven: los diálogos de Qt, la bandeja y la parada real del vigilante.

Cada escenario deja una línea «### N nombre: OK|FALLO — detalle» en el registro
del job, y si alguno falla el proceso sale con 1. Las capturas, el resumen y el
registro del vigilante quedan en la carpeta SALIDA.

    python pruebas_escritorio/conducir.py dist\\CifrarPDF
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

SALIDA = Path(os.environ.get("SALIDA", "salida")).resolve()
RESUMEN: list[str] = []
RESULTADOS: list[tuple[str, bool, str]] = []
T0 = time.monotonic()

# Entorno aislado: configuración, registro y «Escritorio» propios. Se fija antes
# de lanzar nada; el vigilante y el CLI lo heredan.
TEMP = Path(os.environ.get("RUNNER_TEMP", os.environ.get("TEMP", "."))) / "cifrar"
ESCRITORIO = TEMP / "Escritorio"
ORIGEN = TEMP / "origen"
LOG = TEMP / "datos" / "cifrar-pdf.log"
os.environ["CIFRARPDF_CONFIG_DIR"] = str(TEMP / "cfg")
os.environ["CIFRARPDF_DATOS_DIR"] = str(TEMP / "datos")
os.environ["CIFRARPDF_ESCRITORIO"] = str(ESCRITORIO)
os.environ.pop("CIFRARPDF_SIN_BANDEJA", None)
DIST = Path()

CLAVE_FIJA = "clave-fija-2026"
CARPETAS_PREGUNTAR = ("P1", "P2", "P3", "P4", "P6", "P7")

BOTON_ACEPTAR = r"^&?Aceptar$"
BOTON_CANCELAR = r"^&?Cancelar$"
BOTON_SI = r"^&?S[ií]$"
BOTON_NO = r"^&?No$"
ANCHO_MINIMO = 400


# --- Registro del job ---------------------------------------------------------

def anotar(texto: str) -> None:
    linea = f"[{time.monotonic() - T0:7.1f}s] {texto}"
    print(linea, flush=True)
    RESUMEN.append(linea)
    (SALIDA / "resumen.txt").write_text("\n".join(RESUMEN) + "\n", encoding="utf-8")


def resultado(esc: str, comprobaciones: dict[str, bool], extra: str = "") -> bool:
    ok = all(comprobaciones.values())
    fallidas = [nombre for nombre, valor in comprobaciones.items() if not valor]
    detalle = ("todo bien" if ok else "falla: " + "; ".join(fallidas)) + (
        f" ({extra})" if extra else "")
    RESULTADOS.append((esc, ok, detalle))
    anotar(f"### {esc}: {'OK' if ok else 'FALLO'} — {detalle}")
    for nombre, valor in comprobaciones.items():
        anotar(f"      [{'x' if valor else ' '}] {nombre}")
    if not ok:
        print(f"::error title={esc}::{detalle}", flush=True)
        captura(f"FALLO_{esc.split()[0]}")
    return ok


def captura(nombre: str) -> None:
    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(SALIDA / f"{nombre}.png")
        anotar(f"captura {nombre}.png")
    except Exception as error:  # noqa: BLE001 — una captura no tumba la prueba
        anotar(f"captura {nombre}: {error!r}")


def esperar(cond, tiempo: float = 30.0, paso: float = 0.3):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        try:
            valor = cond()
        except Exception:  # noqa: BLE001 — la condición aún no se puede evaluar
            valor = None
        if valor:
            return valor
        time.sleep(paso)
    return None


# --- El producto --------------------------------------------------------------

def cli(*args: str, entrada: str | None = None, tiempo: float = 60) -> str:
    r = subprocess.run([str(DIST / "CifrarPDF-cli.exe"), *args], input=entrada,
                       capture_output=True, text=True, timeout=tiempo,
                       encoding="utf-8", errors="replace")
    salida = (r.stdout or "").strip()
    error = (r.stderr or "").strip()
    anotar(f"$ CifrarPDF-cli {' '.join(args)} -> rc={r.returncode} «{salida}»"
           + (f" err «{error}»" if error else ""))
    return salida


def registro() -> str:
    try:
        return LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def desde(marca: int) -> str:
    return registro()[marca:]


def pids_vigilante() -> list[int]:
    """PID de los CifrarPDF.exe que hacen de vigilante (por su línea de órdenes)."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='CifrarPDF.exe'\" | "
         "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        capture_output=True, text=True, timeout=60)
    return sorted(int(linea.split("\t")[0]) for linea in r.stdout.splitlines()
                  if "--vigilante" in linea)


def hacer_pdf(ruta: Path) -> Path:
    import pikepdf
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        pdf.add_blank_page(page_size=(595, 842))
        pdf.save(ruta)
    return ruta


def soltar(carpeta: str, *nombres: str) -> list[Path]:
    destinos = []
    for nombre in nombres:
        destino = ESCRITORIO / carpeta / nombre
        shutil.copy(hacer_pdf(ORIGEN / nombre), destino)
        destinos.append(destino)
    anotar(f"soltados en {carpeta}: {', '.join(nombres)}")
    return destinos


def cifrado(ruta: Path) -> bool:
    from cifrarpdf import cifrar
    try:
        return ruta.is_file() and cifrar.ya_cifrado(ruta)
    except Exception:  # noqa: BLE001 — ilegible cuenta como no cifrado
        return False


def abre_con(ruta: Path, clave: str) -> bool:
    import pikepdf
    try:
        with pikepdf.open(ruta, password=clave) as pdf:
            return pdf.is_encrypted and pdf.encryption.R == 6
    except Exception as error:  # noqa: BLE001
        anotar(f"  no abre {ruta.name} con «{clave}»: {error!r}")
        return False


def listar(carpeta: str) -> list[str]:
    return sorted(p.name for p in (ESCRITORIO / carpeta).iterdir())


# --- Diálogos del vigilante (pywinauto, UIA) ------------------------------------

def buscar_dialogo(carpeta: str):
    from pywinauto import Desktop
    titulo = f"Cifrar PDF — {carpeta}"
    for w in Desktop(backend="uia").windows():
        try:
            if w.window_text() == titulo and w.is_visible():
                return w
        except Exception:  # noqa: BLE001 — ventana que se cierra mientras se mira
            continue
    return None


def describir(w) -> dict:
    textos = [d.window_text() for d in w.descendants(control_type="Text")
              if d.window_text()]
    # El botón «Close» es el de la barra de título, no de Qt.
    botones = [d.window_text() for d in w.descendants(control_type="Button")
               if d.window_text() and d.window_text() != "Close"]
    if w.descendants(control_type="Edit"):
        tipo = "pedir"
    elif any(re.search(r"(?i)^&?(yes|no|s[ií])$", b) for b in botones):
        tipo = "confirmar"
    else:
        tipo = "avisar"
    r = w.rectangle()
    return {"tipo": tipo, "texto": " | ".join(textos), "botones": botones,
            "ancho": r.right - r.left}


def tiene_boton(info: dict, patron: str) -> bool:
    return any(re.search(patron, b) for b in info["botones"])


CONTADOR = [0]


def esperar_dialogo(carpeta: str, etiqueta: str, previo=None, tiempo: float = 40.0):
    """El siguiente diálogo de la carpeta (distinto de «previo»), descrito y capturado."""
    w = esperar(lambda: (lambda x: x if x is not None and x.handle != previo else None)(
        buscar_dialogo(carpeta)), tiempo)
    if w is None:
        anotar(f"  [{etiqueta}] NO apareció diálogo «Cifrar PDF — {carpeta}» en {tiempo:.0f} s")
        return None, None
    time.sleep(0.6)  # que termine de pintarse
    info = describir(w)
    CONTADOR[0] += 1
    anotar(f"  [{etiqueta}] diálogo {info['tipo']} ancho={info['ancho']} "
           f"texto=«{info['texto']}» botones={info['botones']}")
    captura(f"{etiqueta}_{CONTADOR[0]:02d}_{info['tipo']}")
    return w, info


def visible(w) -> bool:
    return bool(ctypes.windll.user32.IsWindow(w.handle)
                and ctypes.windll.user32.IsWindowVisible(w.handle))


def esperar_cierre(w, tiempo: float = 15.0) -> bool:
    return bool(esperar(lambda: not visible(w), tiempo))


def teclas(w, texto: str) -> None:
    from pywinauto.keyboard import send_keys
    w.set_focus()
    edit = w.descendants(control_type="Edit")
    if edit:
        edit[0].set_focus()
    time.sleep(0.2)
    send_keys(texto, with_spaces=True, pause=0.02)


def contestar(w, clave: str) -> bool:
    teclas(w, clave + "{ENTER}")
    return esperar_cierre(w)


def cancelar(w) -> bool:
    teclas(w, "{ESC}")
    return esperar_cierre(w)


def pulsar(w, patron: str) -> bool:
    for b in w.descendants(control_type="Button"):
        if re.search(patron, b.window_text() or ""):
            b.click_input()
            return esperar_cierre(w)
    return False


def clave_confirmada(carpeta: str, etiqueta: str, clave: str):
    """Contesta el diálogo de contraseña y el de confirmación. Devuelve el primero."""
    w, info = esperar_dialogo(carpeta, etiqueta)
    if w is None or info["tipo"] != "pedir":
        return info
    contestar(w, clave)
    w2, info2 = esperar_dialogo(carpeta, etiqueta, previo=w.handle)
    if w2 is not None:
        info["segundo"] = info2
        contestar(w2, clave)
    return info


def cerrar_restos(carpeta: str) -> None:
    for _ in range(6):
        w = buscar_dialogo(carpeta)
        if w is None:
            return
        anotar(f"  cierro un diálogo sobrante de {carpeta}: {describir(w)['texto']}")
        cancelar(w)
        time.sleep(0.5)


# --- PDF abierto «como Acrobat» -------------------------------------------------

def bloquear(ruta: Path) -> int:
    """Abre el PDF compartiendo solo la lectura, como hace un visor."""
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    generic_read, file_share_read, open_existing = 0x80000000, 1, 3
    asa = k32.CreateFileW(str(ruta), generic_read, file_share_read, None,
                          open_existing, 0, None)
    if not asa or asa == wintypes.HANDLE(-1).value:
        raise OSError(f"CreateFileW {ruta}: {ctypes.get_last_error()}")
    return asa


def soltar_bloqueo(asa: int) -> None:
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle(asa)


# --- Escenarios -----------------------------------------------------------------

def e1_sonda() -> bool:
    """Hay escritorio y bandeja, y el vigilante arranca con su icono."""
    esc = "1 sonda"
    barra = bool(ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None))
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; from PyQt6.QtWidgets import QApplication, QSystemTrayIcon; "
         "a = QApplication(sys.argv); print(QSystemTrayIcon.isSystemTrayAvailable())"],
        capture_output=True, text=True, timeout=60)
    bandeja = r.stdout.strip() == "True"
    anotar(f"  barra de tareas={barra}; isSystemTrayAvailable={r.stdout.strip()!r} "
           f"{r.stderr.strip()}")
    if not (barra and bandeja):
        resultado(esc, {"hay barra de tareas (escritorio interactivo)": barra,
                        "Qt ve el área de notificación": bandeja},
                  "sin escritorio no tiene sentido seguir")
        return False

    # Despeja la consola del agente del runner para que las capturas se lean.
    from pywinauto import Desktop
    for w in Desktop(backend="win32").windows():
        if "hosted-compute-agent" in (w.window_text() or ""):
            ctypes.windll.user32.ShowWindow(w.handle, 6)

    alta = cli("--gui-add", "Fija", entrada=CLAVE_FIJA)
    altas = [cli("--gui-add", nombre, "--modo", "preguntar") for nombre in CARPETAS_PREGUNTAR]
    listo = esperar(lambda: f"Sin barrido inicial en «{CARPETAS_PREGUNTAR[-1]}»" in registro()
                    and pids_vigilante(), 40)
    time.sleep(3)
    pids = pids_vigilante()
    texto = registro()
    captura("1_bandeja")
    return resultado(esc, {
        "hay barra de tareas (escritorio interactivo)": barra,
        "Qt ve el área de notificación": bandeja,
        "altas OK": alta == "OK fija" and all(a.startswith("OK ") for a in altas),
        "vigilante en marcha": bool(listo) and cli("--gui-estado") == "1",
        "con icono en la bandeja": "No hay área de notificación" not in texto
        and "no se pudo montar el icono" not in texto,
        # Cada alta reinicia el vigilante: si la parada no llegara, quedarían
        # vigilantes viejos o el nuevo no arrancaría.
        f"un solo vigilante tras {1 + len(altas)} altas": len(pids) == 1,
    }, f"pids={pids}")


def e2_preguntar() -> bool:
    esc = "2 preguntar básico"
    (pdf,) = soltar("P1", "uno.pdf")
    clave = "clave-uno-2026"
    marca = len(registro())
    info = clave_confirmada("P1", "2", clave) or {}
    ok = esperar(lambda: cifrado(pdf), 30)
    segundo = info.get("segundo", {})
    return resultado(esc, {
        "diálogo de contraseña": info.get("tipo") == "pedir",
        "el texto trae la carpeta": "Carpeta «P1»" in info.get("texto", ""),
        "el texto trae el PDF": "uno.pdf" in info.get("texto", ""),
        f"ancho ≥ {ANCHO_MINIMO} px": info.get("ancho", 0) >= ANCHO_MINIMO,
        "botón «Aceptar»": bool(info) and tiene_boton(info, BOTON_ACEPTAR),
        "botón «Cancelar»": bool(info) and tiene_boton(info, BOTON_CANCELAR),
        "pide confirmarla": "Escríbela otra vez" in segundo.get("texto", ""),
        "cifrado y abre con esa clave": bool(ok) and abre_con(pdf, clave),
        "«PDF protegido» en el registro": "PDF protegido" in desde(marca),
    }, f"ancho={info.get('ancho')}, botones={info.get('botones')}")


def e3_lote() -> bool:
    esc = "3 lote de 3"
    pdfs = soltar("P2", "dos.pdf", "tres.pdf", "cuatro.pdf")
    clave = "clave-lote-2026"
    marca = len(registro())
    info = clave_confirmada("P2", "3", clave) or {}
    w, conf = esperar_dialogo("P2", "3")
    conf = conf or {"tipo": None, "texto": "", "botones": []}
    si = w is not None and conf["tipo"] == "confirmar" and pulsar(w, BOTON_SI)
    todos = esperar(lambda: all(cifrado(p) for p in pdfs), 40)
    sobra = esperar(lambda: buscar_dialogo("P2"), 5)
    if sobra is not None:
        cerrar_restos("P2")
    return resultado(esc, {
        "el primero dice que hay 3": "hay 3 PDF sin proteger" in info.get("texto", ""),
        "pregunta por el lote": "¿Uso esta misma contraseña para todos?" in conf["texto"],
        "botón «Sí»": tiene_boton(conf, BOTON_SI),
        "botón «No»": tiene_boton(conf, BOTON_NO),
        "«Sí» pulsado": si,
        "los 3 cifrados y abren con la clave": bool(todos)
        and all(abre_con(p, clave) for p in pdfs),
        "un solo aviso de éxito": "Protegidos 3 PDF en «P2»" in desde(marca),
        "sin diálogos de más": sobra is None,
    }, f"botones={conf['botones']}")


def e4_en_uso() -> bool:
    """Un PDF del lote abierto en un visor durante más de 60 s."""
    esc = "4 lote con uno en uso"
    pdfs = soltar("P3", "cinco.pdf", "seis.pdf", "siete.pdf")
    clave = "clave-enuso-2026"
    marca = len(registro())
    w, info = esperar_dialogo("P3", "4")
    if w is None:
        return resultado(esc, {"salió el diálogo": False})
    m = re.search(r"proteger «([^»]+)»", info["texto"])
    primero = m.group(1) if m else "cinco.pdf"
    bloqueado = next(p for p in pdfs if p.name != primero)
    asa = bloquear(bloqueado)
    desde_bloqueo = time.monotonic()
    anotar(f"  abierto con FILE_SHARE_READ: {bloqueado.name}")
    try:
        contestar(w, clave)
        w2, _ = esperar_dialogo("P3", "4", previo=w.handle)
        if w2 is not None:
            contestar(w2, clave)
        w3, conf = esperar_dialogo("P3", "4")
        si = w3 is not None and conf["tipo"] == "confirmar" and pulsar(w3, BOTON_SI)
        otros = [p for p in pdfs if p != bloqueado]
        ok_otros = esperar(lambda: all(cifrado(p) for p in otros), 40)
        # Su propio evento seguía en la cola: lo descarta al cumplirse la espera
        # (60 s) sin un segundo aviso.
        descartado = esperar(
            lambda: f"Sigue en uso, ya avisado en el lote: {bloqueado}" in desde(marca), 100, 1)
        retenido = time.monotonic() - desde_bloqueo
        captura("4_tras_la_espera")
    finally:
        soltar_bloqueo(asa)
    nuevo = desde(marca)
    avisos = [linea for linea in nuevo.splitlines()
              if "ERROR:" in linea and bloqueado.name in linea]
    anotar(f"  avisos de {bloqueado.name}: {avisos}")
    cerrar_restos("P3")
    return resultado(esc, {
        "«Sí» pulsado": si,
        "los otros 2 cifrados y abren con la clave": bool(ok_otros)
        and all(abre_con(p, clave) for p in otros),
        "el que está en uso sigue sin cifrar": not cifrado(bloqueado),
        "se omite en el lote": f"Lote: se omite, en uso por otro programa: {bloqueado}" in nuevo,
        "abierto más de 60 s": retenido > 60,
        "su evento se descarta sin otro aviso": bool(descartado),
        "una sola línea de aviso para él": len(avisos) == 1
        and "sigue abierto en otro programa" in avisos[0],
        "sin «no terminó de copiarse»": "no terminó de copiarse" not in nuevo,
    }, f"retenido {retenido:.0f} s")


def e5_cancelar() -> bool:
    esc = "5 cancelar dos veces"
    (pdf,) = soltar("P4", "ocho.pdf")
    marca = len(registro())
    w, info = esperar_dialogo("P4", "5")
    primero = w is not None and info["tipo"] == "pedir" and cancelar(w)
    w2, aviso = esperar_dialogo("P4", "5", previo=w.handle if w else None)
    aviso = aviso or {"tipo": None, "texto": "", "botones": []}
    if w2 is not None and aviso["tipo"] == "avisar":
        teclas(w2, "{ENTER}")
        esperar_cierre(w2)
    w3, ultimo = esperar_dialogo("P4", "5", previo=w2.handle if w2 else None)
    ultimo = ultimo or {"tipo": None, "texto": ""}
    segundo = w3 is not None and ultimo["tipo"] == "pedir" and cancelar(w3)
    marcado = ESCRITORIO / "P4" / "SIN-CIFRAR_ocho.pdf"
    hay_marca = esperar(lambda: marcado.is_file(), 20)
    anotar(f"  P4: {listar('P4')}")
    return resultado(esc, {
        "primer Escape": bool(primero),
        "avisa de la cancelación": "Se ha cancelado la contraseña." in aviso["texto"],
        "el aviso tiene «Aceptar»": tiene_boton(aviso, BOTON_ACEPTAR),
        "último intento": "(Último intento.)" in ultimo["texto"],
        "segundo Escape": bool(segundo),
        "queda SIN-CIFRAR_ y sin cifrar": bool(hay_marca) and not cifrado(marcado),
        "no queda el nombre original": not pdf.exists(),
        "aviso «PDF SIN CIFRAR»": "PDF SIN CIFRAR" in desde(marca),
    })


def e6_set_pass() -> bool:
    """Cambiar la clave de OTRA carpeta no reinicia el vigilante ni cierra el diálogo."""
    esc = "6 cambiar la clave con un diálogo abierto"
    (pdf,) = soltar("P6", "diez.pdf")
    clave = "clave-diez-2026"
    marca = len(registro())
    w, _info = esperar_dialogo("P6", "6")
    if w is None:
        return resultado(esc, {"salió el diálogo": False})
    pid0 = pids_vigilante()
    inicios0 = registro().count("Iniciando vigilancia")
    cambio = cli("--gui-set-pass", "fija", entrada="clave-fija-nueva-2026")
    time.sleep(3)
    sigue = visible(w)
    pid1 = pids_vigilante()
    inicios1 = registro().count("Iniciando vigilancia")
    captura("6_dialogo_tras_set_pass")
    contestar(w, clave)
    w2, _ = esperar_dialogo("P6", "6", previo=w.handle)
    if w2 is not None:
        contestar(w2, clave)
    ok = esperar(lambda: cifrado(pdf), 30)
    anotar(f"  registro: {desde(marca).strip()}")
    return resultado(esc, {
        "--gui-set-pass OK": cambio == "OK",
        "el diálogo sigue abierto": sigue,
        "mismo vigilante": bool(pid0) and pid0 == pid1,
        "sin otro «Iniciando vigilancia»": inicios0 == inicios1,
        "al contestar, cifrado con su clave": bool(ok) and abre_con(pdf, clave),
    }, f"pid {pid0} -> {pid1}")


def e7_reinicio() -> bool:
    """Añadir una carpeta con un diálogo abierto reinicia el vigilante de verdad."""
    esc = "7 reinicio y parada con un diálogo abierto"
    (pdf,) = soltar("P7", "doce.pdf")
    w, _info = esperar_dialogo("P7", "7")
    if w is None:
        return resultado(esc, {"salió el diálogo": False})
    pid0 = pids_vigilante()
    marca = len(registro())
    t = time.monotonic()
    alta = cli("--gui-add", "Nueva", entrada="clave-nueva-2026")
    duro = time.monotonic() - t
    cerrado = esperar_cierre(w, 20)
    marcado = ESCRITORIO / "P7" / "SIN-CIFRAR_doce.pdf"
    hay_marca = esperar(lambda: marcado.is_file(), 15)
    vigila = esperar(lambda: "Vigilando: Nueva" in desde(marca)
                     and "Sin barrido inicial en «P7»" in desde(marca), 30)
    pid1 = pids_vigilante()
    anotar(f"  --gui-add tardó {duro:.1f} s; pid {pid0} -> {pid1}; P7: {listar('P7')}")
    captura("7_tras_gui_add")
    time.sleep(2)  # el observador tarda un instante en empezar a recibir cambios
    (nuevo,) = soltar("Nueva", "trece.pdf")
    ok_nueva = esperar(lambda: cifrado(nuevo), 30)
    texto = desde(marca)

    t = time.monotonic()
    cli("--parar")
    parado = esperar(lambda: cli("--gui-estado") == "0", 15, 0.5)
    tardo = time.monotonic() - t
    quedan = pids_vigilante()
    anotar(f"  registro: {desde(marca).strip()}")
    return resultado(esc, {
        "--gui-add OK": alta == "OK nueva",
        "el diálogo se cierra": cerrado,
        "vigilante nuevo": bool(pid0) and len(pid1) == 1 and pid0 != pid1,
        "«Vigilancia detenida.» en el registro": "Vigilancia detenida." in texto,
        "el PDF del diálogo queda SIN-CIFRAR_": bool(hay_marca) and not cifrado(marcado),
        "no queda en claro con su nombre": not pdf.exists(),
        "vigila la carpeta nueva": bool(vigila),
        "un PDF en la carpeta nueva se cifra": bool(ok_nueva)
        and abre_con(nuevo, "clave-nueva-2026"),
        "--parar: --gui-estado 0 en < 15 s": bool(parado),
        "no queda ningún vigilante": not quedan,
    }, f"--gui-add {duro:.1f} s, --parar {tardo:.1f} s")


ESCENARIOS = (e2_preguntar, e3_lote, e4_en_uso, e5_cancelar, e6_set_pass, e7_reinicio)


def resumen_del_job() -> None:
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    filas = ["| Escenario | Resultado | Detalle |", "|---|---|---|"]
    filas += [f"| {esc} | {'OK' if ok else '**FALLO**'} | {detalle} |"
              for esc, ok, detalle in RESULTADOS]
    with open(destino, "a", encoding="utf-8") as fichero:
        fichero.write("## Prueba de escritorio\n\n" + "\n".join(filas) + "\n")


def main() -> int:
    global DIST
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    DIST = Path(sys.argv[1]).resolve()
    SALIDA.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(TEMP, ignore_errors=True)
    ESCRITORIO.mkdir(parents=True)
    try:
        if e1_sonda():
            for escenario in ESCENARIOS:
                try:
                    escenario()
                except Exception:  # noqa: BLE001 — el resto de escenarios sigue
                    anotar(traceback.format_exc())
                    resultado(escenario.__name__, {"sin excepción del conductor": False},
                              traceback.format_exc(limit=1).strip().splitlines()[-1])
    finally:
        if cli("--gui-estado") == "1":
            cli("--parar")
        try:
            shutil.copy(LOG, SALIDA / "cifrar-pdf.log")
        except OSError:
            pass
    anotar("==== RESUMEN ====")
    for esc, ok, detalle in RESULTADOS:
        anotar(f"{esc:45s} {'OK' if ok else 'FALLO':6s} {detalle}")
    resumen_del_job()
    return 0 if RESULTADOS and all(ok for _esc, ok, _d in RESULTADOS) else 1


if __name__ == "__main__":
    sys.exit(main())
