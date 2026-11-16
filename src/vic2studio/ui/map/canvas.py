"""``MapCanvas``: el lienzo del mapa (wizard §16.1).

Un ``QGraphicsView`` con el mapa como imagen: el color de cada píxel es ``lut[ids[y, x]]`` (``np.take`` sobre el
ráster), con la LUT del modo vigente (``core.map.modes``) y, encima, las fronteras de provincia, estado y país
(``core.map.borders``) y la selección. No lee archivos ni toca el ``Workspace``: todo le llega de ``MapSession``.

**Coordenadas.** El juego cuenta ``y`` hacia el norte y el ráster guarda sus filas así (fila = ``y``); la escena
de Qt cuenta hacia abajo. La escena mide lo que el ráster, en píxeles del mapa, y solo aquí se invierte la
vertical: ``from_game`` y ``to_game`` son la única conversión (``core.map.raster.to_display_row``). El mapa da la
vuelta en horizontal: ``to_game`` reduce la ``x`` al ancho del mapa.

**Refresco.** ``refresh()`` recalcula la LUT y repinta todo (cambio de modo: ≤ 150 ms con vanilla);
``refresh(pids)`` repinta solo las cajas de esas provincias (pintar un dueño: ≤ 50 ms). La imagen es un array de
numpy compartido con un ``QImage`` (sin copias): repintar una caja es escribir en su trozo del array y pedir a Qt
que vuelva a dibujar ese rectángulo. El lienzo llama a ``refresh`` solo cuando ``MapSession.factsChanged`` toca un
campo de ``MapMode.needs`` del modo vigente.

**Elegir.** ``pick_mode`` dice qué hace el clic: ``PICK_NONE`` (seleccionar y arrastrar el mapa),
``PICK_SINGLE`` (un clic emite ``provincePicked`` y nada más), ``PICK_MULTI`` (cada clic añade o quita de la
selección) y ``PICK_BRUSH`` (arrastrar recoge provincias; al soltar, ``strokeFinished`` con todas, una vez).
El lienzo nunca edita: quien escucha la señal llama a ``MapSession``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from ...core.map.borders import LEVEL_COUNTRY, LEVEL_PROVINCE, LEVEL_STATE, LEVELS, border_mask, level_lut
from ...core.map.geometry import box_of, display_box, label_point
from ...core.map.modes import EMPTY_COLOR, MODES, SEA_COLOR, VOID_COLOR, discover_modes, finish_lut
from ...core.map.raster import to_display_row

if TYPE_CHECKING:
    from ...core.map.raster import ProvinceRaster
    from ..session_map import MapSession

PICK_NONE, PICK_SINGLE, PICK_MULTI, PICK_BRUSH = "none", "single", "multi", "brush"
PICK_MODES = (PICK_NONE, PICK_SINGLE, PICK_MULTI, PICK_BRUSH)
ZOOM_MIN, ZOOM_MAX = 0.1, 16.0       # píxeles de pantalla por píxel del mapa
ZOOM_STEP = 1.25
DEFAULT_MODE = "political"
# Fronteras: color (ARGB) por nivel; se mezclan sobre la imagen del modo.
BORDER_COLORS = {LEVEL_PROVINCE: 0x60000000, LEVEL_STATE: 0x90201010, LEVEL_COUNTRY: 0xE0101010}
SELECTION_COLOR = 0xFFFFE680
SELECTION_ALPHA = 0.55
IDS_MIN_ZOOM = 2.0                   # el número de cada provincia (modo IDs) solo se dibuja desde este zoom


def _blend(colors: np.ndarray, color: int, alpha: float) -> np.ndarray:
    """``colors`` (uint32 RGB32) mezclados con ``color`` en proporción ``alpha``."""
    channels = [(colors >> shift) & 0xFF for shift in (16, 8, 0)]
    target = [(color >> shift) & 0xFF for shift in (16, 8, 0)]
    mixed = [(c.astype(np.float32) * (1 - alpha) + t * alpha).astype(np.uint32) for c, t in zip(channels, target)]
    return np.uint32(0xFF000000) | (mixed[0] << 16) | (mixed[1] << 8) | mixed[2]


class _MapItem(QGraphicsItem):
    """La imagen del mapa: un ``QImage`` sobre un array de numpy (``buffer``) en filas de la vista."""

    def __init__(self) -> None:
        super().__init__()
        self.buffer: np.ndarray | None = None
        self.image: QImage | None = None
        self.labels: list[tuple[float, float, str]] = []
        self.show_labels = False

    def set_buffer(self, buffer: np.ndarray | None) -> None:
        self.prepareGeometryChange()
        self.buffer = buffer
        if buffer is None:
            self.image = None
            return
        height, width = buffer.shape
        self.image = QImage(buffer.data, width, height, width * 4, QImage.Format.Format_RGB32)

    def boundingRect(self) -> QRectF:  # noqa: N802 - API de Qt
        if self.buffer is None:
            return QRectF()
        height, width = self.buffer.shape
        return QRectF(0, 0, width, height)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.image is None:
            return
        exposed = option.exposedRect.toAlignedRect().intersected(self.image.rect())
        if exposed.isEmpty():
            return
        painter.drawImage(exposed, self.image, exposed)
        if self.show_labels and self.labels:
            painter.setPen(QColor(20, 20, 20))
            font = painter.font()
            font.setPixelSize(3)
            painter.setFont(font)
            area = option.exposedRect
            for x, y, text in self.labels:
                if area.contains(x, y):
                    painter.drawText(QRectF(x - 6, y - 2, 12, 4), Qt.AlignmentFlag.AlignCenter, text)


class MapCanvas(QGraphicsView):
    provinceHovered = Signal(int)                 # id bajo el cursor (0: ninguno); solo cuando cambia
    provinceClicked = Signal(int, object)         # (id, Qt.KeyboardModifiers) con PICK_NONE
    provincePicked = Signal(int)                  # con PICK_SINGLE y PICK_MULTI
    provinceDoubleClicked = Signal(int)           # doble clic (id; 0 fuera de toda provincia), con PICK_NONE
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
        self._stale = False                  # oculto con cambios sin pintar: se pinta al mostrarse
        self._mode_key: str | None = None
        self._mode_param: object = None
        self._pick_mode = PICK_NONE
        self._selection: tuple[int, ...] = ()
        self._borders = {LEVEL_PROVINCE: True, LEVEL_STATE: False, LEVEL_COUNTRY: True}
        self._lut: np.ndarray | None = None
        self._lut_generation = None
        self._hovered = 0
        self._stroke: list[int] = []
        self._stroking = False
        self._press: QPoint | None = None
        self._zoom = 1.0
        self._lines: list[tuple[int, int, int, bool]] = []   # (id, id, color ARGB, discontinua)
        self._label_cache: dict[int, tuple[float, float]] = {}
        self._labels_for: ProvinceRaster | None = None
        self._item = _MapItem()
        self.setObjectName("mapCanvas")
        self.setScene(QGraphicsScene(self))
        self.scene().addItem(self._item)
        self.setBackgroundBrush(QColor(SEA_COLOR & 0xFFFFFF | 0xFF000000))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.horizontalScrollBar().valueChanged.connect(self._on_scrolled)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        discover_modes()
        if map_session is not None:
            map_session.rasterStateChanged.connect(self._on_raster_state)
            map_session.factsChanged.connect(self._on_facts_changed)
            if follow:
                map_session.selectionChanged.connect(self._on_shared_selection)
            if map_session.raster is not None:
                self.set_raster(map_session.raster)

    # --- contenido ------------------------------------------------------------------------------------

    def _facts(self):
        return None if self.map_session is None else self.map_session.facts

    def _index(self):
        if self.map_session is None:
            return None
        return getattr(self.map_session.session, "index", None)

    def set_raster(self, raster: ProvinceRaster | None) -> None:
        """Cambia el ráster (None: lienzo vacío) y repinta. Con ``map_session`` lo llama solo al estar listo."""
        first = self._raster is None and raster is not None
        self._raster = raster
        self._label_cache = {}
        self._lut = None
        if raster is None:
            self._item.set_buffer(None)
            self.scene().setSceneRect(QRectF())
            return
        # El búfer (48 MB con vanilla) solo existe mientras el lienzo se ve: la sala Mapa tiene cuatro lienzos.
        self._item.set_buffer(np.zeros((raster.height, raster.width), dtype=np.uint32) if self.isVisible() else None)
        self.scene().setSceneRect(QRectF(0, 0, raster.width, raster.height))
        if self._mode_key is None:
            self._mode_key = DEFAULT_MODE if DEFAULT_MODE in MODES else next(iter(MODES), None)
        self._item.labels = []
        self._labels_for = None
        self._sync_labels()
        self.refresh()
        if first:
            self._fit()

    def raster(self) -> ProvinceRaster | None:
        return self._raster

    def set_mode(self, key: str, *, param: object = None) -> None:
        """Pone el modo de mapa ``key`` (de ``core.map.modes.MODES``; ``KeyError`` si no existe) con su
        parámetro (el TAG del modo de núcleos) y repinta."""
        discover_modes()
        if key not in MODES:
            raise KeyError(key)
        self._mode_key = key
        self._mode_param = param
        self._sync_labels()
        self.refresh()

    def mode(self) -> str | None:
        """Clave del modo vigente; None antes del primer ``set_mode``."""
        return self._mode_key

    def mode_param(self) -> object:
        return self._mode_param

    def set_borders(self, level: str, visible: bool) -> None:
        """Muestra u oculta las fronteras de ``level`` (``core.map.borders.LEVELS``)."""
        if level not in LEVELS:
            raise ValueError(level)
        if self._borders.get(level) != bool(visible):
            self._borders[level] = bool(visible)
            self.refresh()

    def borders(self, level: str) -> bool:
        return self._borders.get(level, False)

    def lut(self) -> np.ndarray | None:
        """La LUT vigente (``(N+1,)`` ``uint32``); None sin ráster."""
        return self._lut

    def _compute_lut(self) -> np.ndarray | None:
        raster = self._raster
        if raster is None:
            return None
        facts = self._facts()
        size = raster.max_id + 1
        if facts is None or facts.size != size or self._mode_key not in MODES:
            lut = np.full(size, EMPTY_COLOR, dtype=np.uint32)
            if lut.size:
                lut[0] = VOID_COLOR
            if facts is not None and facts.size == size:
                lut = finish_lut(facts, lut)
            return lut
        mode = MODES[self._mode_key]
        return np.asarray(mode.lut(facts, self._index(), param=self._mode_param), dtype=np.uint32)

    def _compose(self, rows: slice, cols: slice) -> np.ndarray:
        """Colores de la vista en ``[rows, cols]`` (filas de la vista) con fronteras y selección."""
        raster = self._raster
        height = raster.height
        game_rows = slice(height - rows.stop, height - rows.start)
        ids = raster.ids[game_rows, cols][::-1]
        colors = np.take(self._lut, ids)
        facts = self._facts()
        for level in (LEVEL_PROVINCE, LEVEL_STATE, LEVEL_COUNTRY):
            if not self._borders.get(level):
                continue
            if level != LEVEL_PROVINCE and facts is None:
                continue
            group = None if level == LEVEL_PROVINCE else level_lut(facts, level)
            mask = border_mask(ids, group, wrap_x=False)
            if mask.any():
                color = BORDER_COLORS[level]
                alpha = ((color >> 24) & 0xFF) / 255.0
                colors[mask] = _blend(colors[mask], color & 0xFFFFFF, alpha)
        if self._selection:
            selected = np.isin(ids, np.asarray(self._selection, dtype=ids.dtype))
            if selected.any():
                colors[selected] = _blend(colors[selected], SELECTION_COLOR & 0xFFFFFF, SELECTION_ALPHA)
        return colors

    def refresh(self, pids: Iterable[int] | None = None) -> None:
        """Repinta con los hechos actuales: todo (None) o solo las provincias ``pids``. Sin ráster, nada."""
        raster = self._raster
        if raster is None:
            return
        if not self.isVisible():
            # Oculto: sin búfer ni composición; al mostrarse se pinta entero (showEvent).
            self._lut = self._compute_lut()
            self._stale = True
            return
        buffer = self._item.buffer
        if buffer is None:
            self._item.set_buffer(np.zeros((raster.height, raster.width), dtype=np.uint32))
            buffer = self._item.buffer
            pids = None
        if pids is None or self._lut is None:
            self._lut = self._compute_lut()
            buffer[:, :] = self._compose(slice(0, raster.height), slice(0, raster.width))
            self._item.update()
            return
        pids = [int(p) for p in pids]
        self._lut = self._compute_lut()
        box = box_of(raster, pids)
        if box is None:
            return
        view = display_box(box, raster.height)
        # Un píxel de margen: las fronteras de la caja dependen de sus vecinos.
        r0, r1 = max(0, view.y0 - 1), min(raster.height, view.y1 + 2)
        c0, c1 = max(0, view.x0 - 1), min(raster.width, view.x1 + 2)
        buffer[r0:r1, c0:c1] = self._compose(slice(r0, r1), slice(c0, c1))
        self._item.update(QRectF(c0, r0, c1 - c0, r1 - r0))

    def _sync_labels(self) -> None:
        """Las etiquetas del modo IDs se calculan la primera vez que se piden para este ráster (en vanilla, una
        por cada una de sus 3 200 provincias)."""
        wanted = self._mode_key in MODES and MODES[self._mode_key].overlay == "ids"
        self._item.show_labels = wanted
        if wanted and self._raster is not None and self._labels_for is not self._raster:
            self._labels()
            self._labels_for = self._raster

    def _labels(self) -> None:
        raster = self._raster
        labels = []
        if raster is not None:
            for pid in np.flatnonzero(raster.pixel_count).tolist():
                if pid == 0:
                    continue
                point = label_point(raster, pid)
                if point is not None:
                    x, y = point
                    labels.append((x + 0.5, to_display_row(int(round(y)), raster.height) + 0.5, str(pid)))
        self._item.labels = labels

    # --- elegir ---------------------------------------------------------------------------------------

    def pick_mode(self) -> str:
        return self._pick_mode

    def set_pick_mode(self, mode: str) -> None:
        """Uno de ``PICK_MODES`` (``ValueError`` si no). Cambia el cursor; no borra la selección."""
        if mode not in PICK_MODES:
            raise ValueError(mode)
        self._pick_mode = mode
        if mode == PICK_BRUSH:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        elif mode in (PICK_SINGLE, PICK_MULTI):
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().unsetCursor()

    def selection(self) -> tuple[int, ...]:
        return self._selection

    def set_selection(self, pids: Iterable[int]) -> None:
        """Resalta ``pids``. No emite señales del lienzo (la selección compartida es de ``MapSession``)."""
        selection = tuple(dict.fromkeys(int(p) for p in pids))
        if selection == self._selection:
            return
        changed = set(self._selection) ^ set(selection)
        self._selection = selection
        if self._raster is not None and changed:
            self.refresh(changed)

    # --- líneas superpuestas (estrechos y canales) --------------------------------------------------------

    def set_lines(self, lines: Iterable[tuple[int, int, int, bool]]) -> None:
        """Dibuja una línea entre el punto de etiqueta de cada par de provincias ``(a, b, color, dashed)``
        (estrechos, canales); ``[]`` las quita. Con la vuelta horizontal, toma el camino más corto."""
        self._lines = [(int(a), int(b), int(color), bool(dashed)) for a, b, color, dashed in lines]
        self.viewport().update()

    def lines(self) -> list[tuple[int, int, int, bool]]:
        return list(self._lines)

    def _label_point(self, pid: int) -> tuple[float, float]:
        if pid not in self._label_cache:
            self._label_cache[pid] = label_point(self._raster, pid)
        return self._label_cache[pid]

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802 - API de Qt
        super().drawForeground(painter, rect)
        raster = self._raster
        if raster is None or not self._lines:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(1.5 / max(self._zoom, 0.05), 0.4)
        for a, b, color, dashed in self._lines:
            if not (0 < a <= raster.max_id and 0 < b <= raster.max_id):
                continue
            if raster.pixel_count[a] == 0 or raster.pixel_count[b] == 0:
                continue
            ax, ay = self._label_point(a)
            bx, by = self._label_point(b)
            if abs(bx - ax) > raster.width / 2:          # el camino corto cruza el borde
                bx += raster.width if bx < ax else -raster.width
            pen = QPen(QColor((color >> 16) & 255, (color >> 8) & 255, color & 255), width)
            pen.setCosmetic(False)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(self.from_game(ax, ay), self.from_game(bx, by))
            painter.setBrush(pen.color())
            for x, y in ((ax, ay), (bx, by)):
                painter.drawEllipse(self.from_game(x, y), width * 1.6, width * 1.6)
        painter.restore()

    # --- coordenadas y vista --------------------------------------------------------------------------

    def to_game(self, pos: QPoint) -> tuple[int, int] | None:
        """Coordenadas del juego ``(x, y)`` del punto ``pos`` de la vista (píxeles del widget), con la vuelta
        horizontal ya reducida a ``0 ≤ x < ancho``; None sin ráster o fuera del mapa en vertical."""
        raster = self._raster
        if raster is None:
            return None
        scene = self.mapToScene(pos)
        row = int(np.floor(scene.y()))
        if not 0 <= row < raster.height:
            return None
        x = int(np.floor(scene.x())) % raster.width
        return x, to_display_row(row, raster.height)

    def from_game(self, x: float, y: float) -> QPointF:
        """Punto de la **escena** de las coordenadas del juego ``(x, y)`` (la vertical invertida)."""
        raster = self._raster
        height = raster.height if raster is not None else 0
        return QPointF(x + 0.5, height - 1 - y + 0.5)

    def province_at(self, pos: QPoint) -> int:
        """Id de la provincia bajo el punto ``pos`` de la vista; 0 si no hay."""
        found = self.to_game(pos)
        if found is None or self._raster is None:
            return 0
        return int(self._raster.at(*found))

    def view_center_game(self) -> tuple[int, int] | None:
        """El centro de lo visible en coordenadas del juego (lo que guarda un bookmark); None sin ráster."""
        raster = self._raster
        if raster is None:
            return None
        center = self.mapToScene(self.viewport().rect().center())
        x = int(np.clip(np.floor(center.x()), 0, raster.width - 1))
        row = int(np.clip(np.floor(center.y()), 0, raster.height - 1))
        return x, to_display_row(row, raster.height)

    def center_on(self, x: float, y: float) -> None:
        """Centra la vista en las coordenadas del juego ``(x, y)`` sin cambiar el zoom."""
        self.centerOn(self.from_game(x, y))
        self._on_scrolled()

    def center_on_province(self, pid: int, *, zoom_to_fit: bool = False) -> bool:
        """Centra en la provincia (en su punto de etiqueta); con ``zoom_to_fit`` ajusta el zoom a su caja.
        False si no está en el ráster."""
        raster = self._raster
        if raster is None or not 0 < pid <= raster.max_id or raster.pixel_count[pid] == 0:
            return False
        if zoom_to_fit:
            box = display_box(box_of(raster, [pid]), raster.height)
            viewport = self.viewport().rect()
            fit = min(viewport.width() / max(box.width * 3, 1), viewport.height() / max(box.height * 3, 1))
            self.set_zoom(fit)
        point = label_point(raster, pid)
        self.center_on(*point)
        return True

    def zoom(self) -> float:
        """Píxeles de pantalla por píxel del mapa."""
        return self._zoom

    def set_zoom(self, zoom: float, *, anchor: QPoint | None = None) -> None:
        """Pone el zoom (recortado a ``ZOOM_MIN``–``ZOOM_MAX``) dejando fijo el punto ``anchor`` de la vista
        (por defecto, el centro)."""
        zoom = float(min(ZOOM_MAX, max(ZOOM_MIN, zoom)))
        if anchor is None:
            anchor = self.viewport().rect().center()
        before = self.mapToScene(anchor)
        self._zoom = zoom
        self.resetTransform()
        self.scale(zoom, zoom)
        after = self.mapToScene(anchor)
        delta = after - before
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center - delta)
        self._on_scrolled()

    def _fit(self) -> None:
        raster = self._raster
        viewport = self.viewport().rect()
        if raster is None or viewport.width() <= 0:
            return
        zoom = min(viewport.width() / raster.width, viewport.height() / raster.height)
        self.set_zoom(max(ZOOM_MIN, zoom))
        self.centerOn(QPointF(raster.width / 2, raster.height / 2))

    # --- eventos --------------------------------------------------------------------------------------

    def wheelEvent(self, event) -> None:  # noqa: N802 - API de Qt
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self._zoom * (ZOOM_STEP ** steps), anchor=event.position().toPoint())
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            if self._pick_mode == PICK_BRUSH:
                self._stroking = True
                self._stroke = []
                self._collect(self._press)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pick_mode == PICK_NONE:
            self.provinceDoubleClicked.emit(self.province_at(event.position().toPoint()))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        pid = self.province_at(pos)
        if pid != self._hovered:
            self._hovered = pid
            self.provinceHovered.emit(pid)
        if self._stroking:
            self._collect(pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._stroking:
                self._stroking = False
                stroke = tuple(dict.fromkeys(self._stroke))
                self._stroke = []
                if stroke:
                    self.strokeFinished.emit(stroke)
                event.accept()
                return
            press, self._press = self._press, None
            moved = press is not None and (pos - press).manhattanLength() > 4
            super().mouseReleaseEvent(event)
            if not moved:
                self._click(pos, event.modifiers())
            return
        super().mouseReleaseEvent(event)

    def _collect(self, pos: QPoint) -> None:
        pid = self.province_at(pos)
        if pid and pid not in self._stroke:
            self._stroke.append(pid)
            self.set_selection((*self._selection, pid))

    def _click(self, pos: QPoint, modifiers) -> None:
        pid = self.province_at(pos)
        if self._pick_mode == PICK_NONE:
            self.provinceClicked.emit(pid, modifiers)
            if not self.follow or self.map_session is None:
                return
            if not pid:
                self.map_session.set_selection(())
            elif modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                current = list(self.map_session.selection)
                if pid in current:
                    current.remove(pid)
                else:
                    current.append(pid)
                self.map_session.set_selection(current)
            else:
                self.map_session.set_selection((pid,))
            return
        if not pid:
            return
        if self._pick_mode == PICK_MULTI:
            current = list(self._selection)
            if pid in current:
                current.remove(pid)
            else:
                current.append(pid)
            self.set_selection(current)
        self.provincePicked.emit(pid)

    def _on_scrolled(self, *args) -> None:
        self.viewChanged.emit()
        if self.follow and self.map_session is not None and self._raster is not None:
            center = self.view_center_game()
            if center is not None:
                self.map_session.set_view_center(*center)

    # --- MapSession -----------------------------------------------------------------------------------

    def _on_raster_state(self) -> None:
        raster = self.map_session.raster
        if raster is not self._raster:
            self.set_raster(raster)

    def _on_facts_changed(self, pids) -> None:
        if self._raster is None:
            return
        if pids is None:
            self.refresh()
        else:
            self.refresh(pids)

    def _on_shared_selection(self, pids) -> None:
        self.set_selection(pids)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._raster is not None and (self._stale or self._item.buffer is None):
            self._stale = False
            self.refresh()
        if self._raster is not None and self._zoom == 1.0:
            self._fit()

    def hideEvent(self, event) -> None:  # noqa: N802
        """Al dejar de verse (otra sección, otra sala) suelta el búfer; no al minimizar la ventana."""
        super().hideEvent(event)
        if not event.spontaneous() and self._item.buffer is not None:
            self._item.set_buffer(None)
            self._stale = True
