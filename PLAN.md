# Plan: portar «Cifrar PDF» a Windows

Documento de trabajo del porte de **Cifrar PDF** (de los puestos Debian 13 + KDE)
a Windows. No es código: es el guion de lo que había que hacer, las decisiones
tomadas y por qué, y las trampas encontradas. Se conserva como registro: cuando
alguien se pregunte «¿por qué esto está hecho así?», la respuesta suele estar
aquí.

Fecha: 2026-09-10 · Estado: **fases 0 a 4 hechas y el código ya vive en su repo**
(`raulgonzalez-sys/cifrar-pdf-windows`, privada). Falta la fase 5: **probarlo en
un Windows de verdad** — ver «Estado de ejecución» justo debajo.

---

## 0. Decisiones ya tomadas

| Decisión | Elegido | Consecuencia principal |
|---|---|---|
| Dónde vive el código | **Repo nueva** (`cifrar-pdf-windows`) | `debian13-fisat` sigue siendo 100 % bash/Debian. La GUI queda **duplicada** entre repos → hace falta regla de sincronía explícita (§9) |
| Distribución | **Instalador Inno Setup** (`CifrarPDF-Setup.exe`, requiere admin) | Instalación por equipo con contraseña de admin; el **uso sigue siendo opt-in por trabajador/a**, igual que en Linux |
| Motor de cifrado | **pikepdf** (qpdf embebido, AES-256 `R=6`) | Un solo binario que repartir; la contraseña **nunca** pasa por línea de comandos ni por argfile en disco |
| Interfaz | **Fork** de la GUI de Debian, con ramas de plataforma | Se intentó que fuera el MISMO fichero en las dos repos y **se descartó**: exigía cambiar la interfaz de unos puestos en producción solo para acomodar el porte. Coste asumido: una mejora de interfaz se hace dos veces (ver §9) |
| Sistemas objetivo | **Windows 10 y 11, x64** | Es justo el mínimo que pide PyQt6, así que no condiciona nada. Nada de 32 bits ni de Windows anteriores |
| Firma de código | **No se firma** | Asumido: SmartScreen avisará la primera vez. Se resuelve con documentación para SAT, no con código (§8.1) |

---

## 0 bis. Estado de ejecución (2026-09-10)

El código está en esta repo, **`raulgonzalez-sys/cifrar-pdf-windows`** (privada,
GPL v3 — que con PyQt6 no es un trámite, es la licencia obligada salvo comprar la
comercial de Riverbank). En debian13-fisat no quedó nada del porte: se decidió
**no tocar aquellos puestos**, así que la interfaz de aquí es un fork de la de
allí (§9).

| Fase | Estado |
|---|---|
| F0 · Andamiaje | **Hecha** — repo creada, `pyproject.toml` con versiones fijadas, CLAUDE.md propio, CI de `windows-latest` |
| F1 · Backend y contrato | **Hecha** — los 8 subcomandos `--gui-*` más `--parar`; 77 tests en verde |
| F2 · Vigilante | **Hecha** — watchdog + hilo cifrador + icono en el área de notificación + mútex/evento + autoarranque |
| F3 · GUI | **Hecha** — la ventana funciona en los dos sistemas con las mismas ramas de plataforma, pero como **fork**: la copia de Debian se dejó intacta (§9) |
| F4 · Empaquetado | **Hecha** — `.spec` de PyInstaller (dos ejecutables), recurso de versión e instalador de Inno Setup |
| F5 · Pruebas en máquina real | **PENDIENTE — no la puedo hacer yo.** Lo que sí cubre ya el CI: los ejecutables se construyen, el `.exe` responde al contrato, **cifra un PDF real** y el instalador compila |
| F6 · Documentación | **Hecha** — README (SAT + trabajador/a + desarrollo), CLAUDE.md, `GUI_SYNC.md` |
| F7 · Piloto | Pendiente, va después de F5 |

**Lo que sí está verificado**, y cómo:

- **77 tests** pasan (config, nombres imposibles de Windows, cifrado real con
  pikepdf, no recifrar, espera de fichero, contrato completo, secretos,
  autoarranque). Corren en 2 s.
- **Paridad de contrato con el bash, comprobada ejecutando los dos**: las nueve
  operaciones comparadas devuelven exactamente lo mismo, **hasta el texto de los
  errores** (`herramientas/comparar_con_bash.sh` lo repite cuando se quiera).
- **La GUI arranca en Linux contra el backend bash real** y lista bien las
  carpetas, así que las ramas de plataforma no rompen el camino de KDE si algún
  día se decide unificar. (Sin iconos en la comprobación porque el contenedor no
  tiene tema Breeze; en un Plasma 6 real sí resuelven.)
- `ruff` limpio, y `shellcheck -S warning` limpio en el script bash nuevo (el CI
  de esta repo escanea toda la carpeta, así que también le afecta).

**Lo que el CI de la repo del porte comprueba ya en Windows de verdad** (corre en
`windows-latest`): construye los dos ejecutables, el `.exe` contesta el contrato
`--gui-*`, da de alta una carpeta guardando la contraseña en el Administrador de
credenciales, **suelta un PDF real y comprueba que queda protegido**, que se abre
con su contraseña con las páginas intactas y que es AES-256, que al dar de baja
el vigilante queda parado (sin procesos huérfanos), y que el instalador compila
(queda descargable como artefacto de la ejecución).

**Lo que NO está verificado y solo se puede ver en un Windows con sesión de
escritorio abierta:** el icono del área de notificación y sus avisos (el CI corre
**sin** bandeja a propósito), el autoarranque al iniciar sesión, el aviso de
SmartScreen, el antivirus corporativo, y el caso del PDF abierto en un visor. Eso
es la F5, y sigue siendo trabajo de una persona delante de un equipo. Para
hacerla no hace falta esperar a una entrega: el instalador se descarga del
artefacto de la última ejecución del CI.

**Dos cosas que aparecieron al implementar** y que no estaban en el plan
original:

1. **Hacen falta DOS ejecutables, no uno.** En un `.exe` sin consola,
   PyInstaller deja `sys.stdout` a `None` y todo lo que se imprima **se descarta
   sin dar error**. Como la ventana habla con el backend leyendo su salida
   estándar, un único ejecutable sin consola habría dejado la ventana ciega —
   fallando en silencio, que es lo peor. Solución: `CifrarPDF.exe` (sin consola)
   para ventana y vigilante, y `CifrarPDF-cli.exe` (con consola, lanzado con
   `CREATE_NO_WINDOW`) para los `--gui-*`.
2. **Una sola lectura de tamaño estable no basta** para dar un PDF por
   terminado: un programa que escriba a ráfagas parecería acabado en la pausa
   entre trozos. Ahora hacen falta dos lecturas seguidas (~2 s sin crecer). Lo
   encontró un test que fallaba de forma intermitente.
3. **Cifrar no puede depender de que haya icono en la bandeja.** El vigilante se
   quedaba montando el área de notificación en una sesión sin escritorio y
   sobrevivía a la petición de parada, quedando huérfano (lo delató el CI:
   «Terminate orphan process: CifrarPDF»). Ahora, si no se puede montar el icono,
   se vigila igual y se deja dicho en el registro: el icono es comodidad, no
   función.
4. **Parar el vigilante hay que pedirlo varias veces.** Uno recién lanzado tarda
   un par de segundos en registrarse y en ese hueco parece que no está; darlo por
   parado ahí lo dejaba huérfano.
5. **`core.autocrlf` de Windows rompía el sello de la GUI**: git convierte
   LF→CRLF al hacer checkout y el `sha256` del fichero en disco deja de cuadrar
   aunque nadie lo haya tocado. Se arregla con `.gitattributes` (`* -text`).

---

## 1. Punto de partida (lo que hay hoy)

Tres piezas en `debian13-fisat`:

- `archivos/fisat-cifrar-pdf` — **backend bash**, 1 189 líneas. Config, KWallet,
  vigilante `inotifywait`, cifrado con `qpdf`, TUI, menú `kdialog`, y los
  subcomandos **`--gui-*`** no interactivos.
- `archivos/fisat-cifrar-pdf-gui` — **frontend PyQt6**, 1 058 líneas. No toca la
  configuración: **todo** lo hace llamando al bash por `--gui-*`, con la
  contraseña por *stdin*.
- `archivos/fisat-cifrar-pdf.desktop` — lanzador de menú.

Buena noticia para el porte: la GUI ya es **casi** agnóstica de plataforma. Solo
dependen de Linux/KDE cinco puntos concretos (§4, bloque GUI). El resto —
`QFileSystemWatcher`, chips claro/oscuro, drag&drop, `QSettings`, contador de
PDF, menú contextual, atajos — funciona igual en Windows sin tocar nada.

El contrato `--gui-*` es la pieza clave del porte: **si el backend Windows lo
respeta al pie de la letra, la GUI casi no se entera de en qué sistema está.**

---

## 2. Alcance

**Entra:**

- Backend equivalente en Python para Windows 10/11 x64, con el **mismo contrato
  `--gui-*`** y el mismo modelo mental (una carpeta = un nombre + una contraseña).
- Vigilante que cifra al soltar, con barrido inicial de lo ya existente.
- Contraseña en el **Administrador de credenciales de Windows** (equivalente a KWallet).
- Autoarranque por sesión de usuario.
- GUI compartida + empaquetado + instalador + documentación para el trabajador/a.

**No entra:**

- Descifrar PDF. La herramienta protege; abrir es cosa del lector de PDF (igual que hoy).
- Migrar nada de instalaciones previas — misma norma que en `debian13-fisat`:
  **solo instalaciones nuevas**.
- Perfiles itinerantes: la configuración y las carpetas son **locales al equipo**,
  sin roaming (misma norma FISAT).
- Sesión de invitado (no existe el concepto en estos puestos Windows).
- macOS.

---

## 3. Arquitectura destino

```
CifrarPDF.exe            (GUI, subsistema Windows)
   │  subprocess ── mismos argumentos --gui-* que hoy, contraseña por stdin
   ▼
CifrarPDF.exe --gui-*    (modo backend: el MISMO exe, dispatch por argumento)
   │
   ├─ config    %APPDATA%\FISAT\CifrarPDF\carpetas.d\<id>.json
   ├─ secreto   Administrador de credenciales (keyring) │ fallback DPAPI
   ├─ cifrado   pikepdf → AES-256 (R=6)
   └─ vigilante CifrarPDF.exe --vigilante  (watchdog + evento con nombre)
                  ▲
                  └── autoarranque: HKCU\...\CurrentVersion\Run
```

Un **único ejecutable** con despacho por argumento (como el bash actual), no dos
binarios: menos superficie, menos que actualizar y el `Exec=` mental sigue siendo
el mismo. Empaquetado **one-dir** (no one-file): el arranque de un one-file
descomprime en `%TEMP%` y tarda 1-2 s, y la GUI llama al backend en cada
refresco. Con one-dir son ~0,2 s, tolerable. Si aun así se nota lag en el
refresco (dos llamadas por evento, con *debounce* de 400 ms), la vía de escape es
que la GUI, **solo cuando corre congelada en Windows**, invoque las mismas
funciones en proceso en vez de por `subprocess` — mismo contrato, sin cambiar la
lógica.

---

## 4. Tabla de equivalencias Linux → Windows

Es el corazón del porte. Cada fila es una decisión ya razonada.

### Backend

| Hoy (Debian/KDE) | En Windows | Notas / por qué |
|---|---|---|
| `qpdf --encrypt … 256` vía argfile `@` | `pikepdf.Pdf.save(encryption=Encryption(user=pw, owner=pw, R=6, aes=True, metadata=True))` | Mismo qpdf por dentro, misma AES-256. **Mejora de seguridad**: al cifrar en proceso desaparece el argfile temporal y la contraseña no toca el disco |
| `qpdf --is-encrypted` (saltar ya cifrados) | `pikepdf.open()` → si lanza `PasswordError` ⇒ ya cifrado; si abre, comprobar `pdf.is_encrypted` | El doble control cubre el caso de PDF cifrado con contraseña de usuario vacía, que abre sin error |
| Verificación post-cifrado con `qpdf --is-encrypted` | Reabrir el temporal y esperar `PasswordError` | Mantener el paso: hoy protege de dejar un PDF «cifrado» que no lo está |
| `inotifywait -m -e create -e moved_to` | `watchdog` (`ReadDirectoryChangesW`) con un observador y varios `schedule()` | Un solo vigilante multi-carpeta, igual que hoy |
| `lsof` (¿alguien sigue escribiendo?) | Intento de apertura exclusiva (`open(p,'rb+')` → `PermissionError`/WinError 32) **+** tamaño estable en dos lecturas | En Windows el bloqueo obligatorio hace esto **más fiable** que `lsof`. El tamaño estable cubre a quien escribe por trozos cerrando entre medias (Chrome, Drive) |
| `mv temp original` | `os.replace()` **con reintentos** | `os.replace` falla si el original está abierto en un visor. Bucle de reintentos con aviso al final; hoy en Linux esto simplemente funciona (§8) |
| `secret-tool` / KWallet | `keyring` → Administrador de credenciales (protegido por DPAPI) | Se desbloquea con el inicio de sesión de Windows, igual que `pam_kwallet5` en FISAT |
| Fallback fichero `600` | Fallback fichero cifrado con **DPAPI** (`CryptProtectData`, ámbito usuario) | Mejor que el plano de Linux: en Windows los permisos de `%APPDATA%` no son equivalentes a un `chmod 600` |
| `.conf` con `printf %q` + `source` | `carpetas.d\<id>.json` | Formato nuevo, sin herencia del truco de bash. Misma estructura de directorio para que el modelo mental coincida |
| `xdg-user-dir DESKTOP` | `SHGetKnownFolderPath(FOLDERID_Desktop)` por `ctypes` | **Nunca** `%USERPROFILE%\Desktop`: el Escritorio puede estar redirigido (OneDrive/Drive) y hay que respetarlo |
| `~/.config/fisat` | `%APPDATA%\FISAT\CifrarPDF` | Config itinerante del perfil; el registro y el PID, en `%LOCALAPPDATA%` |
| Autostart `.desktop` en `~/.config/autostart` | Valor `FISAT-CifrarPDF` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | HKCU = por usuario, así el «uso opt-in por trabajador/a» se conserva tal cual aunque el programa esté instalado para todo el equipo |
| PID file + `kill` por PID | **Mútex con nombre** (`Local\FISAT-CifrarPDF-Vigilante`) para instancia única + **evento con nombre** (`…-Stop`) para pararlo limpio | Evita el clásico de matar un PID reutilizado. `--gui-estado` = ¿existe el mútex? |
| `notify-send` / `kdialog --passivepopup` | Notificación *toast* de Windows | Fase 1: aviso simple + registro. Fase 2 (recomendada): el vigilante como icono en el área de notificación, con menú «Gestionar carpetas / Ver registro / Salir» — resuelve además el «¿está encendido?» mejor que hoy en Linux |
| TUI de consola + menú `kdialog` | **No se portan** | En Windows la GUI está siempre disponible; una TUI sería código muerto. `--lanzar` abre la GUI directamente |
| `iconv //TRANSLIT` para el *slug* | `unicodedata.normalize('NFKD', …)` | Sin dependencias externas |
| ShellCheck | `ruff` + `pytest` | El CI de la repo nueva (§10) |

### GUI (los únicos puntos a tocar)

| Punto | Cambio |
|---|---|
| `BACKEND = "fisat-cifrar-pdf"` (del PATH) | Helper `comando_backend()`: en Windows, el exe propio (`sys.executable`); en Linux, el nombre en el PATH. Es el único punto que decide plataforma |
| `subprocess.Popen(["xdg-open", …])` | `os.startfile(carpeta)` en Windows |
| `QIcon.fromTheme(...)` (tema Breeze) | Windows no trae tema de iconos: fallback a un **juego mínimo empaquetado** y, en último término, a `QStyle.standardIcon`. Revisar licencia de los iconos que se empaqueten (Breeze es LGPL: uso interno correcto, citándolo) |
| `_icono_de_directory()` (`.directory` de KDE) | No-op en Windows en fase 1. Opcional después: leer `IconResource` de `desktop.ini` |
| `_cfg` con `XDG_CONFIG_HOME` | Helper de rutas compartido con el backend |
| Sin cambios | `QFileSystemWatcher`, chips claro/oscuro, contador de PDF, drag&drop, `QSettings`, atajos, menú contextual, elidido de rutas |

---

## 5. Estructura de la repo nueva

```
cifrar-pdf-windows/
├── CLAUDE.md                  # guía propia (español, convenciones, regla de sincronía)
├── README.md                  # instalación para SAT + uso para el trabajador/a
├── PLAN.md                    # este documento, como referencia viva
├── pyproject.toml             # deps pinneadas: PyQt6, pikepdf, watchdog, keyring
├── cifrarpdf/
│   ├── rutas.py               # escritorio(), config_dir(), log(), pid/estado
│   ├── config.py              # alta/baja/renombrado de carpetas (JSON)
│   ├── secreto.py             # keyring + fallback DPAPI
│   ├── cifrar.py              # pikepdf, verificación, reemplazo con reintentos
│   ├── vigilante.py           # watchdog, barrido inicial, espera de archivo, mútex/evento
│   ├── autostart.py           # HKCU Run
│   ├── notificar.py           # toast / bandeja
│   └── cli.py                 # dispatch --gui-*, --vigilante, --lanzar
├── gui.py                     # COPIA SINCRONIZADA de archivos/fisat-cifrar-pdf-gui
├── recursos/                  # .ico, juego mínimo de iconos
├── empaquetar/
│   ├── CifrarPDF.spec         # PyInstaller (one-dir)
│   └── CifrarPDF.iss          # Inno Setup
├── herramientas/
│   └── sincronizar_gui.py     # diff/copia contra un checkout de debian13-fisat
├── tests/
└── .github/workflows/{ci.yml,release.yml}
```

---

## 6. Fases

Cada fase termina con algo verificable. No pasar a la siguiente sin su criterio.

**F0 · Andamiaje** (~0,5 j)
Crear repo privada, estructura, `pyproject.toml` con versiones fijadas, CLAUDE.md
propio, CI vacío que ya pase.
*Hecho cuando:* `ruff` y `pytest` verdes en `windows-latest`.

**F1 · Backend con paridad de contrato** (~1,5 j)
`rutas`, `config`, `secreto`, `cifrar` y el `cli` con los ocho subcomandos
`--gui-*` (`listar`, `estado`, `asegurar`, `add`, `rename`, `set-pass`, `remove`,
`remove-all`), respondiendo `OK [dato]` / `ERR mensaje` con su código de salida y
leyendo la contraseña por *stdin*. Validación mínima de 8 caracteres, igual que hoy.
*Hecho cuando:* tests que cifran un PDF real generado con pikepdf, comprueban que
se salta uno ya cifrado, y que `--gui-listar` da el mismo TSV de 5 campos
(`id, nombre, carpeta, existe, tiene_clave`) que el bash.

**F2 · Vigilante** (~1 j)
watchdog multi-carpeta, barrido inicial, espera de archivo (bloqueo + tamaño
estable), instancia única por mútex, parada limpia por evento, reintentos de
`os.replace`, autoarranque HKCU, registro rotado.
*Hecho cuando:* soltar un PDF en la carpeta lo deja cifrado; soltar 20 de golpe
también; con el PDF abierto en Edge avisa en vez de corromper; cerrar sesión y
volver a entrar arranca solo el vigilante.

**F3 · GUI compartida** (~1 j)
Extraer los cinco puntos de plataforma en la copia de `gui.py`, empaquetar iconos,
y **aplicar el mismo cambio en `debian13-fisat`** para que las dos copias vuelvan a
ser idénticas salvo esas ramas.
*Hecho cuando:* la ventana abre en Windows con iconos, y en Debian sigue
funcionando igual (probado en un equipo real: no hay KDE en CI).

**F4 · Empaquetado e instalador** (~1 j)
PyInstaller one-dir → `CifrarPDF-Setup.exe` con Inno Setup: instala en
`C:\Program Files\FISAT\CifrarPDF`, atajo en el menú Inicio, desinstalador en el
Panel de control, `MinVersion` para rechazar con mensaje claro cualquier Windows
por debajo de 10 x64, y **sin** autoarranque a nivel de máquina (eso lo activa
cada usuario al crear su primera carpeta). Sin firma: el propio setup dispara
SmartScreen la primera vez (§8.1).
*Hecho cuando:* instalar, usar y desinstalar en un Windows limpio no deja
residuos salvo la config del usuario.

**F5 · Pruebas en máquina real** (~1 j)
Checklist manual de §10 en un Windows 10 y un Windows 11 de FISAT, con el
antivirus corporativo activo.

**F6 · Documentación** (~0,5 j)
README para SAT (instalar/desinstalar/problemas, **con los dos pasos de
SmartScreen y el «Desbloquear» documentados con captura** — es lo primero que se
va a encontrar quien instale), hoja de uso para el trabajador/a en el mismo tono
que la Guía del puesto, y regla de sincronía (§9) escrita en los CLAUDE.md de
**las dos** repos.

**F7 · Piloto y despliegue** (1 semana de calendario)
2-3 equipos voluntarios, recogida de incidencias, y solo después el resto.

**Esfuerzo total: ~6-7 jornadas efectivas**, más la semana de piloto.

---

## 7. Contrato `--gui-*` (a respetar literalmente)

```
--gui-listar            → TSV por carpeta: id \t nombre \t carpeta \t existe(0|1) \t tiene_clave(0|1)
--gui-estado            → "1" si el vigilante está activo, "0" si no
--gui-asegurar          → arranca el vigilante si hace falta
--gui-add NOMBRE        → contraseña por stdin; "OK <id>" | "ERR …"
--gui-rename ID NUEVO   → renombra de verdad la carpeta del Escritorio; "OK" | "ERR …"
--gui-set-pass ID       → contraseña por stdin; "OK" | "ERR …"
--gui-remove ID [--borrar-carpeta]
--gui-remove-all [--borrar-carpetas]
```

Reglas que ya asume la GUI y no se pueden cambiar: el nombre no puede contener
`/` (en Windows, ampliar a `\ : * ? " < > |` y a los nombres reservados tipo
`CON`, `NUL`), la contraseña **siempre** por *stdin*, y los mensajes de error
empiezan por `ERR ` porque la GUI recorta ese prefijo.

---

## 8. Riesgos y trampas conocidas

1. **SmartScreen y el aviso de «editor desconocido».** Decidido: **no se firma**,
   así que el aviso es parte del procedimiento, no un fallo. Salta **dos veces** y
   conviene no confundirlas: (a) al ejecutar el `CifrarPDF-Setup.exe` recién
   descargado, con la pantalla azul de «Windows protegió tu PC» → «Más
   información» → «Ejecutar de todas formas»; y (b) si el instalador se copió por
   red o vino en un ZIP, Windows le pone la *marca de la web* y puede seguir
   quejándose → Propiedades del fichero → **Desbloquear**. Ambos pasos van con
   captura en la hoja para SAT (F6). El programa ya instalado no vuelve a
   avisar. Si en el futuro se quisiera quitar el aviso, la vía es un certificado
   OV (~300 €/año) o Azure Trusted Signing, y solo afecta al empaquetado (F4).
2. **Antivirus.** Los ejecutables de PyInstaller dan falsos positivos con cierta
   frecuencia. Probar con el antivirus real de FISAT en F5 y, si hace falta,
   pedir exclusión de la carpeta de instalación.
3. **Escritorio redirigido a la nube.** Si el Escritorio está sincronizado
   (OneDrive o Drive para escritorio), la carpeta de cifrado **se sube a la nube**
   y cada cifrado dispara una resubida. Doble efecto: ruido de sincronización y,
   sobre todo, que el PDF *sin cifrar* puede subirse antes de que el vigilante
   actúe. Mitigación: usar la API de carpeta conocida (ya previsto), avisar en la
   documentación, y valorar ofrecer una ubicación local (`%LOCALAPPDATA%`) como
   alternativa. **Comprobar en F5 cómo están configurados los equipos reales.**
4. **PDF abierto en un visor.** `os.replace` falla si el original está abierto
   (Windows bloquea de verdad, Linux no). Reintentos + aviso claro: «cierra el
   PDF y vuelve a soltarlo». Es el cambio de comportamiento más visible respecto
   a Debian.
5. **Arranque del ejecutable.** Ver §3: one-dir, y la vía de escape en proceso si
   el refresco de la ventana se nota lento.
6. **Credenciales.** El Administrador de credenciales está disponible desde el
   inicio de sesión, así que la espera de ~30 s que el bash hace por KWallet
   probablemente no hace falta; mantener un reintento corto igualmente, por si el
   perfil aún se está montando.
7. **Rutas largas y acentos.** Python 3 maneja Unicode sin problema, pero el
   límite de 260 caracteres sigue existiendo si no está activado el soporte de
   rutas largas. Nombres de carpeta del Escritorio: sin riesgo real; documentado
   por si aparece.
8. **Mínimo Windows 10 x64.** Confirmado que la flota es Windows 10 y 11 de 64
   bits, que es exactamente lo que soporta PyQt6 → riesgo cerrado. El instalador
   debe rechazar con un mensaje claro cualquier cosa por debajo, en vez de
   instalarse y fallar al arrancar (`MinVersion` de Inno Setup).
9. **Duplicidad de la GUI entre repos.** El riesgo real a medio plazo. Ver §9.

---

## 9. La GUI es un fork (decisión revisada)

El plan original era que `gui.py` y `archivos/fisat-cifrar-pdf-gui` de
debian13-fisat fuesen **el mismo fichero**, byte a byte, con lo específico de
cada sistema detrás de `ES_WINDOWS`, y un sello `sha256` comprobado en CI para
que nadie olvidara sincronizar.

**Se descartó al final**: para que fuesen idénticos había que cambiar la
interfaz de los puestos Debian —en producción y funcionando— solo por acomodar
el porte, y el riesgo no lo valía. Aquellos puestos se quedan como estaban.

Así que aquí hay un **fork declarado**, con su coste asumido: **una mejora de
interfaz se hace dos veces.** Para que eso no degenere en dos programas
distintos:

- `herramientas/comparar_gui.py RUTA_A_debian13-fisat` enseña las diferencias
  cuando hay que portar un cambio. **No copia**: copiar el fichero entero
  rompería las ramas de plataforma del destino.
- Al tocar la interfaz, el mensaje del commit dice si el cambio debería ir
  también a la otra copia.
- Lo que **sí** se mantiene idéntico es el contrato `--gui-*` entre los dos
  backends, y eso sí se comprueba ejecutándolos
  (`herramientas/comparar_con_bash.sh`). Es la pieza que de verdad importa: si
  los backends responden igual, las dos interfaces pueden evolucionar sin
  llevarse por delante la lógica.

## 10. Pruebas

**CI (`windows-latest`, gratis y sí existe):** `ruff`, `pytest` del backend
(*slug*, ids únicos, lectura/escritura de config, cifrado real de un PDF,
detección de ya-cifrado, espera de archivo con un fichero bloqueado a propósito),
*smoke test* de la GUI con `QT_QPA_PLATFORM=offscreen`, y build completo
(PyInstaller + Inno Setup vía chocolatey) subiendo el instalador como artefacto.
En un tag `v*`, release con el `CifrarPDF-Setup.exe` adjunto — mismo mecanismo de
distribución que la repo de Debian.

**Manual en máquina real (F5), lo que el CI no puede ver:** primera instalación
como admin; alta de carpeta por un usuario sin privilegios; contraseña en el
Administrador de credenciales; soltar 1 PDF, 20 PDF, un PDF ya cifrado, un PDF
abierto en un visor; renombrar y borrar carpeta; cerrar y abrir sesión
(autoarranque); dos usuarios distintos en el mismo equipo sin verse la
configuración; desinstalar; y comportamiento con el antivirus corporativo activo.

---

## 11. Despliegue

Instalación por equipo con admin (SAT o quien tenga la contraseña local), uso
activado por cada trabajador/a desde el atajo del menú Inicio — misma filosofía
que en Debian: **la herramienta está, la usa quien la necesita.** Hoja de uso
corta, en el tono de la Guía del puesto, con las tres cosas que de verdad importan:
la carpeta cifra lo que se suelta dentro, la contraseña la eliges tú y no se puede
recuperar, y un PDF ya cifrado no se vuelve a cifrar.

---

## 12. Supuestos con los que se arranca

No queda ninguna decisión bloqueando el trabajo. Lo que no se ha fijado
expresamente se cierra así, y se revisa solo si el piloto (F7) lo desmiente:

- **Escritorio en la nube.** Se usa la API de carpeta conocida y se respeta el
  Escritorio que tenga cada equipo, esté redirigido o no. **No** se ofrece una
  ubicación local alternativa en esta primera versión. Queda documentado en la
  hoja del trabajador/a que si su Escritorio se sincroniza, el PDF puede subirse
  a la nube en el instante que va sin cifrar (riesgo 3): es el único punto del
  plan que podría exigir un cambio de diseño más adelante, y el piloto lo dirá.
- **Quién instala.** SAT o quien tenga la contraseña de admin local del equipo,
  a demanda. Sin volumen fijado y sin despliegue masivo: se instala donde haga
  falta, igual que en Debian.
- **Antivirus.** Se asume Defender. Si aparece un falso positivo sobre el
  ejecutable de PyInstaller, la solución es una exclusión de
  `C:\Program Files\FISAT\CifrarPDF`; se comprueba en F5 y solo se documenta si
  llega a pasar.
- **Icono en el área de notificación: sí**, en F2, con menú «Gestionar carpetas /
  Ver registro / Salir». Es la forma más barata de que el vigilante sea visible
  (en Debian no hay manera de saber si está encendido sin abrir la ventana), y
  encima es lo que da los avisos *toast* sin dependencias extra.
- **Registro.** Mismo criterio que en Linux: fichero de texto rotado, con la
  ventana enseñándolo desde el propio menú. Sin telemetría de ningún tipo.
