"""Panel «Cambios pendientes»: lo que escribiría un guardado ahora mismo y su diff (wizard §6.5, P1, D13).

Muestra un ``core.project.ChangeSet``: una fila por archivo (acción, ruta y líneas
añadidas y quitadas) y, debajo, el diff del archivo seleccionado con las líneas
coloreadas. Lo usan la sección «Cambios pendientes» de la sala Proyecto y el
diálogo de revisión antes de guardar. No calcula nada: quien lo usa le pasa el
``ChangeSet`` (``Session.changeset``).

Las cuentas son las del diff entero (``PlannedWrite.lines``): el diff que se muestra
viene recortado a ``MAX_DIFF_LINES`` y, contadas sobre él, «Recuperar las filas» de VSM
decía +134 −134 en vez de +3 438 −3 438. La línea de recorte del núcleo
(«... (+N lines)») se dice en el idioma de la interfaz («… y N líneas más»).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.project import ChangeSet, PlannedWrite, WriteAction
from ...core.project.diffing import split_truncation
from ...core.vfs import DESCRIPTOR_REL
from ...i18n import N_, tr
from .. import theme
from ..viewers.common import format_number
from ..widgets import make_icon, mark_data

ACTION_KEYS = {
    WriteAction.CREATE: N_("pending.action.create"),
    WriteAction.MODIFY: N_("pending.action.modify"),
    WriteAction.COPY_FROM_GAME: N_("pending.action.copy"),
    WriteAction.TRASH: N_("pending.action.trash"),
}
ACTION_ICONS = {
    WriteAction.CREATE: ("file", "success"),
    WriteAction.MODIFY: ("file_text", "ink_soft"),
    WriteAction.COPY_FROM_GAME: ("copy", "warning"),
    WriteAction.TRASH: ("error", "danger"),
}


def write_label(write: PlannedWrite) -> str:
    """Ruta que se muestra: la relativa del juego o, para el descriptor, el nombre de su archivo."""
    if str(write.rel) == str(DESCRIPTOR_REL):
        return write.target.name
    return str(write.rel)


def shown_diff(diff: str) -> str:
    """El diff con la línea de recorte del núcleo traducida: «… y 12 177 líneas más»."""
    body, hidden = split_truncation(diff or "")
    if not hidden:
        return diff or ""
    return body + "\n" + tr("pending.diff_more", count=format_number(hidden))


def display_diff(write: PlannedWrite) -> str:
    """El diff tal como se muestra: en las cabeceras del descriptor, su nombre de archivo y no la ruta reservada, y
    el recorte en el idioma de la interfaz."""
    if str(write.rel) != str(DESCRIPTOR_REL) or not write.diff:
        return shown_diff(write.diff)
    lines = write.diff.split("\n")
    for index, line in enumerate(lines[:2]):
        if line.startswith(("---", "+++")):
            lines[index] = line.replace(str(DESCRIPTOR_REL), write_label(write))
    return shown_diff("\n".join(lines))


def changed_lines(diff: str) -> tuple[int, int]:
    """(añadidas, quitadas) de un diff unificado (sin contar las cabeceras ``+++``/``---``)."""
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def line_counts(diff: str, lines: tuple[int, int] | None) -> tuple[int, int] | None:
    """(añadidas, quitadas) del cambio entero: las que da el núcleo (``lines``) o, si no las trae, las del diff, solo
    si no viene recortado (contar sobre el recortado daba cifras falsas). None: binario, sin diff o desconocidas."""
    if lines is not None:
        return tuple(lines)
    if not diff or diff.startswith("Binary files "):
        return None
    body, hidden = split_truncation(diff)
    return None if hidden else changed_lines(body)


def lines_text(diff: str, lines: tuple[int, int] | None) -> str:
    """«+3 438 −3 438» (o vacío si no se sabe)."""
    counts = line_counts(diff, lines)
    if counts is None:
        return ""
    return tr("pending.lines", added=format_number(counts[0]), removed=format_number(counts[1]))


class DiffHighlighter(QSyntaxHighlighter):
    """Colorea un diff unificado: líneas añadidas en verde, quitadas en rojo y cabeceras en bronce."""

    def __init__(self, document):
        super().__init__(document)
        self._formats = {}
        for name, color, background in (("+", "success", QColor(47, 93, 35, 38)),
                                         ("-", "danger", QColor(139, 26, 26, 34)),
                                         ("@", "syntax_keyword", None), ("h", "bronze_dark", None)):
            fmt = QTextCharFormat()
            fmt.setForeground(theme.color(color))
            if background is not None:
                fmt.setBackground(background)
            self._formats[name] = fmt

    def highlightBlock(self, text: str) -> None:
        if text.startswith(("+++", "---")):
            kind = "h"
        elif text[:1] in ("+", "-", "@"):
            kind = text[:1]
        else:
            return
        self.setFormat(0, len(text), self._formats[kind])


class PendingChangesPanel(QWidget):
    """Lista de escrituras planificadas y el diff de la seleccionada."""

    selection_changed = Signal(object)   # PlannedWrite | None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.changeset = ChangeSet()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary = QLabel()
        self.summary.setObjectName("pendingSummary")
        self.summary.setWordWrap(True)
        self.summary.setFont(theme.font("body_bold"))
        layout.addWidget(self.summary)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setObjectName("pendingTree")
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.splitter.addWidget(self.tree)
        diff_box = QWidget()
        diff_layout = QVBoxLayout(diff_box)
        diff_layout.setContentsMargins(0, 0, 0, 0)
        diff_layout.setSpacing(4)
        self.diff_caption = QLabel()
        self.diff_caption.setProperty("role", "caption")
        self.diff_caption.setFont(theme.font("caption"))
        diff_layout.addWidget(self.diff_caption)
        self.diff = QPlainTextEdit()
        self.diff.setObjectName("pendingDiff")
        self.diff.setReadOnly(True)
        self.diff.setFont(theme.font("mono"))
        self.diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mark_data(self.diff)
        self.highlighter = DiffHighlighter(self.diff.document())
        diff_layout.addWidget(self.diff, 1)
        self.splitter.addWidget(diff_box)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter, 1)
        self.retranslate()

    def set_changeset(self, changeset: ChangeSet) -> None:
        previous = self.current_write()
        self.changeset = changeset
        self.tree.clear()
        select = None
        for write in changeset.writes:
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, write)
            icon, color = ACTION_ICONS[write.action]
            item.setIcon(1, make_icon(icon, color, "cream"))
            self.tree.addTopLevelItem(item)
            if previous is not None and str(previous.rel) == str(write.rel):
                select = item
        self._fill_items()
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(select or self.tree.topLevelItem(0))
        else:
            self._show_diff(None)
        self._retranslate_summary()

    def current_write(self) -> PlannedWrite | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def select(self, rel) -> bool:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole).rel) == str(rel):
                self.tree.setCurrentItem(item)
                return True
        return False

    def _fill_items(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            write: PlannedWrite = item.data(0, Qt.ItemDataRole.UserRole)
            item.setText(0, write_label(write))
            item.setToolTip(0, str(write.target))
            item.setText(1, tr(ACTION_KEYS[write.action]))
            item.setText(2, lines_text(write.diff, getattr(write, "lines", None))
                         if write.action is not WriteAction.TRASH else "")

    def _on_current_changed(self, current, previous) -> None:
        write = None if current is None else current.data(0, Qt.ItemDataRole.UserRole)
        self._show_diff(write)
        self.selection_changed.emit(write)

    def _show_diff(self, write: PlannedWrite | None) -> None:
        if write is None:
            self.diff.setPlainText("")
            self.diff_caption.setText(tr("pending.diff_none"))
            return
        self.diff.setPlainText(display_diff(write))
        self._retranslate_caption(write)

    def _retranslate_caption(self, write: PlannedWrite) -> None:
        if write.action is WriteAction.TRASH:
            self.diff_caption.setText(tr("pending.diff_trash", name=write_label(write)))
        elif not write.diff:
            self.diff_caption.setText(tr("pending.diff_empty", name=write_label(write)))
        else:
            self.diff_caption.setText(tr("pending.diff_caption", name=write_label(write)))

    def _retranslate_summary(self) -> None:
        writes = self.changeset.writes
        if not writes:
            self.summary.setText(tr("pending.summary_none"))
            return
        text = tr("pending.summary_one" if len(writes) == 1 else "pending.summary", count=len(writes))
        copies = self.changeset.copies_from_game
        if copies:
            text += " · " + tr("pending.summary_copies_one" if copies == 1 else "pending.summary_copies",
                               count=copies)
        if self.changeset.trashed:
            text += " · " + tr("pending.summary_trash", count=self.changeset.trashed)
        self.summary.setText(text)

    def retranslate(self) -> None:
        self.tree.setHeaderLabels([tr("pending.col.file"), tr("pending.col.action"), tr("pending.col.lines")])
        self._fill_items()
        self._retranslate_summary()
        write = self.current_write()
        if write is None:
            self.diff_caption.setText(tr("pending.diff_none"))
        else:
            self._retranslate_caption(write)
