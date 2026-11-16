"""Selector de imagen de un evento o una decisión, con importación (wizard §14.5, §14.7).

``PicturePicker`` es el editor del tipo ``Picture``: enseña la miniatura de la imagen actual (o «la del id»
cuando el campo falta en una decisión, H21), lista las de la carpeta y tiene «Importar…», que convierte una
imagen propia al formato del juego y la añade al mod como documento nuevo en la misma transacción que el
cambio del campo.

Formatos, medidos en vanilla: las 286 imágenes de evento son TGA de 521×203 sin comprimir (285 de 24 bits y
1 de 32); las 149 de decisión son DDS de 95×95 sin comprimir y de 32 bits. ``encode_picture`` escribe
exactamente eso: el DDS con ``core.gfx.dds.write_dds`` (A8R8G8B8, D11) y el TGA de 24 bits con Pillow. La
imagen de origen se recorta al centro con la proporción del destino y se reduce; nunca se deforma.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ...core.vfs.paths import VPath


@dataclass(frozen=True)
class PictureSpec:
    """Dónde y cómo se guarda una imagen: carpeta relativa, tamaño en píxeles y extensión."""

    folder: str
    size: tuple[int, int]
    suffix: str

    def rel(self, name: str) -> VPath:
        """La ruta del archivo de la imagen ``name`` (el valor del campo ``picture``)."""
        return VPath.of(f"{self.folder}/{name}{self.suffix}")


EVENT_PICTURE = PictureSpec("gfx/pictures/events", (521, 203), ".tga")
DECISION_PICTURE = PictureSpec("gfx/pictures/decisions", (95, 95), ".dds")
SPECS = {"events": EVENT_PICTURE, "decisions": DECISION_PICTURE}      # por ``Picture.folder``


def encode_picture(source: Path | bytes, spec: PictureSpec) -> bytes:
    """Los bytes del archivo del juego para la imagen ``source`` (una ruta o los bytes de un PNG, JPG, BMP,
    TGA o DDS): recorte centrado a la proporción de ``spec.size``, reducción y codificación según
    ``spec.suffix``. ``ValueError`` si no es una imagen legible. No escribe nada."""
    raise NotImplementedError


class PicturePicker(QWidget):
    """Editor de un campo ``Picture``. Misma API mínima que los selectores de ``ui/pickers``."""

    value_committed = Signal(object)             # el nombre elegido (str) o None: sin valor
    imported = Signal(object)                    # VPath del archivo añadido al mod

    def __init__(self, spec: PictureSpec, session=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def value(self) -> str | None:
        raise NotImplementedError

    def set_value(self, value: str | None) -> None:
        raise NotImplementedError

    def set_default_name(self, name: str | None) -> None:
        """La imagen que usa el juego si el campo falta (el id de la decisión): se enseña atenuada."""
        raise NotImplementedError

    def names(self) -> list[str]:
        """Las imágenes de la carpeta en la vista efectiva (sin extensión), ordenadas."""
        raise NotImplementedError

    def import_image(self, source: Path, name: str) -> bool:
        """Convierte ``source``, la añade al mod como ``spec.rel(name)`` y confirma ``name`` como valor.
        Dentro de la transacción de quien confirma el campo; False (sin cambios) si no es una imagen."""
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
