#!/usr/bin/env bash
# Construye Victoria II Mod Studio para Linux (PyInstaller, one-folder) y lo comprime.
#
# Uso: packaging/build_linux.sh [--system] [--install]
#   --system   usa el Python actual (debe tener PyInstaller y las dependencias)
#              en vez de crear el entorno virtual build/venv-linux (requiere red).
#   --install  instala el resultado para el usuario actual: ~/.local/opt/vic2studio,
#              enlace ~/.local/bin/vic2studio y lanzador en el menú de aplicaciones.
# Variable PYTHON: intérprete base (por defecto python3, 3.10 o superior).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
USE_SYSTEM=0
INSTALL=0

for arg in "$@"; do
    case "$arg" in
        --system) USE_SYSTEM=1 ;;
        --install) INSTALL=1 ;;
        -h | --help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

cd "$ROOT"

if [[ $USE_SYSTEM -eq 1 ]]; then
    PY="$PYTHON"
else
    VENV="$ROOT/build/venv-linux"
    [[ -x "$VENV/bin/python" ]] || "$PYTHON" -m venv "$VENV"
    PY="$VENV/bin/python"
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r "$ROOT/requirements.txt" "pyinstaller>=6.0"
fi

if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller no está disponible en $PY (instálalo o ejecuta sin --system)." >&2
    exit 1
fi

export PYTHONPATH="$ROOT/src"
VERSION="$("$PY" -c 'import vic2studio; print(vic2studio.__version__)')"
APP_NAME="$("$PY" -c 'import vic2studio; print(vic2studio.APP_NAME)')"

"$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$ROOT/dist" \
    --workpath "$ROOT/build/pyinstaller" \
    "$ROOT/packaging/vic2studio.spec"

APP_DIR="$ROOT/dist/$APP_NAME"
cp "$ROOT/packaging/linux/vic2studio.desktop" "$APP_DIR/"
ARCHIVE="$ROOT/dist/vic2studio-$VERSION-linux-$(uname -m).tar.gz"
tar -C "$ROOT/dist" -czf "$ARCHIVE" "$APP_NAME"
echo "Aplicación: $APP_DIR"
echo "Archivo:    $ARCHIVE"

if [[ $INSTALL -eq 1 ]]; then
    OPT_DIR="$HOME/.local/opt/vic2studio"
    BIN_LINK="$HOME/.local/bin/vic2studio"
    APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    rm -rf -- "$OPT_DIR"
    mkdir -p -- "$(dirname -- "$OPT_DIR")" "$(dirname -- "$BIN_LINK")" "$APPS_DIR"
    cp -a -- "$APP_DIR" "$OPT_DIR"
    ln -sfn -- "$OPT_DIR/$APP_NAME" "$BIN_LINK"
    # Ruta absoluta y entre comillas: el menú puede no tener ~/.local/bin en el PATH.
    sed "s|^Exec=.*|Exec=\"$BIN_LINK\"|" "$ROOT/packaging/linux/vic2studio.desktop" \
        > "$APPS_DIR/vic2studio.desktop"
    echo "Instalado en $OPT_DIR (lanzador: $APPS_DIR/vic2studio.desktop)"
fi
