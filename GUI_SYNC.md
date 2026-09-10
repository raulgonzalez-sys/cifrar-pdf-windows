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

## Qué NO se puede comprobar automáticamente

Nada de esto lo ve el CI: no hay KDE ni sesión de Windows con pantalla. Una
ventana que abre bien en un sistema puede estar rota en el otro, así que un
cambio de interfaz se prueba **a mano en los dos**.
