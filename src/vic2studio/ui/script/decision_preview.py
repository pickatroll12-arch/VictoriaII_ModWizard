"""Vista previa procedural de una decisión (wizard §13.8): la imagen de 95×95, el título, la descripción y
las condiciones y el efecto en frases (``core.script.phrases``). Sin recursos del juego salvo la imagen de
la propia decisión, leída de la instalación del usuario si existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ...i18n import N_

PICTURE_SIZE = (95, 95)                          # la imagen de una decisión, en píxeles


@dataclass(frozen=True)
class DecisionPreviewData:
    """Lo que pinta la vista previa; textos y frases en el idioma elegido."""

    ident: str
    title: str | None
    desc: str | None
    potential: str                               # «Aparece si: …»
    allow: str                                   # «Se puede tomar si: …»
    effect: str                                  # «Al tomarla: …»
    picture: Path | None = None                  # archivo de la imagen (DDS); None: no existe o sin arte


class DecisionPreview(QWidget):
    """Vista previa de una decisión, con conmutador ES/EN."""

    EMPTY_KEY = N_("decisions.preview.empty")

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def bind(self, ref) -> None:
        """Enlaza con la decisión ``ref`` y se repinta con cada cambio suyo o de sus textos. None: vacío."""
        raise NotImplementedError

    def set_data(self, data: DecisionPreviewData | None) -> None:
        raise NotImplementedError

    def data(self) -> DecisionPreviewData | None:
        raise NotImplementedError

    def set_preview_language(self, lang: str) -> None:
        raise NotImplementedError

    def set_game_art(self, enabled: bool) -> None:
        raise NotImplementedError

    def render_image(self, width: int = 0) -> QImage:
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
