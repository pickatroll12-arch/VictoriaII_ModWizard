"""Sección «Mundo» de la sala Mapa (wizard §16.1–§16.3): el lienzo con sus modos y la ficha de la provincia.

A la izquierda, el lienzo (``ui/map/canvas.py``) con la barra de modos, las fronteras, la fecha de trabajo y la
brocha; a la derecha, la ficha de la provincia elegida (dueño, controlador, núcleos, recursos, edificios y su
línea temporal), sus POPs y la leyenda del modo. Todo lo que cambia pasa por ``session.map`` (``MapSession``), una
transacción por gesto: un campo de la ficha, un núcleo o un trazo de brocha son un paso de deshacer.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ....core.map.borders import LEVEL_COUNTRY, LEVEL_PROVINCE, LEVEL_STATE
from ....core.map.modes import discover_modes
from ....i18n import N_, language, tr
from ...map.canvas import PICK_BRUSH, PICK_NONE, MapCanvas
from ...pages.base import BasePage
from ...session_map import RASTER_FAILED, RASTER_LOADING, RASTER_READY
from ...shell.working_date import WorkingDateSelector
from ...widgets import EmptyState, make_icon, show_in_stack

# Lo que la brocha puede pintar (``core.domain.province.PAINT_KEYS``) con su rótulo.
BRUSH_FIELDS = (
    ("owner", N_("map.field.owner")), ("controller", N_("map.field.controller")),
    ("trade_goods", N_("map.field.trade_goods")), ("life_rating", N_("map.field.life_rating")),
    ("terrain", N_("map.field.terrain")), ("railroad", N_("map.field.railroad")),
    ("fort", N_("map.field.fort")), ("naval_base", N_("map.field.naval_base")),
)
NUMERIC_FIELDS = ("life_rating", "railroad", "fort", "naval_base")
BORDER_LEVELS = ((LEVEL_PROVINCE, N_("map.borders.province")), (LEVEL_STATE, N_("map.borders.state")),
                 (LEVEL_COUNTRY, N_("map.borders.country")))
# Rótulos de los modos y textos de la leyenda que da el núcleo (``MapMode.label``, ``LegendItem.text_key``).
MODE_LABELS = (
    N_("map.mode.political"), N_("map.mode.rgo"), N_("map.mode.infrastructure"), N_("map.mode.life_rating"),
    N_("map.mode.terrain"), N_("map.mode.regions"), N_("map.mode.continents"), N_("map.mode.climates"),
    N_("map.mode.culture"), N_("map.mode.religion"), N_("map.mode.cores"), N_("map.mode.population"),
    N_("map.mode.ids"),
)
LEGEND_KEYS = (
    N_("map.legend.none"), N_("map.legend.zero"), N_("map.legend.pick_tag"), N_("map.legend.core"),
    N_("map.legend.owned_no_core"), N_("map.legend.range"), N_("map.legend.more_than"), N_("map.legend.no_pops"),
    N_("map.legend.ids"),
)
RASTER_ERRORS = (N_("map.error.no_provinces"), N_("map.error.no_definition"), N_("map.error.bad_bmp"),
                 N_("map.error.other"))
POP_COLUMNS = (N_("map.pops.col.type"), N_("map.pops.col.culture"), N_("map.pops.col.religion"),
               N_("map.pops.col.size"))
TAB_PROVINCE, TAB_POPS, TAB_LEGEND = 0, 1, 2


def _swatch(color: int) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor((color >> 16) & 255, (color >> 8) & 255, color & 255))
    return QIcon(pixmap)


class WorldPage(BasePage):
    key = "world"
    title_key = N_("section.map.world")
    subtitle_key = N_("map.world.subtitle")
    icon_name = "map"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.map = session.map
        self._province = 0
        self._loading_fields = False
        super().__init__(parent)
        self.map.rasterStateChanged.connect(self._on_raster_state)
        self.map.rasterProgress.connect(self._on_progress)
        self.map.factsChanged.connect(self._on_facts_changed)
        self.map.selectionChanged.connect(self._on_selection)
        session.projectOpened.connect(self._on_project_opened)
        session.projectClosed.connect(self._on_project_closed)
        session.documentsChanged.connect(self._on_documents_changed)
        session.workingDateChanged.connect(self._on_date_changed)
        self._update_state()

    # --- construcción -----------------------------------------------------------------------------------

    def build(self) -> None:
        self.date_selector = WorkingDateSelector(self.session)
        self.date_selector.setObjectName("workingDate")
        self.header.trailing.addWidget(self.date_selector, 0, Qt.AlignmentFlag.AlignVCenter)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("worldSplitter")
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addLayout(self._build_toolbar())
        left_layout.addLayout(self._build_brush())
        self.stack = QStackedWidget()
        self.canvas = MapCanvas(self.map)
        self.canvas.setMinimumSize(320, 240)
        self.canvas.provinceHovered.connect(self._on_hover)
        self.canvas.strokeFinished.connect(self._on_stroke)
        self.empty = EmptyState("map")
        self.load_button = QPushButton()
        self.load_button.setObjectName("mapLoad")
        self.load_button.clicked.connect(lambda: self.map.load_raster(force=self.map.raster_state == RASTER_FAILED))
        self.empty.add_action(self.load_button)
        self.progress = QProgressBar()
        self.progress.setObjectName("mapProgress")
        self.progress.setTextVisible(False)
        self.empty.extra.addWidget(self.progress)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas)
        left_layout.addWidget(self.stack, 1)
        self.hover_label = QLabel()
        self.hover_label.setObjectName("mapHover")
        left_layout.addWidget(self.hover_label)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("worldTabs")
        self.tabs.addTab(self._build_province(), "")
        self.tabs.addTab(self._build_pops(), "")
        self.tabs.addTab(self._build_legend(), "")
        self.tabs.setMinimumWidth(300)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.body.addWidget(splitter, 1)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.mode_label = QLabel()
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mapMode")
        for mode in discover_modes():
            self.mode_combo.addItem("", mode.key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_selected)
        self.mode_label.setBuddy(self.mode_combo)
        self.tag_edit = QLineEdit()
        self.tag_edit.setObjectName("mapCoresTag")
        self.tag_edit.setMaximumWidth(80)
        self.tag_edit.editingFinished.connect(self._on_mode_selected)
        self.tag_edit.hide()
        row.addWidget(self.mode_label)
        row.addWidget(self.mode_combo)
        row.addWidget(self.tag_edit)
        row.addSpacing(10)
        self.border_checks = {}
        for level, _key in BORDER_LEVELS:
            check = QCheckBox()
            check.setObjectName(f"mapBorders_{level}")
            check.setChecked(self.canvas_borders_default(level))
            check.toggled.connect(lambda on, level=level: self.canvas.set_borders(level, on))
            self.border_checks[level] = check
            row.addWidget(check)
        row.addStretch(1)
        return row

    @staticmethod
    def canvas_borders_default(level: str) -> bool:
        return level in (LEVEL_PROVINCE, LEVEL_COUNTRY)

    def _build_brush(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.brush_button = QToolButton()
        self.brush_button.setObjectName("mapBrush")
        self.brush_button.setCheckable(True)
        self.brush_button.setIcon(make_icon("quill", "gold_light"))
        self.brush_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.brush_button.toggled.connect(self._on_brush_toggled)
        self.brush_field = QComboBox()
        self.brush_field.setObjectName("mapBrushField")
        for key, _label in BRUSH_FIELDS:
            self.brush_field.addItem("", key)
        self.brush_value = QLineEdit()
        self.brush_value.setObjectName("mapBrushValue")
        self.brush_value.setMaximumWidth(140)
        self.brush_hint = QLabel()
        self.brush_hint.setObjectName("mapBrushHint")
        row.addWidget(self.brush_button)
        row.addWidget(self.brush_field)
        row.addWidget(self.brush_value)
        row.addWidget(self.brush_hint, 1)
        return row

    def _build_province(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        self.province_title = QLabel()
        self.province_title.setObjectName("provinceTitle")
        self.province_title.setWordWrap(True)
        layout.addWidget(self.province_title)
        self.province_info = QLabel()
        self.province_info.setObjectName("provinceInfo")
        self.province_info.setWordWrap(True)
        layout.addWidget(self.province_info)
        self.form = QFormLayout()
        self.form_labels = {}
        self.editors = {}
        for key in ("owner", "controller", "trade_goods", "terrain"):
            edit = QLineEdit()
            edit.setObjectName(f"province_{key}")
            edit.editingFinished.connect(lambda key=key: self._commit_text(key))
            self._add_row(key, edit)
        for key, maximum in (("life_rating", 100), ("railroad", 6), ("fort", 6), ("naval_base", 6)):
            spin = QSpinBox()
            spin.setObjectName(f"province_{key}")
            spin.setRange(0, maximum)
            spin.editingFinished.connect(lambda key=key: self._commit_number(key))
            self._add_row(key, spin)
        cores = QLineEdit()
        cores.setObjectName("province_cores")
        cores.editingFinished.connect(self._commit_cores)
        self._add_row("cores", cores)
        layout.addLayout(self.form)
        self.timeline_label = QLabel()
        layout.addWidget(self.timeline_label)
        self.timeline = QListWidget()
        self.timeline.setObjectName("provinceTimeline")
        self.timeline.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.timeline, 1)
        return page

    def _add_row(self, key: str, editor: QWidget) -> None:
        label = QLabel()
        self.form_labels[key] = label
        self.editors[key] = editor
        self.form.addRow(label, editor)

    def _build_pops(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        self.pops_summary = QLabel()
        self.pops_summary.setObjectName("popsSummary")
        self.pops_summary.setWordWrap(True)
        layout.addWidget(self.pops_summary)
        self.pops_table = QTableWidget(0, len(POP_COLUMNS))
        self.pops_table.setObjectName("popsTable")
        self.pops_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                        | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.pops_table.verticalHeader().hide()
        self.pops_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pops_table.itemChanged.connect(self._on_pop_edited)
        layout.addWidget(self.pops_table, 1)
        row = QHBoxLayout()
        self.scale_spin = QSpinBox()
        self.scale_spin.setObjectName("popsScale")
        self.scale_spin.setRange(10, 500)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setValue(110)
        self.scale_spin.setSuffix(" %")
        self.scale_button = QPushButton()
        self.scale_button.setObjectName("popsScaleButton")
        self.scale_button.clicked.connect(self._scale_pops)
        row.addWidget(self.scale_spin)
        row.addWidget(self.scale_button)
        row.addStretch(1)
        layout.addLayout(row)
        self._pop_refs = []
        return page

    def _build_legend(self) -> QWidget:
        self.legend = QListWidget()
        self.legend.setObjectName("mapLegend")
        self.legend.setIconSize(QSize(14, 14))
        self.legend.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return self.legend

    # --- textos -------------------------------------------------------------------------------------

    def retranslate(self) -> None:
        super().retranslate()
        modes = {mode.key: mode for mode in discover_modes()}
        for index in range(self.mode_combo.count()):
            mode = modes.get(self.mode_combo.itemData(index))
            if mode is not None:
                self.mode_combo.setItemText(index, tr(mode.label))
        self.mode_label.setText(tr("map.mode"))
        self.tag_edit.setPlaceholderText(tr("map.cores_tag"))
        for level, key in BORDER_LEVELS:
            self.border_checks[level].setText(tr(key))
        for index, (_key, label) in enumerate(BRUSH_FIELDS):
            self.brush_field.setItemText(index, tr(label))
        self.brush_button.setText(tr("map.brush"))
        self.brush_button.setToolTip(tr("map.brush_tooltip"))
        self.brush_value.setPlaceholderText(tr("map.brush_value"))
        self.brush_hint.setText(tr("map.brush_hint") if self.brush_button.isChecked() else "")
        labels = dict(BRUSH_FIELDS)
        for key, label in self.form_labels.items():
            label.setText(tr(labels[key]) if key in labels else tr("map.field.cores"))
        self.editors["cores"].setPlaceholderText(tr("map.cores_hint"))
        self.timeline_label.setText(tr("map.timeline"))
        self.tabs.setTabText(TAB_PROVINCE, tr("map.tab.province"))
        self.tabs.setTabText(TAB_POPS, tr("map.tab.pops"))
        self.tabs.setTabText(TAB_LEGEND, tr("map.tab.legend"))
        self.pops_table.setHorizontalHeaderLabels([tr(key) for key in POP_COLUMNS])
        self.scale_button.setText(tr("map.pops.scale"))
        self.load_button.setText(tr("map.load"))
        self._update_state()
        self._show_province()
        self._fill_legend()

    # --- estado del ráster ----------------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().showEvent(event)
        if self.session.project is not None and self.map.raster_state not in (RASTER_READY, RASTER_LOADING,
                                                                               RASTER_FAILED):
            self.map.load_raster()
        if self.map.raster is not None and self.map.facts is None:
            self.map.refresh_facts()

    def is_busy(self) -> bool:
        return self.map.raster_state == RASTER_LOADING

    def _update_state(self) -> None:
        state = self.map.raster_state
        if self.session.project is None:
            self.empty.set_texts(tr("map.empty.no_project"), tr("map.empty.no_project_text"))
            self.load_button.hide()
            self.progress.hide()
            show_in_stack(self.stack, self.empty)
        elif state == RASTER_READY:
            show_in_stack(self.stack, self.canvas)
        elif state == RASTER_LOADING:
            self.empty.set_texts(tr("map.empty.loading"), tr("map.empty.loading_text"))
            self.load_button.hide()
            self.progress.show()
            show_in_stack(self.stack, self.empty)
        elif state == RASTER_FAILED:
            self.empty.set_texts(tr("map.empty.failed"), tr(self.map.raster_error or "map.error.other"))
            self.load_button.show()
            self.progress.hide()
            show_in_stack(self.stack, self.empty)
        else:
            self.empty.set_texts(tr("map.empty.idle"), tr("map.empty.idle_text"))
            self.load_button.show()
            self.progress.hide()
            show_in_stack(self.stack, self.empty)

    def _on_raster_state(self) -> None:
        self._update_state()

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def _on_project_opened(self, project) -> None:
        self.date_selector.reload()
        self._update_state()
        if self.isVisible():
            self.map.load_raster()

    def _on_project_closed(self) -> None:
        self._province = 0
        self._update_state()
        self._show_province()
        self._fill_legend()

    def _on_date_changed(self, date) -> None:
        self._show_province()

    def _on_documents_changed(self, rels) -> None:
        if any("bookmarks" in str(rel).lower() for rel in rels or ()):
            self.date_selector.reload()
        if self._province:
            QTimer.singleShot(0, self._show_province)

    # --- modos ---------------------------------------------------------------------------------------

    def _on_mode_selected(self, *args) -> None:
        key = self.mode_combo.currentData()
        if key is None:
            return
        is_cores = key == "cores"
        self.tag_edit.setVisible(is_cores)
        param = self.tag_edit.text().strip().upper() or None if is_cores else None
        self.canvas.set_mode(key, param=param)
        self._fill_legend()

    def set_mode(self, key: str, param=None) -> None:
        """Elige el modo ``key`` en la barra (lo que haría el usuario)."""
        index = self.mode_combo.findData(key)
        if index < 0:
            raise KeyError(key)
        if key == "cores" and param is not None:
            self.tag_edit.setText(str(param))
        if self.mode_combo.currentIndex() == index:
            self._on_mode_selected()
        else:
            self.mode_combo.setCurrentIndex(index)

    def _legend_text(self, item) -> str:
        if item.symbol is not None:
            kind, name = item.symbol
            locsync = self.session.locsync
            text = None
            if locsync is not None:
                try:
                    text = locsync.text(name, language())
                except Exception:  # noqa: BLE001 - un texto que no se lee deja el nombre
                    text = None
            return f"{text} ({name})" if text and text != name else name
        if item.text_key:
            return tr(item.text_key, **dict(item.args))
        return item.text

    def _fill_legend(self) -> None:
        self.legend.clear()
        facts = self.map.facts
        key = self.canvas.mode()
        if facts is None or key is None:
            return
        modes = {mode.key: mode for mode in discover_modes()}
        mode = modes.get(key)
        if mode is None:
            return
        try:
            items = mode.legend(facts, self.session.index, param=self.canvas.mode_param())
        except Exception:  # noqa: BLE001 - una leyenda rota no tumba la página
            items = []
        for item in items:
            text = self._legend_text(item)
            if item.count is not None:
                text = tr("map.legend.count", text=text, count=item.count)
            entry = QListWidgetItem(_swatch(item.color), text)
            self.legend.addItem(entry)

    def _on_facts_changed(self, pids) -> None:
        if pids is None:
            self._fill_legend()
        if self._province and (pids is None or self._province in pids):
            self._show_province()

    # --- brocha ---------------------------------------------------------------------------------------

    def _on_brush_toggled(self, on: bool) -> None:
        self.canvas.set_pick_mode(PICK_BRUSH if on else PICK_NONE)
        self.brush_hint.setText(tr("map.brush_hint") if on else "")

    def brush_value_typed(self):
        key = self.brush_field.currentData()
        text = self.brush_value.text().strip()
        if not text:
            return None
        if key in NUMERIC_FIELDS:
            try:
                return int(text)
            except ValueError:
                return None
        return text.upper() if key in ("owner", "controller") else text

    def _on_stroke(self, pids) -> None:
        key = self.brush_field.currentData()
        value = self.brush_value_typed()
        if value is None:
            self.request_status("map.status.brush_empty")
            self.canvas.set_selection(self.map.selection)
            return
        try:
            count = self.map.paint(pids, key, value)
        except Exception as exc:  # noqa: BLE001 - el motivo se muestra
            self.request_status("map.status.failed", error=str(exc))
            count = 0
        self.canvas.set_selection(self.map.selection)
        self.request_status("map.status.painted", count=count, field=tr(dict(BRUSH_FIELDS)[key]),
                            value=str(value))

    # --- ficha de la provincia ------------------------------------------------------------------------

    def _on_hover(self, pid: int) -> None:
        if not pid:
            self.hover_label.setText("")
            return
        name = self.map.province_name(pid)
        self.hover_label.setText(tr("map.hover", id=pid, name=name or "—"))

    def _on_selection(self, pids) -> None:
        self._province = pids[-1] if pids else 0
        self._show_province()

    def select_province(self, pid: int, *, center: bool = True) -> None:
        self.map.set_selection((int(pid),))
        if center:
            self.canvas.center_on_province(int(pid))

    def focus_field(self, ref, field=()) -> bool:
        """Abre la ficha de la provincia de ``ref`` (su historia o un bloque de POPs)."""
        ident = str(getattr(ref, "ident", ref))
        number = ident.split(":", 1)[1].split("#", 1)[0] if ":" in ident else ident
        if not number.isdigit():
            return False
        self.select_province(int(number))
        self.tabs.setCurrentIndex(TAB_POPS if getattr(ref, "kind", "") == "pops" else TAB_PROVINCE)
        return True

    def _show_province(self) -> None:
        pid = self._province
        provinces = self.map.provinces if self.session.project is not None else None
        enabled = bool(pid) and provinces is not None
        for editor in self.editors.values():
            editor.setEnabled(enabled)
        self.timeline.clear()
        if not enabled:
            self.province_title.setText(tr("map.province.none"))
            self.province_info.setText("")
            self._fill_pops(None, None)
            return
        try:
            info = provinces.info(pid)
        except Exception:  # noqa: BLE001 - un id fuera de definition.csv
            self.province_title.setText(tr("map.province.unknown", id=pid))
            self.province_info.setText("")
            self._fill_pops(None, None)
            return
        date = self.session.working_date
        name = self.map.province_name(pid) or info.name
        self.province_title.setText(tr("map.province.title", id=pid, name=name))
        lines = [tr("map.province.sea") if info.is_sea else tr("map.province.land")]
        if info.region:
            lines.append(tr("map.province.region", region=info.region))
        if info.continent:
            lines.append(tr("map.province.continent", continent=info.continent))
        if info.climate:
            lines.append(tr("map.province.climate", climate=info.climate))
        facts = self.map.facts
        if facts is not None and 0 < pid < facts.size:
            terrain = facts.name("terrains", int(facts.terrain[pid]))
            if terrain:
                lines.append(tr("map.province.terrain_map", terrain=terrain))
        lines.append(tr("map.province.file", file=str(info.history)) if info.history
                     else tr("map.province.no_history"))
        if info.duplicates:
            lines.append(tr("map.province.duplicates", count=len(info.duplicates)))
        self.province_info.setText("\n".join(lines))
        for editor in self.editors.values():
            editor.setEnabled(not info.is_sea)
        state = provinces.state(pid, date)
        self._loading_fields = True
        try:
            for key in ("owner", "controller", "trade_goods", "terrain"):
                self.editors[key].setText(getattr(state, key) or "")
            self.editors["life_rating"].setValue(state.life_rating or 0)
            for key in ("railroad", "fort", "naval_base"):
                self.editors[key].setValue(getattr(state, key))
            self.editors["cores"].setText(" ".join(state.cores))
        finally:
            self._loading_fields = False
        for event in provinces.timeline(pid):
            changes = ", ".join(f"{key} = {value}" for key, value in event.changes)
            self.timeline.addItem(QListWidgetItem(f"{event.date} · {changes}"))
        self._fill_pops(pid, date)

    def _commit(self, key: str, value) -> None:
        if self._loading_fields or not self._province:
            return
        try:
            changed = self.map.set_value(self._province, key, value)
        except Exception as exc:  # noqa: BLE001 - el motivo se muestra
            self.request_status("map.status.failed", error=str(exc))
            self._show_province()
            return
        if changed:
            label = tr(dict(BRUSH_FIELDS)[key])
            self.request_status("map.status.set", id=self._province, field=label,
                                value="—" if value is None else str(value))

    def _commit_text(self, key: str) -> None:
        text = self.editors[key].text().strip()
        if key in ("owner", "controller"):
            text = text.upper()
        self._commit(key, text or None)

    def _commit_number(self, key: str) -> None:
        self._commit(key, int(self.editors[key].value()))

    def _commit_cores(self) -> None:
        if self._loading_fields or not self._province:
            return
        provinces = self.map.provinces
        wanted = [tag.upper() for tag in self.editors["cores"].text().replace(",", " ").split() if tag]
        current = [tag.upper() for tag in provinces.cores(self._province, self.session.working_date)]
        try:
            for tag in current:
                if tag not in wanted:
                    self.map.set_core(self._province, tag, False)
            for tag in wanted:
                if tag not in current:
                    self.map.set_core(self._province, tag, True)
        except Exception as exc:  # noqa: BLE001 - el motivo se muestra
            self.request_status("map.status.failed", error=str(exc))
        self._show_province()

    # --- POPs ---------------------------------------------------------------------------------------

    def _fill_pops(self, pid, date) -> None:
        self._loading_fields = True
        try:
            self.pops_table.setRowCount(0)
            self._pop_refs = []
            if not pid:
                self.pops_summary.setText("")
                self.scale_button.setEnabled(False)
                return
            pops = self.map.provinces.pops()
            blocks = pops.pops_index.blocks(pid, date)
            folder = pops.pops_index.folder_for(date)
            total = 0
            for ref in blocks:
                try:
                    found = pops.read(ref)
                except (KeyError, FileNotFoundError):
                    continue
                for pop in found:
                    row = self.pops_table.rowCount()
                    self.pops_table.insertRow(row)
                    for column, value in enumerate((pop.type, pop.culture, pop.religion, str(pop.size))):
                        item = QTableWidgetItem(value)
                        self.pops_table.setItem(row, column, item)
                    self._pop_refs.append((ref, pop.index))
                    total += pop.size
            if folder is None:
                self.pops_summary.setText(tr("map.pops.no_folder"))
            elif not blocks:
                self.pops_summary.setText(tr("map.pops.none", folder=str(folder)))
            else:
                self.pops_summary.setText(tr("map.pops.summary", total=total, count=len(self._pop_refs),
                                             folder=str(folder), blocks=len(blocks)))
            self.scale_button.setEnabled(bool(blocks))
        finally:
            self._loading_fields = False

    def _on_pop_edited(self, item: QTableWidgetItem) -> None:
        if self._loading_fields or not self._province:
            return
        row, column = item.row(), item.column()
        if row >= len(self._pop_refs):
            return
        ref, index = self._pop_refs[row]
        text = item.text().strip()
        keys = ("type", "culture", "religion", "size")
        values = {keys[column]: text}
        if column == 3:
            try:
                values["size"] = int(text)
            except ValueError:
                self._show_province()
                return
        from ....core.domain.province import UNDO_POPS

        pops = self.map.provinces.pops()
        try:
            with self.session.edit(UNDO_POPS, province=self._province):
                pops.set(ref, index, **values)
        except Exception as exc:  # noqa: BLE001 - el motivo se muestra
            self.request_status("map.status.failed", error=str(exc))
        self._after_pops()

    def _scale_pops(self) -> None:
        if not self._province:
            return
        from ....core.domain.province import UNDO_POPS

        pops = self.map.provinces.pops()
        factor = self.scale_spin.value() / 100.0
        blocks = pops.pops_index.blocks(self._province, self.session.working_date)
        if not blocks:
            return
        with self.session.edit(UNDO_POPS, province=self._province):
            for ref in blocks:
                pops.scale(ref, factor)
        self._after_pops()

    def _after_pops(self) -> None:
        pid = self._province
        pops = self.map.provinces.pops()
        facts = self.map.facts
        date = self.session.working_date
        if facts is not None:
            culture, religion = pops.majority(pid, date)
            facts.set_population(pid, pops.total(pid, date), culture, religion)
            self.map.factsChanged.emit(frozenset({pid}))
        self._show_province()
