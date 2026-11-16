"""Asistente «Nuevo país» (receta ``new_country``, wizard §14.2). Iteración 6.

Ocho pasos que se validan en vivo y entre los que se puede volver atrás:

1. **Identidad**: nombre y adjetivo ES/EN, TAG sugerido a partir del nombre (``suggest_tags``) y comprobado en
   vivo (``check_tag``), y «Basar en…» un país existente para rellenar el resto.
2. **Color y banderas**: color de mapa (aviso si se parece al de otro país), cultura gráfica, colores de uniforme
   opcionales y el taller de banderas.
3. **Pueblo**: cultura principal, culturas aceptadas y religión.
4. **Partidos**: plantilla con un partido por ideología o «Copiar partidos de…» con el prefijo del TAG nuevo.
5. **Gobierno y sociedad**: gobierno, partido gobernante, reformas, cámara alta, pluralidad, alfabetización,
   prestigio, valor nacional, escuela tecnológica y civilizado.
6. **Tecnologías**: casillas con plantillas («civilizado», «no civilizado», «como <país>»).
7. **Territorio y ejército** (opcional): provincias (con «Elegir en el mapa»), núcleo, capital y un ejército
   inicial.
8. **Revisión**: el plan de cambios (archivo · acción · líneas, y el diff de cada uno) de
   ``core.domain.country.plan_new_country``. «Crear país» lo aplica en **una** transacción (``undo.new_country``,
   un Ctrl+Z lo deshace) y, si «Guardar al terminar» está marcado, guarda.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ....core.domain import country as core_country
from ....core.domain.tags import check_tag, suggest_tags, taken_tags
from ....i18n import N_, tr, translator
from ...pickers.culture_picker import CultureListPicker, CulturePicker, ReligionPicker
from ...pickers.fields import ColorField, SymbolPicker
from ...pickers.issue_picker import IssuePicker
from ...pickers.province_picker import LAND, MapPickDialog, ProvincePicker
from ...pickers.tag_picker import TagPicker
from ...pickers.tech_tree import TEMPLATES, TechChecklist
from ...widgets import make_icon, mark_data
from .. import countries_facade, domain_context
from ..flag_studio import FlagStudio
from ..upper_house import UpperHouseField

STEPS = (N_("countries.wizard.step.identity"), N_("countries.wizard.step.flags"), N_("countries.wizard.step.people"),
         N_("countries.wizard.step.parties"), N_("countries.wizard.step.government"),
         N_("countries.wizard.step.technology"), N_("countries.wizard.step.territory"),
         N_("countries.wizard.step.review"))
TAG_REASONS = {"pattern": N_("countries.tag.pattern"), "reserved": N_("countries.tag.reserved"),
               "script_word": N_("countries.tag.script_word"), "windows_device": N_("countries.tag.windows_device"),
               "dynamic": N_("countries.tag.dynamic"), "taken": N_("countries.tag.taken")}
CREATE_ERRORS = {"tag": N_("countries.error.tag"), "file_exists": N_("countries.error.file_exists"),
                 "no_name": N_("countries.error.no_name"), "bad_party": N_("countries.error.bad_party"),
                 "province": N_("countries.error.province"), "capital": N_("countries.error.capital")}
ACTIONS = {"create": N_("countries.plan.create"), "modify": N_("countries.plan.modify"),
           "copy_from_game": N_("countries.plan.copy"), "trash": N_("countries.plan.trash")}
ROLE_PID = Qt.ItemDataRole.UserRole


def _row(*widgets) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    for widget in widgets:
        if widget is None:
            row.addStretch(1)
        else:
            row.addWidget(widget)
    return row


class NewCountryWizard(QDialog):
    """El asistente; ``spec()`` da la ``NewCountrySpec`` de lo que hay escrito y ``create()`` la aplica."""

    created = Signal(str)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setObjectName("newCountryWizard")
        self.resize(980, 720)
        self.plan = None
        self.created_tag: str | None = None
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self.step_list = mark_data(QListWidget())
        self.step_list.setObjectName("wizardSteps")
        self.step_list.setFixedWidth(210)
        for _ in STEPS:
            self.step_list.addItem(QListWidgetItem())
        self.step_list.currentRowChanged.connect(self._on_step_clicked)
        top.addWidget(self.step_list)
        right = QVBoxLayout()
        self.step_title = QLabel()
        self.step_title.setObjectName("wizardStepTitle")
        self.step_title.setProperty("role", "title")
        right.addWidget(self.step_title)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.error_label = QLabel()
        self.error_label.setObjectName("wizardError")
        self.error_label.setWordWrap(True)
        right.addWidget(self.error_label)
        top.addLayout(right, 1)
        outer.addLayout(top, 1)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("wizardCancel")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton()
        self.back_button.setObjectName("wizardBack")
        self.back_button.clicked.connect(self.back)
        self.next_button = QPushButton()
        self.next_button.setObjectName("wizardNext")
        self.next_button.clicked.connect(self.next)
        self.save_check = QCheckBox()
        self.save_check.setObjectName("wizardSaveAtEnd")
        self.save_check.setChecked(True)
        self.create_button = QPushButton()
        self.create_button.setObjectName("wizardCreate")
        self.create_button.setIcon(make_icon("plus", "gold_light"))
        self.create_button.clicked.connect(self.create)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_check)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.create_button)
        outer.addLayout(buttons)
        self._build_identity()
        self._build_flags()
        self._build_people()
        self._build_parties()
        self._build_government()
        self._build_technology()
        self._build_territory()
        self._build_review()
        translator().languageChanged.connect(self._on_language)
        self.retranslate()
        self.go(0)

    # --- pasos ------------------------------------------------------------------------------------

    def _page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.stack.addWidget(page)
        return page, form

    def _build_identity(self) -> None:
        page, form = self._page()
        self.id_labels = [QLabel() for _ in range(6)]
        self.name_en = QLineEdit()
        self.name_en.setObjectName("countryNameEn")
        self.name_es = QLineEdit()
        self.name_es.setObjectName("countryNameEs")
        self.adj_en = QLineEdit()
        self.adj_en.setObjectName("countryAdjEn")
        self.adj_es = QLineEdit()
        self.adj_es.setObjectName("countryAdjEs")
        self.tag_edit = QLineEdit()
        self.tag_edit.setObjectName("countryTag")
        self.tag_edit.setMaxLength(3)
        self.tag_status = QLabel()
        self.tag_status.setObjectName("countryTagStatus")
        self.suggestions = QHBoxLayout()
        self.suggestion_buttons: list[QPushButton] = []
        self.base_picker = TagPicker(self.session)
        self.base_button = QPushButton()
        self.base_button.setObjectName("countryBaseOn")
        self.base_button.clicked.connect(self.base_on_current)
        for label, widget in zip(self.id_labels[:4], (self.name_en, self.name_es, self.adj_en, self.adj_es)):
            form.addRow(label, widget)
        tag_row = QVBoxLayout()
        tag_row.addLayout(_row(self.tag_edit, self.tag_status, None))
        tag_row.addLayout(self.suggestions)
        form.addRow(self.id_labels[4], tag_row)
        form.addRow(self.id_labels[5], _row(self.base_picker, self.base_button))
        self.name_en.textChanged.connect(self._on_name)
        self.name_es.textChanged.connect(self._on_name)
        self.tag_edit.textChanged.connect(self._on_tag)

    def _build_flags(self) -> None:
        page, form = self._page()
        self.flag_labels = [QLabel() for _ in range(4)]
        self.color_field = ColorField()
        self.color_field.setObjectName("countryColor")
        self.color_field.value_committed.connect(self._on_color)
        self.gfx_picker = SymbolPicker(self.session, "graphical_culture")
        self.uniform_check = QCheckBox()
        self.uniform_check.setObjectName("countryUniform")
        self.uniform_fields = [ColorField() for _ in range(3)]
        uniforms = QVBoxLayout()
        uniforms.addWidget(self.uniform_check)
        for field in self.uniform_fields:
            field.setEnabled(False)
            uniforms.addWidget(field)
        self.uniform_check.toggled.connect(lambda on: [f.setEnabled(on) for f in self.uniform_fields])
        self.flag_studio = FlagStudio()
        form.addRow(self.flag_labels[0], self.color_field)
        form.addRow(self.flag_labels[1], self.gfx_picker)
        form.addRow(self.flag_labels[2], uniforms)
        form.addRow(self.flag_labels[3], self.flag_studio)

    def _build_people(self) -> None:
        page, form = self._page()
        self.people_labels = [QLabel() for _ in range(3)]
        self.culture_picker = CulturePicker(self.session)
        self.cultures_picker = CultureListPicker(self.session)
        self.religion_picker = ReligionPicker(self.session)
        for label, widget in zip(self.people_labels, (self.culture_picker, self.cultures_picker,
                                                      self.religion_picker)):
            form.addRow(label, widget)

    def _build_parties(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stack.addWidget(page)
        self.party_template = QRadioButton()
        self.party_template.setObjectName("partiesTemplate")
        self.party_template.setChecked(True)
        self.party_copy = QRadioButton()
        self.party_copy.setObjectName("partiesCopy")
        self.party_group = QButtonGroup(self)
        self.party_group.addButton(self.party_template)
        self.party_group.addButton(self.party_copy)
        self.party_source = TagPicker(self.session)
        self.party_source.setObjectName("partiesSource")
        layout.addWidget(self.party_template)
        layout.addLayout(_row(self.party_copy, self.party_source, None))
        self.party_table = mark_data(QTableWidget(0, 4))
        self.party_table.setObjectName("partiesTable")
        self.party_table.verticalHeader().hide()
        self.party_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.party_table, 1)
        self.party_template.toggled.connect(self._refresh_parties)
        self.party_source.value_committed.connect(self._refresh_parties)

    def _build_government(self) -> None:
        page = QWidget()
        self.stack.addWidget(page)
        grid = QGridLayout(page)
        left = QFormLayout()
        self.gov_labels = [QLabel() for _ in range(9)]
        self.government_picker = SymbolPicker(self.session, "government")
        self.ruling_combo = QComboBox()
        self.ruling_combo.setObjectName("rulingParty")
        self.plurality_spin = QDoubleSpinBox()
        self.plurality_spin.setObjectName("plurality")
        self.plurality_spin.setRange(0, 100)
        self.literacy_spin = QDoubleSpinBox()
        self.literacy_spin.setObjectName("literacy")
        self.literacy_spin.setRange(0, 1)
        self.literacy_spin.setSingleStep(0.05)
        self.literacy_spin.setDecimals(2)
        self.prestige_spin = QDoubleSpinBox()
        self.prestige_spin.setObjectName("prestige")
        self.prestige_spin.setRange(0, 1000)
        self.value_picker = SymbolPicker(self.session, "national_value")
        self.school_picker = SymbolPicker(self.session, "tech_school")
        self.civilized_check = QCheckBox()
        self.civilized_check.setObjectName("civilized")
        self.civilized_check.setChecked(True)
        for label, widget in zip(self.gov_labels, (self.government_picker, self.ruling_combo, self.plurality_spin,
                                                   self.literacy_spin, self.prestige_spin, self.value_picker,
                                                   self.school_picker, self.civilized_check)):
            left.addRow(label, widget)
        grid.addLayout(left, 0, 0)
        right = QVBoxLayout()
        self.reforms_title = QLabel()
        self.issue_picker = IssuePicker(self.session)
        self.upper_title = QLabel()
        self.upper_house = UpperHouseField(self.session)
        right.addWidget(self.reforms_title)
        right.addWidget(self.issue_picker)
        right.addWidget(self.upper_title)
        right.addWidget(self.upper_house)
        right.addStretch(1)
        grid.addLayout(right, 0, 1)
        self.civilized_check.toggled.connect(self.issue_picker.set_civilized)

    def _build_technology(self) -> None:
        page = QWidget()
        self.stack.addWidget(page)
        layout = QVBoxLayout(page)
        self.tech_template = QComboBox()
        self.tech_template.setObjectName("wizardTechTemplate")
        for key in TEMPLATES:
            self.tech_template.addItem("", key)
        self.tech_like = TagPicker(self.session)
        self.tech_apply = QPushButton()
        self.tech_apply.setObjectName("wizardTechApply")
        self.tech_apply.clicked.connect(self.apply_tech_template)
        layout.addLayout(_row(self.tech_template, self.tech_like, self.tech_apply, None))
        self.tech_checklist = TechChecklist(self.session)
        layout.addWidget(self.tech_checklist, 1)

    def _build_territory(self) -> None:
        page = QWidget()
        self.stack.addWidget(page)
        layout = QVBoxLayout(page)
        self.territory_intro = QLabel()
        self.territory_intro.setWordWrap(True)
        layout.addWidget(self.territory_intro)
        self.province_picker = ProvincePicker(self.session, allow=LAND)
        self.province_add = QPushButton()
        self.province_add.setObjectName("territoryAdd")
        self.province_add.clicked.connect(self.add_province_from_picker)
        self.province_map = QPushButton()
        self.province_map.setObjectName("territoryMap")
        self.province_map.setIcon(make_icon("map", "gold_light"))
        self.province_map.clicked.connect(self.pick_provinces_on_map)
        self.province_remove = QPushButton()
        self.province_remove.setObjectName("territoryRemove")
        self.province_remove.clicked.connect(self.remove_selected_province)
        layout.addLayout(_row(self.province_picker, self.province_add, self.province_map, self.province_remove))
        self.province_list = mark_data(QListWidget())
        self.province_list.setObjectName("territoryList")
        layout.addWidget(self.province_list, 1)
        form = QFormLayout()
        self.terr_labels = [QLabel() for _ in range(4)]
        self.cores_check = QCheckBox()
        self.cores_check.setObjectName("territoryCores")
        self.cores_check.setChecked(True)
        self.capital_combo = QComboBox()
        self.capital_combo.setObjectName("territoryCapital")
        self.army_spin = QSpinBox()
        self.army_spin.setObjectName("territoryArmy")
        self.army_spin.setRange(0, 20)
        self.army_type = QComboBox()
        self.army_type.setObjectName("territoryArmyType")
        for label, widget in zip(self.terr_labels, (self.cores_check, self.capital_combo, self.army_spin,
                                                    self.army_type)):
            form.addRow(label, widget)
        layout.addLayout(form)

    def _build_review(self) -> None:
        page = QWidget()
        self.stack.addWidget(page)
        layout = QVBoxLayout(page)
        self.review_intro = QLabel()
        self.review_intro.setWordWrap(True)
        layout.addWidget(self.review_intro)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.plan_table = mark_data(QTableWidget(0, 3))
        self.plan_table.setObjectName("planTable")
        self.plan_table.verticalHeader().hide()
        header = self.plan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.plan_table.itemSelectionChanged.connect(self._show_diff)
        splitter.addWidget(self.plan_table)
        self.diff_view = mark_data(QPlainTextEdit())
        self.diff_view.setObjectName("planDiff")
        self.diff_view.setReadOnly(True)
        splitter.addWidget(self.diff_view)
        layout.addWidget(splitter, 1)

    # --- textos -----------------------------------------------------------------------------------

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr(N_("countries.wizard.title")))
        for i, key in enumerate(STEPS):
            self.step_list.item(i).setText(f"{i + 1}. {tr(key)}")
        self.cancel_button.setText(tr(N_("entity.cancel")))
        self.back_button.setText(tr(N_("countries.wizard.back")))
        self.next_button.setText(tr(N_("countries.wizard.next")))
        self.create_button.setText(tr(N_("countries.wizard.create")))
        self.save_check.setText(tr(N_("countries.wizard.save_at_end")))
        for label, key in zip(self.id_labels, (N_("countries.field.name_en"), N_("countries.field.name_es"),
                                               N_("countries.field.adj_en"), N_("countries.field.adj_es"),
                                               N_("countries.field.tag"), N_("countries.field.base_on"))):
            label.setText(tr(key))
        self.base_button.setText(tr(N_("countries.wizard.base_fill")))
        for label, key in zip(self.flag_labels, (N_("countries.field.color"), N_("countries.field.graphical_culture"),
                                                 N_("countries.field.uniform"), N_("countries.field.flags"))):
            label.setText(tr(key))
        self.uniform_check.setText(tr(N_("countries.wizard.uniform")))
        for label, key in zip(self.people_labels, (N_("countries.field.primary_culture"), N_("countries.field.cultures"),
                                                   N_("countries.field.religion"))):
            label.setText(tr(key))
        self.party_template.setText(tr(N_("countries.wizard.parties_template")))
        self.party_copy.setText(tr(N_("countries.wizard.parties_copy")))
        self.party_table.setHorizontalHeaderLabels([tr(N_("countries.party.name")),
                                                    tr(N_("countries.party.ideology")),
                                                    tr(N_("countries.party.dates")),
                                                    tr(N_("countries.party.policies"))])
        for label, key in zip(self.gov_labels, (N_("countries.field.government"), N_("countries.field.ruling_party"),
                                                N_("countries.field.plurality"), N_("countries.field.literacy"),
                                                N_("countries.field.prestige"), N_("countries.field.nationalvalue"),
                                                N_("countries.field.school"), N_("countries.field.civilized"))):
            label.setText(tr(key))
        self.reforms_title.setText(tr(N_("countries.field.reforms")))
        self.upper_title.setText(tr(N_("countries.field.upper_house")))
        for i in range(self.tech_template.count()):
            self.tech_template.setItemText(i, tr(TEMPLATES[self.tech_template.itemData(i)]))
        self.tech_apply.setText(tr(N_("pickers.tech.apply")))
        self.territory_intro.setText(tr(N_("countries.wizard.territory_intro")))
        self.province_add.setText(tr(N_("countries.wizard.add_province")))
        self.province_map.setText(tr(N_("countries.wizard.pick_on_map")))
        self.province_remove.setText(tr(N_("countries.wizard.remove_province")))
        for label, key in zip(self.terr_labels, (N_("countries.field.cores"), N_("countries.field.capital"),
                                                 N_("countries.field.army"), N_("countries.field.army_type"))):
            label.setText(tr(key))
        self.review_intro.setText(tr(N_("countries.wizard.review_intro")))
        self.plan_table.setHorizontalHeaderLabels([tr(N_("countries.plan.file")), tr(N_("countries.plan.action")),
                                                   tr(N_("countries.plan.lines"))])
        self._on_tag()
        self._update_nav()

    # --- navegación -------------------------------------------------------------------------------

    def current_step(self) -> int:
        return self.stack.currentIndex()

    def go(self, step: int) -> None:
        step = max(0, min(len(STEPS) - 1, step))
        if step > self.current_step():
            for earlier in range(self.current_step(), step):
                if self.step_error(earlier):
                    step = earlier
                    break
        self.stack.setCurrentIndex(step)
        self.step_list.blockSignals(True)
        self.step_list.setCurrentRow(step)
        self.step_list.blockSignals(False)
        self.step_title.setText(tr(STEPS[step]))
        if step == 3:
            self._refresh_parties()
        if step == 4:
            self._refresh_ruling()
        if step == 6:
            self._refresh_army_types()
        if step == len(STEPS) - 1:
            self.refresh_plan()
        self._update_nav()

    def _on_step_clicked(self, row: int) -> None:
        if row >= 0:
            self.go(row)

    def next(self) -> None:
        self.go(self.current_step() + 1)

    def back(self) -> None:
        self.go(self.current_step() - 1)

    def step_error(self, step: int) -> str | None:
        """Clave del motivo por el que no se puede pasar de ``step``; None si se puede."""
        if step == 0:
            if not (self.name_en.text().strip() or self.name_es.text().strip()):
                return N_("countries.error.no_name")
            result = check_tag(self.tag_edit.text().strip(), taken_tags(self.session.index))
            if not result.ok:
                return TAG_REASONS[result.reason]
        if step == 4 and abs(self.upper_house.total() - 100) > 0.001 and self.upper_house.value():
            return N_("countries.error.upper_house")
        return None

    def _update_nav(self) -> None:
        step = self.current_step()
        error = self.step_error(step)
        self.error_label.setText(tr(error, tag=self.tag_edit.text().strip()) if error else "")
        self.back_button.setEnabled(step > 0)
        self.next_button.setEnabled(step < len(STEPS) - 1 and error is None)
        self.create_button.setEnabled(step == len(STEPS) - 1 and self.plan is not None)

    # --- paso 1 -----------------------------------------------------------------------------------

    def _on_name(self, *args) -> None:
        name = self.name_en.text().strip() or self.name_es.text().strip()
        suggestions = suggest_tags(name, taken_tags(self.session.index)) if name else []
        for button in self.suggestion_buttons:
            self.suggestions.removeWidget(button)
            button.deleteLater()
        self.suggestion_buttons = []
        for tag in suggestions:
            button = QPushButton(tag)
            button.setObjectName(f"tagSuggestion_{tag}")
            button.clicked.connect(lambda _checked=False, t=tag: self.tag_edit.setText(t))
            self.suggestions.addWidget(button)
            self.suggestion_buttons.append(button)
        if not self.tag_edit.text() and suggestions:
            self.tag_edit.setText(suggestions[0])
        self._update_nav()

    def suggested_tags(self) -> list[str]:
        return [button.text() for button in self.suggestion_buttons]

    def _on_tag(self, *args) -> None:
        text = self.tag_edit.text().strip()
        if text != text.upper():
            self.tag_edit.setText(text.upper())
            return
        if not text:
            self.tag_status.setText("")
        else:
            result = check_tag(text, taken_tags(self.session.index))
            self.tag_status.setText(tr(N_("countries.tag.ok")) if result.ok else tr(TAG_REASONS[result.reason],
                                                                                    tag=text))
            self.tag_status.setProperty("invalid", not result.ok)
        self._update_nav()

    def base_on(self, tag: str) -> None:
        """«Basar en…»: rellena color, cultura gráfica, pueblo, gobierno y tecnologías con los de ``tag``."""
        context = domain_context(self.session)
        if context is None or not tag:
            return
        profile = core_country.country_profile(context, tag)
        if profile.get("color"):
            self.color_field.set_value(tuple(profile["color"]))
            self.flag_studio.set_color(profile["color"])
        if profile.get("graphical_culture"):
            self.gfx_picker.set_value(profile["graphical_culture"])
        if profile.get("primary_culture"):
            self.culture_picker.set_value(profile["primary_culture"])
        self.cultures_picker.set_values(profile.get("cultures", ()))
        if profile.get("religion"):
            self.religion_picker.set_value(profile["religion"])
        if profile.get("government"):
            self.government_picker.set_value(profile["government"])
        if profile.get("nationalvalue"):
            self.value_picker.set_value(profile["nationalvalue"])
        if "literacy" in profile:
            self.literacy_spin.setValue(profile["literacy"])
        if "plurality" in profile:
            self.plurality_spin.setValue(profile["plurality"])
        if "civilized" in profile:
            self.civilized_check.setChecked(profile["civilized"])
        self.tech_checklist.set_selected(profile.get("technologies", ()))
        self.party_source.set_value(tag)

    def base_on_current(self) -> None:
        self.base_on(self.base_picker.value())

    # --- paso 2 -----------------------------------------------------------------------------------

    def _on_color(self, color) -> None:
        if color:
            self.flag_studio.set_color(color)

    # --- paso 4 -----------------------------------------------------------------------------------

    def parties(self) -> tuple[core_country.PartySpec, ...]:
        tag = self.tag_edit.text().strip() or "XXX"
        context = domain_context(self.session)
        if context is None:
            return ()
        if self.party_copy.isChecked() and self.party_source.value():
            return core_country.copy_parties(context, self.party_source.value(), tag)
        return core_country.party_template(tag, context.index)

    def _refresh_parties(self, *args) -> None:
        parties = self.parties()
        self.party_table.setRowCount(len(parties))
        for row, party in enumerate(parties):
            values = (party.name, party.ideology, f"{party.start_date} – {party.end_date}",
                      ", ".join(party.policies.values()))
            for column, value in enumerate(values):
                self.party_table.setItem(row, column, QTableWidgetItem(value))

    def _refresh_ruling(self) -> None:
        current = self.ruling_combo.currentData()
        self.ruling_combo.clear()
        for party in self.parties():
            self.ruling_combo.addItem(party.name, party.name)
        index = self.ruling_combo.findData(current) if current else 0
        self.ruling_combo.setCurrentIndex(max(index, 0))

    # --- paso 6 -----------------------------------------------------------------------------------

    def apply_tech_template(self) -> None:
        self.tech_checklist.set_selected(self.template(self.tech_template.currentData(), self.tech_like.value()))

    def template(self, key: str, tag: str | None = None) -> set[str]:
        """Las tecnologías de la plantilla ``key`` (misma lógica que ``TechTreeDialog``)."""
        from ...pickers.tech_tree import TechTreeDialog

        return TechTreeDialog.template(self, key, tag)

    @property
    def checklist(self):
        return self.tech_checklist

    # --- paso 7 -----------------------------------------------------------------------------------

    def provinces(self) -> list[int]:
        return [self.province_list.item(i).data(ROLE_PID) for i in range(self.province_list.count())]

    def set_provinces(self, pids) -> None:
        self.province_list.clear()
        for pid in pids:
            name = self.session.map.province_name(pid) if hasattr(self.session, "map") else ""
            item = QListWidgetItem(f"{pid} - {name}" if name else str(pid))
            item.setData(ROLE_PID, int(pid))
            self.province_list.addItem(item)
        current = self.capital_combo.currentData()
        self.capital_combo.clear()
        self.capital_combo.addItem("—", None)
        for pid in self.provinces():
            name = self.session.map.province_name(pid) if hasattr(self.session, "map") else ""
            self.capital_combo.addItem(f"{pid} - {name}" if name else str(pid), pid)
        index = self.capital_combo.findData(current) if current is not None else -1
        self.capital_combo.setCurrentIndex(index if index >= 0 else (1 if self.provinces() else 0))

    def add_province_from_picker(self) -> None:
        pid = self.province_picker.value()
        if pid is not None and pid not in self.provinces():
            self.set_provinces(self.provinces() + [pid])

    def pick_provinces_on_map(self) -> None:
        chosen = MapPickDialog.pick(self.session, multiple=True, initial=self.provinces(), allow=LAND, parent=self)
        if chosen is not None:
            self.set_provinces(list(chosen))

    def remove_selected_province(self) -> None:
        row = self.province_list.currentRow()
        if row >= 0:
            pids = self.provinces()
            del pids[row]
            self.set_provinces(pids)

    def _refresh_army_types(self) -> None:
        from ..oob_editor import unit_types

        current = self.army_type.currentData()
        self.army_type.clear()
        for name in unit_types(self.session, False):
            self.army_type.addItem(name, name)
        index = self.army_type.findData(current) if current else 0
        self.army_type.setCurrentIndex(max(index, 0))

    # --- paso 8 -----------------------------------------------------------------------------------

    def spec(self) -> core_country.NewCountrySpec:
        tag = self.tag_edit.text().strip().upper()
        name = {lang: text for lang, text in (("en", self.name_en.text().strip()),
                                              ("es", self.name_es.text().strip())) if text}
        adjective = {lang: text for lang, text in (("en", self.adj_en.text().strip()),
                                                   ("es", self.adj_es.text().strip())) if text}
        color = self.color_field.value() or (128, 128, 128)
        uniforms = tuple(field.value() or color for field in self.uniform_fields) \
            if self.uniform_check.isChecked() else ()
        parties = self.parties()
        ruling = self.ruling_combo.currentData() or (parties[0].name if parties else None)
        provinces = tuple(self.provinces())
        capital = self.capital_combo.currentData()
        if capital is None and provinces:
            capital = provinces[0]
        armies = ()
        if self.army_spin.value() and capital is not None and self.army_type.currentData():
            from ....core.domain.country import ArmySpec, RegimentSpec

            unit = self.army_type.currentData()
            regiments = tuple(RegimentSpec(f"{n} {tag}", unit, capital) for n in range(1, self.army_spin.value() + 1))
            armies = (ArmySpec(tr(N_("countries.wizard.army_name"), tag=tag), capital, regiments),)
        try:
            flags = self.flag_studio.flags()
        except ValueError:
            flags = {}
        return core_country.NewCountrySpec(
            tag=tag, name=name, adjective=adjective, color=tuple(color), graphical_culture=self.gfx_picker.value()
            or "Generic", uniform_colors=uniforms, flags=flags, primary_culture=self.culture_picker.value(),
            cultures=tuple(self.cultures_picker.values()), religion=self.religion_picker.value(), parties=parties,
            government=self.government_picker.value(), ruling_party=ruling, reforms=self.issue_picker.value(),
            upper_house=self.upper_house.value(), plurality=self.plurality_spin.value(),
            literacy=self.literacy_spin.value(), prestige=self.prestige_spin.value(),
            nationalvalue=self.value_picker.value(), civilized=self.civilized_check.isChecked(),
            school=self.school_picker.value(), technologies=tuple(sorted(self.tech_checklist.selected())),
            capital=capital, provinces=provinces, cores=self.cores_check.isChecked(), armies=armies)

    def refresh_plan(self) -> None:
        context = domain_context(self.session)
        self.plan = None
        self.plan_table.setRowCount(0)
        self.diff_view.setPlainText("")
        if context is None:
            return
        try:
            self.plan = core_country.plan_new_country(context, self.spec())
        except core_country.CountryError as exc:
            self.error_label.setText(tr(CREATE_ERRORS.get(exc.code, N_("countries.error.tag")), detail=exc.detail,
                                        tag=self.tag_edit.text()))
            self._update_nav()
            return
        changes = self.plan.changes
        self.plan_table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            lines = "" if change.lines is None else f"+{change.lines[0]} −{change.lines[1]}"
            for column, value in enumerate((str(change.rel), tr(ACTIONS.get(change.action, change.action)), lines)):
                self.plan_table.setItem(row, column, QTableWidgetItem(value))
        if changes:
            self.plan_table.selectRow(0)
        self._update_nav()

    def _show_diff(self) -> None:
        row = self.plan_table.currentRow()
        if self.plan is None or not 0 <= row < len(self.plan.changes):
            self.diff_view.setPlainText("")
            return
        change = self.plan.changes[row]
        self.diff_view.setPlainText(change.diff or tr(N_("countries.plan.binary")))

    def create(self) -> bool:
        """Crea el país en una transacción; con «Guardar al terminar», guarda. True si se creó."""
        context = domain_context(self.session)
        if context is None:
            return False
        spec = self.spec()
        try:
            with self.session.edit(core_country.UNDO_NEW_COUNTRY, tag=spec.tag, name=spec.display_name()):
                core_country.build_new_country(context, spec)
        except core_country.CountryError as exc:
            self.error_label.setText(tr(CREATE_ERRORS.get(exc.code, N_("countries.error.tag")), detail=exc.detail,
                                        tag=spec.tag))
            return False
        if context.loc is not None:
            context.loc.invalidate()
        if self.save_check.isChecked():
            self.session.save()
        self.created_tag = spec.tag
        self.created.emit(spec.tag)
        self.accept()
        return True


def facade(session):
    return countries_facade(session)
