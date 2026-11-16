"""Sección «Guerras de inicio» de la sala Guerra (wizard §14.8). Iteración 6.

Arriba, la línea temporal de todas las guerras (``WarTimeline``); debajo, la lista y el detalle de la elegida:
sus bandos con quién entra y sale en cada fecha, y sus objetivos (CB, actor, receptor, estado y tercer país).
«Nueva guerra…» abre ``NewWarDialog``: nombre, fechas, atacantes y defensores (el primero de cada bando es su
líder) y objetivos, cuyos campos «estado» y «tercer país» se activan según las opciones de paz (``po_*``) del CB.
El diálogo enseña el archivo que va a crear y lo crea en **una** transacción (``undo.new_war``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ....core.domain import war as core_war
from ....i18n import N_, tr, translator
from ...countries import domain_context
from ...pages.base import BasePage
from ...pickers.fields import SymbolPicker
from ...pickers.province_picker import LAND, ProvincePicker
from ...pickers.tag_picker import SymbolListPicker, TagPicker
from ...widgets import make_icon, mark_data
from .war_timeline import WarTimeline

ROLE_REL = Qt.ItemDataRole.UserRole
ACTION_LABELS = {"add_attacker": N_("war.action.add_attacker"), "add_defender": N_("war.action.add_defender"),
                 "rem_attacker": N_("war.action.rem_attacker"), "rem_defender": N_("war.action.rem_defender")}
WAR_ERRORS = {"no_name": N_("war.error.no_name"), "no_date": N_("war.error.no_date"),
              "no_sides": N_("war.error.no_sides"), "same_side": N_("war.error.same_side"),
              "dates_order": N_("war.error.dates_order"), "file_exists": N_("war.error.file_exists"),
              "relation_type": N_("war.error.relation_type"), "relation_same": N_("war.error.relation_same"),
              "relation_exists": N_("war.error.relation_exists")}
GOAL_COLUMNS = (N_("war.goal.cb"), N_("war.goal.actor"), N_("war.goal.receiver"), N_("war.goal.state"),
                N_("war.goal.country"), N_("war.goal.date"))


def war_error_text(exc: core_war.WarError) -> str:
    return tr(WAR_ERRORS.get(exc.code, N_("war.error.no_name")), detail=exc.detail)


class NewWarDialog(QDialog):
    """El asistente «Nueva guerra»; ``spec()`` da la ``WarSpec`` y ``create()`` la aplica."""

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setObjectName("newWarDialog")
        self.resize(820, 680)
        self.created_rel = None
        self.goals: list[core_war.WarGoal] = []
        outer = QVBoxLayout(self)
        form = QFormLayout()
        self.labels = [QLabel() for _ in range(5)]
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("warName")
        self.start_edit = QLineEdit(str(getattr(session, "working_date", "") or "1836.1.1"))
        self.start_edit.setObjectName("warStart")
        self.end_check = QCheckBox()
        self.end_check.setObjectName("warHasEnd")
        self.end_edit = QLineEdit()
        self.end_edit.setObjectName("warEnd")
        self.end_edit.setEnabled(False)
        self.end_check.toggled.connect(self.end_edit.setEnabled)
        self.attackers = SymbolListPicker(session, "tag")
        self.attackers.setObjectName("warAttackers")
        self.defenders = SymbolListPicker(session, "tag")
        self.defenders.setObjectName("warDefenders")
        end_row = QHBoxLayout()
        end_row.addWidget(self.end_check)
        end_row.addWidget(self.end_edit, 1)
        form.addRow(self.labels[0], self.name_edit)
        form.addRow(self.labels[1], self.start_edit)
        form.addRow(self.labels[2], end_row)
        form.addRow(self.labels[3], self.attackers)
        form.addRow(self.labels[4], self.defenders)
        outer.addLayout(form)
        self.goals_title = QLabel()
        outer.addWidget(self.goals_title)
        goal_form = QHBoxLayout()
        self.cb_picker = SymbolPicker(session, "cb")
        self.cb_picker.setObjectName("warGoalCb")
        self.cb_picker.value_committed.connect(self._on_cb)
        self.actor_combo = QComboBox()
        self.actor_combo.setObjectName("warGoalActor")
        self.receiver_combo = QComboBox()
        self.receiver_combo.setObjectName("warGoalReceiver")
        self.state_picker = ProvincePicker(session, allow=LAND)
        self.state_picker.setObjectName("warGoalState")
        self.country_picker = TagPicker(session)
        self.country_picker.setObjectName("warGoalCountry")
        self.goal_add = QPushButton()
        self.goal_add.setObjectName("warGoalAdd")
        self.goal_add.setIcon(make_icon("plus", "gold_light"))
        self.goal_add.clicked.connect(self.add_goal_from_form)
        for widget in (self.cb_picker, self.actor_combo, self.receiver_combo, self.state_picker, self.country_picker,
                       self.goal_add):
            goal_form.addWidget(widget)
        outer.addLayout(goal_form)
        self.goal_hint = QLabel()
        self.goal_hint.setObjectName("warGoalHint")
        self.goal_hint.setWordWrap(True)
        outer.addWidget(self.goal_hint)
        self.goal_table = mark_data(QTableWidget(0, len(GOAL_COLUMNS) - 1))
        self.goal_table.setObjectName("warGoals")
        self.goal_table.verticalHeader().hide()
        self.goal_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.goal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.goal_table.setMaximumHeight(120)
        outer.addWidget(self.goal_table)
        self.preview_title = QLabel()
        outer.addWidget(self.preview_title)
        self.preview = mark_data(QPlainTextEdit())
        self.preview.setObjectName("warPreview")
        self.preview.setReadOnly(True)
        outer.addWidget(self.preview, 1)
        self.error_label = QLabel()
        self.error_label.setObjectName("warError")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.create)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        for model in (self.attackers.list.model(), self.defenders.list.model()):
            model.rowsInserted.connect(self._on_sides)
            model.rowsRemoved.connect(self._on_sides)
            model.rowsMoved.connect(self._on_sides)
        for edit in (self.name_edit, self.start_edit, self.end_edit):
            edit.textChanged.connect(self.refresh_preview)
        self.end_check.toggled.connect(self.refresh_preview)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()
        self._on_cb(None)

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr(N_("war.new.title")))
        for label, key in zip(self.labels, (N_("war.field.name"), N_("war.field.start"), N_("war.field.end"),
                                            N_("war.field.attackers"), N_("war.field.defenders"))):
            label.setText(tr(key))
        self.end_check.setText(tr(N_("war.new.has_end")))
        self.goals_title.setText(tr(N_("war.new.goals")))
        self.goal_add.setText(tr(N_("war.new.add_goal")))
        self.goal_table.setHorizontalHeaderLabels([tr(key) for key in GOAL_COLUMNS[:-1]])
        self.preview_title.setText(tr(N_("war.new.preview")))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr(N_("war.new.create")))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr(N_("entity.cancel")))
        self._on_cb(self.cb_picker.value())
        self.refresh_preview()

    def _on_sides(self, *args) -> None:
        tags = self.attackers.values() + self.defenders.values()
        for combo, default in ((self.actor_combo, self.attackers.values()), (self.receiver_combo,
                                                                             self.defenders.values())):
            current = combo.currentData()
            combo.clear()
            for tag in tags:
                combo.addItem(tag, tag)
            index = combo.findData(current) if current in default else -1
            if index < 0 and default:
                index = combo.findData(default[0])
            if index < 0:
                index = combo.findData(current) if current else -1
            combo.setCurrentIndex(max(index, 0) if tags else -1)
        self.refresh_preview()

    def _on_cb(self, cb) -> None:
        state, country = core_war.goal_needs(getattr(self.session, "index", None), cb)
        self.state_picker.setEnabled(state)
        self.country_picker.setEnabled(country)
        hints = []
        if state:
            hints.append(tr(N_("war.new.hint_state")))
        if country:
            hints.append(tr(N_("war.new.hint_country")))
        self.goal_hint.setText(" ".join(hints) if cb else tr(N_("war.new.hint_cb")))

    def add_goal(self, cb: str, actor: str, receiver: str, state: int | None = None,
                 country: str | None = None) -> None:
        self.goals.append(core_war.WarGoal(cb, actor, receiver, state, country))
        self._fill_goals()

    def add_goal_from_form(self) -> bool:
        cb, actor, receiver = self.cb_picker.value(), self.actor_combo.currentData(), self.receiver_combo.currentData()
        if not cb or not actor or not receiver:
            self.error_label.setText(tr(N_("war.error.goal_incomplete")))
            return False
        needs_state, needs_country = core_war.goal_needs(self.session.index, cb)
        state = self.state_picker.value() if needs_state else None
        country = self.country_picker.value() if needs_country else None
        self.add_goal(cb, actor, receiver, state, country)
        return True

    def _fill_goals(self) -> None:
        self.goal_table.setRowCount(len(self.goals))
        for row, goal in enumerate(self.goals):
            values = (goal.casus_belli, goal.actor, goal.receiver,
                      "" if goal.state_province_id is None else str(goal.state_province_id), goal.country or "")
            for column, value in enumerate(values):
                self.goal_table.setItem(row, column, QTableWidgetItem(value))
        self.refresh_preview()

    def spec(self) -> core_war.WarSpec:
        end = self.end_edit.text().strip() if self.end_check.isChecked() else None
        return core_war.WarSpec(self.name_edit.text().strip(), self.start_edit.text().strip(),
                                tuple(self.attackers.values()), tuple(self.defenders.values()),
                                tuple(self.goals), end or None)

    def problem(self) -> str | None:
        try:
            core_war.check_war(self.spec())
        except core_war.WarError as exc:
            return war_error_text(exc)
        return None

    def refresh_preview(self, *args) -> None:
        problem = self.problem()
        self.error_label.setText(problem or "")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(problem is None)
        if problem is not None:
            self.preview.setPlainText("")
            return
        spec = self.spec()
        context = domain_context(self.session)
        prefix = getattr(getattr(context, "settings", None), "prefix", None) or "MOD"
        rel = core_war.war_rel(spec, prefix)
        text = core_war.war_text(spec).decode("cp1252", "replace").replace("\r\n", "\n")
        self.preview.setPlainText(f"# {rel}\n{text}")

    def create(self) -> bool:
        context = domain_context(self.session)
        if context is None or self.problem() is not None:
            return False
        spec = self.spec()
        try:
            with self.session.edit(core_war.UNDO_NEW_WAR, name=spec.name):
                self.created_rel = core_war.build_war(context, spec)
        except core_war.WarError as exc:
            self.error_label.setText(war_error_text(exc))
            return False
        self.accept()
        return True


class WarsPage(BasePage):
    key = "wars"
    title_key = N_("section.war.wars")
    subtitle_key = N_("war.wars.subtitle")
    icon_name = "swords"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.items: list[tuple[object, core_war.WarModel]] = []
        self.dialog = None
        self._stale = False                    # la lista espera a que la página se vea (ver ``reload``)
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        session.workingDateChanged.connect(self.reload)
        session.indexStateChanged.connect(self.reload)
        self.reload()

    def build(self) -> None:
        top = QHBoxLayout()
        self.new_button = QPushButton()
        self.new_button.setObjectName("warsNew")
        self.new_button.setIcon(make_icon("plus", "gold_light"))
        self.new_button.clicked.connect(self.open_new_war)
        self.active_label = QLabel()
        self.active_label.setObjectName("warsActive")
        top.addWidget(self.new_button)
        top.addWidget(self.active_label, 1)
        self.body.addLayout(top)
        self.timeline = WarTimeline()
        self.timeline.warClicked.connect(self.select_row)
        self.body.addWidget(self.timeline)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("warsList")
        self.list.currentRowChanged.connect(self._show)
        splitter.addWidget(self.list)
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(6, 0, 0, 0)
        self.detail_title = mark_data(QLabel())      # nombre de la guerra: dato
        self.detail_title.setObjectName("warsDetailTitle")
        self.detail_title.setProperty("role", "title")
        layout.addWidget(self.detail_title)
        self.detail_info = QLabel()
        self.detail_info.setObjectName("warsDetailInfo")
        self.detail_info.setWordWrap(True)
        self.detail_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_info)
        self.events_title = QLabel()
        layout.addWidget(self.events_title)
        self.events = mark_data(QTableWidget(0, 3))
        self.events.setObjectName("warsEvents")
        self.events.verticalHeader().hide()
        self.events.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.events.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.events.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.events, 1)
        self.goals_title = QLabel()
        layout.addWidget(self.goals_title)
        self.goals = mark_data(QTableWidget(0, len(GOAL_COLUMNS)))
        self.goals.setObjectName("warsGoals")
        self.goals.verticalHeader().hide()
        self.goals.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.goals.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.goals, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self.body.addWidget(splitter, 1)

    def retranslate(self) -> None:
        super().retranslate()
        self.new_button.setText(tr(N_("war.new.button")))
        self.events_title.setText(tr(N_("war.wars.events")))
        self.goals_title.setText(tr(N_("war.wars.goals")))
        self.events.setHorizontalHeaderLabels([tr(N_("war.col.date")), tr(N_("war.col.action")),
                                               tr(N_("war.col.tag"))])
        self.goals.setHorizontalHeaderLabels([tr(key) for key in GOAL_COLUMNS])
        self.reload()

    # --- datos ------------------------------------------------------------------------------------

    def _on_documents(self, rels) -> None:
        if any(str(rel).lower().startswith(core_war.WARS_FOLDER + "/") for rel in rels or ()):
            self.reload()

    def reload(self, *args) -> None:
        """Rehace la lista de guerras. Fuera de la vista solo se apunta y se rehace al enseñarla (o al pedir sus
        datos): leer todas las guerras y las reglas del juego en cada reindexado frenaba la interfaz al validar."""
        if self.session.project is not None and not self.isVisible():
            self._stale = True
            self._render_active()                # el idioma cambia aunque la lista espere
            return
        self._stale = False
        self._reload_now()

    def _ensure_loaded(self) -> None:
        if self._stale:
            self._stale = False
            self._reload_now()

    def showEvent(self, event) -> None:
        self._ensure_loaded()
        super().showEvent(event)

    def _render_active(self) -> None:
        """«N de M guerras activas en <fecha>» con la lista actual (vacío sin proyecto)."""
        if self.session.project is None:
            self.active_label.setText("")
            return
        date = str(self.session.working_date)
        active = sum(1 for _rel, model in self.items if model.active_at(date))
        self.active_label.setText(tr(N_("war.wars.active"), count=active, total=len(self.items), date=date))

    def _reload_now(self) -> None:
        context = domain_context(self.session)
        current = self.current_rel()
        self.items = core_war.wars(context) if context is not None else []
        self.list.blockSignals(True)
        self.list.clear()
        date = str(self.session.working_date) if self.session.project is not None else None
        active = 0
        for rel, model in self.items:
            on = date is not None and model.active_at(date)
            active += on
            item = QListWidgetItem(("● " if on else "○ ") + (model.name or rel.name))
            item.setData(ROLE_REL, rel)
            self.list.addItem(item)
        self.list.blockSignals(False)
        rules = self.session.map.rules() if self.session.project is not None and hasattr(self.session, "map") \
            else None
        self.timeline.set_data([(model.name or rel.name, model.start, model.end) for rel, model in self.items],
                               getattr(rules, "bookmarks", ()) or (), date, getattr(rules, "end_date", None))
        self._render_active()
        self.new_button.setEnabled(self.session.project is not None)
        row = next((i for i, (rel, _m) in enumerate(self.items) if current is not None and rel == current), 0)
        if self.items:
            self.select_row(row)
        else:
            self._show(-1)

    def current_rel(self):
        self._ensure_loaded()
        item = self.list.currentItem()
        return item.data(ROLE_REL) if item is not None else None

    def select_row(self, row: int) -> None:
        self._ensure_loaded()
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
            self._show(row)

    def select_war(self, ident: str) -> bool:
        self._ensure_loaded()
        wanted = ident.lower().removesuffix(".txt")
        for row, (rel, model) in enumerate(self.items):
            if rel.name.lower().removesuffix(".txt") == wanted or model.name.lower() == wanted:
                self.select_row(row)
                return True
        return False

    def _show(self, row: int) -> None:
        self.timeline.selected = row
        self.timeline.update()
        if not 0 <= row < len(self.items):
            self.detail_title.setText(tr(N_("war.wars.none")))
            self.detail_info.setText("")
            self.events.setRowCount(0)
            self.goals.setRowCount(0)
            return
        rel, model = self.items[row]
        self.detail_title.setText(model.name or rel.name)
        self.detail_info.setText(tr(N_("war.wars.info"), file=str(rel), start=model.start or "?",
                                    end=model.end or tr(N_("war.wars.open")),
                                    attackers=", ".join(model.attackers) or "—",
                                    defenders=", ".join(model.defenders) or "—"))
        self.events.setRowCount(len(model.events))
        for index, event in enumerate(model.events):
            for column, value in enumerate((event.date, tr(ACTION_LABELS[event.action]), event.tag)):
                self.events.setItem(index, column, QTableWidgetItem(value))
        self.goals.setRowCount(len(model.goals))
        for index, goal in enumerate(model.goals):
            values = (goal.casus_belli, goal.actor, goal.receiver,
                      "" if goal.state_province_id is None else str(goal.state_province_id), goal.country or "",
                      goal.date or "")
            for column, value in enumerate(values):
                self.goals.setItem(index, column, QTableWidgetItem(value))

    # --- acciones ---------------------------------------------------------------------------------

    def new_war_dialog(self) -> NewWarDialog:
        """El diálogo «Nueva guerra» sin abrirlo (las pruebas lo rellenan y llaman a ``create``)."""
        self.dialog = NewWarDialog(self.session, self)
        self.dialog.accepted.connect(self._on_created)
        return self.dialog

    def open_new_war(self) -> None:
        if self.session.project is None:
            return
        self.new_war_dialog().open()

    def _on_created(self) -> None:
        rel = self.dialog.created_rel if self.dialog is not None else None
        self.reload()
        if rel is not None:
            self.select_war(rel.name)
            self.status_requested.emit(N_("war.new.done"), {"file": str(rel)})

    def focus_field(self, ref, field=()) -> bool:
        return self.select_war(str(getattr(ref, "ident", ref)))
