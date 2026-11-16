"""Sección «Estrechos y canales» de la sala Mapa (wizard §16.4): las filas de ``map/adjacencies.csv``.

A la izquierda, el mapa con una línea por fila (dorada para los estrechos, azul discontinua para los canales y
roja para los pasos cerrados); a la derecha, la tabla del archivo y el formulario para añadir una fila. «Dibujar
en el mapa» rellena el formulario con tres clics: la provincia de salida, la de llegada y la de mar que cruza.

Añadir y quitar son un paso de deshacer cada uno (``MapSession.add_adjacency`` / ``remove_adjacency``); el
archivo conserva su cabecera, sus comentarios y el resto de filas byte a byte (``core/map/adjacency.py``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from ....core.map.adjacency import TYPE_CANAL, TYPE_IMPASSABLE, TYPE_SEA, TYPES
from ....core.map.modes import argb
from ....i18n import N_, tr
from ...map.canvas import PICK_NONE, PICK_SINGLE, MapCanvas
from ...pages.base import BasePage
from ...pickers.province_picker import ANY, LAND, SEA, ProvincePicker
from ...session_map import RASTER_FAILED, RASTER_LOADING, RASTER_READY
from ...widgets import EmptyState, make_icon, show_in_stack

TYPE_LABELS = {TYPE_SEA: N_("map.straits.type.sea"), TYPE_IMPASSABLE: N_("map.straits.type.impassable"),
               TYPE_CANAL: N_("map.straits.type.canal")}
TYPE_COLORS = {TYPE_SEA: argb(230, 190, 60), TYPE_CANAL: argb(60, 140, 230), TYPE_IMPASSABLE: argb(210, 50, 40)}
COLUMNS = (N_("map.straits.col.from"), N_("map.straits.col.to"), N_("map.straits.col.type"),
           N_("map.straits.col.through"), N_("map.straits.col.data"), N_("map.straits.col.comment"))
ADD_ERRORS = {"adjacency_type": N_("map.straits.error.type"), "adjacency_same": N_("map.straits.error.same"),
              "adjacency_exists": N_("map.straits.error.exists"), "adjacency_missing": N_("map.straits.error.missing")}
DRAW_STEPS = (N_("map.straits.draw.from"), N_("map.straits.draw.to"), N_("map.straits.draw.through"))
ROLE_ROW = Qt.ItemDataRole.UserRole


class StraitsPage(BasePage):
    key = "straits"
    title_key = N_("section.map.straits")
    subtitle_key = N_("map.straits.subtitle")
    icon_name = "anchor"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.map = session.map
        self._rows = []
        self._draw_step = -1
        super().__init__(parent)
        self.map.rasterStateChanged.connect(self._update_state)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents_changed)
        session.indexStateChanged.connect(self._on_index_state)
        self.reload()

    # --- construcción -----------------------------------------------------------------------------------

    def build(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.canvas = MapCanvas(self.map, follow=False)
        self.canvas.setMinimumSize(320, 240)
        self.canvas.provincePicked.connect(self._on_picked)
        self.canvas.provinceClicked.connect(self._on_clicked)
        self.canvas.provinceHovered.connect(self._on_hover)
        self.empty = EmptyState("anchor")
        self.load_button = QPushButton()
        self.load_button.setObjectName("straitsLoad")
        self.load_button.clicked.connect(lambda: self.map.load_raster(force=self.map.raster_state == RASTER_FAILED))
        self.empty.add_action(self.load_button)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas)
        left_layout.addWidget(self.stack, 1)
        self.hover_label = QLabel()
        left_layout.addWidget(self.hover_label)
        splitter.addWidget(left)

        right = QWidget()
        right.setMinimumWidth(360)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(6, 0, 0, 0)
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("straitsFilter")
        self.filter_combo.addItem("", None)
        for kind in TYPES:
            self.filter_combo.addItem("", kind)
        self.filter_combo.currentIndexChanged.connect(lambda _index: self._fill())
        layout.addWidget(self.filter_combo)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("straitsTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, 2)
        row = QHBoxLayout()
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("straitsRemove")
        self.remove_button.setIcon(make_icon("trash", "gold_light"))
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.add_label = QLabel()
        self.add_label.setObjectName("straitsAddTitle")
        layout.addWidget(self.add_label)
        form = QFormLayout()
        self.form_labels = [QLabel() for _ in range(6)]
        self.start_picker = ProvincePicker(self.session, allow=LAND)
        self.start_picker.setObjectName("straitsFrom")
        self.end_picker = ProvincePicker(self.session, allow=ANY)
        self.end_picker.setObjectName("straitsTo")
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("straitsType")
        for kind in TYPES:
            self.type_combo.addItem("", kind)
        self.through_picker = ProvincePicker(self.session, allow=SEA)
        self.through_picker.setObjectName("straitsThrough")
        self.data_spin = QSpinBox()
        self.data_spin.setObjectName("straitsData")
        self.data_spin.setRange(0, 99)
        self.comment_edit = QLineEdit()
        self.comment_edit.setObjectName("straitsComment")
        for label, editor in zip(self.form_labels, (self.start_picker, self.end_picker, self.type_combo,
                                                     self.through_picker, self.data_spin, self.comment_edit)):
            form.addRow(label, editor)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.draw_button = QToolButton()
        self.draw_button.setObjectName("straitsDraw")
        self.draw_button.setCheckable(True)
        self.draw_button.setIcon(make_icon("map", "gold_light"))
        self.draw_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.draw_button.toggled.connect(self._on_draw_toggled)
        self.add_button = QPushButton()
        self.add_button.setObjectName("straitsAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(self.add_from_form)
        buttons.addWidget(self.draw_button)
        buttons.addStretch(1)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)
        self.status_label = QLabel()
        self.status_label.setObjectName("straitsStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.body.addWidget(splitter, 1)

    def retranslate(self) -> None:
        super().retranslate()
        self.filter_combo.setItemText(0, tr("map.straits.filter_all"))
        for index, kind in enumerate(TYPES, start=1):
            self.filter_combo.setItemText(index, tr(TYPE_LABELS[kind]))
        for index, kind in enumerate(TYPES):
            self.type_combo.setItemText(index, tr(TYPE_LABELS[kind]))
        self.table.setHorizontalHeaderLabels([tr(key) for key in COLUMNS])
        for label, key in zip(self.form_labels, COLUMNS):
            label.setText(tr(key))
        self.add_label.setText(tr("map.straits.add_title"))
        self.remove_button.setText(tr("map.straits.remove"))
        self.add_button.setText(tr("map.straits.add"))
        self.draw_button.setText(tr("map.straits.draw"))
        self.draw_button.setToolTip(tr("map.straits.draw_tooltip"))
        self.load_button.setText(tr("map.load"))
        self._update_state()
        self._fill()

    # --- estado -------------------------------------------------------------------------------------------

    def _update_state(self, *args) -> None:
        state = self.map.raster_state
        if self.session.project is None:
            self.empty.set_texts(tr("map.empty.no_project"), tr("map.empty.no_project_text"))
            self.load_button.hide()
            show_in_stack(self.stack, self.empty)
        elif state == RASTER_READY:
            show_in_stack(self.stack, self.canvas)
            if self.canvas.mode() is None:
                self.canvas.set_mode("terrain")
            self._draw_lines()
        elif state == RASTER_LOADING:
            self.empty.set_texts(tr("map.empty.loading"), tr("map.empty.loading_text"))
            self.load_button.hide()
            show_in_stack(self.stack, self.empty)
        else:
            failed = state == RASTER_FAILED
            self.empty.set_texts(tr("map.empty.failed" if failed else "map.empty.idle"),
                                 tr(self.map.raster_error or "map.error.other") if failed
                                 else tr("map.empty.idle_text"))
            self.load_button.show()
            show_in_stack(self.stack, self.empty)

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().showEvent(event)
        if self.session.project is not None and self.map.raster_state not in (RASTER_READY, RASTER_LOADING,
                                                                               RASTER_FAILED):
            self.map.load_raster()
        if self.map.raster is not None and self.map.facts is None:
            self.map.refresh_facts()

    def is_busy(self) -> bool:
        return self.map.raster_state == RASTER_LOADING

    def reload(self, *args) -> None:
        self._rows = self.map.adjacencies().rows() if self.session.project is not None else []
        for picker in (self.start_picker, self.end_picker, self.through_picker):
            picker.reload()
        self.add_button.setEnabled(self.session.project is not None)
        self.draw_button.setEnabled(self.session.project is not None)
        self._fill()

    def _on_documents_changed(self, rels) -> None:
        if self.session.project is None:
            return
        key = self.map.adjacencies_rel().key
        if not rels or any(str(rel).upper().replace("\\", "/") == key for rel in rels):
            self.reload()

    def _on_index_state(self, *args) -> None:
        for picker in (self.start_picker, self.end_picker, self.through_picker):
            picker.reload()

    def rows(self):
        """Las filas que muestra la tabla (con el filtro de tipo)."""
        wanted = self.filter_combo.currentData()
        return [row for row in self._rows if wanted is None or row.type == wanted]

    def _fill(self) -> None:
        rows = self.rows()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for row in rows:
                index = self.table.rowCount()
                self.table.insertRow(index)
                label = tr(TYPE_LABELS[row.type]) if row.type in TYPE_LABELS else row.type
                values = (row.start, row.end, label, row.through or "", row.data or "", row.comment)
                for column, value in enumerate(values):
                    item = QTableWidgetItem("" if value is None else str(value))
                    item.setData(ROLE_ROW, row)
                    if column in (0, 1, 3) and value:
                        item.setToolTip(self.map.province_name(int(value)) or "")
                    self.table.setItem(index, column, item)
        finally:
            self.table.blockSignals(False)
        self.remove_button.setEnabled(False)
        self._draw_lines()

    def _draw_lines(self) -> None:
        if self.map.raster is None:
            return
        lines = []
        for row in self.rows():
            if not row.start or not row.end:
                continue
            color = TYPE_COLORS.get(row.type, TYPE_COLORS[TYPE_IMPASSABLE])
            lines.append((row.start, row.end, color, row.type == TYPE_CANAL))
        self.canvas.set_lines(lines)

    def selected_row(self):
        items = self.table.selectedItems()
        return items[0].data(ROLE_ROW) if items else None

    def _on_row_selected(self) -> None:
        row = self.selected_row()
        self.remove_button.setEnabled(row is not None)
        if row is None:
            self.canvas.set_selection(())
            return
        pids = [pid for pid in (row.start, row.end, row.through) if pid]
        self.canvas.set_selection(pids)
        if row.start and self.map.raster is not None:
            self.canvas.center_on_province(row.start)

    def select_row(self, line: int) -> bool:
        for index in range(self.table.rowCount()):
            row = self.table.item(index, 0).data(ROLE_ROW)
            if row.line == line:
                self.table.selectRow(index)
                return True
        return False

    def _on_clicked(self, pid: int, modifiers) -> None:
        for index in range(self.table.rowCount()):
            row = self.table.item(index, 0).data(ROLE_ROW)
            if pid and pid in (row.start, row.end, row.through):
                self.table.selectRow(index)
                return

    def _on_hover(self, pid: int) -> None:
        self.hover_label.setText(tr("map.hover", id=pid, name=self.map.province_name(pid) or "—") if pid else "")

    # --- dibujar y añadir -----------------------------------------------------------------------------------

    def _on_draw_toggled(self, on: bool) -> None:
        self._draw_step = 0 if on else -1
        self.canvas.set_pick_mode(PICK_SINGLE if on else PICK_NONE)
        if on:
            self.type_combo.setCurrentIndex(self.type_combo.findData(TYPE_SEA))
            self.canvas.set_selection(())
        self.status_label.setText(tr(DRAW_STEPS[0]) if on else "")

    def _on_picked(self, pid: int) -> None:
        if self._draw_step < 0:
            return
        picker = (self.start_picker, self.end_picker, self.through_picker)[self._draw_step]
        provinces = self.map.provinces
        is_sea = provinces is not None and provinces.is_sea(pid)
        if (picker.allow == LAND and is_sea) or (picker.allow == SEA and not is_sea):
            self.status_label.setText(tr("map.straits.draw.wrong", id=pid))
            return
        picker.set_value(pid)
        self.canvas.set_selection([p for p in (self.start_picker.value(), self.end_picker.value(),
                                               self.through_picker.value()) if p])
        self._draw_step += 1
        if self._draw_step >= len(DRAW_STEPS):
            self.draw_button.setChecked(False)
            self.status_label.setText(tr("map.straits.draw.done"))
        else:
            self.status_label.setText(tr(DRAW_STEPS[self._draw_step]))

    def add_from_form(self):
        """Añade la fila del formulario; devuelve la ``Adjacency`` nueva o None (con el motivo en la página)."""
        start, end = self.start_picker.value(), self.end_picker.value()
        if not start or not end:
            self.status_label.setText(tr(ADD_ERRORS["adjacency_missing"]))
            return None
        kind = self.type_combo.currentData()
        through = self.through_picker.value() or 0
        try:
            added = self.map.add_adjacency(start, end, kind, through=through, data=self.data_spin.value(),
                                           comment=self.comment_edit.text().strip())
        except ValueError as exc:
            self.status_label.setText(tr(ADD_ERRORS.get(str(exc), "map.straits.error.type")))
            return None
        self.reload()
        self.select_row(added.line)
        self.status_label.setText(tr("map.straits.added", start=start, end=end))
        return added

    def remove_selected(self) -> bool:
        row = self.selected_row()
        if row is None:
            return False
        try:
            self.map.remove_adjacency(row)
        except KeyError:
            self.reload()
            return False
        self.reload()
        self.status_label.setText(tr("map.straits.removed", start=row.start, end=row.end))
        return True

    def focus_field(self, ref, field=()) -> bool:
        """Selecciona la fila de ``ref`` (``adjacency:<línea>`` o ``<de>-<a>``)."""
        ident = str(getattr(ref, "ident", ref))
        if ident.isdigit():
            return self.select_row(int(ident))
        parts = [part for part in ident.replace(":", "-").split("-") if part.isdigit()]
        if len(parts) >= 2:
            a, b = int(parts[0]), int(parts[1])
            for index in range(self.table.rowCount()):
                row = self.table.item(index, 0).data(ROLE_ROW)
                if {row.start, row.end} == {a, b}:
                    self.table.selectRow(index)
                    return True
        return False
