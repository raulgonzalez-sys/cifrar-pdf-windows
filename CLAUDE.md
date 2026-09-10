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
  existen para que no se rompa por descuido.
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

## Sincronía de `gui.py` con debian13-fisat

`gui.py` es **byte a byte idéntico** a `archivos/fisat-cifrar-pdf-gui` de
debian13-fisat; lo específico de cada sistema va detrás de `ES_WINDOWS`. Al
tocarlo hay que propagarlo a la otra repo y resellar:

```bash
python herramientas/sincronizar_gui.py --llevar /ruta/a/debian13-fisat
python herramientas/sincronizar_gui.py --comprobar-sello
```

El CI falla si `gui.py` cambia sin resellar. Detalles en `GUI_SYNC.md`.

## Qué NO se puede verificar en CI

El CI de `windows-latest` cubre el backend de verdad (credenciales, registro,
cifrado, el `.exe` construido) y que la ventana se construye sin pantalla. **No
cubre** nada visual ni de sesión real: iconos, notificaciones del área de
notificación, autoarranque al iniciar sesión, el aviso de SmartScreen, ni el
antivirus corporativo. Todo eso se comprueba a mano en un equipo (ver la fase 5
del plan en debian13-fisat) y así hay que decirlo al informar: «pasa el CI» no
es «probado en un puesto».
