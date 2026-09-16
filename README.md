# Cifrar PDF (FISAT) — Windows 10/11

Cifra con contraseña, automáticamente, los PDF que sueltas en tus carpetas.
Pensado para informes confidenciales que hay que enviar a terceros.

Es el porte a Windows de la herramienta `fisat-cifrar-pdf` de los puestos
Debian 13 + KDE de la Fundación FISAT ([debian13-fisat]). Misma idea, mismo
cifrado (**AES-256**), misma interfaz — pero con las piezas de Windows:
Administrador de credenciales, autoarranque por usuario e instalador.

[debian13-fisat]: https://github.com/raulgonzalez-sys/debian13-fisat

Las decisiones del porte y por qué son así están en **`PLAN.md`**.

---

## Para quien lo usa

1. Abre **Cifrar PDF** en el menú Inicio.
2. **Añadir carpeta**: le pones un nombre y eliges cómo quieres la contraseña
   (ver abajo). Se crea en tu Escritorio.
3. A partir de ahí, **todo PDF que sueltes en esa carpeta se cifra solo**. Sale
   un aviso cuando está hecho.

Tres cosas que conviene tener claras:

- **Cada carpeta tiene su propia contraseña.** Puedes tener varias carpetas con
  contraseñas distintas.
- **La contraseña no se puede recuperar.** No la guarda nadie más que tu propia
  cuenta de Windows, y sin ella el PDF no se abre. Si se pierde, se pierde.
- **Un PDF ya cifrado no se vuelve a cifrar**, así que puedes soltar lo que sea
  sin miedo a cifrarlo dos veces.

### Dos formas de poner la contraseña

Al crear una carpeta —y siempre que pulses **Contraseña**— eliges una de las dos:

- **Usar siempre esta contraseña.** Se guarda una vez en el Administrador de
  credenciales de Windows y se aplica sola a cada PDF que sueltes. Es lo de
  siempre y lo más cómodo para una carpeta de uso diario.
- **Preguntar cada vez que suelte un PDF.** No se guarda ninguna contraseña en
  el equipo: te la pide en el momento de cifrar, dos veces para que no se cuele
  una errata. Si sueltas varios PDF de golpe, te pregunta **una sola vez** y te
  ofrece usar esa contraseña para todos. En la lista, esas carpetas llevan la
  marca «🔑 Pregunta cada vez».

Con «preguntar cada vez», si cierras el diálogo sin escribir nada se te da un
último intento y, si tampoco, **el PDF se queda sin cifrar** y se renombra a
`SIN-CIFRAR_<nombre>.pdf` para que lo veas. No se pierde: la próxima vez que
sueltes un PDF en esa carpeta entra en el lote y recupera su nombre al cifrarse.
Al iniciar sesión no se pregunta nada a propósito.

Si el PDF está **abierto en un visor** cuando lo sueltas, no se puede sustituir
por la versión protegida: la herramienta espera unos segundos y, si sigue
abierto, avisa. Ciérralo y vuelve a soltarlo.

Si tu Escritorio está sincronizado con la nube (OneDrive, Google Drive),
recuerda que el PDF puede subirse en el rato que está sin cifrar. Para
documentación sensible, mejor soltarla ya dentro de la carpeta que dejarla
primero en el Escritorio.

## Para SAT: instalar

Descarga `CifrarPDF-Setup-<versión>.exe` de la **[última entrega](../../releases/latest)**
y ejecútalo **como administrador**. Instala en `C:\Program Files\FISAT\CifrarPDF`
y añade la entrada al menú Inicio.

Ese enlace lleva siempre a la versión más reciente, así que no hay que tocar el
README en cada entrega; el histórico está en [Releases](../../releases).

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
| «No tiene contraseña guardada» | La contraseña se borró del Administrador de credenciales (perfil nuevo, cuenta distinta). En la ventana: *Contraseña*. Ojo: en una carpeta que pregunta cada vez **no** sale este aviso, sale «🔑 Pregunta cada vez» |
| Aparecen ficheros `SIN-CIFRAR_…` | Una carpeta que pregunta cada vez y nadie escribió la contraseña. Ese PDF **sigue sin proteger**: suelta otro PDF en la carpeta y entrará en el mismo lote |
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
pytest -q                          # tests (corren en segundos)
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
| `cifrarpdf/preguntar.py` | Modo «preguntar cada vez»: diálogo, lote en memoria y marcado `SIN-CIFRAR_` |
| `cifrarpdf/proceso.py` | Instancia única (mútex) y parada ordenada (evento con nombre) |
| `cifrarpdf/autostart.py` | Autoarranque por usuario en `HKCU\...\Run` |
| `cifrarpdf/cli.py` | El contrato `--gui-*` — **idéntico al del backend bash de Debian** |
| `gui.py` | La ventana. **Fork** de `archivos/fisat-cifrar-pdf-gui` de debian13-fisat: los cambios se portan a mano (ver `GUI_SYNC.md`) |

El contrato `--gui-*` y su salida (`OK [dato]` / `ERR mensaje`, contraseña por
entrada estándar) son lo que permite que la ventana sea prácticamente la misma en
los dos sistemas sin duplicar la lógica. Cambiarlo aquí obliga a cambiarlo
también en el bash de Debian; `herramientas/comparar_con_bash.sh` comprueba que
las dos implementaciones siguen respondiendo igual.

## Licencia

**GPL v3 o posterior** (ver `LICENSE`), y no es un detalle administrativo: PyQt6
se distribuye bajo GPL v3 **o** licencia comercial de Riverbank, así que
cualquier programa que la use y se reparta —aunque sea solo dentro de FISAT—
tiene que ser GPL v3 salvo que se compre esa licencia comercial. La elección es
la correcta.

El resto de dependencias es compatible: pikepdf (MPL-2.0, con qpdf dentro, que
es Apache-2.0), watchdog (Apache-2.0) y keyring (MIT).
