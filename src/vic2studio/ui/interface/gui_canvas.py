"""Lienzo de una ventana ``.gui`` (wizard §17.2): cada elemento es un ``QGraphicsItem`` con su imagen.

La escena es la pantalla a la resolución elegida (1024×768, 1280×720 o 1920×1080). El fondo de la ventana y
cada elemento se dibujan con ``core.gui.render.GuiRenderer``: sus sprites, sus textos y, donde falta el arte, el
estilo procedural (recuadro discontinuo con el nombre). Arrastrar un elemento emite ``moved(ruta, dx, dy)`` y el
asa de su esquina emite ``resized(ruta, ancho, alto)``: quien aloja el lienzo lo convierte en una edición del
``.gui`` (un paso de deshacer que cambia solo la línea ``position`` o ``size``). La rejilla se dibuja cada 8 px y
el imán redondea a ella. El lienzo nunca guarda nodos: solo rutas de elemento.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from . import to_pixmap

GRID = 8
HANDLE = 8
SELECTION = QColor(232, 190, 90)
GRID_COLOR = QColor(255, 255, 255, 28)


class ResizeHandle(QGraphicsRectItem):
    """El asa de la esquina inferior derecha de un elemento."""

    def __init__(self, owner: ElementItem) -> None:
        super().__init__(0, 0, HANDLE, HANDLE, owner)
        self.owner = owner
        self.setBrush(QBrush(SELECTION))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self._start: QPointF | None = None
        self._size = (0.0, 0.0)

    def place(self) -> None:
        rect = self.owner.rect()
        self.setPos(rect.width() - HANDLE, rect.height() - HANDLE)

    def mousePressEvent(self, event) -> None:
        self._start = event.scenePos()
        self._size = (self.owner.rect().width(), self.owner.rect().height())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:
            return
        delta = event.scenePos() - self._start
        width = max(4.0, self.owner.canvas.snap_value(self._size[0] + delta.x()))
        height = max(4.0, self.owner.canvas.snap_value(self._size[1] + delta.y()))
        self.owner.set_box(width, height)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._start is None:
            return
        self._start = None
        rect = self.owner.rect()
        if (round(rect.width()), round(rect.height())) != (round(self._size[0]), round(self._size[1])):
            self.owner.canvas.resized.emit(self.owner.path, int(round(rect.width())), int(round(rect.height())))
        event.accept()


class ElementItem(QGraphicsRectItem):
    """Un elemento de la ventana: su caja, su imagen y su asa. Se arrastra si ``movable``."""

    def __init__(self, canvas: GuiCanvas, path: str, rect, pixmap, *, movable: bool, resizable: bool) -> None:
        super().__init__(0, 0, rect.w, rect.h)
        self.canvas = canvas
        self.path = path
        self.setPos(rect.x, rect.y)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.picture = QGraphicsPixmapItem(pixmap, self) if pixmap is not None else None
        flags = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        if movable:
            flags |= QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setFlags(flags)
        self.handle = ResizeHandle(self) if resizable else None
        if self.handle is not None:
            self.handle.place()
            self.handle.setVisible(False)
        self._press: QPointF | None = None

    def set_box(self, width: float, height: float) -> None:
        self.setRect(0, 0, width, height)
        if self.picture is not None:
            pixmap = self.picture.pixmap()
            if not pixmap.isNull():
                self.picture.setPixmap(pixmap.scaled(int(width), int(height)))
        if self.handle is not None:
            self.handle.place()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.canvas.snap:
            return QPointF(self.canvas.snap_value(value.x()), self.canvas.snap_value(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if self.handle is not None:
                self.handle.setVisible(bool(value))
            self.setPen(QPen(SELECTION, 2) if value else QPen(Qt.PenStyle.NoPen))
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        self._press = self.pos()
        super().mousePressEvent(event)
        self.canvas.selected.emit(self.path)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        start, self._press = self._press, None
        if start is None:
            return
        delta = self.pos() - start
        dx, dy = int(round(delta.x())), int(round(delta.y()))
        if dx or dy:
            self.canvas.moved.emit(self.path, dx, dy)


class GuiCanvas(QGraphicsView):
    """La pantalla con una ventana. ``show_window`` la (re)dibuja; las ediciones salen por señales."""

    selected = Signal(str)                  # ruta del elemento elegido
    moved = Signal(str, int, int)           # ruta, dx, dy
    resized = Signal(str, int, int)         # ruta, ancho, alto

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCanvas")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QBrush(QColor(28, 32, 38)))
        self.items_by_path: dict[str, ElementItem] = {}
        self.screen = (1024, 768)
        self.grid = True
        self.snap = False
        self.zoom_to_window = False             # True: el encuadre es la ventana (con margen), no la pantalla
        self.window_path: str | None = None

    # --- dibujo --------------------------------------------------------------------------------

    def snap_value(self, value: float) -> float:
        return float(round(value / GRID) * GRID) if self.snap else float(value)

    def show_window(self, renderer, document, window, screen: tuple[int, int], *, extra=()) -> None:
        """Dibuja ``window`` (y ``extra``, los elementos sueltos del archivo) sobre una pantalla ``screen``."""
        from ...core.gui import element_path

        scene = self.scene()
        scene.clear()
        self.items_by_path = {}
        self.screen = (int(screen[0]), int(screen[1]))
        scene.setSceneRect(QRectF(0, 0, self.screen[0], self.screen[1]))
        screen_rect = scene.addRect(QRectF(0, 0, self.screen[0], self.screen[1]), QPen(QColor(90, 90, 90)))
        screen_rect.setZValue(-10)
        rects = renderer.layout(window, self.screen)
        for loose in extra:
            rects.update(renderer.layout(loose, self.screen))
        win = rects[window.uid]
        self.window_path = element_path(window)
        background = document.background_of(window)
        back = renderer._sprite_for(background, (win.w, win.h)) if background is not None else None
        panel = back if back is not None else renderer.panel((win.w, win.h))
        z = 0
        for element in [*window.walk(), *(el for loose in extra for el in loose.walk())]:
            rect = rects[element.uid]
            if element is window:
                pixmap = to_pixmap(panel)
            elif element is background and back is not None:
                continue
            else:
                image = renderer.element_image(element, (rect.w, rect.h))
                if image is None:
                    image = renderer.placeholder((rect.w, rect.h), element.name)
                pixmap = to_pixmap(image)
            item = ElementItem(self, element_path(element), rect, pixmap, movable=True,
                               resizable=element.size is not None)
            item.setZValue(z)
            z += 1
            scene.addItem(item)
            self.items_by_path[item.path] = item
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self.grid:
            return
        painter.setPen(QPen(GRID_COLOR, 1))
        left = int(rect.left()) - int(rect.left()) % GRID
        top = int(rect.top()) - int(rect.top()) % GRID
        x = left
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += GRID * 4
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += GRID * 4

    # --- selección y vista ---------------------------------------------------------------------

    def select_path(self, path: str | None) -> None:
        scene = self.scene()
        scene.clearSelection()
        item = self.items_by_path.get(path) if path else None
        if item is not None:
            item.setSelected(True)
            self.ensureVisible(item)

    def selected_path(self) -> str | None:
        items = self.scene().selectedItems()
        return items[0].path if items and isinstance(items[0], ElementItem) else None

    def fit(self) -> None:
        """Encuadra la pantalla entera o, con ``zoom_to_window``, la ventana con un margen."""
        target = self.scene().sceneRect()
        item = self.items_by_path.get(self.window_path) if self.zoom_to_window and self.window_path else None
        if item is not None:
            box = item.sceneBoundingRect()
            margin = max(24.0, 0.08 * max(box.width(), box.height()))
            target = box.adjusted(-margin, -margin, margin, margin)
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)

    def set_zoom_to_window(self, enabled: bool) -> None:
        self.zoom_to_window = bool(enabled)
        self.fit()

    def set_grid(self, enabled: bool) -> None:
        self.grid = bool(enabled)
        self.viewport().update()

    def set_snap(self, enabled: bool) -> None:
        self.snap = bool(enabled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit()
