"""TEMPORAL: conductor de la prueba de escritorio en Windows (no mergear).

Maneja el CifrarPDF.exe congelado de verdad en la sesión interactiva del runner:
vigilante con bandeja, diálogos del modo «preguntar» (pywinauto, UIA), avisos y
la ventana de gestión con un arrastre real desde el Explorador.

    python pruebas_escritorio/conducir.py sonda
    python pruebas_escritorio/conducir.py conjunto dist\\CifrarPDF
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
from ctypes import wintypes
from pathlib import Path

SALIDA = Path(os.environ.get("SALIDA", "salida")).resolve()
SALIDA.mkdir(parents=True, exist_ok=True)
RESUMEN: list[str] = []
RESULTADOS: list[tuple[str, str, str]] = []
T0 = time.monotonic()


def anotar(texto: str) -> None:
    linea = f"[{time.monotonic() - T0:7.1f}s] {texto}"
    print(linea, flush=True)
    RESUMEN.append(linea)
    (SALIDA / "resumen.txt").write_text("\n".join(RESUMEN) + "\n", encoding="utf-8")


def resultado(esc: str, estado: str, detalle: str) -> None:
    RESULTADOS.append((esc, estado, detalle))
    anotar(f"### {esc}: {estado} — {detalle}")


def captura(nombre: str):
    from PIL import ImageGrab
    imagen = ImageGrab.grab(all_screens=True)
    ruta = SALIDA / f"{nombre}.png"
    imagen.save(ruta)
    anotar(f"captura {ruta.name}")
    return ruta


def capturas_seguidas(prefijo: str, veces: int = 4, intervalo: float = 1.0) -> None:
    """Varias capturas seguidas: el globo/toast aparece y se va."""
    for i in range(veces):
        time.sleep(intervalo)
        captura(f"{prefijo}_{i}")
        volcar_toasts(prefijo)


def volcar_toasts(prefijo: str) -> None:
    try:
        from pywinauto import Desktop
        for w in Desktop(backend="uia").windows():
            nombre = w.window_text()
            clase = w.class_name()
            if "otific" in nombre or "Toast" in clase or "CoreWindow" in clase:
                textos = [d.window_text() for d in w.descendants()
                          if d.window_text()][:20]
                anotar(f"  toast? [{prefijo}] «{nombre}» ({clase}): {textos}")
    except Exception as error:  # noqa: BLE001
        anotar(f"  toast? error: {error!r}")


def centro_notificaciones(nombre: str) -> None:
    """Abre el centro de notificaciones (Win+N), lo captura y lo cierra."""
    from pywinauto.keyboard import send_keys
    try:
        send_keys("{VK_LWIN down}n{VK_LWIN up}")
        time.sleep(2.5)
        captura(nombre)
        volcar_toasts(nombre)
        try:
            from pywinauto import Desktop
            for w in Desktop(backend="uia").windows():
                if "otific" in w.window_text():
                    textos = [d.window_text() for d in w.descendants() if d.window_text()]
                    anotar(f"  centro: {textos[:40]}")
        except Exception as error:  # noqa: BLE001
            anotar(f"  centro: {error!r}")
        send_keys("{ESC}")
        time.sleep(1)
    except Exception as error:  # noqa: BLE001
        anotar(f"  centro de notificaciones: {error!r}")


def quitar_no_molestar() -> None:
    """Entorno: el runner trae «No molestar» activado y ahí no sale ningún
    globo. Se desactiva desde el centro de notificaciones (ajuste del sistema,
    no del producto)."""
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    send_keys("{VK_LWIN down}n{VK_LWIN up}")
    time.sleep(2.5)
    hecho = False
    for w in Desktop(backend="uia").windows():
        if "otific" not in w.window_text():
            continue
        for d in w.descendants():
            if d.window_text() == "Do Not Disturb" and d.element_info.control_type in (
                    "Button", "CheckBox"):
                try:
                    estado = d.get_toggle_state()
                    anotar(f"  [entorno] No molestar: estado {estado}")
                    if estado:
                        d.toggle()
                except Exception as error:  # noqa: BLE001
                    anotar(f"  [entorno] toggle: {error!r}; pruebo con clic")
                    d.click_input()
                hecho = True
                break
    time.sleep(1.5)
    captura("C0_no_molestar")
    for w in Desktop(backend="uia").windows():
        if "otific" in w.window_text():
            textos = [d.window_text() for d in w.descendants() if d.window_text()]
            anotar(f"  [entorno] centro tras quitar No molestar ({hecho}): {textos[:8]}")
    send_keys("{ESC}")
    time.sleep(1)


def globo_de_control() -> None:
    """Entorno: globo con System.Windows.Forms.NotifyIcon (mismo mecanismo,
    Shell_NotifyIcon, que QSystemTrayIcon.showMessage)."""
    guion = (
        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true;"
        "$n.ShowBalloonTip(8000, 'Globo de control', 'PowerShell NotifyIcon', 'Info');"
        "Start-Sleep -Seconds 9; $n.Dispose()")
    subprocess.Popen(["powershell", "-NoProfile", "-Command", guion])
    capturas_seguidas("C0_globo_control", 4, 1.2)


def ajustes_notificaciones() -> None:
    for clave in (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings",
                  r"HKCU\Software\Microsoft\Windows\CurrentVersion\PushNotifications",
                  r"HKCU\Software\Policies\Microsoft\Windows\Explorer",
                  r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"):
        r = subprocess.run(["reg", "query", clave], capture_output=True, text=True)
        anotar(f"$ reg query {clave}\n{(r.stdout or r.stderr).strip()[:1500]}")


def esperar(cond, tiempo: float = 30.0, paso: float = 0.3):
    limite = time.monotonic() + tiempo
    while time.monotonic() < limite:
        try:
            valor = cond()
        except Exception:  # noqa: BLE001
            valor = None
        if valor:
            return valor
        time.sleep(paso)
    return None


# --- Entorno aislado ---------------------------------------------------------

TEMP = Path(os.environ.get("RUNNER_TEMP", os.environ.get("TEMP", "."))) / "cifrar"
os.environ["CIFRARPDF_CONFIG_DIR"] = str(TEMP / "cfg")
os.environ["CIFRARPDF_DATOS_DIR"] = str(TEMP / "datos")
os.environ["CIFRARPDF_ESCRITORIO"] = str(TEMP / "Escritorio")
ESCRITORIO = TEMP / "Escritorio"
ORIGEN = TEMP / "origen"
LOG = TEMP / "datos" / "cifrar-pdf.log"
DIST: Path = Path()
SINCLAVE = ["sinclave"]


def cli(*args: str, entrada: str | None = None, tiempo: float = 60) -> str:
    r = subprocess.run([str(DIST / "CifrarPDF-cli.exe"), *args], input=entrada,
                       capture_output=True, text=True, timeout=tiempo,
                       encoding="utf-8", errors="replace")
    salida = (r.stdout or "").strip()
    anotar(f"$ CifrarPDF-cli {' '.join(args)} -> rc={r.returncode} «{salida}»"
           + (f" err «{r.stderr.strip()}»" if r.stderr.strip() else ""))
    return salida


def registro() -> str:
    try:
        return LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def contar(texto: str) -> int:
    return registro().count(texto)


def lineas_desde(marca: int) -> str:
    return registro()[marca:]


def pid_vigilante() -> list[int]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='CifrarPDF.exe'\" | "
         "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
        capture_output=True, text=True, timeout=60)
    pids = []
    for linea in r.stdout.splitlines():
        if "--vigilante" in linea:
            pids.append(int(linea.split("\t")[0]))
    return pids


def hacer_pdf(ruta: Path, paginas: int = 1) -> Path:
    import pikepdf
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        for _ in range(paginas):
            pdf.add_blank_page(page_size=(595, 842))
        pdf.save(ruta)
    return ruta


def plantilla(nombre: str) -> Path:
    return hacer_pdf(ORIGEN / "plantillas" / nombre)


def soltar(carpeta: str, *nombres: str) -> list[Path]:
    destinos = []
    for nombre in nombres:
        destino = ESCRITORIO / carpeta / nombre
        shutil.copy(plantilla(nombre), destino)
        destinos.append(destino)
    anotar(f"soltados en {carpeta}: {', '.join(nombres)}")
    return destinos


def cifrado(ruta: Path) -> bool:
    from cifrarpdf import cifrar
    try:
        return ruta.is_file() and cifrar.ya_cifrado(ruta)
    except Exception:  # noqa: BLE001
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


# --- Diálogos (pywinauto, UIA) ----------------------------------------------

DIALOGOS: list[dict] = []
CONTADOR = [0]


def _escritorio_uia():
    from pywinauto import Desktop
    return Desktop(backend="uia")


def buscar_dialogo(carpeta: str):
    titulo = f"Cifrar PDF — {carpeta}"
    for w in _escritorio_uia().windows():
        try:
            if w.window_text() == titulo and w.is_visible():
                return w
        except Exception:  # noqa: BLE001
            continue
    return None


def describir(w) -> dict:
    textos = [d.window_text() for d in w.descendants(control_type="Text")
              if d.window_text()]
    botones = [d.window_text() for d in w.descendants(control_type="Button")]
    edits = w.descendants(control_type="Edit")
    if edits:
        tipo = "pedir"
    elif any(re.search(r"(?i)^&?(yes|s[ií])$", b or "") for b in botones):
        tipo = "confirmar"
    else:
        tipo = "avisar"
    r = w.rectangle()
    return {"tipo": tipo, "textos": textos, "botones": botones,
            "handle": w.handle, "rect": (r.left, r.top, r.right, r.bottom)}


def esperar_dialogo(carpeta: str, esc: str, tiempo: float = 40.0, previo=None):
    w = esperar(lambda: (lambda x: x if x is not None and x.handle != previo else None)(
        buscar_dialogo(carpeta)), tiempo)
    if w is None:
        anotar(f"  [{esc}] NO apareció diálogo «Cifrar PDF — {carpeta}» en {tiempo:.0f} s")
        return None, None
    time.sleep(0.6)  # que termine de pintarse
    info = describir(w)
    CONTADOR[0] += 1
    info["n"] = CONTADOR[0]
    info["esc"] = esc
    DIALOGOS.append(info)
    anotar(f"  [{esc}] diálogo {info['tipo']} rect={info['rect']} textos={info['textos']} "
           f"botones={info['botones']}")
    info["captura"] = captura(f"{esc}_{CONTADOR[0]:02d}_{info['tipo']}").name
    return w, info


def esperar_cierre(w, tiempo: float = 15.0) -> bool:
    handle = w.handle
    return bool(esperar(lambda: not ctypes.windll.user32.IsWindow(handle)
                        or not ctypes.windll.user32.IsWindowVisible(handle), tiempo))


def teclear(w, texto: str) -> None:
    from pywinauto.keyboard import send_keys
    w.set_focus()
    edit = w.descendants(control_type="Edit")
    if edit:
        edit[0].set_focus()
    time.sleep(0.2)
    send_keys(texto, with_spaces=True, pause=0.02)


def contestar_clave(w, clave: str) -> bool:
    from pywinauto.keyboard import send_keys
    teclear(w, clave)
    send_keys("{ENTER}")
    return esperar_cierre(w)


def cancelar(w) -> bool:
    from pywinauto.keyboard import send_keys
    w.set_focus()
    time.sleep(0.2)
    send_keys("{ESC}")
    return esperar_cierre(w)


def aceptar_aviso(w) -> bool:
    from pywinauto.keyboard import send_keys
    w.set_focus()
    time.sleep(0.2)
    send_keys("{ENTER}")
    return esperar_cierre(w)


def pulsar_si(w) -> bool:
    for b in w.descendants(control_type="Button"):
        if re.search(r"(?i)^&?(yes|s[ií])$", b.window_text() or ""):
            b.click_input()
            return esperar_cierre(w)
    return False


def ciclo_dos_claves(carpeta: str, esc: str, clave: str):
    """Primer diálogo + confirmación. Devuelve info del primero."""
    w, info = esperar_dialogo(carpeta, esc)
    if w is None:
        return None
    if info["tipo"] != "pedir":
        anotar(f"  [{esc}] esperaba «pedir», salió {info['tipo']}")
        return info
    contestar_clave(w, clave)
    w2, info2 = esperar_dialogo(carpeta, esc, previo=w.handle)
    if w2 is None:
        return info
    info["segundo"] = info2
    contestar_clave(w2, clave)
    return info


def cerrar_restos(carpeta: str) -> None:
    for _ in range(6):
        w = buscar_dialogo(carpeta)
        if w is None:
            return
        anotar(f"  limpiando diálogo sobrante de {carpeta}: {describir(w)['textos']}")
        cancelar(w)
        time.sleep(0.5)


# --- Bloqueo «como Acrobat» ---------------------------------------------------

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                            wintypes.HANDLE]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 1
OPEN_EXISTING = 3
INVALID = wintypes.HANDLE(-1).value
k32.CreateEventW.restype = wintypes.HANDLE
k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
NOMBRE_EVENTO = r"Local\FISAT-CifrarPDF-Parar"
ASA_EVENTO = [None]


def sujetar_evento() -> None:
    """Arnés: mantiene viva la parada con nombre para que --parar la encuentre."""
    if ASA_EVENTO[0] is None:
        ASA_EVENTO[0] = k32.CreateEventW(None, True, False, NOMBRE_EVENTO)
        anotar(f"  [arnés] sujeto el evento de parada (handle {ASA_EVENTO[0]})")


def soltar_evento() -> None:
    if ASA_EVENTO[0] is not None:
        k32.CloseHandle(ASA_EVENTO[0])
        ASA_EVENTO[0] = None
        anotar("  [arnés] soltado el evento de parada")


def bloquear(ruta: Path):
    h = k32.CreateFileW(str(ruta), GENERIC_READ, FILE_SHARE_READ, None,
                        OPEN_EXISTING, 0, None)
    if h == INVALID or not h:
        raise OSError(f"CreateFileW {ruta}: {ctypes.get_last_error()}")
    return h


# --- Escenarios ---------------------------------------------------------------

CLAVE_FIJA = "clave-fija-2026"


def diagnostico_parada() -> None:
    """¿Para --parar al vigilante CON bandeja? Y con el contraste sin bandeja."""
    esc = "C0 parada"
    esperar(lambda: pid_vigilante(), 30)
    time.sleep(4)
    pid0 = pid_vigilante()
    t = time.monotonic()
    cli("--parar")
    dur = time.monotonic() - t
    time.sleep(2)
    sin_arnes = (pid_vigilante(), cli("--gui-estado"), contar("Vigilancia detenida"), round(dur, 1))
    anotar(f"  con bandeja, sin arnés: pid antes {pid0}; después/estado/detenidas/segundos {sin_arnes}")
    sujetar_evento()
    t = time.monotonic()
    cli("--parar")
    dur = time.monotonic() - t
    time.sleep(2)
    con_arnes = (pid_vigilante(), cli("--gui-estado"), contar("Vigilancia detenida"), round(dur, 1))
    anotar(f"  con bandeja, evento sujeto por el arnés: {con_arnes}")
    soltar_evento()
    os.environ["CIFRARPDF_SIN_BANDEJA"] = "1"
    cli("--gui-asegurar")
    del os.environ["CIFRARPDF_SIN_BANDEJA"]
    esperar(lambda: pid_vigilante(), 30)
    time.sleep(3)
    t = time.monotonic()
    cli("--parar")
    dur = time.monotonic() - t
    time.sleep(2)
    sin_bandeja = (pid_vigilante(), cli("--gui-estado"), contar("Vigilancia detenida"), round(dur, 1))
    anotar(f"  SIN bandeja, sin arnés: {sin_bandeja}")
    resultado(esc, "fallo" if sin_arnes[1] == "1" else "ok",
              f"con bandeja --parar deja el vigilante vivo={sin_arnes[1] == '1'}; "
              f"con el evento sujeto se para={con_arnes[1] == '0'}; "
              f"sin bandeja se para={sin_bandeja[1] == '0'}")
    # Deja el vigilante (con bandeja) en marcha otra vez, ya con el arnés.
    sujetar_evento()
    if cli("--gui-estado") == "1":
        cli("--parar")
    cli("--gui-asegurar")


def preparar() -> None:
    if TEMP.exists():
        shutil.rmtree(TEMP, ignore_errors=True)
    ESCRITORIO.mkdir(parents=True)
    # Despeja la consola del agente del runner para que las capturas se lean.
    from pywinauto import Desktop
    for w in Desktop(backend="win32").windows():
        if "hosted-compute-agent" in (w.window_text() or ""):
            ctypes.windll.user32.ShowWindow(w.handle, 6)
    cli("--gui-add", "Fija", entrada=CLAVE_FIJA)
    diagnostico_parada()
    sujetar_evento()
    for nombre in ("P1", "P2", "P3", "P4", "P6"):
        cli("--gui-add", nombre, "--modo", "preguntar")
    ok = esperar(lambda: contar("Sin barrido inicial en «P6»") >= 1 and pid_vigilante(), 40)
    time.sleep(3)
    anotar(f"vigilante: {pid_vigilante()}  estado={cli('--gui-estado')}")
    sin_icono = ("No hay área de notificación" in registro()
                 or "no se pudo montar el icono" in registro())
    resultado("C0 vigilante con bandeja", "ok" if ok and not sin_icono else "fallo",
              f"arrancado={bool(ok)}; ¿sin icono? {sin_icono}")
    captura("C0_bandeja")
    ajustes_notificaciones()
    try:
        quitar_no_molestar()
        globo_de_control()
    except Exception:  # noqa: BLE001
        anotar(traceback.format_exc())


def c1() -> None:
    esc = "C1"
    marca = len(registro())
    (pdf,) = soltar("P1", "uno.pdf")
    clave = "clave-uno-2026"
    info = ciclo_dos_claves("P1", esc, clave)
    ok_cif = esperar(lambda: cifrado(pdf), 30)
    capturas_seguidas("C1_aviso", 4, 0.8)
    ok_abre = bool(ok_cif) and abre_con(pdf, clave)
    centro_notificaciones("C1_centro_notificaciones")
    textos = " | ".join(info["textos"]) if info else ""
    t2 = " | ".join(info.get("segundo", {}).get("textos", [])) if info else ""
    nuevo = lineas_desde(marca)
    checks = {
        "titulo": info is not None,
        "carpeta en texto": "Carpeta «P1»" in textos,
        "nombre pdf": "uno.pdf" in textos,
        "mínimo 8": "mínimo 8 caracteres" in textos,
        "segundo diálogo": "Escríbela otra vez para confirmarla." in t2,
        "cifrado": bool(ok_cif),
        "abre con la clave": ok_abre,
        "registro PDF protegido": "PDF protegido — Cifrado correctamente: uno.pdf" in nuevo,
    }
    anotar(f"  registro: {nuevo.strip()}")
    resultado(esc, "ok" if all(checks.values()) else "fallo", str(checks))


def c2() -> None:
    esc = "C2"
    marca = len(registro())
    n0 = len([d for d in DIALOGOS if d["tipo"] == "pedir"])
    pdfs = soltar("P2", "dos.pdf", "tres.pdf", "cuatro.pdf")
    clave = "clave-lote-2026"
    info = ciclo_dos_claves("P2", esc, clave)
    w, conf = esperar_dialogo("P2", esc)
    si = False
    if w is not None and conf["tipo"] == "confirmar":
        si = pulsar_si(w)
    todos = esperar(lambda: all(cifrado(p) for p in pdfs), 40)
    # ¿algún diálogo de más en los segundos siguientes?
    extra = esperar(lambda: buscar_dialogo("P2"), 8)
    pedir = len([d for d in DIALOGOS if d["tipo"] == "pedir"]) - n0
    abren = all(abre_con(p, clave) for p in pdfs) if todos else False
    textos = " | ".join(info["textos"]) if info else ""
    ctexto = " | ".join(conf["textos"]) if conf else ""
    checks = {
        "primero dice 3": "hay 3 PDF sin proteger" in textos,
        "confirmar con lista": "¿Uso esta misma contraseña para todos?" in ctexto
        and all(p.name in ctexto for p in pdfs),
        "sí pulsado": si,
        "3 cifrados": bool(todos),
        "abren con la clave": abren,
        "2 diálogos de contraseña": pedir == 2,
        "sin diálogo extra": extra is None,
    }
    anotar(f"  registro: {lineas_desde(marca).strip()}")
    if extra is not None:
        cerrar_restos("P2")
    resultado(esc, "ok" if all(checks.values()) else "fallo", str(checks))


def c3() -> None:
    esc = "C3"
    marca = len(registro())
    pdfs = soltar("P3", "cinco.pdf", "seis.pdf", "siete.pdf")
    clave = "clave-enuso-2026"
    w, info = esperar_dialogo("P3", esc)
    if w is None:
        resultado(esc, "fallo", "no salió diálogo")
        return
    m = re.search(r"proteger «([^»]+)»", " ".join(info["textos"]))
    primero = m.group(1) if m else "cinco.pdf"
    bloqueado = next(p for p in pdfs if p.name != primero)
    asa = bloquear(bloqueado)
    anotar(f"  primero={primero}; bloqueado (CreateFileW, FILE_SHARE_READ): {bloqueado.name}")
    contestar_clave(w, clave)
    w2, _ = esperar_dialogo("P3", esc, previo=w.handle)
    if w2 is not None:
        contestar_clave(w2, clave)
    w3, conf = esperar_dialogo("P3", esc)
    si = pulsar_si(w3) if w3 is not None and conf["tipo"] == "confirmar" else False
    otros = [p for p in pdfs if p != bloqueado]
    ok_otros = esperar(lambda: all(cifrado(p) for p in otros), 40)
    aviso = esperar(lambda: "sigue abierto en otro programa" in lineas_desde(marca), 20)
    capturas_seguidas("C3_aviso_en_uso", 5, 0.8)
    centro_notificaciones("C3_centro_notificaciones")
    bloq_sin = not cifrado(bloqueado)
    nuevo = lineas_desde(marca)
    checks = {
        "sí pulsado": si,
        "otros cifrados": bool(ok_otros) and all(abre_con(p, clave) for p in otros),
        "bloqueado sin cifrar": bloq_sin,
        "registro «Lote: se omite, en uso»": "Lote: se omite, en uso por otro programa" in nuevo,
        "aviso «sigue abierto…Ciérralo y vuelve a soltarlo»": bool(aviso) and
        "Ciérralo y vuelve a soltarlo en la carpeta." in nuevo,
    }
    anotar(f"  registro: {nuevo.strip()}")
    # Qué pasa al cerrar el visor: se suelta el handle a los 10 s.
    time.sleep(10)
    k32.CloseHandle(asa)
    anotar(f"  handle de {bloqueado.name} cerrado; ¿se cifra solo?")
    tras = esperar(lambda: cifrado(bloqueado), 30)
    extra = buscar_dialogo("P3")
    anotar(f"  tras cerrar: cifrado={bool(tras)} "
           f"abre con la clave del lote={abre_con(bloqueado, clave) if tras else None} "
           f"diálogo={extra is not None}; registro: {lineas_desde(marca + len(nuevo)).strip()}")
    cerrar_restos("P3")
    resultado(esc, "ok" if all(checks.values()) else "fallo", str(checks))


def c4() -> None:
    esc = "C4"
    marca = len(registro())
    (pdf,) = soltar("P4", "ocho.pdf")
    w, info = esperar_dialogo("P4", esc)
    c1_ok = w is not None and info["tipo"] == "pedir" and cancelar(w)
    w2, aviso = esperar_dialogo("P4", esc, previo=w.handle if w else None)
    aviso_txt = " | ".join(aviso["textos"]) if aviso else ""
    if w2 is not None and aviso["tipo"] == "avisar":
        aceptar_aviso(w2)
    w3, ult = esperar_dialogo("P4", esc, previo=w2.handle if w2 else None)
    ult_txt = " | ".join(ult["textos"]) if ult else ""
    if w3 is not None and ult["tipo"] == "pedir":
        cancelar(w3)
    marcado = ESCRITORIO / "P4" / "SIN-CIFRAR_ocho.pdf"
    hay_marca = esperar(lambda: marcado.is_file(), 20)
    capturas_seguidas("C4_aviso_sin_cifrar", 4, 0.8)
    nuevo = lineas_desde(marca)
    checks1 = {
        "primer Escape": bool(c1_ok),
        "aviso «Se ha cancelado la contraseña.»": "Se ha cancelado la contraseña." in aviso_txt,
        "último intento": "(Último intento.)" in ult_txt,
        "marcado SIN-CIFRAR_": bool(hay_marca),
        "aviso PDF SIN CIFRAR": "PDF SIN CIFRAR" in nuevo,
    }
    anotar(f"  P4 tras cancelar: {listar('P4')}")
    # Segunda parte: otro PDF y el lote se lleva el marcado.
    marca2 = len(registro())
    (nueve,) = soltar("P4", "nueve.pdf")
    clave = "clave-recupera-2026"
    info2 = ciclo_dos_claves("P4", esc, clave)
    w4, conf = esperar_dialogo("P4", esc)
    si = pulsar_si(w4) if w4 is not None and conf["tipo"] == "confirmar" else False
    limpio = ESCRITORIO / "P4" / "ocho.pdf"
    ok = esperar(lambda: cifrado(nueve) and cifrado(limpio) and not marcado.exists(), 40)
    anotar(f"  P4 al final: {listar('P4')}; registro: {lineas_desde(marca2).strip()}")
    checks2 = {
        "segundo dice 2": bool(info2) and "hay 2 PDF sin proteger" in " ".join(info2["textos"]),
        "lista con el marcado": bool(conf) and "SIN-CIFRAR_ocho.pdf" in " ".join(conf["textos"]),
        "sí": si,
        "ambos cifrados y nombre limpio": bool(ok),
        "abren": bool(ok) and abre_con(nueve, clave) and abre_con(limpio, clave),
    }
    cerrar_restos("P4")
    checks1.update(checks2)
    resultado(esc, "ok" if all(checks1.values()) else "fallo", str(checks1))


def c6() -> None:
    esc = "C6"
    marca = len(registro())
    (pdf,) = soltar("P6", "diez.pdf")
    w, info = esperar_dialogo("P6", esc)
    if w is None:
        resultado(esc, "fallo", "no salió diálogo")
        return
    pid0 = pid_vigilante()
    inicios0 = contar("Iniciando vigilancia")
    r1 = cli("--gui-set-pass", "fija", entrada="clave-fija-nueva-2026")
    r2 = cli("--gui-set-pass", "fija", "--modo", "preguntar")
    time.sleep(3)
    sigue = bool(ctypes.windll.user32.IsWindowVisible(w.handle))
    pid1 = pid_vigilante()
    inicios1 = contar("Iniciando vigilancia")
    captura("C6_dialogo_tras_set_pass")
    contestar_clave(w, "clave-diez-2026")
    w2, _ = esperar_dialogo("P6", esc, previo=w.handle)
    if w2 is not None:
        contestar_clave(w2, "clave-diez-2026")
    ok = esperar(lambda: cifrado(pdf), 30)
    abre = bool(ok) and abre_con(pdf, "clave-diez-2026")
    checks = {
        "set-pass OK": r1 == "OK" and r2 == "OK",
        "diálogo sigue abierto": sigue,
        "mismo PID": pid0 == pid1 and bool(pid0),
        "sin nuevo «Iniciando vigilancia»": inicios0 == inicios1,
        "P6 cifrado con su clave": abre,
    }
    anotar(f"  pid {pid0} -> {pid1}; inicios {inicios0} -> {inicios1}; "
           f"registro: {lineas_desde(marca).strip()}")
    resultado(esc, "ok" if all(checks.values()) else "fallo", str(checks))

    # Contraste: --gui-add SÍ reinicia.
    esc = "C6b"
    time.sleep(2)
    marca = len(registro())
    (once,) = soltar("P6", "once.pdf")
    w, info = esperar_dialogo("P6", esc)
    if w is None:
        resultado(esc, "fallo", "no salió diálogo")
        return
    pid0 = pid_vigilante()
    salida = cli("--gui-add", "SinClave", entrada="clave-sinclave-2026")
    if salida.startswith("OK "):
        SINCLAVE[0] = salida[3:]
    cerrado = esperar_cierre(w, 20)
    time.sleep(15)
    pid1 = pid_vigilante()
    extra = buscar_dialogo("P6")
    anotar(f"  contraste: add={salida}; diálogo cerrado={cerrado}; pid {pid0} -> {pid1}; "
           f"P6={listar('P6')}; once cifrado={cifrado(once)}; ¿otro diálogo? {extra is not None}")
    anotar(f"  registro: {lineas_desde(marca).strip()}")
    captura("C6b_tras_gui_add")
    if extra is not None:
        cerrar_restos("P6")
    estado = ("cifrado" if cifrado(once) else
              "marcado SIN-CIFRAR_" if (ESCRITORIO / "P6" / "SIN-CIFRAR_once.pdf").exists()
              else "en claro sin marcar" if once.exists() else "desaparecido")
    resultado(esc, "ok" if cerrado and pid0 != pid1 else "fallo",
              f"reinicio={pid0 != pid1}, diálogo cerrado={cerrado}, once.pdf: {estado}")


def ventana() -> None:
    esc = "C7"
    from pywinauto import Desktop, mouse
    # Fija vuelve a fija con clave (paso a fija, barrido) para el arrastre.
    cli("--gui-set-pass", "fija", "--modo", "fija", entrada=CLAVE_FIJA)
    # SinClave: se le borra la credencial.
    from cifrarpdf import secreto
    secreto.borrar(SINCLAVE[0])
    anotar(f"  credencial de {SINCLAVE[0]} borrada; tiene_clave={secreto.tiene_clave(SINCLAVE[0])}")
    cli("--gui-add", "Noexiste", entrada="clave-noexiste-2026")
    time.sleep(3)
    gui = subprocess.Popen([str(DIST / "CifrarPDF.exe")])
    w = esperar(lambda: Desktop(backend="uia").window(title="Cifrar PDF — FISAT")
                .wrapper_object(), 40)
    if not w:
        resultado(esc, "fallo", "la ventana no apareció")
        return
    time.sleep(3)
    # Quita la carpeta del disco con el vigilante en marcha.
    try:
        shutil.rmtree(ESCRITORIO / "Noexiste")
        anotar("  Noexiste borrada del disco")
    except OSError as error:
        anotar(f"  no se pudo borrar Noexiste: {error!r}")
    time.sleep(3)
    ctypes.windll.user32.MoveWindow(w.handle, 10, 0, 1000, 715, True)
    time.sleep(1.5)
    w.set_focus()
    captura("C7_ventana_estados")
    filas = [i.window_text() for i in w.descendants(control_type="ListItem")]
    textos = [t.window_text() for t in w.descendants(control_type="Text") if t.window_text()]
    anotar(f"  filas (accesible): {filas}")
    anotar(f"  textos: {textos}")
    chips = {
        "accesible coherente": any("sin contraseña" in f for f in filas)
        and any("pregunta la contraseña cada vez" in f for f in filas)
        and any("carpeta no encontrada" in f for f in filas)
        and any(f.endswith(", lista") for f in filas),
    }
    resultado(esc, "ok (mirar captura)" if all(chips.values()) else "parcial", str(chips))

    # C8: arrastre real desde el Explorador.
    esc = "C8"
    origen = ORIGEN / "arrastre"
    fuente = hacer_pdf(origen / "arrastrado.pdf")
    subprocess.Popen(["explorer.exe", str(origen)])
    def _explorador():
        for v in Desktop(backend="uia").windows():
            if v.class_name() == "CabinetWClass":
                return v
        return None
    exp = esperar(_explorador, 30)
    if not exp:
        anotar("  ventanas: " + str([(v.window_text(), v.class_name())
                                     for v in Desktop(backend="uia").windows()]))
        captura("C8_sin_explorador")
        resultado(esc, "no_verificable", "no se abrió la ventana del Explorador")
        return
    user32 = ctypes.windll.user32
    user32.ShowWindow(exp.handle, 9)
    user32.MoveWindow(exp.handle, 0, 0, 480, 650, True)
    user32.MoveWindow(w.handle, 490, 0, 530, 700, True)
    time.sleep(2)
    w.set_focus()
    exp.set_focus()
    time.sleep(1)
    item = esperar(lambda: [i for i in exp.descendants(control_type="ListItem")
                            if i.window_text().startswith("arrastrado")], 15)
    destino_fila = [i for i in w.descendants(control_type="ListItem")
                    if i.window_text().startswith("Fija")]
    captura("C8_antes_arrastre")
    if not item or not destino_fila:
        resultado(esc, "no_verificable",
                  f"no encuentro el elemento (item={bool(item)}, fila={bool(destino_fila)})")
        return
    ri = item[0].rectangle()
    rf = destino_fila[0].rectangle()
    a = (ri.left + 30, (ri.top + ri.bottom) // 2)
    b = ((rf.left + rf.right) // 2, (rf.top + rf.bottom) // 2)
    anotar(f"  arrastre {a} -> {b}")
    mouse.press(coords=a)
    time.sleep(0.3)
    for i in range(1, 26):
        x = a[0] + (b[0] - a[0]) * i // 25
        y = a[1] + (b[1] - a[1]) * i // 25
        mouse.move(coords=(x, y))
        time.sleep(0.05)
    time.sleep(0.5)
    captura("C8_durante_arrastre")
    mouse.release(coords=b)
    time.sleep(0.8)
    captura("C8_tras_soltar")
    copia = ESCRITORIO / "Fija" / "arrastrado.pdf"
    llego = esperar(lambda: copia.exists(), 15)
    estado_barra = [t.window_text() for t in w.descendants(control_type="Text")
                    if "Copiado" in t.window_text()]
    ok = esperar(lambda: cifrado(copia), 40)
    abre = bool(ok) and abre_con(copia, CLAVE_FIJA)
    original = not cifrado(fuente)
    anotar(f"  barra de estado: {estado_barra}")
    resultado(esc, "ok" if llego and ok and abre and original else "fallo",
              f"copiado={bool(llego)}, barra={estado_barra}, cifrado={bool(ok)}, "
              f"abre con la clave de Fija={abre}, original intacto={original}")

    # Banda de «detenido».
    cli("--parar")
    time.sleep(6)
    w.set_focus()
    captura("C9_ventana_detenido")
    textos = [t.window_text() for t in w.descendants(control_type="Text") if t.window_text()]
    anotar(f"  textos con el vigilante parado: {textos}")
    resultado("C9 banda detenido", "ok" if any("detenido" in t.lower() for t in textos)
              else "parcial", f"textos={textos}")
    gui.terminate()


def real_sin_arnes() -> None:
    """C10: lo que vería una trabajadora. Sin el arnés, añadir una carpeta
    con el vigilante en marcha: ¿se vigila la carpeta nueva?"""
    esc = "C10"
    cli("--gui-asegurar")
    esperar(lambda: pid_vigilante(), 30)
    time.sleep(4)
    soltar_evento()
    pid0 = pid_vigilante()
    inicios0 = contar("Iniciando vigilancia")
    t = time.monotonic()
    salida = cli("--gui-add", "Nueva", entrada="clave-nueva-2026")
    dur = time.monotonic() - t
    time.sleep(3)
    pid1 = pid_vigilante()
    (pdf,) = soltar("Nueva", "nuevo.pdf")
    ok = esperar(lambda: cifrado(pdf), 25)
    estado = cli("--gui-estado")
    anotar(f"  gui-add tardó {dur:.1f} s; pid {pid0} -> {pid1}; inicios "
           f"{inicios0} -> {contar('Iniciando vigilancia')}; estado={estado}; "
           f"nuevo.pdf cifrado={bool(ok)}")
    resultado(esc, "ok" if ok else "fallo",
              f"add={salida}, tardó {dur:.1f} s, mismo vigilante={pid0 == pid1}, "
              f"--gui-estado={estado}, PDF en la carpeta nueva cifrado={bool(ok)}")
    sujetar_evento()


def conjunto(dist: str) -> int:
    global DIST
    DIST = Path(dist).resolve()
    preparar()
    for fn in (c1, c2, c3, c4, c6, ventana, real_sin_arnes):
        try:
            fn()
        except Exception:  # noqa: BLE001
            anotar(traceback.format_exc())
            resultado(fn.__name__, "error del conductor", traceback.format_exc(limit=1))
            captura(f"error_{fn.__name__}")
    try:
        cli("--parar")
    finally:
        try:
            shutil.copy(LOG, SALIDA / "cifrar-pdf.log")
        except OSError:
            pass
    anotar("\n==== RESUMEN ====")
    for esc, estado, detalle in RESULTADOS:
        anotar(f"{esc:28s} {estado:10s} {detalle}")
    anotar(f"diálogos vistos: {len(DIALOGOS)}")
    return 0


def sonda() -> int:
    anotar("== SONDA ==")
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
    app = QApplication(sys.argv)
    anotar(f"isSystemTrayAvailable: {QSystemTrayIcon.isSystemTrayAvailable()}")
    del app
    captura("sonda")
    return 0


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "sonda"
    if modo == "conjunto":
        sys.exit(conjunto(sys.argv[2]))
    sys.exit(sonda())
