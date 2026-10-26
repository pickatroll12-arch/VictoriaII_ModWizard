"""Vistas de texto de solo lectura: ``TextView`` (base) y ``CodeView`` (código Clausewitz).

Las líneas son las del parser (``\\r\\n``, ``\\n`` y un ``\\r`` suelto separan líneas,
como en los editores de texto): ``display_text`` las normaliza a ``\\n`` para que
cada bloque del QTextDocument sea una línea de los diagnósticos.

Un archivo grande no bloquea la interfaz: ``build_document`` prepara el
QTextDocument en el hilo de la tarea (por trozos, porque cada inserción retiene
el GIL) y la vista solo lo cuelga, y no antes de hacerse visible. Cada texto
llega en un documento nuevo: reemplazar el de uno viejo con marcas era varias
veces más lento. Colgarlo sigue costando una maquetación de todos sus bloques
(``QPlainTextEdit.setDocument`` la hace siempre, ~0,6 s con 1,3 M líneas), y
otra cada vez que cambia el ancho de la vista: por eso el margen y la barra
vertical se ajustan antes de colgarlo, con un documento vacío colgado. Crear en
la tarea el ``QTextLayout`` de cada bloque la bajaría a ~0,25 s, pero alarga la
carga ~6 s y ocupa ~350 MB más aunque el código no llegue a mostrarse (20 MB).

Soltar ese documento al cambiar de archivo también para la interfaz: 0,16–0,35 s
con 1,3 M líneas ya colgadas (sin colgar, ~0,05 s), casi todo por destruir sus
``QTextLayout``. No hay forma segura de repartirlo ni de evitarlo (NF-DOC-DELETE):
vaciarlo por trozos con ``QTextCursor`` cuesta 1,4–1,9 s en total, en pasos de
13–30 ms pero con el GIL tomado; reutilizarlo con ``setPlainText`` suelta lo mismo
de una vez (0,16–0,31 s), y destruirlo en otro hilo no es seguro, porque los
bloques maquetados guardan referencias a motores de fuente del hilo de la interfaz.

El resaltado es perezoso: solo se calcula para las líneas que llegan a verse
(``QTextLayout.setFormats``), así que su coste no depende del tamaño del archivo.
Las cadenas que abarcan varias líneas se localizan antes, de una pasada
(``string_continuations``), para poder colorear cada línea por separado. El
fondo de las líneas con diagnósticos también se pinta solo en las que se ven: con
una ``ExtraSelection`` por línea marcada, colgar o soltar un documento costaba
del orden de 60 µs por marca.
"""

from __future__ import annotations

import atexit
import bisect
import re
from typing import Callable

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QPlainTextDocumentLayout, QPlainTextEdit, QTextEdit, QWidget
from shiboken6 import createdByPython

from ...core.cancel import CancelCheck, raise_if_cancelled
from .. import theme
from ..widgets import draw_icon, mark_data
from .common import ERROR, INFO, SEVERITY_COLOR, SEVERITY_ICON, WARNING

TAB_WIDTH = 4
DOCUMENT_CHUNK = 16_384  # caracteres por inserción al construir un documento (cada una retiene el GIL)
ALWAYS_SCROLL_LINES = 10_000  # con más líneas no cabe en ninguna pantalla: la barra vertical está desde el principio
MARKER_TINTS = {ERROR: QColor(139, 26, 26, 46), WARNING: QColor(160, 110, 0, 40), INFO: QColor(91, 65, 38, 22)}
CURRENT_LINE_TINT = QColor(201, 162, 74, 60)

# Separan bloques de QTextDocument (o líneas dentro de uno) sin ser saltos para el parser.
_FALSE_BREAKS = "\u2028\u2029\ufdd0\ufdd1"
_LINE_BREAKS = re.compile(f"\r\n?|[{_FALSE_BREAKS}]")
_TOKENS = re.compile(
    r'(?P<comment>#.*)'
    r'|(?P<string>"[^"]*"?)'
    r'|(?P<op><=|>=|!=|==|[=<>])'
    r'|(?P<brace>[{}])'
    r'|(?P<word>[^\s{}=<>!"#]+)'
)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d+)*|\.\d+)")
_OPERATOR_AHEAD = re.compile(r"\s*(?:<=|>=|!=|==|[=<>])")
_KEYWORDS = frozenset({"yes", "no"})
# Comentarios y cadenas del texto completo: una cadena puede cruzar saltos de línea.
_SPANS = re.compile(r'#[^\n]*|"[^"]*"?')
_NEWLINE = re.compile("\n")


def display_text(text: str) -> str:
    """Texto apto para QPlainTextEdit con las mismas líneas que cuenta el parser.

    ``\\r\\n`` y el ``\\r`` suelto pasan a ``\\n``; U+2028, U+2029, U+FDD0 y U+FDD1, que
    QTextDocument también tomaría por saltos y el parser no, a espacios. Las columnas no cambian.
    """
    if "\r" not in text and not any(ch in text for ch in _FALSE_BREAKS):
        return text
    return _LINE_BREAKS.sub(lambda m: " " if m.group() in _FALSE_BREAKS else "\n", text)


def string_continuations(text: str) -> frozenset[int]:
    """Líneas (0-based) que empiezan dentro de una cadena abierta en una línea anterior."""
    if '"' not in text:
        return frozenset()
    starts = None
    lines: set[int] = set()
    for match in _SPANS.finditer(text):
        begin, end = match.span()
        if text[begin] != '"' or "\n" not in match.group():
            continue
        if starts is None:
            starts = [m.start() for m in _NEWLINE.finditer(text)]
        first = bisect.bisect_left(starts, begin)   # línea de la comilla de apertura
        last = bisect.bisect_left(starts, end - 1)  # línea del último carácter
        lines.update(range(first + 1, last + 1))
    return frozenset(lines)


def syntax_ranges(line: str, in_string: bool = False) -> list[tuple[int, int, str]]:
    """``(inicio, longitud, clase)`` del resaltado de una línea; ``in_string`` si empieza dentro de una cadena."""
    ranges = []
    start = 0
    if in_string:
        end = line.find('"')
        if end < 0:
            return [(0, len(line), "string")] if line else []
        ranges.append((0, end + 1, "string"))
        start = end + 1
    for match in _TOKENS.finditer(line, start):
        kind = match.lastgroup
        begin, end = match.span()
        if kind == "word":
            word = match.group()
            if _OPERATOR_AHEAD.match(line, end):
                kind = "key"
            elif _NUMBER.fullmatch(word):
                kind = "number"
            elif word.lower() in _KEYWORDS:
                kind = "keyword"
            else:
                continue
        ranges.append((begin, end - begin, kind))
    return ranges


def build_document(text: str, font: QFont, tab_stop: float, cancelled: CancelCheck = None) -> QTextDocument:
    """Documento con ``text`` para una ``TextView``; se puede construir en el hilo de una tarea.

    ``setPlainText`` retendría el GIL (y pararía la interfaz) mientras dura: el
    texto se inserta por trozos. El documento sale ya movido al hilo de la interfaz.
    """
    document = QTextDocument()
    document.setUndoRedoEnabled(False)
    document.setDocumentLayout(QPlainTextDocumentLayout(document))
    # QPlainTextEdit guarda la fuente y la tabulación en su documento: las del nuevo se fijan aquí.
    document.setDefaultFont(font)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    option.setTabStopDistance(tab_stop)
    document.setDefaultTextOption(option)
    cursor = QTextCursor(document)
    for start in range(0, len(text), DOCUMENT_CHUNK):
        raise_if_cancelled(cancelled)
        cursor.insertText(text[start:start + DOCUMENT_CHUNK])
    application = QCoreApplication.instance()
    if application is not None:
        document.moveToThread(application.thread())
    return document


def _char_format(color: str, *, italic: bool = False, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(theme.color(color))
    if italic:
        fmt.setFontItalic(True)
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


class LazyHighlighter(QObject):
    """Aplica ``syntax_ranges`` a cada línea la primera vez que se hace visible."""

    def __init__(self, view: CodeView, continuations: frozenset[int]):
        super().__init__(view)
        self.view = view
        self.continuations = continuations
        self.done: set[int] = set()
        self.formats = {
            "comment": _char_format("syntax_comment", italic=True),
            "string": _char_format("syntax_string"),
            "number": _char_format("syntax_number"),
            "keyword": _char_format("syntax_keyword", bold=True),
            "key": _char_format("syntax_key"),
            "brace": _char_format("syntax_brace", bold=True),
            "op": _char_format("syntax_brace"),
        }
        self._busy = False
        view.updateRequest.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.highlight_visible)

    def detach(self) -> None:
        self.view.updateRequest.disconnect(self._schedule)
        self._timer.stop()

    def _schedule(self, *args) -> None:
        if not self._busy:
            self._timer.start()

    def highlight_visible(self) -> int:
        """Colorea las líneas visibles pendientes; devuelve cuántas ha coloreado."""
        view = self.view
        document = view.document()
        block = view.firstVisibleBlock()
        offset = view.contentOffset()
        bottom = view.viewport().height()
        first = last = None
        count = 0
        while block.isValid():
            top = view.blockBoundingGeometry(block).translated(offset).top()
            if top > bottom:
                break
            number = block.blockNumber()
            if number not in self.done:
                self.done.add(number)
                ranges = syntax_ranges(block.text(), number in self.continuations)
                if ranges:
                    formats = []
                    for start, length, kind in ranges:
                        item = QTextLayout.FormatRange()
                        item.start, item.length, item.format = start, length, self.formats[kind]
                        formats.append(item)
                    block.layout().setFormats(formats)
                    first = block if first is None else first
                    last = block
                    count += 1
            block = block.next()
        if first is not None:
            self._busy = True
            try:
                end = last.position() + last.length()
                document.markContentsDirty(first.position(), end - first.position())
            finally:
                self._busy = False
        return count


class _Gutter(QWidget):
    def __init__(self, view: CodeView):
        super().__init__(view)
        self.view = view

    def sizeHint(self) -> QSize:
        return QSize(self.view.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self.view.paint_gutter(event)


def _release_copies() -> None:
    """Al cerrar, cambia lo copiado desde Python por un QMimeData creado por Qt.

    En algunas plataformas (offscreen) el portapapeles destruye su contenido después de
    cerrarse el intérprete, y destruir entonces un objeto creado desde Python rompe el proceso.
    """
    if not isinstance(QGuiApplication.instance(), QGuiApplication):
        return  # sin aplicación gráfica no hay portapapeles
    clipboard = QGuiApplication.clipboard()
    for mode in (QClipboard.Mode.Clipboard, QClipboard.Mode.Selection):
        data = clipboard.mimeData(mode)
        if data is not None and createdByPython(data):
            clipboard.setText(data.text(), mode)


atexit.register(_release_copies)


class TextView(QPlainTextEdit):
    """Texto de solo lectura, sin ajuste de línea, que muestra documentos de ``build_document``.

    ``set_document`` cuelga el documento cuando la vista se hace visible: un archivo
    abierto en otra pestaña no paga su maquetación. Copiar conserva el texto exacto
    (el portapapeles de Qt cambiaría los espacios duros por espacios).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        mark_data(self)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setFont(theme.font("mono"))
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * TAB_WIDTH)
        self._pending: QTextDocument | None = None

    def document_factory(self) -> Callable[..., QTextDocument]:
        """``fabrica(texto, cancelled=None)``: ``build_document`` con la fuente y la tabulación de
        esta vista. Se puede llamar desde el hilo de una tarea."""
        font, tab_stop = QFont(self.font()), self.tabStopDistance()
        return lambda text, cancelled=None: build_document(text, font, tab_stop, cancelled)

    def set_document(self, document: QTextDocument | None) -> None:
        """Muestra ``document`` (de ``document_factory``); ``None`` deja la vista vacía."""
        self._pending = document if document is not None else self.document_factory()("")
        if self.isVisible():
            self._attach()

    def text_document(self) -> QTextDocument:
        """El documento que se muestra o, si aún no se ha colgado, el que se mostrará."""
        return self._pending if self._pending is not None else self.document()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending is not None:
            self._attach()

    def createMimeDataFromSelection(self) -> QMimeData:
        # Creado desde Python: ``_release_copies`` lo suelta antes de que se cierre el intérprete.
        mime = QMimeData()
        mime.setText(self.textCursor().selectedText().replace("\u2029", "\n"))
        return mime

    def _attach(self) -> None:
        document, self._pending = self._pending, None
        old = self.document()
        owned = old.parent() is self
        self.setExtraSelections([])  # sus cursores son del documento viejo
        # Lo que cambia el ancho de la vista (el margen, la barra vertical) vuelve a maquetar entero el
        # documento colgado: se cambia con uno vacío, ni con el viejo ni, después, con el nuevo. Con
        # «según haga falta», la barra aparecería en diferido tras colgar uno largo.
        blank = self.document_factory()("")
        blank.setParent(self)
        self.setDocument(blank)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn
                                        if document.blockCount() >= ALWAYS_SCROLL_LINES
                                        else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._document_changing(document)
        document.setParent(self)
        self.setDocument(document)
        blank.deleteLater()
        if owned:
            old.deleteLater()  # con uno grande, lo más caro del cambio: ver el docstring del módulo
        self._document_attached()

    def _document_changing(self, document: QTextDocument) -> None:
        """Se llama justo antes de colgar ``document``."""

    def _document_attached(self) -> None:
        """Se llama con cada documento nuevo ya colgado."""


class CodeView(TextView):
    """``set_source(texto, marcas)``; las marcas son ``{línea: gravedad}`` (``error``/``warning``/``info``)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("codeView")
        self._gutter = _Gutter(self)
        self._gutter_width = 0
        self._markers: dict[int, str] = {}
        self._continuations: frozenset[int] = frozenset()
        self._target: tuple[int, int | None] | None = None  # cursor pedido antes de colgar el documento
        self._highlighter: LazyHighlighter | None = None
        self.highlighted = False
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_gutter_width()

    # --- API -----------------------------------------------------------------------------

    def set_source(self, text: str, markers: dict[int, str] | None = None, *, highlight: bool = True,
                   continuations: frozenset[int] | None = None, document: QTextDocument | None = None) -> None:
        """Muestra ``text`` (ya normalizado con ``display_text``).

        ``document`` (de ``document_factory`` con ese texto) y ``continuations`` (ver
        ``string_continuations``) pueden llegar precalculados desde un hilo; si no,
        se calculan aquí.
        """
        if self._highlighter is not None:
            self._highlighter.detach()
            self._highlighter.deleteLater()
            self._highlighter = None
        self._markers = dict(markers or {})
        self.highlighted = highlight
        if highlight and continuations is None:
            continuations = string_continuations(text)
        self._continuations = continuations or frozenset()
        self._target = None
        self.set_document(document if document is not None else self.document_factory()(text))

    def clear_source(self) -> None:
        self.set_source("", None, highlight=False)

    def markers(self) -> dict[int, str]:
        return dict(self._markers)

    def highlighted_lines(self) -> int:
        """Líneas ya coloreadas (el resto se colorea al hacerse visible)."""
        return len(self._highlighter.done) if self._highlighter is not None else 0

    def go_to_line(self, line: int, column: int | None = None) -> bool:
        """Coloca el cursor en ``line`` (1-based) y la centra; ``False`` si no existe."""
        block = self.text_document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        if self._pending is not None:
            self._target = (block.blockNumber() + 1, column)
            return True
        cursor = QTextCursor(block)
        if column:
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor,
                                min(column - 1, max(0, block.length() - 1)))
        self.setTextCursor(cursor)
        self.centerCursor()
        self._refresh_selections()
        return True

    def current_line(self) -> int:
        if self._pending is not None:
            return self._target[0] if self._target is not None else 1
        return self.textCursor().blockNumber() + 1

    def _document_changing(self, document: QTextDocument) -> None:
        # Cambiar el margen después obligaría a maquetar otra vez el documento nuevo.
        self._update_gutter_width(document.blockCount())

    def _document_attached(self) -> None:
        if self.highlighted:
            self._highlighter = LazyHighlighter(self, self._continuations)
        target, self._target = self._target, None
        if target is None:
            self.moveCursor(QTextCursor.MoveOperation.Start)
            self._refresh_selections()
        else:
            self.go_to_line(*target)
        if self._highlighter is not None:
            self._highlighter.highlight_visible()
        self._update_gutter_width()

    # --- margen de números de línea ------------------------------------------------------

    def gutter_width(self) -> int:
        return self._gutter_width

    def _update_gutter_width(self, lines: int | None = None) -> None:
        digits = max(3, len(str(max(1, self.blockCount() if lines is None else lines))))
        width = int(QFontMetricsF(self.font()).horizontalAdvance("9") * digits) + 30
        if width != self._gutter_width:
            self._gutter_width = width
            self.setViewportMargins(width, 0, 0, 0)
            self._place_gutter()

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def _place_gutter(self) -> None:
        area = self.contentsRect()
        self._gutter.setGeometry(QRect(area.left(), area.top(), self._gutter_width, area.height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_gutter()

    def paint_gutter(self, event: QPaintEvent) -> None:
        p = QPainter(self._gutter)
        rect = QRectF(self._gutter.rect())
        p.fillRect(event.rect(), theme.color("parchment_light"))
        p.setPen(theme.color("parchment_shadow"))
        edge = rect.right() - 0.5
        p.drawLine(QPointF(edge, rect.top()), QPointF(edge, rect.bottom()))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        current = self.textCursor().blockNumber()
        width = self._gutter.width()
        line_height = self.fontMetrics().height()
        normal = self.font()
        bold = QFont(normal)
        bold.setWeight(QFont.Weight.Bold)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = number + 1
                severity = self._markers.get(line)
                if severity is not None:
                    icon = QRectF(3, top + (line_height - 13) / 2, 13, 13)
                    draw_icon(p, SEVERITY_ICON[severity], icon, theme.color(SEVERITY_COLOR[severity]))
                p.setFont(bold if number == current else normal)
                p.setPen(theme.color("velvet_text" if number == current else "ink_muted"))
                p.drawText(QRectF(0, top, width - 8, line_height),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(line))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    # --- fondos de las líneas -------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._markers:
            self._paint_markers(event.rect())
        super().paintEvent(event)

    def _paint_markers(self, area: QRect) -> None:
        """Fondo de las líneas marcadas que se ven, bajo el texto y la línea actual."""
        p = QPainter(self.viewport())
        offset = self.contentOffset()
        margin = self.document().documentMargin()
        width = max(self.viewport().width(), self.document().documentLayout().documentSize().width())
        # Como una selección de ancho completo: del margen del texto al borde que deja QPlainTextEdit.
        left, right = offset.x() + margin, offset.x() + width - margin + self.cursorWidth()
        block = self.firstVisibleBlock()
        while block.isValid():
            rect = self.blockBoundingGeometry(block).translated(offset)
            if rect.top() > area.bottom():
                break
            severity = self._markers.get(block.blockNumber() + 1)
            if severity is not None and block.isVisible() and rect.bottom() >= area.top():
                p.fillRect(QRectF(left, rect.top(), right - left, rect.height()), MARKER_TINTS[severity])
            block = block.next()
        p.end()

    def _refresh_selections(self) -> None:
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(CURRENT_LINE_TINT)
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        self.setExtraSelections([current])
        self._gutter.update()
