# -*- mode: python ; coding: utf-8 -*-
"""Especificación de PyInstaller para Victoria II Mod Studio (modo one-folder).

Uso desde la raíz del proyecto (los scripts build_* lo hacen por ti):

    python -m PyInstaller --noconfirm --clean packaging/vic2studio.spec

Resultado: ``dist/Victoria II Mod Studio/`` con el ejecutable del mismo nombre.
Los datos (i18n, qss, assets) se copian con su ruta dentro del paquete, de modo
que el código los encuentra igual que sin congelar: ``Path(__file__).parent``.
"""

import sys
from pathlib import Path

# SPECPATH lo define PyInstaller: carpeta que contiene este .spec.
ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
PKG = SRC / "vic2studio"

sys.path.insert(0, str(SRC))
from vic2studio import APP_NAME  # noqa: E402  (solo metadatos; no importa Qt)

# Los mismos patrones que [tool.setuptools.package-data] de pyproject.toml.
DATA_PATTERNS = ("i18n/*.json", "ui/*.qss", "assets/**/*")


def package_data(patterns):
    """Pares (origen, carpeta de destino) que conservan la ruta relativa al paquete."""
    datas = []
    for pattern in patterns:
        for path in sorted(PKG.glob(pattern)):
            if path.is_file() and "__pycache__" not in path.parts:
                target = Path("vic2studio") / path.parent.relative_to(PKG)
                datas.append((str(path), str(target)))
    return datas


def package_modules():
    """Módulos del paquete, por si alguno se importa de forma dinámica (sin los ``__main__``)."""
    modules = []
    for path in sorted(PKG.rglob("*.py")):
        parts = path.relative_to(SRC).with_suffix("").parts
        if parts[-1] == "__main__":
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return modules


# El icono de Windows se generará en packaging/icons/ (planificado); sin él se usa el de PyInstaller.
ICON = ROOT / "packaging" / "icons" / "vic2studio.ico"

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=package_data(DATA_PATTERNS),
    hiddenimports=package_modules(),
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if sys.platform == "win32" and ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
