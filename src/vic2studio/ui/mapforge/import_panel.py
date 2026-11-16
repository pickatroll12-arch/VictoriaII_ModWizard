"""Pantalla «Importar recursos» del taller (wizard §18.6): una ranura por archivo, voltear, la fuente de tierra y
mar y la matriz «Lo que falta se reconstruye».

El panel recoge archivos (por diálogo o arrastrando) y enseña lo que devuelve ``bitmaps.inspect``; comprobar y
construir el mundo los pide al asistente, que los manda al proceso trabajador.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...core.mapforge.imports.bitmaps import LAND_SOURCES, SLOTS, ImportSet
from ...i18n import N_, tr
from ..widgets import make_icon

SLOT_LABELS = {
    "provinces": N_("forge.import.slot.provinces"), "definition": N_("forge.import.slot.definition"),
    "default_map": N_("forge.import.slot.default_map"), "terrain": N_("forge.import.slot.terrain"),
    "rivers": N_("forge.import.slot.rivers"), "heightmap": N_("forge.import.slot.heightmap"),
    "mask": N_("forge.import.slot.mask"), "positions": N_("forge.import.slot.positions"),
    "fmg_json": N_("forge.import.slot.fmg_json"),
}
SOURCE_LABELS = {"sea_starts": N_("forge.import.source.sea_starts"), "terrain": N_("forge.import.source.terrain"),
                 "rivers": N_("forge.import.source.rivers"), "heightmap": N_("forge.import.source.heightmap"),
                 "mask": N_("forge.import.source.mask"), "fmg": N_("forge.import.source.fmg")}
MATRIX_STEPS = {"provinces": N_("forge.import.step.provinces"), "land_sea": N_("forge.import.step.land_sea"),
                "relief": N_("forge.import.step.relief"), "terrain": N_("forge.import.step.terrain"),
                "rivers": N_("forge.import.step.rivers"), "positions": N_("forge.import.step.positions"),
                "definition": N_("forge.import.step.definition"), "states": N_("forge.import.step.states"),
                "continents": N_("forge.import.step.continents"), "climates": N_("forge.import.step.climates"),
                "owners": N_("forge.import.step.owners"), "economy": N_("forge.import.step.economy"),
                "names": N_("forge.import.step.names")}
ORIGIN_LABELS = {"file": N_("forge.import.from.file"), "rule": N_("forge.import.from.rule"),
                 "generated": N_("forge.import.from.generated"), "missing": N_("forge.import.from.missing")}
FILTERS = {"provinces": "*.bmp *.png", "terrain": "*.bmp *.png", "rivers": "*.bmp *.png",
           "heightmap": "*.png *.bmp", "mask": "*.png *.bmp", "definition": "*.csv", "default_map": "*.map",
           "positions": "*.txt", "fmg_json": "*.json"}


class ImportPanel(QWidget):
    inspectRequested = Signal()
    buildRequested = Signal()

    def __init__(self, parent: QWidget | None = None, *, slots=SLOTS) -> None:
        super().__init__(parent)
        self.slots = tuple(slots)
        self.files: dict[str, object] = {}
        self.report = None
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel()
        self.hint.setObjectName("forgeImportHint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.slot_table = QTableWidget(len(self.slots), 3)
        self.slot_table.setObjectName("forgeImportSlots")
        self.slot_table.verticalHeader().hide()
        self.slot_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.slot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.horizontalHeader().setStretchLastSection(True)
        self._buttons: dict[str, QPushButton] = {}
        for r, slot in enumerate(self.slots):
            button = QPushButton()
            button.setObjectName(f"forgeImportPick_{slot}")
            button.setIcon(make_icon("folder_open"))
            button.clicked.connect(lambda _c=False, s=slot: self.pick(s))
            self._buttons[slot] = button
            self.slot_table.setCellWidget(r, 2, button)
        layout.addWidget(self.slot_table, 2)
        form = QFormLayout()
        self.flip_label = QLabel()
        self.flip_combo = QComboBox()
        self.flip_combo.setObjectName("forgeImportFlip")
        for _ in range(3):
            self.flip_combo.addItem("")
        self.source_label = QLabel()
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("forgeImportSource")
        self.source_combo.addItem("", None)
        for s in LAND_SOURCES:
            self.source_combo.addItem("", s)
        form.addRow(self.flip_label, self.flip_combo)
        form.addRow(self.source_label, self.source_combo)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.inspect_button = QPushButton()
        self.inspect_button.setObjectName("forgeImportInspect")
        self.inspect_button.setIcon(make_icon("validate"))
        self.inspect_button.clicked.connect(self.inspectRequested)
        self.build_button = QPushButton()
        self.build_button.setObjectName("forgeImportBuild")
        self.build_button.setIcon(make_icon("map"))
        self.build_button.clicked.connect(self.buildRequested)
        row.addWidget(self.inspect_button)
        row.addWidget(self.build_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.matrix_title = QLabel()
        self.matrix_title.setObjectName("forgeImportMatrixTitle")
        layout.addWidget(self.matrix_title)
        self.matrix = QTableWidget(0, 2)
        self.matrix.setObjectName("forgeImportMatrix")
        self.matrix.verticalHeader().hide()
        self.matrix.horizontalHeader().hide()
        self.matrix.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.matrix.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.matrix, 2)
        self.issues = QTreeWidget()
        self.issues.setObjectName("forgeImportIssues")
        self.issues.setHeaderHidden(True)
        self.issues.setHeaderLabels([""])   # oculta, pero sin el «1» que Qt pone por defecto
        self.issues.setRootIsDecorated(False)
        layout.addWidget(self.issues, 1)
        self._refresh()

    def retranslate(self) -> None:
        self.hint.setText(tr("forge.import.hint"))
        self.slot_table.setHorizontalHeaderLabels([tr("forge.import.col.slot"), tr("forge.import.col.file"), ""])
        for slot, b in self._buttons.items():
            b.setText(tr("forge.import.pick"))
        self.flip_label.setText(tr("forge.import.flip"))
        flips = (N_("forge.import.flip.auto"), N_("forge.import.flip.no"), N_("forge.import.flip.yes"))
        for i, key in enumerate(flips):
            self.flip_combo.setItemText(i, tr(key))
        self.source_label.setText(tr("forge.import.source"))
        self.source_combo.setItemText(0, tr("forge.import.source.auto"))
        for i, s in enumerate(LAND_SOURCES, start=1):
            self.source_combo.setItemText(i, tr(SOURCE_LABELS[s]))
        self.inspect_button.setText(tr("forge.import.inspect"))
        self.build_button.setText(tr("forge.import.build"))
        self.matrix_title.setText(tr("forge.import.matrix"))
        self._refresh()

    # --- archivos -----------------------------------------------------------------------------------------

    def pick(self, slot: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr(SLOT_LABELS[slot]), "", FILTERS.get(slot, "*"))
        if path:
            self.set_file(slot, path)

    def set_file(self, slot: str, value) -> None:
        if value is None:
            self.files.pop(slot, None)
        else:
            self.files[slot] = value
        self.report = None
        self._refresh()

    def import_set(self) -> ImportSet:
        flip = {0: None, 1: False, 2: True}[self.flip_combo.currentIndex()]
        return ImportSet(dict(self.files), flip_y=flip, land_source=self.source_combo.currentData())

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - API de Qt
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            slot = guess_slot(path.name)
            if slot in self.slots:
                self.set_file(slot, str(path))

    # --- resultados ---------------------------------------------------------------------------------------

    def set_report(self, report) -> None:
        from .review import SEVERITY_ICONS
        from ...i18n import language

        self.report = report
        self.issues.clear()
        for issue in (report.issues if report is not None else []):
            item = QTreeWidgetItem([issue.message(language())])
            item.setIcon(0, make_icon(SEVERITY_ICONS.get(issue.severity, "info")))
            item.setToolTip(0, issue.code)
            self.issues.addTopLevelItem(item)
        self._refresh()

    def _refresh(self) -> None:
        for r, slot in enumerate(self.slots):
            self.slot_table.setItem(r, 0, QTableWidgetItem(tr(SLOT_LABELS[slot])))
            v = self.files.get(slot)
            name = Path(v).name if isinstance(v, (str, Path)) else (tr("forge.import.in_memory") if v else "—")
            self.slot_table.setItem(r, 1, QTableWidgetItem(name))
        matrix = self.report.matrix if self.report is not None else _guess_matrix(self.files)
        self.matrix.setRowCount(len(matrix))
        for r, (step, origin) in enumerate(matrix.items()):
            self.matrix.setItem(r, 0, QTableWidgetItem(tr(MATRIX_STEPS.get(step, "forge.import.step.names"))))
            kind, _, detail = origin.partition(":")
            text = tr(ORIGIN_LABELS.get(kind, "forge.import.from.generated"))
            if detail:
                text += f" ({tr(SOURCE_LABELS.get(detail, 'forge.import.source.auto'))})"
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, origin)
            self.matrix.setItem(r, 1, item)
        has_prov = "provinces" in self.files or "fmg_json" in self.files
        self.inspect_button.setEnabled(has_prov or "heightmap" in self.files)
        self.build_button.setEnabled((self.report is not None and self.report.ok) or
                                     ("heightmap" in self.files and not has_prov))


def guess_slot(name: str) -> str | None:
    n = name.lower()
    if n.endswith(".json"):
        return "fmg_json"
    for key, slot in (("provinces", "provinces"), ("definition", "definition"), ("default", "default_map"),
                      ("terrain", "terrain"), ("rivers", "rivers"), ("height", "heightmap"), ("mask", "mask"),
                      ("positions", "positions")):
        if key in n:
            return slot
    return None


def _guess_matrix(files: dict) -> dict:
    from ...core.mapforge.imports.bitmaps import ImportReport, _matrix

    rep = ImportReport()
    _matrix(ImportSet(dict(files)), rep)
    return rep.matrix


__all__ = ["ImportPanel", "guess_slot", "SLOT_LABELS"]
