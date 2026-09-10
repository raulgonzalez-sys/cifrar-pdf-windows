# Cifrar PDF (FISAT) — Windows 10/11

Cifra con contraseña, automáticamente, los PDF que sueltas en tus carpetas.
Pensado para informes confidenciales que hay que enviar a terceros.

Es el porte a Windows de la herramienta `fisat-cifrar-pdf` de los puestos
Debian 13 + KDE de la Fundación FISAT ([debian13-fisat]). Misma idea, mismo
cifrado (**AES-256**), misma interfaz — pero con las piezas de Windows:
Administrador de credenciales, autoarranque por usuario e instalador.

[debian13-fisat]: https://github.com/raulgonzalez-sys/debian13-fisat

---

## Para quien lo usa

1. Abre **Cifrar PDF** en el menú Inicio.
2. **Añadir carpeta**: le pones un nombre y una contraseña. Se crea en tu
   Escritorio.
3. A partir de ahí, **todo PDF que sueltes en esa carpeta se cifra solo**, con la
   contraseña de esa carpeta. Sale un aviso cuando está hecho.

Tres cosas que conviene tener claras:

- **Cada carpeta tiene su propia contraseña.** Puedes tener varias carpetas con
  contraseñas distintas.
- **La contraseña no se puede recuperar.** No la guarda nadie más que tu propia
  cuenta de Windows, y sin ella el PDF no se abre. Si se pierde, se pierde.
- **Un PDF ya cifrado no se vuelve a cifrar**, así que puedes soltar lo que sea
  sin miedo a cifrarlo dos veces.

Si el PDF está **abierto en un visor** cuando lo sueltas, no se puede sustituir
por la versión protegida: la herramienta espera unos segundos y, si sigue
abierto, avisa. Ciérralo y vuelve a soltarlo.

Si tu Escritorio está sincronizado con la nube (OneDrive, Google Drive),
recuerda que el PDF puede subirse en el rato que está sin cifrar. Para
documentación sensible, mejor soltarla ya dentro de la carpeta que dejarla
primero en el Escritorio.

## Para SAT: instalar

Descarga `CifrarPDF-Setup-<versión>.exe` de la última entrega
([Releases](../../releases)) y ejecútalo **como administrador**. Instala en
`C:\Program Files\FISAT\CifrarPDF` y añade la entrada al menú Inicio.

**El ejecutable no está firmado**, así que Windows avisará. Es esperado:

1. Pantalla azul de **«Windows protegió tu PC»** → *Más información* →
   *Ejecutar de todas formas*.
2. Si el instalador llegó por carpeta de red, por correo o dentro de un ZIP,
   Windows le pone la *marca de la web* y puede seguir quejándose: clic derecho
   en el fichero → *Propiedades* → marcar **Desbloquear** → *Aceptar*.

Una vez instalado, el programa no vuelve a avisar.

Requisitos: Windows 10 o 11 de **64 bits**. El instalador rechaza versiones
anteriores con un mensaje claro en lugar de instalarse y fallar después.

### Qué hace y qué no hace al instalarse

- **No arranca nada por su cuenta.** El vigilante se registra en el autoarranque
  **de cada usuario** (`HKCU\...\CurrentVersion\Run`) cuando esa persona crea su
  primera carpeta. Quien no lo use no tiene nada corriendo.
- **No toca el cortafuegos, ni servicios, ni nada del sistema.** Solo copia
  ficheros a Program Files.
- **No manda nada a ninguna parte.** Sin telemetría, sin red: el cifrado es
  local.

### Desinstalar

Panel de control → *Programas* → **Cifrar PDF (FISAT)**. Detiene el vigilante y
borra los ficheros del programa.

**No borra** las carpetas del Escritorio, ni la configuración
(`%APPDATA%\FISAT\CifrarPDF`), ni las contraseñas del Administrador de
credenciales. Es deliberado: son datos de la persona. Para dejarlo todo limpio,
antes de desinstalar se usa **«Quitar todas las carpetas»** en la ventana.

### Si algo va mal

| Síntoma | Qué mirar |
|---|---|
| Los PDF no se cifran | ¿Está el vigilante en marcha? En la ventana, el punto de la esquina inferior derecha: verde = activo. También el icono junto al reloj |
| «No tiene contraseña guardada» | La contraseña se borró del Administrador de credenciales (perfil nuevo, cuenta distinta). En la ventana: *Cambiar contraseña* |
| Nada aparece en el registro | *Ver registro* en la ventana, o `%LOCALAPPDATA%\FISAT\CifrarPDF\cifrar-pdf.log` |
| El antivirus bloquea el .exe | Falso positivo típico de los ejecutables empaquetados con PyInstaller. Excluir `C:\Program Files\FISAT\CifrarPDF` |
| El PDF sigue sin cifrar tras soltarlo | Suele estar abierto en un visor. Ciérralo y vuelve a soltarlo |

## Para quien lo desarrolla

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

python -m cifrarpdf --ayuda        # backend
python gui.py                      # ventana
pytest -q                          # tests (77, corren en segundos)
ruff check .                       # lint

pyinstaller empaquetar\CifrarPDF.spec --noconfirm    # → dist\CifrarPDF\
iscc empaquetar\CifrarPDF.iss                        # → salida\CifrarPDF-Setup-*.exe
```

Se puede desarrollar en Linux (los tests pasan), pero **lo que se prueba en
Linux no vale como verificación**: el registro, DPAPI, el Administrador de
credenciales, los mútex con nombre y el bloqueo de ficheros son ramas de
Windows. El CI corre en `windows-latest` justamente por eso.

### Cómo está montado

```
CifrarPDF.exe          sin consola  → ventana de gestión y vigilante (bandeja)
CifrarPDF-cli.exe      con consola  → subcomandos --gui-* y --parar
```

Dos ejecutables del mismo código, y hacen falta los dos: en un `.exe` sin
consola `sys.stdout` es `None` y lo que se imprima se pierde **en silencio**;
como la ventana habla con el backend leyendo su salida estándar, el backend
tiene que ser el de consola (que se lanza con `CREATE_NO_WINDOW`, así que no
asoma ninguna ventana negra).

| Módulo | De qué se ocupa |
|---|---|
| `cifrarpdf/rutas.py` | Configuración, registro y Escritorio (por API de carpeta conocida: puede estar redirigido) |
| `cifrarpdf/config.py` | Carpetas configuradas (un JSON por carpeta), nombres válidos, identificadores |
| `cifrarpdf/secreto.py` | Contraseña en el Administrador de credenciales; de reserva, fichero cifrado con DPAPI |
| `cifrarpdf/cifrar.py` | Cifrado con pikepdf (AES-256, `R=6`), verificación y reemplazo con reintentos |
| `cifrarpdf/espera.py` | Esperar a que el PDF esté completo (bloqueo + tamaño estable) |
| `cifrarpdf/vigilante.py` | watchdog + hilo cifrador + icono en la bandeja |
| `cifrarpdf/proceso.py` | Instancia única (mútex) y parada ordenada (evento con nombre) |
| `cifrarpdf/autostart.py` | Autoarranque por usuario en `HKCU\...\Run` |
| `cifrarpdf/cli.py` | El contrato `--gui-*` — **idéntico al del backend bash de Debian** |
| `gui.py` | La ventana. **Copia sincronizada** de `archivos/fisat-cifrar-pdf-gui` (ver `GUI_SYNC.md`) |

El contrato `--gui-*` y su salida (`OK [dato]` / `ERR mensaje`, contraseña por
entrada estándar) son lo que hace que la ventana sea la misma en los dos
sistemas. Cambiarlo aquí obliga a cambiarlo también en el bash de Debian.

## Licencia

**GPL v3 o posterior** (ver `LICENSE`), y no es un detalle administrativo: PyQt6
se distribuye bajo GPL v3 **o** licencia comercial de Riverbank, así que
cualquier programa que la use y se reparta —aunque sea solo dentro de FISAT—
tiene que ser GPL v3 salvo que se compre esa licencia comercial. La elección es
la correcta.

El resto de dependencias es compatible: pikepdf (MPL-2.0, con qpdf dentro, que
es Apache-2.0), watchdog (Apache-2.0) y keyring (MIT).
