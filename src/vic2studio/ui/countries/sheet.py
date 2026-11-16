"""Ficha nacional (sala Naciones › Países, wizard §14.2). Iteración 6.

Una pestaña por tema, todas sobre la **fecha de trabajo** de la sesión (lo que se ve es lo vigente en esa fecha y
lo que se escribe va al bloque que decide ``HistoryView``, §10.6):

- **Identidad**: nombre y adjetivo ES/EN (localización), color y cultura gráfica (archivo de país), capital,
  cultura principal, culturas aceptadas, religión y civilizado (historia).
- **Banderas**: las 5 banderas actuales y el taller para sustituirlas.
- **Partidos**: los ``party`` del archivo de país; añadir y quitar.
- **Política**: gobierno, partido gobernante, pluralidad, prestigio, valor nacional, reformas y cámara alta.
- **Tecnologías**: casillas con plantillas.
- **Territorio**: las provincias que posee en la fecha de trabajo (se editan en el mapa).
- **Sociedad**: alfabetización, conciencia y escuela tecnológica.
- **Ejército**: órdenes de batalla (``OobEditor``).
- **Diplomacia**: alianzas, vasallajes y uniones y las guerras en las que participa.
- **Textos**: todas las claves de localización del país (nombre, adjetivo y partidos), editables en ES y EN.

Cada gesto es **una** transacción (``session.edit``) con su etiqueta de deshacer.
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ...core.domain import nation as core_nation
from ...core.domain import war as core_war
from ...core.gfx.flags import FLAG_SUFFIXES
from ...core.vfs.paths import VPath
from ...i18n import N_, tr, translator
from ..pickers.culture_picker import CultureListPicker, CulturePicker, ReligionPicker
from ..pickers.fields import ColorField, SymbolPicker
from ..pickers.issue_picker import IssuePicker
from ..pickers.province_picker import LAND, ProvincePicker
from ..pickers.tag_picker import TagPicker
from ..pickers.tech_tree import TEMPLATES, TechChecklist
from ..widgets import make_icon, mark_data
from . import countries_facade, domain_context, loc_text
from .flag_studio import FlagStudio, to_pixmap
from .oob_editor import OobEditor
from .upper_house import UpperHouseField

TABS = (("identity", N_("countries.tab.identity")), ("flags", N_("countries.tab.flags")),
        ("parties", N_("countries.tab.parties")), ("politics", N_("countries.tab.politics")),
        ("technology", N_("countries.tab.technology")), ("territory", N_("countries.tab.territory")),
        ("society", N_("countries.tab.society")), ("army", N_("countries.tab.army")),
        ("diplomacy", N_("countries.tab.diplomacy")), ("texts", N_("countries.tab.texts")))
RELATION_LABELS = {"alliance": N_("war.diplomacy.alliance"), "vassal": N_("war.diplomacy.vassal"),
                   "union": N_("war.diplomacy.union")}
LANGS = ("en", "es")
LOC_AREA = "countries"


def flag_bytes(session, rel: VPath) -> bytes | None:
    """Los bytes vigentes de una bandera: los del documento abierto (editado en la sesión) o los del disco."""
    project = session.project
    if project is None:
        return None
    peek = getattr(project.ws, "peek", None)
    handle = peek(rel) if peek is not None else None
    if handle is not None:
        if handle.deleted:
            return None
        if isinstance(handle.model, (bytes, bytearray)):
            return bytes(handle.model)
    read = getattr(project.vfs, "read_bytes", None)       # los proyectos falsos de las pruebas no lo tienen
    try:
        return read(rel) if read is not None else None
    except (FileNotFoundError, OSError):
        return None


def flag_image(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    import io

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image.convert("RGBA")
    except (OSError, ValueError, SyntaxError):
        return None


class NationalSheet(QWidget):
    """La ficha de un país (``bind(tag)``); emite ``status_requested`` como las páginas."""

    status_requested = Signal(str, object)
    openWar = Signal(object)        # VPath de la guerra (la página la abre en la sala Guerra)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.tag: str | None = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.flag_label = QLabel()
        self.flag_label.setObjectName("sheetFlag")
        self.flag_label.setFixedSize(97, 68)
        self.title = mark_data(QLabel())         # nombre del país y TAG: datos del mod
        self.title.setObjectName("sheetTitle")
        self.title.setProperty("role", "title")
        self.date_label = QLabel()
        self.date_label.setObjectName("sheetDate")
        header.addWidget(self.flag_label)
        header.addWidget(self.title, 1)
        header.addWidget(self.date_label)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("sheetTabs")
        layout.addWidget(self.tabs, 1)
        self.pages: dict[str, QWidget] = {}
        for key, _label in TABS:
            page = QWidget()
            page.setObjectName(f"sheetTab_{key}")
            self.pages[key] = page
            self.tabs.addTab(page, "")
        self._build_identity()
        self._build_flags()
        self._build_parties()
        self._build_politics()
        self._build_technology()
        self._build_territory()
        self._build_society()
        self._build_army()
        self._build_diplomacy()
        self._build_texts()
        self.tabs.currentChanged.connect(self._on_tab)
        session.workingDateChanged.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        session.indexStateChanged.connect(self._on_index)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    # --- construcción -----------------------------------------------------------------------------

    def _form(self, key: str) -> QFormLayout:
        form = QFormLayout(self.pages[key])
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        return form

    def _build_identity(self) -> None:
        form = self._form("identity")
        self.identity_labels = [QLabel() for _ in range(12)]
        self.name_edits = {lang: QLineEdit() for lang in LANGS}
        self.adj_edits = {lang: QLineEdit() for lang in LANGS}
        for lang in LANGS:
            self.name_edits[lang].setObjectName(f"sheetName_{lang}")
            self.adj_edits[lang].setObjectName(f"sheetAdj_{lang}")
            self.name_edits[lang].editingFinished.connect(lambda lang=lang: self._commit_text("", lang))
            self.adj_edits[lang].editingFinished.connect(lambda lang=lang: self._commit_text("_ADJ", lang))
        self.color_field = ColorField()
        self.color_field.setObjectName("sheetColor")
        self.color_field.value_committed.connect(lambda value: self._commit_file("color", value))
        self.gfx_picker = SymbolPicker(self.session, "graphical_culture")
        self.gfx_picker.setObjectName("sheetGraphicalCulture")
        self.gfx_picker.value_committed.connect(lambda value: self._commit_file("graphical_culture", value))
        self.capital_picker = ProvincePicker(self.session, allow=LAND)
        self.capital_picker.setObjectName("sheetCapital")
        self.capital_picker.value_committed.connect(lambda value: self._commit_history("capital", value))
        self.culture_picker = CulturePicker(self.session)
        self.culture_picker.setObjectName("sheetPrimaryCulture")
        self.culture_picker.value_committed.connect(lambda value: self._commit_history("primary_culture", value))
        self.cultures_picker = CultureListPicker(self.session)
        self.cultures_picker.setObjectName("sheetCultures")
        self.cultures_apply = QPushButton()
        self.cultures_apply.setObjectName("sheetCulturesApply")
        self.cultures_apply.clicked.connect(self.apply_cultures)
        self.religion_picker = ReligionPicker(self.session)
        self.religion_picker.setObjectName("sheetReligion")
        self.religion_picker.value_committed.connect(lambda value: self._commit_history("religion", value))
        self.civilized_check = QCheckBox()
        self.civilized_check.setObjectName("sheetCivilized")
        self.civilized_check.toggled.connect(self._on_civilized)
        cultures = QVBoxLayout()
        cultures.addWidget(self.cultures_picker)
        cultures.addWidget(self.cultures_apply, 0, Qt.AlignmentFlag.AlignLeft)
        widgets = (self.name_edits["en"], self.name_edits["es"], self.adj_edits["en"], self.adj_edits["es"],
                   self.color_field, self.gfx_picker, self.capital_picker, self.culture_picker, None,
                   self.religion_picker, self.civilized_check)
        for label, widget in zip(self.identity_labels, widgets):
            if widget is None:
                form.addRow(label, cultures)
            else:
                form.addRow(label, widget)
        self.file_info = mark_data(QLabel())     # rutas de archivo: datos
        self.file_info.setObjectName("sheetFiles")
        self.file_info.setWordWrap(True)
        self.file_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.identity_labels[11], self.file_info)

    def _build_flags(self) -> None:
        layout = QVBoxLayout(self.pages["flags"])
        self.current_flags_title = QLabel()
        layout.addWidget(self.current_flags_title)
        grid = QGridLayout()
        self.current_flags: dict[str, QLabel] = {}
        self.current_flag_names: dict[str, QLabel] = {}
        for column, suffix in enumerate(FLAG_SUFFIXES):
            picture = QLabel()
            picture.setObjectName(f"sheetFlag{suffix or '_base'}")
            picture.setFixedSize(97, 68)
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = mark_data(QLabel())            # nombre de archivo: dato
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(picture, 0, column)
            grid.addWidget(name, 1, column)
            self.current_flags[suffix] = picture
            self.current_flag_names[suffix] = name
        layout.addLayout(grid)
        self.new_flags_title = QLabel()
        layout.addWidget(self.new_flags_title)
        self.flag_studio = FlagStudio()
        layout.addWidget(self.flag_studio)
        self.flags_apply = QPushButton()
        self.flags_apply.setObjectName("sheetFlagsApply")
        self.flags_apply.setIcon(make_icon("check", "gold_light"))
        self.flags_apply.clicked.connect(self.apply_flags)
        layout.addWidget(self.flags_apply, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

    def _build_parties(self) -> None:
        layout = QVBoxLayout(self.pages["parties"])
        self.party_table = mark_data(QTableWidget(0, 4))
        self.party_table.setObjectName("sheetParties")
        self.party_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.party_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.party_table.verticalHeader().hide()
        self.party_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.party_table, 1)
        row = QHBoxLayout()
        self.party_name = QLineEdit()
        self.party_name.setObjectName("sheetPartyName")
        self.party_ideology = SymbolPicker(self.session, "ideology")
        self.party_ideology.setObjectName("sheetPartyIdeology")
        self.party_add = QPushButton()
        self.party_add.setObjectName("sheetPartyAdd")
        self.party_add.setIcon(make_icon("plus", "gold_light"))
        self.party_add.clicked.connect(self.add_party_from_form)
        self.party_remove = QPushButton()
        self.party_remove.setObjectName("sheetPartyRemove")
        self.party_remove.setIcon(make_icon("trash", "gold_light"))
        self.party_remove.clicked.connect(self.remove_selected_party)
        for widget in (self.party_name, self.party_ideology, self.party_add, self.party_remove):
            row.addWidget(widget)
        layout.addLayout(row)

    def _build_politics(self) -> None:
        grid = QGridLayout(self.pages["politics"])
        form = QFormLayout()
        self.politics_labels = [QLabel() for _ in range(5)]
        self.government_picker = SymbolPicker(self.session, "government")
        self.government_picker.setObjectName("sheetGovernment")
        self.government_picker.value_committed.connect(lambda value: self._commit_history("government", value))
        self.ruling_combo = QComboBox()
        self.ruling_combo.setObjectName("sheetRulingParty")
        self.ruling_combo.activated.connect(
            lambda _index: self._commit_history("ruling_party", self.ruling_combo.currentData()))
        self.plurality_spin = self._spin("sheetPlurality", 0, 100, 1, 1, "plurality")
        self.prestige_spin = self._spin("sheetPrestige", 0, 10000, 1, 1, "prestige")
        self.value_picker = SymbolPicker(self.session, "national_value")
        self.value_picker.setObjectName("sheetNationalValue")
        self.value_picker.value_committed.connect(lambda value: self._commit_history("nationalvalue", value))
        for label, widget in zip(self.politics_labels, (self.government_picker, self.ruling_combo,
                                                        self.plurality_spin, self.prestige_spin, self.value_picker)):
            form.addRow(label, widget)
        grid.addLayout(form, 0, 0)
        right = QVBoxLayout()
        self.reforms_title = QLabel()
        self.issue_picker = IssuePicker(self.session)
        self.reforms_apply = QPushButton()
        self.reforms_apply.setObjectName("sheetReformsApply")
        self.reforms_apply.clicked.connect(self.apply_reforms)
        self.upper_title = QLabel()
        self.upper_house = UpperHouseField(self.session)
        self.upper_apply = QPushButton()
        self.upper_apply.setObjectName("sheetUpperApply")
        self.upper_apply.clicked.connect(self.apply_upper_house)
        for widget in (self.reforms_title, self.issue_picker, self.reforms_apply, self.upper_title,
                       self.upper_house, self.upper_apply):
            right.addWidget(widget)
        right.addStretch(1)
        grid.addLayout(right, 0, 1)

    def _spin(self, name: str, low: float, high: float, step: float, decimals: int, key: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName(name)
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.editingFinished.connect(lambda: self._commit_history(key, round(spin.value(), decimals)))
        return spin

    def _build_technology(self) -> None:
        layout = QVBoxLayout(self.pages["technology"])
        row = QHBoxLayout()
        self.tech_template = QComboBox()
        self.tech_template.setObjectName("sheetTechTemplate")
        for key in TEMPLATES:
            self.tech_template.addItem("", key)
        self.tech_like = TagPicker(self.session)
        self.tech_fill = QPushButton()
        self.tech_fill.setObjectName("sheetTechFill")
        self.tech_fill.clicked.connect(self.fill_tech_template)
        self.tech_apply = QPushButton()
        self.tech_apply.setObjectName("sheetTechApply")
        self.tech_apply.setIcon(make_icon("check", "gold_light"))
        self.tech_apply.clicked.connect(self.apply_technologies)
        for widget in (self.tech_template, self.tech_like, self.tech_fill):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.tech_apply)
        layout.addLayout(row)
        self.tech_checklist = TechChecklist(self.session)
        layout.addWidget(self.tech_checklist, 1)

    def _build_territory(self) -> None:
        layout = QVBoxLayout(self.pages["territory"])
        self.territory_note = QLabel()
        self.territory_note.setWordWrap(True)
        layout.addWidget(self.territory_note)
        self.province_list = mark_data(QListWidget())
        self.province_list.setObjectName("sheetProvinces")
        layout.addWidget(self.province_list, 1)

    def _build_society(self) -> None:
        form = self._form("society")
        self.society_labels = [QLabel() for _ in range(5)]
        self.literacy_spin = self._spin("sheetLiteracy", 0, 1, 0.05, 2, "literacy")
        self.nonstate_spin = self._spin("sheetNonStateLiteracy", 0, 1, 0.05, 2, "non_state_culture_literacy")
        self.consciousness_spin = self._spin("sheetConsciousness", 0, 10, 0.5, 1, "consciousness")
        self.nonstate_consciousness_spin = self._spin("sheetNonStateConsciousness", 0, 10, 0.5, 1,
                                                      "nonstate_consciousness")
        self.school_picker = SymbolPicker(self.session, "tech_school")
        self.school_picker.setObjectName("sheetSchool")
        self.school_picker.value_committed.connect(lambda value: self._commit_history("schools", value))
        for label, widget in zip(self.society_labels, (self.literacy_spin, self.nonstate_spin,
                                                       self.consciousness_spin, self.nonstate_consciousness_spin,
                                                       self.school_picker)):
            form.addRow(label, widget)

    def _build_army(self) -> None:
        layout = QVBoxLayout(self.pages["army"])
        self.oob_editor = OobEditor(self.session)
        self.oob_editor.status_requested.connect(self.status_requested)
        layout.addWidget(self.oob_editor)

    def _build_diplomacy(self) -> None:
        layout = QVBoxLayout(self.pages["diplomacy"])
        self.relations_title = QLabel()
        layout.addWidget(self.relations_title)
        self.relation_table = mark_data(QTableWidget(0, 4))
        self.relation_table.setObjectName("sheetRelations")
        self.relation_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.relation_table.verticalHeader().hide()
        self.relation_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.relation_table, 1)
        self.wars_title = QLabel()
        layout.addWidget(self.wars_title)
        self.war_list = mark_data(QListWidget())
        self.war_list.setObjectName("sheetWars")
        self.war_list.itemDoubleClicked.connect(lambda item: self.openWar.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.war_list, 1)

    def _build_texts(self) -> None:
        layout = QVBoxLayout(self.pages["texts"])
        self.texts_note = QLabel()
        self.texts_note.setWordWrap(True)
        layout.addWidget(self.texts_note)
        self.text_table = mark_data(QTableWidget(0, 3))
        self.text_table.setObjectName("sheetTexts")
        self.text_table.verticalHeader().hide()
        self.text_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.text_table.itemChanged.connect(self._on_text_item)
        layout.addWidget(self.text_table, 1)

    # --- textos -----------------------------------------------------------------------------------

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        for index, (_key, label) in enumerate(TABS):
            self.tabs.setTabText(index, tr(label))
        keys = (N_("countries.field.name_en"), N_("countries.field.name_es"), N_("countries.field.adj_en"),
                N_("countries.field.adj_es"), N_("countries.field.color"), N_("countries.field.graphical_culture"),
                N_("countries.field.capital"), N_("countries.field.primary_culture"), N_("countries.field.cultures"),
                N_("countries.field.religion"), N_("countries.field.civilized"), N_("countries.field.files"))
        for label, key in zip(self.identity_labels, keys):
            label.setText(tr(key))
        self.cultures_apply.setText(tr(N_("countries.sheet.apply")))
        self.current_flags_title.setText(tr(N_("countries.sheet.current_flags")))
        self.new_flags_title.setText(tr(N_("countries.sheet.new_flags")))
        self.flags_apply.setText(tr(N_("countries.sheet.flags_apply")))
        for suffix, label in self.current_flag_names.items():
            label.setText(f"{self.tag or 'TAG'}{suffix}.tga")
        self.party_table.setHorizontalHeaderLabels([tr(N_("countries.party.name")),
                                                    tr(N_("countries.party.ideology")),
                                                    tr(N_("countries.party.dates")),
                                                    tr(N_("countries.party.policies"))])
        self.party_name.setPlaceholderText(tr(N_("countries.party.name")))
        self.party_add.setText(tr(N_("countries.sheet.party_add")))
        self.party_remove.setText(tr(N_("countries.sheet.party_remove")))
        for label, key in zip(self.politics_labels, (N_("countries.field.government"), N_("countries.field.ruling_party"),
                                                     N_("countries.field.plurality"), N_("countries.field.prestige"),
                                                     N_("countries.field.nationalvalue"))):
            label.setText(tr(key))
        self.reforms_title.setText(tr(N_("countries.field.reforms")))
        self.reforms_apply.setText(tr(N_("countries.sheet.apply")))
        self.upper_title.setText(tr(N_("countries.field.upper_house")))
        self.upper_apply.setText(tr(N_("countries.sheet.apply")))
        for i in range(self.tech_template.count()):
            self.tech_template.setItemText(i, tr(TEMPLATES[self.tech_template.itemData(i)]))
        self.tech_fill.setText(tr(N_("countries.sheet.tech_fill")))
        self.tech_apply.setText(tr(N_("countries.sheet.tech_apply")))
        for label, key in zip(self.society_labels, (N_("countries.field.literacy"), N_("countries.field.nonstate_literacy"),
                                                    N_("countries.field.consciousness"),
                                                    N_("countries.field.nonstate_consciousness"),
                                                    N_("countries.field.school"))):
            label.setText(tr(key))
        self.relations_title.setText(tr(N_("countries.sheet.relations")))
        self.relation_table.setHorizontalHeaderLabels([tr(N_("war.diplomacy.col.type")),
                                                       tr(N_("war.diplomacy.col.other")),
                                                       tr(N_("war.diplomacy.col.start")),
                                                       tr(N_("war.diplomacy.col.end"))])
        self.wars_title.setText(tr(N_("countries.sheet.wars")))
        self.texts_note.setText(tr(N_("countries.sheet.texts_note")))
        self.text_table.setHorizontalHeaderLabels([tr(N_("countries.sheet.text_key")), "English", "Español"])
        self.reload()

    # --- datos ------------------------------------------------------------------------------------

    def _countries(self) -> core_nation.Countries | None:
        return countries_facade(self.session)

    def date(self):
        return getattr(self.session, "working_date", None)

    def bind(self, tag: str | None) -> None:
        self.tag = tag.upper() if tag else None
        self.oob_editor.bind(self.tag)
        self.reload()

    def _on_index(self, *args) -> None:
        """Los selectores que dependen del índice (ideologías, reformas, tecnologías) se rehacen con él."""
        if getattr(self.session, "index", None) is None:
            return
        self.upper_house.reload()
        self.issue_picker.reload()
        self.tech_checklist.reload()
        self.reload()

    def _on_documents(self, rels) -> None:
        if self.tag is not None and not self._loading:
            self.reload()

    def _on_tab(self, index: int) -> None:
        self.reload_tab(TABS[index][0])

    def current_tab(self) -> str:
        return TABS[self.tabs.currentIndex()][0]

    def show_tab(self, key: str) -> None:
        for index, (name, _label) in enumerate(TABS):
            if name == key:
                self.tabs.setCurrentIndex(index)

    def reload(self, *args) -> None:
        countries = self._countries()
        enabled = self.tag is not None and countries is not None
        self.tabs.setEnabled(enabled)
        date = self.date()
        self.date_label.setText(tr(N_("countries.sheet.date"), date=str(date)) if date is not None else "")
        if not enabled:
            self.title.setText(tr(N_("countries.sheet.none")))
            self.flag_label.clear()
            return
        self.title.setText(self._name_line())
        image = flag_image(flag_bytes(self.session, VPath.of(f"gfx/flags/{self.tag}.tga")))
        if image is not None:
            self.flag_label.setPixmap(to_pixmap(image))
        else:
            self.flag_label.clear()
        for key, _label in TABS:
            self.reload_tab(key)

    def _name_line(self) -> str:
        name = loc_text(self.session, self.tag)
        return f"{self.tag} · {name}" if name else str(self.tag)

    def reload_tab(self, key: str) -> None:
        countries = self._countries()
        if self.tag is None or countries is None:
            return
        self._loading = True
        try:
            getattr(self, f"_load_{key}")(countries, self.date())
        finally:
            self._loading = False

    def _load_identity(self, countries, date) -> None:
        loc = self.session.locsync
        for lang in LANGS:
            with QSignalBlocker(self.name_edits[lang]):
                self.name_edits[lang].setText(loc.text(self.tag, lang) or "")
            with QSignalBlocker(self.adj_edits[lang]):
                self.adj_edits[lang].setText(loc.text(f"{self.tag}_ADJ", lang) or "")
        color = countries.file_value(self.tag, "color")
        with QSignalBlocker(self.color_field):
            self.color_field.set_value(tuple(color) if color else None)
        with QSignalBlocker(self.gfx_picker):
            self.gfx_picker.set_value(countries.file_value(self.tag, "graphical_culture"))
        values = countries.values(self.tag, date)
        capital = values.get("capital")
        with QSignalBlocker(self.capital_picker):
            self.capital_picker.set_value(int(capital) if capital and str(capital).isdigit() else None)
        with QSignalBlocker(self.culture_picker):
            self.culture_picker.set_value(values.get("primary_culture"))
        with QSignalBlocker(self.cultures_picker):
            self.cultures_picker.set_values(countries.cultures(self.tag, date))
        with QSignalBlocker(self.religion_picker):
            self.religion_picker.set_value(values.get("religion"))
        with QSignalBlocker(self.civilized_check):
            self.civilized_check.setChecked(str(values.get("civilized", "no")).lower() == "yes")
        record = countries.record(self.tag)
        files = [str(record.handle.rel)] if record is not None and getattr(record, "handle", None) else []
        country_file = countries.country_file(self.tag)
        if country_file:
            files.append(f"common/{country_file}")
        self.file_info.setText("\n".join(files))

    def _load_flags(self, countries, date) -> None:
        for suffix, label in self.current_flags.items():
            image = flag_image(flag_bytes(self.session, VPath.of(f"gfx/flags/{self.tag}{suffix}.tga")))
            if image is None:
                label.clear()
                label.setText(tr(N_("countries.sheet.no_flag")))
            else:
                label.setPixmap(to_pixmap(image))
            self.current_flag_names[suffix].setText(f"{self.tag}{suffix}.tga")
        color = countries.file_value(self.tag, "color")
        if color:
            self.flag_studio.set_color(tuple(color))

    def file_parties(self) -> list[tuple[str, str, str, str]]:
        """``(nombre, ideología, fechas, políticas)`` de los partidos del archivo de país, en su orden."""
        countries = self._countries()
        record = countries.country_record(self.tag) if countries is not None and self.tag else None
        if record is None:
            return []
        rows = []
        policies = ("economic_policy", "trade_policy", "religious_policy", "citizenship_policy", "war_policy")
        for group in record.groups("party"):
            block = group.block
            dates = f"{block.get_text('start_date') or ''} – {block.get_text('end_date') or ''}"
            rows.append((block.get_text("name") or "", block.get_text("ideology") or "", dates,
                         ", ".join(block.get_text(key) for key in policies if block.get_text(key))))
        return rows

    def _load_parties(self, countries, date) -> None:
        rows = self.file_parties()
        self.party_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.party_table.setItem(row, column, QTableWidgetItem(value))
        self.party_table.resizeColumnsToContents()

    def _load_politics(self, countries, date) -> None:
        values = countries.values(self.tag, date)
        with QSignalBlocker(self.government_picker):
            self.government_picker.set_value(values.get("government"))
        current = values.get("ruling_party")
        self.ruling_combo.clear()
        for name, _ideology, _dates, _policies in self.file_parties():
            if self.ruling_combo.findData(name) < 0:
                self.ruling_combo.addItem(name, name)
        if current and self.ruling_combo.findData(current) < 0:
            self.ruling_combo.addItem(str(current), current)
        self.ruling_combo.setCurrentIndex(max(0, self.ruling_combo.findData(current)) if current else -1)
        for spin, key in ((self.plurality_spin, "plurality"), (self.prestige_spin, "prestige")):
            with QSignalBlocker(spin):
                spin.setValue(_float(values.get(key)))
        with QSignalBlocker(self.value_picker):
            self.value_picker.set_value(values.get("nationalvalue"))
        civilized = str(values.get("civilized", "no")).lower() == "yes"
        self.issue_picker.set_civilized(civilized)
        self.issue_picker.set_value(countries.reforms(self.tag, date))
        self.upper_house.set_value(countries.upper_house(self.tag, date))

    def _load_technology(self, countries, date) -> None:
        self.tech_checklist.set_selected(countries.technologies(self.tag, date))

    def _load_territory(self, countries, date) -> None:
        pids = countries.provinces(self.tag, date)
        self.territory_note.setText(tr(N_("countries.sheet.territory_note"), count=len(pids), date=str(date)))
        self.province_list.clear()
        for pid in pids:
            name = self.session.map.province_name(pid) if hasattr(self.session, "map") else None
            item = QListWidgetItem(f"{pid} - {name}" if name else str(pid))
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.province_list.addItem(item)

    def _load_society(self, countries, date) -> None:
        values = countries.values(self.tag, date)
        for spin, key in ((self.literacy_spin, "literacy"), (self.nonstate_spin, "non_state_culture_literacy"),
                          (self.consciousness_spin, "consciousness"),
                          (self.nonstate_consciousness_spin, "nonstate_consciousness")):
            with QSignalBlocker(spin):
                spin.setValue(_float(values.get(key)))
        with QSignalBlocker(self.school_picker):
            self.school_picker.set_value(values.get("schools"))

    def _load_army(self, countries, date) -> None:
        if self.oob_editor.tag != self.tag:
            self.oob_editor.bind(self.tag)
        else:
            self.oob_editor.reload()

    def _load_diplomacy(self, countries, date) -> None:
        context = domain_context(self.session)
        relations = core_war.relations(context, self.tag) if context is not None else []
        self.relation_table.setRowCount(len(relations))
        for row, relation in enumerate(relations):
            other = relation.second if relation.first.upper() == self.tag else relation.first
            values = (tr(RELATION_LABELS.get(relation.type, relation.type)), other, relation.start_date or "",
                      relation.end_date or "")
            for column, value in enumerate(values):
                self.relation_table.setItem(row, column, QTableWidgetItem(value))
        self.war_list.clear()
        for rel, model in core_war.wars(context) if context is not None else ():
            if self.tag in {tag.upper() for tag in model.participants()}:
                side = tr(N_("war.side.attacker")) if self.tag in {t.upper() for t in model.attackers} \
                    else tr(N_("war.side.defender"))
                item = QListWidgetItem(f"{model.name} · {model.start or '?'} – {model.end or '…'} · {side}")
                item.setData(Qt.ItemDataRole.UserRole, rel)
                self.war_list.addItem(item)

    def text_keys(self) -> list[str]:
        keys = [self.tag, f"{self.tag}_ADJ"]
        for name, _ideology, _dates, _policies in self.file_parties():
            if name and name not in keys:
                keys.append(name)
        return keys

    def _load_texts(self, countries, date) -> None:
        loc = self.session.locsync
        keys = self.text_keys()
        with QSignalBlocker(self.text_table):
            self.text_table.setRowCount(len(keys))
            for row, key in enumerate(keys):
                item = QTableWidgetItem(key)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.text_table.setItem(row, 0, item)
                for column, lang in enumerate(LANGS, start=1):
                    cell = QTableWidgetItem(loc.text(key, lang) or "")
                    cell.setData(Qt.ItemDataRole.UserRole, (key, lang))
                    self.text_table.setItem(row, column, cell)

    # --- edición ----------------------------------------------------------------------------------

    def _apply(self, label: str, action, **fmt) -> bool:
        """Ejecuta ``action(countries, date)`` en una transacción ``label``; False si falla o no cambia nada."""
        countries = self._countries()
        if self.tag is None or countries is None or self._loading:
            return False
        try:
            with self.session.edit(label, tag=self.tag, **fmt):
                action(countries, self.date())
        except (core_nation.NationError, ValueError, KeyError) as exc:
            self.status_requested.emit(N_("countries.sheet.failed"), {"error": str(exc)})
            self.reload()
            return False
        self.status_requested.emit(N_("countries.sheet.done"), {"tag": self.tag})
        return True

    def _commit_history(self, key: str, value) -> bool:
        return self._apply(core_nation.UNDO_COUNTRY_SET, lambda c, d: c.set(self.tag, key, value, d), field=key)

    def _commit_file(self, key: str, value) -> bool:
        if value is None:
            return False
        value = tuple(value) if key == "color" else value
        return self._apply(core_nation.UNDO_COUNTRY_FILE, lambda c, d: c.set_file_value(self.tag, key, value),
                           field=key)

    def _on_civilized(self, on: bool) -> None:
        if self._commit_history("civilized", on):
            self.issue_picker.set_civilized(on)

    def set_text(self, key: str, lang: str, text: str) -> bool:
        loc = self.session.locsync
        if self.tag is None or loc is None or (loc.text(key, lang) or "") == text:
            return False
        try:
            with self.session.edit(core_nation.UNDO_COUNTRY_TEXTS, tag=self.tag):
                loc.set_text(key, lang, text, area=LOC_AREA)
        except (ValueError, KeyError, OSError) as exc:
            self.status_requested.emit(N_("countries.sheet.failed"), {"error": str(exc)})
            return False
        loc.invalidate()
        self.reload()
        return True

    def _commit_text(self, suffix: str, lang: str) -> None:
        if self.tag is None or self._loading:
            return
        edit = (self.adj_edits if suffix else self.name_edits)[lang]
        self.set_text(f"{self.tag}{suffix}", lang, edit.text().strip())

    def _on_text_item(self, item: QTableWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and not self._loading:
            key, lang = data
            self.set_text(key, lang, item.text().strip())

    def apply_cultures(self) -> bool:
        wanted = list(self.cultures_picker.values())
        return self._apply(core_nation.UNDO_COUNTRY_SET, lambda c, d: c.set_cultures(self.tag, wanted, d),
                           field="culture")

    def apply_reforms(self) -> bool:
        reforms = self.issue_picker.value()
        return self._apply(core_nation.UNDO_COUNTRY_REFORMS, lambda c, d: c.set_reforms(self.tag, reforms, d))

    def apply_upper_house(self) -> bool:
        shares = self.upper_house.value()
        if shares and abs(self.upper_house.total() - 100) > 0.001:
            self.status_requested.emit(N_("countries.error.upper_house"), {})
            return False
        return self._apply(core_nation.UNDO_COUNTRY_UPPER_HOUSE,
                           lambda c, d: c.set_upper_house(self.tag, shares, d))

    def fill_tech_template(self) -> None:
        from ..pickers.tech_tree import TechTreeDialog

        key = self.tech_template.currentData()
        self.tech_checklist.set_selected(TechTreeDialog.template(self, key, self.tech_like.value()))

    @property
    def checklist(self):
        """Para ``TechTreeDialog.template`` (la plantilla «como» sin país devuelve lo marcado)."""
        return self.tech_checklist

    def apply_technologies(self) -> bool:
        wanted = self.tech_checklist.selected()
        return self._apply(core_nation.UNDO_COUNTRY_TECH, lambda c, d: c.set_technologies(self.tag, wanted, d))

    def apply_flags(self) -> bool:
        from ...core.project.binary import put_bytes

        try:
            flags = self.flag_studio.flags()
        except ValueError as exc:
            self.status_requested.emit(N_("countries.sheet.failed"), {"error": str(exc)})
            return False
        project = self.session.project

        def action(countries, date):
            for suffix, data in flags.items():
                put_bytes(project.ws, VPath.of(f"gfx/flags/{self.tag}{suffix}.tga"), data)
        return self._apply(core_nation.UNDO_COUNTRY_FLAGS, action)

    def add_party(self, name: str, ideology: str) -> bool:
        return self._apply(core_nation.UNDO_COUNTRY_FILE, lambda c, d: c.add_party(self.tag, name, ideology),
                           field="party")

    def add_party_from_form(self) -> bool:
        name, ideology = self.party_name.text().strip(), self.party_ideology.value()
        if not name or not ideology:
            self.status_requested.emit(N_("countries.sheet.party_incomplete"), {})
            return False
        if self.add_party(name, ideology):
            self.party_name.clear()
            return True
        return False

    def remove_selected_party(self) -> bool:
        row = self.party_table.currentRow()
        if row < 0:
            return False
        return self._apply(core_nation.UNDO_COUNTRY_FILE, lambda c, d: c.remove_party(self.tag, row), field="party")


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
