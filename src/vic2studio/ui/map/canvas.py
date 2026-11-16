"""``MapCanvas``: el lienzo del mapa (wizard §16.1). Contrato de la iteración 5.

Un ``QGraphicsView`` con el mapa como imagen: el color de cada píxel es ``lut[ids[y, x]]`` (``np.take`` sobre el
ráster, por teselas), con la LUT del modo vigente (``core.map.modes``) y, encima, las fronteras de provincia,
estado y país (``core.map.borders``) y la selección. No lee archivos ni toca el ``Workspace``: todo le llega de
``MapSession``.

**Coordenadas.** El juego cuenta ``y`` hacia el norte y el ráster guarda sus filas así (fila = ``y``); la escena
de Qt cuenta hacia abajo. La escena mide lo que el ráster, en píxeles del mapa, y solo aquí se invierte la
vertical: ``from_game`` y ``to_game`` son la única conversión (``core.map.raster.to_display_row``). El mapa da la
vuelta en horizontal: se puede desplazar sin fin hacia el este o el oeste.

**Refresco.** ``refresh()`` recalcula la LUT y repinta todo (cambio de modo: ≤ 150 ms con vanilla);
``refresh(pids)`` repinta solo las cajas de esas provincias (pintar un dueño: ≤ 50 ms). El lienzo llama a
``refresh`` solo cuando ``MapSession.factsChanged`` toca un campo de ``MapMode.needs`` del modo vigente.

**Elegir.** ``pick_mode`` dice qué hace el clic: ``PICK_NONE`` (seleccionar y arrastrar el mapa),
``PICK_SINGLE`` (un clic emite ``provincePicked`` y nada más), ``PICK_MULTI`` (cada clic añade o quita de la
selección) y ``PICK_BRUSH`` (arrastrar recoge provincias; al soltar, ``strokeFinished`` con todas, una vez).
El lienzo nunca edita: quien escucha la señal llama a ``MapSession``.

En el commit de contrato solo existe el constructor; lo demás lanza ``NotImplementedError`` (cadena B).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, Signal
from PySide6.QtWidgets import QGraphicsView, QWidget

if TYPE_CHECKING:
    from ...core.map.raster import ProvinceRaster
    from ..session_map import MapSession

PICK_NONE, PICK_SINGLE, PICK_MULTI, PICK_BRUSH = "none", "single", "multi", "brush"
PICK_MODES = (PICK_NONE, PICK_SINGLE, PICK_MULTI, PICK_BRUSH)
ZOOM_MIN, ZOOM_MAX = 0.1, 16.0       # píxeles de pantalla por píxel del mapa


class MapCanvas(QGraphicsView):
    provinceHovered = Signal(int)                 # id bajo el cursor (0: ninguno); solo cuando cambia
    provinceClicked = Signal(int, object)         # (id, Qt.KeyboardModifiers) con PICK_NONE
    provincePicked = Signal(int)                  # con PICK_SINGLE y PICK_MULTI
    strokeFinished = Signal(object)               # tuple[int, ...] de un trazo de PICK_BRUSH, en orden
    viewChanged = Signal()                        # desplazamiento o zoom

    def __init__(self, map_session: MapSession | None = None, parent: QWidget | None = None, *,
                 follow: bool = True) -> None:
        """``map_session``: de dónde salen el ráster y los hechos (None: un lienzo vacío hasta ``set_raster``).
        ``follow=False`` es para los lienzos auxiliares (``MapPickDialog``): no escriben ``view_center`` ni la
        selección compartida de ``MapSession``."""
        super().__init__(parent)
        self.map_session = map_session
        self.follow = follow
        self._raster: ProvinceRaster | None = None
        self._mode_key: str | None = None
        self._mode_param: object = None
        self._pick_mode = PICK_NONE
        self._selection: tuple[int, ...] = ()

    # --- contenido ------------------------------------------------------------------------------------

    def set_raster(self, raster: ProvinceRaster | None) -> None:
        """Cambia el ráster (None: lienzo vacío) y repinta. Con ``map_session`` lo llama solo al estar listo."""
        raise NotImplementedError

    def raster(self) -> ProvinceRaster | None:
        raise NotImplementedError

    def set_mode(self, key: str, *, param: object = None) -> None:
        """Pone el modo de mapa ``key`` (de ``core.map.modes.MODES``; ``KeyError`` si no existe) con su
        parámetro (el TAG del modo de núcleos) y repinta."""
        raise NotImplementedError

    def mode(self) -> str | None:
        """Clave del modo vigente; None antes del primer ``set_mode``."""
        raise NotImplementedError

    def mode_param(self) -> object:
        raise NotImplementedError

    def set_borders(self, level: str, visible: bool) -> None:
        """Muestra u oculta las fronteras de ``level`` (``core.map.borders.LEVELS``)."""
        raise NotImplementedError

    def refresh(self, pids: Iterable[int] | None = None) -> None:
        """Repinta con los hechos actuales: todo (None) o solo las provincias ``pids``. Sin ráster, nada."""
        raise NotImplementedError

    # --- elegir ---------------------------------------------------------------------------------------

    def pick_mode(self) -> str:
        raise NotImplementedError

    def set_pick_mode(self, mode: str) -> None:
        """Uno de ``PICK_MODES`` (``ValueError`` si no). Cambia el cursor; no borra la selección."""
        raise NotImplementedError

    def selection(self) -> tuple[int, ...]:
        raise NotImplementedError

    def set_selection(self, pids: Iterable[int]) -> None:
        """Resalta ``pids``. No emite señales del lienzo (la selección compartida es de ``MapSession``)."""
        raise NotImplementedError

    # --- coordenadas y vista --------------------------------------------------------------------------

    def to_game(self, pos: QPoint) -> tuple[int, int] | None:
        """Coordenadas del juego ``(x, y)`` del punto ``pos`` de la vista (píxeles del widget), con la vuelta
        horizontal ya reducida a ``0 ≤ x < ancho``; None sin ráster o fuera del mapa en vertical."""
        raise NotImplementedError

    def from_game(self, x: float, y: float) -> QPointF:
        """Punto de la **escena** de las coordenadas del juego ``(x, y)`` (la vertical invertida)."""
        raise NotImplementedError

    def province_at(self, pos: QPoint) -> int:
        """Id de la provincia bajo el punto ``pos`` de la vista; 0 si no hay."""
        raise NotImplementedError

    def view_center_game(self) -> tuple[int, int] | None:
        """El centro de lo visible en coordenadas del juego (lo que guarda un bookmark); None sin ráster."""
        raise NotImplementedError

    def center_on(self, x: float, y: float) -> None:
        """Centra la vista en las coordenadas del juego ``(x, y)`` sin cambiar el zoom."""
        raise NotImplementedError

    def center_on_province(self, pid: int, *, zoom_to_fit: bool = False) -> bool:
        """Centra en la provincia (en su punto de etiqueta); con ``zoom_to_fit`` ajusta el zoom a su caja.
        False si no está en el ráster."""
        raise NotImplementedError

    def zoom(self) -> float:
        """Píxeles de pantalla por píxel del mapa."""
        raise NotImplementedError

    def set_zoom(self, zoom: float, *, anchor: QPoint | None = None) -> None:
        """Pone el zoom (recortado a ``ZOOM_MIN``–``ZOOM_MAX``) dejando fijo el punto ``anchor`` de la vista
        (por defecto, el centro)."""
        raise NotImplementedError
