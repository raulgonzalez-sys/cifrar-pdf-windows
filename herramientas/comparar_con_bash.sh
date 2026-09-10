#!/bin/bash
# Compara la salida del backend BASH de los puestos Debian con la del backend
# PYTHON de Windows, en las mismas operaciones. Deben coincidir hasta el texto
# de los errores: eso es el contrato --gui-* del que depende que la ventana sea
# la misma en los dos sistemas.
#
# Se ejecuta en Linux (es donde corre el bash), con un checkout de debian13-fisat:
#
#     bash herramientas/comparar_con_bash.sh /ruta/a/debian13-fisat
#
# Necesita el intérprete de Python con el paquete instalado («pip install -e .»)
# accesible como «python3», o la variable PYTHON apuntando a él.

set -u

DEBIAN_REPO="${1:-}"
PYTHON="${PYTHON:-python3}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "$DEBIAN_REPO" ] || [ ! -f "$DEBIAN_REPO/archivos/fisat-cifrar-pdf" ]; then
    echo "Uso: bash herramientas/comparar_con_bash.sh /ruta/a/debian13-fisat" >&2
    exit 1
fi

BASH_BIN="$DEBIAN_REPO/archivos/fisat-cifrar-pdf"
TRABAJO="$(mktemp -d)"
trap 'rm -rf "$TRABAJO"' EXIT

correr_bash() {
    local clave="$1"; shift
    rm -rf "$TRABAJO/bash"
    mkdir -p "$TRABAJO/bash/.config" "$TRABAJO/bash/Escritorio"
    printf '%s' "$clave" | HOME="$TRABAJO/bash" XDG_CONFIG_HOME="$TRABAJO/bash/.config" \
        timeout 20 bash "$BASH_BIN" "$@" 2>/dev/null
}

correr_python() {
    local clave="$1"; shift
    rm -rf "$TRABAJO/py"
    mkdir -p "$TRABAJO/py/cfg" "$TRABAJO/py/datos" "$TRABAJO/py/Escritorio"
    printf '%s' "$clave" | ( cd "$RAIZ" && \
        CIFRARPDF_CONFIG_DIR="$TRABAJO/py/cfg" \
        CIFRARPDF_DATOS_DIR="$TRABAJO/py/datos" \
        CIFRARPDF_ESCRITORIO="$TRABAJO/py/Escritorio" \
        timeout 20 "$PYTHON" -m cifrarpdf "$@" 2>/dev/null )
}

fallos=0
comparar() {
    local titulo="$1" clave="$2"; shift 2
    local salida_bash salida_py
    salida_bash=$(correr_bash "$clave" "$@")
    salida_py=$(correr_python "$clave" "$@")
    if [ "$salida_bash" = "$salida_py" ]; then
        printf 'IGUAL     %-32s → %s\n' "$titulo" "$salida_bash"
    else
        printf 'DISTINTO  %-32s\n  bash:   %s\n  python: %s\n' \
            "$titulo" "$salida_bash" "$salida_py"
        fallos=$((fallos + 1))
    fi
}

comparar "alta correcta"          "contraseña-larga" --gui-add "Informes"
comparar "contraseña corta"       "corta"            --gui-add "Informes"
comparar "nombre con barra"       "contraseña-larga" --gui-add "con/barra"
comparar "nombre vacío"           "contraseña-larga" --gui-add ""
comparar "renombrar inexistente"  ""                 --gui-rename "fantasma" "Otro"
comparar "clave de inexistente"   "contraseña-larga" --gui-set-pass "fantasma"
comparar "quitar inexistente"     ""                 --gui-remove "fantasma"
comparar "quitar todas en vacío"  ""                 --gui-remove-all
comparar "listado vacío"          ""                 --gui-listar

echo
if [ "$fallos" -eq 0 ]; then
    echo "Las dos implementaciones responden igual."
else
    echo "$fallos diferencia(s): el contrato --gui-* ha divergido."
    exit 1
fi
