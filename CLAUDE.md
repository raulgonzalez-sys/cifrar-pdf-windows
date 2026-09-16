# CLAUDE.md

Guía para Claude Code (claude.ai/code) al trabajar en esta repo.

## Qué es esto

El porte a **Windows 10/11 x64** de la herramienta **Cifrar PDF** de los puestos
Debian 13 + KDE de la **Fundación FISAT Salesianos Social** (fisat.es). Cifra con
contraseña (AES-256) los PDF que se sueltan en carpetas del Escritorio.

La repo de Debian, `debian13-fisat`, es la **referencia de comportamiento**: allí
viven el backend bash canónico (`archivos/fisat-cifrar-pdf`), la GUI canónica
(`archivos/fisat-cifrar-pdf-gui`) y el plan de este porte
(`PLAN_CIFRAR_PDF_WINDOWS.md`). Ante la duda de qué debe hacer algo, se mira allí.

Quienes usan esto son **trabajadoras y trabajadores de la fundación** (técnicos/as,
orientadores/as, coordinadores/as) haciendo inserción sociolaboral, no personal
técnico. Los mensajes se escriben para ellas.

## Convenciones

- **Todo en español**: mensajes, comentarios, docstrings, nombres de funciones y
  variables. Los nombres de la API de Windows y de las librerías se dejan como
  son (`SHGetKnownFolderPath`, `QSystemTrayIcon`).
- **Paridad con Debian antes que mejoras.** Si el bash y esto hacen lo mismo de
  forma distinta sin motivo, es un error. Cuando Windows obliga a hacerlo de otra
  manera (bloqueo de ficheros, credenciales, registro), se hace y **se explica en
  un comentario por qué**.
- **El contrato `--gui-*` es intocable** sin cambiar también el bash. Su forma
  está en `cifrarpdf/cli.py` y en el README; los tests de `tests/test_cli.py`
  existen para que no se rompa por descuido. `herramientas/comparar_con_bash.sh`
  lo comprueba contra el bash de verdad (en Linux, con un checkout de
  debian13-fisat al lado).
- **La contraseña nunca en `argv`.** Siempre por entrada estándar. En un
  argumento sería visible en la lista de procesos.
- **Nada de migraciones.** Igual que en debian13-fisat: instalaciones nuevas. No
  se detecta ni se convierte configuración de versiones anteriores.
- **Perfiles locales, sin itinerancia.** La configuración y las carpetas son de
  ese equipo. Lo que tenga que sobrevivir va a Google Drive.
- **`ruff check .` y `pytest -q` antes de cada commit.**
- **Comentar el «por qué», no el «qué».** Los comentarios de este código valen
  cuando cuentan una trampa ya pisada (por ejemplo: por qué hay dos ejecutables,
  o por qué los `hiddenimports` del `.spec` no son opcionales).

## Trampas ya identificadas (no volver a pisarlas)

1. **Dos ejecutables, no uno.** `CifrarPDF.exe` (sin consola) para ventana y
   vigilante; `CifrarPDF-cli.exe` (con consola) para `--gui-*` y `--parar`. En un
   `.exe` sin consola `sys.stdout` es `None` y `print()` se descarta **sin
   error**: si el backend fuese ese, la ventana no leería nada nunca. Ver
   `cifrarpdf/rutas.py`.
2. **`ctypes` sin prototipos trunca los HANDLE de 64 bits.** Por omisión el valor
   devuelto se trata como `c_int`. Todas las llamadas a la API van por
   `cifrarpdf/_win.py`, que declara `restype`/`argtypes` en un solo sitio.
3. **El código de error hay que leerlo justo después de la llamada.**
   `ctypes.get_last_error()` lo pisa cualquier llamada intermedia; con
   `CreateMutexW` eso es la diferencia entre detectar una instancia duplicada y
   no detectarla.
4. **El Escritorio puede estar redirigido** (OneDrive, Drive para escritorio,
   perfiles de red). Nunca `%USERPROFILE%\Desktop`: siempre
   `SHGetKnownFolderPath`.
5. **`os.replace` falla si el PDF está abierto en un visor** (en Windows el
   bloqueo es real; en Linux no). De ahí los reintentos y el aviso final de
   `cifrarpdf/cifrar.py`. Es la diferencia de comportamiento más visible frente a
   Debian.
6. **Un fichero sin bloquear no está necesariamente completo.** El `open` de
   Python no pide acceso exclusivo, así que solo se detecta a quien escribe si él
   denegó la escritura. La red de seguridad es el tamaño estable durante varias
   lecturas (`LECTURAS_ESTABLES`), y con una sola no basta: en una pausa entre
   ráfagas parecería terminado.
7. **`keyring` y `watchdog` eligen su backend en ejecución**, así que PyInstaller
   no los ve. Van declarados en `hiddenimports` del `.spec`; si faltan, el `.exe`
   se queda sin credenciales o sin vigilancia — funcionando a medias, que es la
   peor forma de fallar. El CI lo comprueba ejecutando el `.exe` construido.
8. **Nada de UPX** en el empaquetado: dispara falsos positivos de antivirus y no
   compensa.
9. **`core.autocrlf` cambia los ficheros al hacer checkout.** En Windows, git
   convierte LF→CRLF por omisión (los runners lo traen activado). Eso hizo
   fallar el primer CI de la repo, y además haría que comparar `gui.py` con la
   copia de Debian marcase **todas** las líneas como distintas sin que nadie
   haya tocado nada. Lo desactiva `.gitattributes` con `* -text`: **no se toca
   ese fichero** sin entender esto.
10. **Parar el vigilante hay que pedirlo varias veces.** Uno recién lanzado tarda
    un par de segundos en tomar el mútex, y en ese hueco `activo()` es False; si
    se da por parado ahí, acaba de arrancar después y queda **huérfano**. Pasó en
    el CI («Terminate orphan process: CifrarPDF»). `parar()` insiste cada 250 ms
    y solo se rinde tras ver el mútex libre varias veces seguidas.
11. **`"$env:ProgramFiles(x86)"` no se expande en PowerShell**: parsea
    `$env:ProgramFiles` y deja `(x86)` como texto. Va con el nombre entre llaves,
    `${env:ProgramFiles(x86)}`. Rompió el paso del instalador en el CI.
12. **El diálogo del modo «preguntar» no puede ser un proceso aparte.** El bash
    de Debian lanza kdialog (o la propia GUI con `--pedir-pass`) y recoge la
    contraseña por la salida estándar del hijo. Aquí eso no vale por la trampa 1
    —en un `.exe` sin consola el `print` se descarta— y además Qt solo construye
    ventanas en el hilo principal. Por eso lo muestra **el propio vigilante** en
    su hilo de Qt: el hilo que cifra encola una `preguntar.Peticion` y espera.
    Consecuencia: **sin bucle de Qt no hay diálogo** (bandeja no disponible,
    `CIFRARPDF_SIN_BANDEJA=1`), y esas carpetas dejan los PDF marcados
    `SIN-CIFRAR_`; queda dicho en el registro al arrancar.
13. **El renombrado a `SIN-CIFRAR_` vuelve por el vigilante.** Mover el fichero
    dentro de la misma carpeta es un evento de watchdog como cualquier otro: si
    no se ignorara ese prefijo (en `_Manejador._quizas`) se preguntaría la
    contraseña en bucle sobre el mismo PDF. Mismo motivo por el que el bucle de
    `inotifywait` del bash los salta.
14. **Tres mentiras de `QIcon` que dejan huecos.** `QIcon.fromTheme()` puede
    devolver un icono **no nulo pero vacío**, así que preguntar con `isNull()`
    no dispara la cadena de alternativas: se pregunta con
    `QIcon.hasThemeIcon()`. `QIcon(ruta)` **nunca** es nulo aunque el fichero
    no se pueda decodificar, porque Qt lo carga en diferido: quien decide es
    el `QPixmap`. Y `QIcon.pixmap()` **no amplía** por encima del tamaño
    natural del fichero y devuelve el pixmap con `devicePixelRatio` 1 — al
    125-150 % de escalado, que es lo normal en Windows, sale borroso. Todo
    icono pasa por `pixmap_nitido()`.
15. **`palette(mid)` no es un color de texto.** Es el rol de sombreado de
    marcos, derivado del fondo: daba unos 2:1 de contraste en la ruta y el
    contador de PDF. Y `lightness() < 128` para decidir si el tema es oscuro
    se equivoca con grises medios. Todo el color va por la capa única de la
    cabecera de `gui.py` (`tema_oscuro()` por luminancias, `semantico()`,
    `escala_fuente()`), y `Ventana.changeEvent` la recalcula al cambiar el
    tema del sistema: si no, los chips se quedan con los colores del tema
    anterior hasta cerrar y reabrir la ventana.
16. **Nada de píxeles fijos para la ventana.** Con 760×520 fijos la barra de
    herramientas no cabía y Qt escondía acciones tras el botón de
    desbordamiento; y al 150 % en un 1366×768 una ventana «generosa» sale más
    alta que el escritorio. `_dimensionar()` calcula en unidades de fuente y
    acota a la pantalla disponible. Por lo mismo, los tamaños de letra son
    relativos: quien sube la fuente del sistema por vista cansada hacía crecer
    todo menos justo los textos que peor se leían.
17. **`QToolBar` crea sus botones con `NoFocus`.** La barra entera quedaba
    fuera del recorrido del Tab, así que sin ratón no se llegaba a ninguna
    acción. Se les pone `TabFocus` a mano al construirla.

## `gui.py` es un fork de la GUI de Debian

`gui.py` **deriva** de `archivos/fisat-cifrar-pdf-gui` de debian13-fisat, pero
**no es el mismo fichero**: allí la interfaz no lleva las ramas `ES_WINDOWS`.
Se valoró unificarlas y se descartó, para no cambiar la interfaz de unos puestos
que están en producción y funcionan solo por acomodar el porte.

Consecuencia asumida: **una mejora de interfaz se hace dos veces**. Al tocar
`gui.py`, dejar dicho en el commit si el cambio debería ir también a Debian (y al
revés). Para ver diferencias:

```bash
python herramientas/comparar_gui.py /ruta/a/debian13-fisat
```

**No copiar el fichero entero de una copia a la otra**: se llevaría por delante
las ramas de plataforma del destino. Detalles en `GUI_SYNC.md`.

## Qué NO se puede verificar en CI

El CI de `windows-latest` cubre el backend de verdad (credenciales, registro,
cifrado, el `.exe` construido) y que la ventana se construye sin pantalla. **No
cubre** nada visual ni de sesión real: iconos, notificaciones del área de
notificación, autoarranque al iniciar sesión, el aviso de SmartScreen, ni el
antivirus corporativo. Todo eso se comprueba a mano en un equipo (ver la fase 5
del plan en debian13-fisat) y así hay que decirlo al informar: «pasa el CI» no
es «probado en un puesto».
