#!/usr/bin/env bash
# Empaqueta como AppImage la carpeta que deja PyInstaller (dist/<APP_NAME>/).
#
# Uso: packaging/linux/build_appimage.sh [PYTHON]
#   Antes: PyInstaller con packaging/vic2studio.spec (lo hace packaging/build_linux.sh).
#   PYTHON: intérprete con el que leer la versión (por defecto python3).
#   APPIMAGETOOL: ruta de appimagetool; si no está, se descarga la versión continua oficial.
# Resultado: dist/Victoria_II_Mod_Studio-<versión>-<arquitectura>.AppImage
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${1:-python3}"
ARCH="$(uname -m)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src"
VERSION="$("$PY" -c 'import vic2studio; print(vic2studio.__version__)')"
APP_NAME="$("$PY" -c 'import vic2studio; print(vic2studio.APP_NAME)')"
APP_DIR="$ROOT/dist/$APP_NAME"
[[ -x "$APP_DIR/$APP_NAME" ]] || { echo "Falta $APP_DIR: construye antes con PyInstaller." >&2; exit 1; }

APPDIR="$ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$APP_DIR" "$APPDIR/usr/lib/vic2studio"

cat > "$APPDIR/AppRun" <<APPRUN
#!/bin/sh
# Lanza la aplicación congelada que va dentro del AppImage.
HERE="\$(dirname "\$(readlink -f "\$0")")"
exec "\$HERE/usr/lib/vic2studio/$APP_NAME" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"

cp packaging/linux/vic2studio.desktop "$APPDIR/vic2studio.desktop"
cp packaging/linux/vic2studio.desktop "$APPDIR/usr/share/applications/vic2studio.desktop"
cp packaging/icons/vic2studio.png "$APPDIR/vic2studio.png"
cp packaging/icons/vic2studio.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/vic2studio.png"
ln -sf vic2studio.png "$APPDIR/.DirIcon"

TOOL="${APPIMAGETOOL:-}"
if [[ -z "$TOOL" ]]; then
    TOOL="$ROOT/build/appimagetool-$ARCH.AppImage"
    if [[ ! -x "$TOOL" ]]; then
        curl -fsSL -o "$TOOL" \
            "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
        chmod +x "$TOOL"
    fi
fi

OUT="$ROOT/dist/Victoria_II_Mod_Studio-$VERSION-$ARCH.AppImage"
rm -f "$OUT"
# Sin FUSE (contenedores, CI) appimagetool se descomprime y se ejecuta desde una carpeta temporal.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" --no-appstream "$APPDIR" "$OUT"
echo "AppImage: $OUT"
