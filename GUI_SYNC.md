# Sincronía de `gui.py`

`gui.py` de esta repo y `archivos/fisat-cifrar-pdf-gui` de **debian13-fisat**
son el **mismo fichero**: byte a byte idénticos. Todo lo que depende del sistema
está detrás de `ES_WINDOWS` (cómo se localiza el backend, abrir la carpeta,
iconos, rutas de configuración), así que una sola copia sirve para KDE y para
Windows.

Por qué duplicado y no importado: son dos repos separadas, sin dependencia entre
ellas. Es la misma duplicidad consciente que ya existe en debian13-fisat (los
heredocs de `instalar-cifrar-pdf.sh`, el `CRT_B64` de
`rotar_certificado_flota.sh`) y se mantiene igual: **a mano, con red de
seguridad.**

## Cómo se mantiene

El sello de más abajo es el `sha256` del `gui.py` que está sincronizado. El CI
ejecuta `--comprobar-sello` en cada push: si `gui.py` cambia y el sello no, la
comprobación falla. No es un candado técnico (nada impide resellar sin tocar la
otra repo), es un **recordatorio que no se puede ignorar sin verlo**.

Al cambiar la interfaz:

```bash
# 1. Se edita gui.py aquí (o el fichero canónico allí, da igual cuál)
# 2. Se propaga a la otra copia
python herramientas/sincronizar_gui.py --llevar /ruta/a/debian13-fisat
#    (o --traer si la buena es la de allí; --diff para ver diferencias)
# 3. Se comprueba
python herramientas/sincronizar_gui.py --comprobar-sello
# 4. Commit en LAS DOS repos
```

Y hay que probarlo en los dos sistemas: no hay KDE ni Windows con pantalla en
CI, así que una ventana que abre en uno puede quedar rota en el otro.

sha256 = 6994e4b77dce9095ea80549d55f3f48b5be8391b842c80be729f0166c9b76c60