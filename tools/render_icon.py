"""Dibuja el emblema de la aplicación en ``packaging/icons/``: ``vic2studio.png`` (256 px, para el AppImage y el
lanzador de Linux) y ``vic2studio.ico`` (16 a 256 px, para el ejecutable y el instalador de Windows).

Es el mismo emblema que ``ui.main_window.app_icon``. Uso, desde la raíz del proyecto:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/render_icon.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vic2studio.ui.widgets.ornaments import emblem_pixmap  # noqa: E402

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    emblem_pixmap(size).save(buffer, "PNG")
    return bytes(buffer.data())


def main(out_dir: Path = ROOT / "packaging" / "icons") -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841  (QPixmap necesita la aplicación)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vic2studio.png").write_bytes(_png_bytes(256))
    # Cada tamaño se dibuja aparte: el emblema se ve mejor así que reducido desde 256.
    images = [Image.open(io.BytesIO(_png_bytes(size))).convert("RGBA") for size in ICO_SIZES]
    images[-1].save(out_dir / "vic2studio.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                    append_images=images[:-1])
    print(out_dir / "vic2studio.png")
    print(out_dir / "vic2studio.ico")


if __name__ == "__main__":
    main()
