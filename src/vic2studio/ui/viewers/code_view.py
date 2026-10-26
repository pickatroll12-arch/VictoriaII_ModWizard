"""Vista de código de solo lectura: números de línea, marcas de diagnóstico y resaltado Clausewitz.

Las líneas se cuentan como en el parser (solo ``\\n`` separa líneas): el texto
que se muestra tiene los ``\\r`` sueltos sustituidos por espacios para que
QTextDocument no los convierta en saltos y las líneas coincidan con los
diagnósticos.

El resaltado es perezoso: solo se calcula para las líneas que llegan a verse
(``QTextLayout.setFormats``), así que su coste no depende del tamaño del archivo.
Las cadenas que abarcan varias líneas se localizan antes, de una pasada
(``string_continuations``), para poder colorear cada línea por separado.
"""

from __future__ import annotations

import bisect
import re

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QTextLayout,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .. import theme
from ..widgets import draw_icon, mark_data
from .common import ERROR, INFO, SEVERITY_COLOR, SEVERITY_ICON, SEVERITY_RANK, WARNING

TAB_WIDTH = 4

_LINE_BREAKS = re.compile("\r\n?|[  ]")
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
    """Texto apto para QPlainTextEdit con las mismas líneas que cuenta el parser."""
    if "\r" not in text and " " not in text and " " not in text:
        return text
    return _LINE_BREAKS.sub(lambda m: "\n" if m.group(0) == "\r\n" else " ", text)


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


class CodeView(QPlainTextEdit):
    """``set_source(texto, marcas)``; las marcas son ``{línea: gravedad}`` (``error``/``warning``/``info``)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("codeView")
        mark_data(self)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setFont(theme.font("mono"))
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * TAB_WIDTH)
        self._gutter = _Gutter(self)
        self._gutter_width = 0
        self._markers: dict[int, str] = {}
        self._highlighter: LazyHighlighter | None = None
        self.highlighted = False
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_gutter_width()

    # --- API -----------------------------------------------------------------------------

    def set_source(self, text: str, markers: dict[int, str] | None = None, *, highlight: bool = True,
                   continuations: frozenset[int] | None = None) -> None:
        """Muestra ``text`` (ya normalizado con ``display_text``).

        ``continuations`` (ver ``string_continuations``) puede llegar precalculado
        desde un hilo; si no, se calcula aquí.
        """
        if self._highlighter is not None:
            self._highlighter.detach()
            self._highlighter.deleteLater()
            self._highlighter = None
        self._markers = dict(markers or {})
        self.setPlainText(text)
        self.highlighted = highlight
        if highlight:
            if continuations is None:
                continuations = string_continuations(text)
            self._highlighter = LazyHighlighter(self, continuations)
            self._highlighter.highlight_visible()
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self._refresh_selections()
        self._update_gutter_width()

    def clear_source(self) -> None:
        self.set_source("", None, highlight=False)

    def markers(self) -> dict[int, str]:
        return dict(self._markers)

    def highlighted_lines(self) -> int:
        """Líneas ya coloreadas (el resto se colorea al hacerse visible)."""
        return len(self._highlighter.done) if self._highlighter is not None else 0

    def go_to_line(self, line: int, column: int | None = None) -> bool:
        """Coloca el cursor en ``line`` (1-based) y la centra; ``False`` si no existe."""
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        cursor = QTextCursor(block)
        if column:
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor,
                                min(column - 1, max(0, block.length() - 1)))
        self.setTextCursor(cursor)
        self.centerCursor()
        self._refresh_selections()
        return True

    def current_line(self) -> int:
        return self.textCursor().blockNumber() + 1

    # --- margen de números de línea ------------------------------------------------------

    def gutter_width(self) -> int:
        return self._gutter_width

    def _update_gutter_width(self, *args) -> None:
        digits = max(3, len(str(max(1, self.blockCount()))))
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

    # --- selecciones ---------------------------------------------------------------------

    def _refresh_selections(self) -> None:
        selections = []
        tints = {ERROR: QColor(139, 26, 26, 46), WARNING: QColor(160, 110, 0, 40), INFO: QColor(91, 65, 38, 22)}
        document = self.document()
        for line, severity in sorted(self._markers.items(), key=lambda item: SEVERITY_RANK[item[1]], reverse=True):
            block = document.findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(tints[severity])
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = QTextCursor(block)
            selections.append(selection)
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(201, 162, 74, 60))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)
        self.setExtraSelections(selections)
        self._gutter.update()
