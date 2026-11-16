"""Vista previa procedural de un evento (wizard §13.8).

Dibuja con QPainter una ventana con las proporciones de la del juego: el título, la imagen de 521×203, la
descripción y un botón por opción. No usa ningún recurso del juego salvo la imagen del propio evento, que se
lee de la instalación del usuario cuando existe (``set_game_art(False)`` la sustituye por un marco
procedural: las capturas del repositorio van siempre así). Interpreta los códigos de color ``§Y…§W`` y deja
los ``$VARIABLE$`` como fichas. En la iteración 8 pasa a usar el renderizador ``.gui`` real.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ...i18n import N_

PICTURE_SIZE = (521, 203)                        # la imagen de un evento, en píxeles


@dataclass(frozen=True)
class EventPreviewData:
    """Lo que pinta la vista previa. Los textos ya vienen en el idioma elegido (``None``: la clave no tiene
    texto y se pinta la propia clave, atenuada)."""

    ident: str
    province: bool                               # province_event: la ventana pequeña, sin imagen grande
    title: str | None
    desc: str | None
    options: tuple[str | None, ...]
    picture: Path | None = None                  # archivo de la imagen (TGA); None: no existe o sin arte
    major: bool = False


class EventPreview(QWidget):
    """Vista previa de un evento, con conmutador ES/EN."""

    EMPTY_KEY = N_("events.preview.empty")

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def bind(self, ref) -> None:
        """Enlaza con el evento ``ref`` y se repinta con cada cambio suyo o de sus textos. None: vacío."""
        raise NotImplementedError

    def set_data(self, data: EventPreviewData | None) -> None:
        """Pinta ``data`` a mano, sin registro (pruebas y capturas)."""
        raise NotImplementedError

    def data(self) -> EventPreviewData | None:
        raise NotImplementedError

    def set_preview_language(self, lang: str) -> None:
        """Idioma de los textos del evento (no el de la interfaz)."""
        raise NotImplementedError

    def set_game_art(self, enabled: bool) -> None:
        raise NotImplementedError

    def set_current_option(self, index: int | None) -> None:
        """Resalta una opción (la tarjeta con el foco)."""
        raise NotImplementedError

    def render_image(self, width: int = 0) -> QImage:
        """La vista previa como imagen (pruebas y capturas); ``width`` 0: el tamaño natural."""
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
