# `gui.py` frente a la GUI de Debian: es un FORK

`gui.py` **deriva** de `archivos/fisat-cifrar-pdf-gui` de la repo
**debian13-fisat**, pero **no son el mismo fichero**: allí la interfaz sigue
siendo la de KDE, sin las ramas `ES_WINDOWS` que necesita Windows (localización
del backend, abrir carpeta, iconos estándar de Qt donde no hay tema, rutas de
configuración, fuente monoespaciada del registro).

Se intentó que fueran idénticas y **se descartó a propósito**: habría exigido
cambiar la interfaz de los puestos Debian —que funcionan y están en producción—
solo para acomodar el porte. No compensaba.

Consecuencia asumida: **una mejora de interfaz hay que hacerla dos veces**, aquí
y allí. Es el precio de no tocar lo que funciona.

## Cómo portar un cambio de una a otra

```bash
# Ver en qué se diferencian (ignora las ramas de plataforma esperadas)
python herramientas/comparar_gui.py /ruta/a/debian13-fisat
```

Después se aplica el cambio a mano en la otra copia. **No se copia el fichero
entero de un lado a otro**: se llevaría por delante las ramas de plataforma del
destino y rompería esa versión.

Al tocar la interfaz, conviene dejar dicho en el mensaje del commit si el cambio
también debería ir a la otra copia, para que quien lo lea después no tenga que
adivinarlo.

## Lo que está en la copia de Debian y aquí NO

Los **tres diálogos sueltos**: `--pedir-pass`, `--avisar` y `--preguntar` (con
`modo_pedir_pass()`, `modo_mensaje()` y `_app_suelta()`). Allí sirven para que
el vigilante bash pueda pedir la contraseña o avisar cuando no hay kdialog ni
zenity instalados: lanza la GUI como proceso hijo y lee la respuesta de su
salida estándar o de su código de salida.

Aquí ese camino no existe a propósito. En un `.exe` sin consola la salida
estándar no llega a ninguna parte (trampa 1 de `CLAUDE.md`), así que el
vigilante muestra los tres diálogos **él mismo**, en su propio hilo de Qt — ver
`cifrarpdf/preguntar.py` y `vigilante._bucle_con_bandeja`. Añadir esos modos a
`gui.py` sería código que nadie llama.

Consecuencia agradable: el fallo que arregló el commit de Debian del 14/09 —en
un equipo con PyQt6 pero sin kdialog ni zenity, los avisos de «las contraseñas
no coincidían» no llegaban a verse y la oferta de lote no salía nunca— **aquí
nunca pudo darse**, porque los tres diálogos siempre han ido por el mismo
camino. Lo que sí se portó es todo lo demás de ese commit: los textos que dicen
la verdad, el recorte de nombres largos y las causas distinguidas.

## Lo que hay aquí y en Debian NO

`_identificar_en_barra_de_tareas()`: el equivalente Windows del WM_CLASS que
allí se fija con `setDesktopFileName`. Windows no tiene `.desktop`, así que se
declara un identificador de modelo de aplicación
(`SetCurrentProcessExplicitAppUserModelID`) para que la ventana se agrupe con
su acceso directo en la barra de tareas.

Y el respaldo de iconos: en Debian, un nombre que no esté en el tema cae al
logo de la fundación; aquí cae a los iconos estándar de Qt (`_ESTANDAR`) y, si
tampoco hay, **se queda sin icono a propósito** — la barra muestra siempre el
texto de la acción, y eso es mejor que colar un icono que no pega. El logo solo
es el suelo del icono de carpeta, que es donde un hueco descuadraría la fila.

## Qué NO se puede comprobar automáticamente

Nada de esto lo ve el CI: no hay KDE ni sesión de Windows con pantalla. Una
ventana que abre bien en un sistema puede estar rota en el otro, así que un
cambio de interfaz se prueba **a mano en los dos**.
