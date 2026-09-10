# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de CifrarPDF.exe con PyInstaller.

Se genera en modo **one-dir** (una carpeta con el .exe y sus dependencias), no
one-file, a propósito: el one-file se descomprime en %TEMP% en cada arranque y
tarda 1-2 s, y la ventana llama al backend (este mismo .exe) en cada refresco de
la lista. Con one-dir el arranque es de décimas. El instalador de Inno Setup ya
reparte una carpeta, así que no se pierde nada.

    pyinstaller empaquetar/CifrarPDF.spec --noconfirm

Los «hiddenimports» no son opcionales: keyring elige su backend en tiempo de
ejecución y watchdog importa el observador según el sistema, así que el análisis
estático de PyInstaller no los ve y sin declararlos el .exe se queda sin
credenciales o sin vigilancia — funcionando a medias, que es la peor forma de
fallar.
"""

import os

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(RAIZ, "arranque.py")],
    pathex=[RAIZ],
    binaries=[],
    datas=[
        (os.path.join(RAIZ, "recursos", "cifrarpdf.png"), "recursos"),
        (os.path.join(RAIZ, "recursos", "cifrarpdf.ico"), "recursos"),
    ],
    hiddenimports=[
        "gui",
        "keyring.backends.Windows",
        "keyring.backends.chainer",
        "keyring.backends.fail",
        "keyring.backends.null",
        "watchdog.observers.read_directory_changes",
        "watchdog.observers.polling",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# DOS ejecutables del mismo código, y hacen falta los dos (ver cifrarpdf/rutas.py):
#
#   CifrarPDF.exe      sin consola → ventana de gestión y vigilante en la bandeja
#   CifrarPDF-cli.exe  con consola → subcomandos --gui-*, que la ventana lee por
#                                    la SALIDA ESTÁNDAR. En un .exe sin consola
#                                    sys.stdout es None y lo impreso se pierde en
#                                    silencio, así que el backend no puede ser el
#                                    otro. Se lanza con CREATE_NO_WINDOW: no
#                                    aparece ninguna ventana negra.

comun = dict(
    debug=False,
    strip=False,
    upx=False,  # UPX dispara falsos positivos de antivirus: no compensa
    icon=os.path.join(RAIZ, "recursos", "cifrarpdf.ico"),
    version=os.path.join(RAIZ, "empaquetar", "version.txt"),
)

exe_ventana = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="CifrarPDF", console=False, **comun,
)

exe_consola = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="CifrarPDF-cli", console=True, **comun,
)

coleccion = COLLECT(
    exe_ventana,
    exe_consola,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CifrarPDF",
)
