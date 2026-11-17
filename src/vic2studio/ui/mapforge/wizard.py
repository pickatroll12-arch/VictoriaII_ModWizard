"""El asistente del taller de mapas (wizard §18.2): pasos a la izquierda, vista previa en el centro, parámetros y
herramientas a la derecha y la barra de semilla, regeneración, deshacer, progreso y problemas abajo.

Pantallas de la iteración 9a (nivel «Solo mapa»): 0 ¿Qué quieres hacer?, 1 Lienzo, 2 Relieve, 3 Clima y agua,
4 Terreno, 5 Provincias, 6 Estados, continentes y climas, 7 Dueños, 9 Población y economía, 10 Nombres,
11 Estrechos y detalles, 12 Revisión y exportación y 13 Hecho. Con el origen «Importar bitmaps» las pantallas 2–5
se sustituyen por «Importar recursos» (§18.6). La 8 (culturas y religiones) es del nivel Mundo (9b).

Todo el cálculo va al proceso trabajador (``ForgeClient``); el asistente guarda el mundo de la vista previa
(etapa de celdas + ráster a W/4) y, en la revisión, el final (escala 1). Las ediciones a mano son ``EditOp`` del
mundo con su propia pila de deshacer; el proyecto del taller y la exportación se escriben en **una** transacción
del proyecto (``undo.mapforge_export``), o con «Guardar proyecto» (``undo.mapforge_save``).
"""

from __future__ import annotations

import logging
import random

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ...core.mapforge import edits as edit_ops
from ...core.mapforge.data.templates import FMG_TEMPLATES
from ...core.mapforge.imports import fmg_template
from ...core.mapforge.params import ForgeParams, LatticeSpec, Level, Origin, Owners
from ...core.mapforge.pipeline import step_ids
from ...core.mapforge.validate import fix_params, world_issues
from ...core.mapforge.worker import ForgeCommand
from ...i18n import N_, tr
from ..widgets import make_icon
from .entity_tables import NamesTable, StraitsTable
from .import_panel import ImportPanel
from .preview import MODE_LABELS, MODES, PreviewView, render, to_qimage
from .review import ReviewPanel
from .worker_client import ForgeClient

log = logging.getLogger(__name__)

# (clave, número visible, título, paso del pipeline desde el que regenerar)
SCREENS = (
    ("start", "0", N_("forge.screen.start"), None),
    ("canvas", "1", N_("forge.screen.canvas"), "relief"),
    ("relief", "2", N_("forge.screen.relief"), "relief"),
    ("climate", "3", N_("forge.screen.climate"), "climate"),
    ("terrain", "4", N_("forge.screen.terrain"), "biomes"),
    ("import", "2–5", N_("forge.screen.import"), None),
    ("provinces", "5", N_("forge.screen.provinces"), "provinces"),
    ("states", "6", N_("forge.screen.states"), "states"),
    ("owners", "7", N_("forge.screen.owners"), "owners"),
    ("economy", "9", N_("forge.screen.economy"), "economy"),
    ("names", "10", N_("forge.screen.names"), "names"),
    ("details", "11", N_("forge.screen.details"), None),
    ("review", "12", N_("forge.screen.review"), None),
    ("done", "13", N_("forge.screen.done"), None),
)
SCREEN_KEYS = tuple(s[0] for s in SCREENS)
GENERATED_ONLY = ("relief", "climate", "terrain")          # ocultas con «Importar bitmaps»
STATUS_LABELS = {"pending": N_("forge.status.pending"), "computed": N_("forge.status.computed"),
                 "edited": N_("forge.status.edited"), "imported": N_("forge.status.imported"),
                 "locked": N_("forge.status.locked")}
SIZES = ((5616, 2160), (2808, 1080), (1404, 540))
# El archivo que dice si el mapa del taller es el del mod (la exportación siempre lo escribe con este nombre).
EXPORTED_MAP = "map/provinces.bmp"
# Dónde está el mapa del proyecto del taller (``ForgeWizard.map_state``).
MAP_NOT_IN_MOD, MAP_UNSAVED, MAP_SAVED = "none", "unsaved", "saved"
MAP_CHANGED = "changed"            # el mod tiene lo exportado antes, pero el mapa del taller ha cambiado después
# Nombre visible de cada plantilla de relieve (las de FMG, con su nombre en inglés como clave).
TEMPLATE_LABELS = {
    "volcano": N_("forge.template.name.volcano"),
    "highIsland": N_("forge.template.name.high_island"),
    "lowIsland": N_("forge.template.name.low_island"),
    "continents": N_("forge.template.name.continents"),
    "archipelago": N_("forge.template.name.archipelago"),
    "atoll": N_("forge.template.name.atoll"),
    "mediterranean": N_("forge.template.name.mediterranean"),
    "peninsula": N_("forge.template.name.peninsula"),
    "pangea": N_("forge.template.name.pangea"),
    "isthmus": N_("forge.template.name.isthmus"),
    "shattered": N_("forge.template.name.shattered"),
    "taklamakan": N_("forge.template.name.taklamakan"),
    "oldWorld": N_("forge.template.name.old_world"),
    "fractious": N_("forge.template.name.fractious"),
}
TEMPLATE_ERRORS = {"unknown_op": N_("forge.template.error.unknown_op"),
                   "bad_number": N_("forge.template.error.bad_number"),
                   "bad_range": N_("forge.template.error.bad_range"), "bad_axis": N_("forge.template.error.bad_axis"),
                   "missing": N_("forge.template.error.missing")}
TOOLS = (("none", N_("forge.tool.none")), ("raise", N_("forge.tool.raise")), ("lower", N_("forge.tool.lower")),
         ("smooth", N_("forge.tool.smooth")), ("flatten", N_("forge.tool.flatten")),
         ("land", N_("forge.tool.land")), ("sea", N_("forge.tool.sea")))
LEVELS = (("map", N_("forge.level.map"), N_("forge.level.map.text")),
          ("world", N_("forge.level.world"), N_("forge.level.world.text")),
          ("overlay", N_("forge.level.overlay"), N_("forge.level.overlay.text")))
ORIGINS = (("generate", N_("forge.origin.generate")), ("bitmaps", N_("forge.origin.bitmaps")),
           ("heightmap", N_("forge.origin.heightmap")), ("fmg_json", N_("forge.origin.fmg_json")))
IMPORTED = ("bitmaps", "fmg_json")             # orígenes cuyas provincias vienen del archivo
# (pantalla, campo, tipo, (mín, máx, paso, decimales), avanzado, etiqueta)
FIELDS = (
    ("canvas", "land_provinces", "int", (0, 60000, 50, 0), False, N_("forge.param.land_provinces")),
    ("canvas", "sea_provinces", "int", (0, 20000, 10, 0), False, N_("forge.param.sea_provinces")),
    ("relief", "land_fraction", "float", (0.05, 0.95, 0.01, 2), False, N_("forge.param.land_fraction")),
    ("climate", "lat_south", "float", (-90, 0, 1, 0), True, N_("forge.param.lat_south")),
    ("climate", "lat_north", "float", (0, 90, 1, 0), True, N_("forge.param.lat_north")),
    ("climate", "temp_equator", "float", (-10, 50, 1, 0), True, N_("forge.param.temp_equator")),
    ("climate", "precipitation", "float", (0.1, 4, 0.1, 1), False, N_("forge.param.precipitation")),
    ("climate", "min_lake_cells", "int", (1, 500, 1, 0), True, N_("forge.param.min_lake_cells")),
    ("climate", "river_flux_quantile", "float", (0.3, 0.99, 0.01, 2), False, N_("forge.param.river_amount")),
    ("terrain", "hills_height", "int", (21, 99, 1, 0), True, N_("forge.param.hills_height")),
    ("terrain", "mountain_height", "int", (22, 100, 1, 0), True, N_("forge.param.mountain_height")),
    ("terrain", "farmland_share", "float", (0, 1, 0.05, 2), False, N_("forge.param.farmland_share")),
    ("provinces", "land_provinces", "int", (0, 60000, 50, 0), False, N_("forge.param.land_provinces")),
    ("provinces", "sea_provinces", "int", (0, 20000, 10, 0), False, N_("forge.param.sea_provinces")),
    ("provinces", "size_variance", "float", (0, 2, 0.05, 2), True, N_("forge.param.size_variance")),
    ("states", "provinces_per_state", "float", (1, 20, 0.1, 2), False, N_("forge.param.provinces_per_state")),
    ("owners", "existing_tags", "int", (1, 500, 1, 0), False, N_("forge.param.existing_tags")),
    ("owners", "colonized_fraction", "float", (0, 1, 0.05, 2), True, N_("forge.param.colonized_fraction")),
    ("owners", "countries", "int", (1, 400, 1, 0), False, N_("forge.param.countries")),
    ("owners", "culture_groups", "int", (1, 64, 1, 0), False, N_("forge.param.culture_groups")),
    ("owners", "civilized_fraction", "float", (0, 1, 0.05, 2), True, N_("forge.param.civilized_fraction")),
    ("economy", "total_population", "int", (1_000_000, 2_000_000_000, 1_000_000, 0), False,
     N_("forge.param.total_population")),
    ("details", "strait_max_gap_px", "int", (1, 64, 1, 0), False, N_("forge.param.strait_max_gap_px")),
)


# Campos del panel de dueños que solo tienen sentido en un nivel (los demás valen en todos).
LEVEL_FIELDS = {"existing_tags": "map", "colonized_fraction": "map", "countries": "world", "culture_groups": "world",
                "civilized_fraction": "world"}


def panel_slots() -> tuple[str, ...]:
    """Las ranuras de la importación: las de los bitmaps y la del JSON de FMG."""
    from ...core.mapforge.imports.bitmaps import SLOTS

    return tuple(SLOTS) + ("fmg_json",)


def _disk_stamp(project, rel: str) -> tuple | None:
    """(ruta, mtime en ns, tamaño) del archivo que gana en la VFS para ``rel``: cambia si el archivo cambia en el disco.
    None si no hay archivo o no se puede mirar."""
    entry = project.vfs.resolve(rel)
    path = getattr(entry, "path", None)
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return str(path), st.st_mtime_ns, st.st_size


def preview_scale(width: int) -> int:
    return 4 if width >= 2808 else (2 if width >= 1404 else 1)


class ForgeWizard(QWidget):
    navigate_requested = Signal(str)
    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None, *, inline: bool | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("forgeWizard")
        self.session = session
        if inline is None:
            import os

            inline = os.environ.get("VIC2STUDIO_FORGE_INLINE") == "1"
        self.client = ForgeClient(self, inline=inline)
        self.client.progress.connect(self._on_progress)
        self.client.finished.connect(self._on_finished)
        self.client.failed.connect(self._on_failed)
        self.client.cancelled.connect(self._on_cancelled)
        self.client.busyChanged.connect(self._on_busy)
        self.params = ForgeParams(seed=1)
        self.level = "map"
        self.origin = "generate"
        self.project_name = "mundo"
        self.install = None
        self.world = None              # vista previa: etapa de celdas + ráster a W/s
        self.final = None              # ráster final (escala 1) para la revisión
        self.files = None
        # (mundo, parámetros) con los que se pidió el render final, y el final del que salieron ``files``: si el
        # mundo o los parámetros cambian después, la revisión ya no es la de lo que se ve y no se deja exportar.
        self._final_for: tuple[object, ForgeParams] | None = None
        self._files_for = None
        self.inputs = None
        self.import_report = None
        self.exported: list[str] = []
        # rel → sha256 de lo que exportó este proyecto del taller (de ``export`` o del proyecto guardado): con él la
        # pantalla 13 sabe si el mapa del mod es este, también tras guardar, deshacer o volver a abrir el proyecto.
        self._exported_hashes: dict[str, str] = {}
        self._digest_memo: tuple[object, str] | None = None
        self._disk_memo: tuple[object, str] | None = None
        # La receta (``_recipe``) del mundo que se exportó y lo que dijo la exportación (archivos, provincias): sin
        # ella, la pantalla 13 llamaba «Hecho» a un mapa cambiado después de exportar y abría el de antes.
        self._exported_recipe: tuple | None = None
        self._exported_counts: tuple[int, int] | None = None
        self._recipe_memo: tuple | None = None
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._stroke: list[list[float]] = []
        self._pending_step: str | None = None
        self._deferred: list = []
        self._widgets: dict[tuple[str, str], QWidget] = {}
        self._advanced: list[QWidget] = []
        self._labels: dict[tuple[str, str], QLabel] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(450)
        self._debounce.timeout.connect(self._regenerate_pending)
        self._build()
        # Los campos se crean en el mínimo de su rango (0 provincias, 5 % de tierra, 1 000 000 de habitantes…): sin
        # esto, al abrir el taller enseñaban esos mínimos y tocar uno los metía en los parámetros (mapas de 13
        # provincias).
        self._load_params_into_widgets()
        self.retranslate()
        self._apply_level_visibility()
        for name in ("documentsChanged", "saved"):
            signal = getattr(session, name, None)
            if signal is not None:
                signal.connect(self._on_mod_changed)
        self.go("start")

    # --- construcción -------------------------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self._split = split
        self.steps = QListWidget()
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps.setObjectName("forgeSteps")
        self.steps.setMinimumWidth(230)
        self.steps.setMaximumWidth(290)
        for key in SCREEN_KEYS:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.steps.addItem(item)
        self.steps.currentRowChanged.connect(self._on_step_row)
        split.addWidget(self.steps)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.mode_label = QLabel()
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("forgeMode")
        for m in MODES:
            self.mode_combo.addItem("", m)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._refresh_preview())
        top.addWidget(self.mode_label)
        top.addWidget(self.mode_combo)
        top.addStretch(1)
        self.problems_label = QLabel()
        self.problems_label.setObjectName("forgeProblems")
        self.progress = QProgressBar()
        self.progress.setObjectName("forgeProgress")
        self.progress.setMaximumWidth(260)
        self.progress.setTextVisible(True)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("forgeCancel")
        self.cancel_button.clicked.connect(self.client.cancel)
        top.addWidget(self.problems_label)
        top.addWidget(self.progress)
        top.addWidget(self.cancel_button)
        cl.addLayout(top)
        self.hover_label = QLabel()
        self.hover_label.setObjectName("forgeHover")
        self.preview = PreviewView()
        self.preview.stroke.connect(self._on_stroke)
        self.preview.strokeFinished.connect(self._on_stroke_finished)
        self.preview.renamed.connect(self._on_rename_at)
        self.preview.hovered.connect(self._on_hover)
        cl.addWidget(self.preview, 1)
        cl.addWidget(self.hover_label)
        split.addWidget(center)
        self.panels = QStackedWidget()
        self.panels.setObjectName("forgePanels")
        self.panels.setMinimumWidth(330)
        self._panel_index: dict[str, int] = {}
        for key in SCREEN_KEYS:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            area.setWidget(getattr(self, f"_panel_{key}")())
            self._panel_index[key] = self.panels.addWidget(area)
        split.addWidget(self.panels)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)
        outer.addWidget(self._bottom_bar())

    def _title(self, key: str) -> QLabel:
        label = QLabel()
        label.setObjectName(f"forgePanelTitle_{key}")
        label.setWordWrap(True)
        label.setProperty("role", "subtitle")
        return label

    def _form(self, screen: str, layout: QVBoxLayout) -> QFormLayout:
        form = QFormLayout()
        for scr, field, kind, (lo, hi, step, dec), adv, label_key in FIELDS:
            if scr != screen:
                continue
            if kind == "int":
                w = QSpinBox()
                w.setRange(int(lo), int(hi))
                w.setSingleStep(int(step))
                w.setGroupSeparatorShown(True)
                w.valueChanged.connect(lambda v, f=field, s=screen: self._param_changed(s, f, int(v)))
            else:
                w = QDoubleSpinBox()
                w.setRange(lo, hi)
                w.setSingleStep(step)
                w.setDecimals(dec)
                w.valueChanged.connect(lambda v, f=field, s=screen: self._param_changed(s, f, float(v)))
            w.setObjectName(f"forgeParam_{screen}_{field}")
            label = QLabel()
            label.setProperty("i18n", label_key)
            form.addRow(label, w)
            self._widgets[(screen, field)] = w
            self._labels[(screen, field)] = label
            if adv:
                self._advanced += [label, w]
        layout.addLayout(form)
        return form

    def _panel(self, key: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 0, 6, 0)
        title = self._title(key)
        layout.addWidget(title)
        setattr(self, f"title_{key}", title)
        return w, layout

    def _panel_start(self) -> QWidget:
        w, layout = self._panel("start")
        self.level_buttons: dict[str, QRadioButton] = {}
        self.level_texts: dict[str, QLabel] = {}
        group = QButtonGroup(w)
        for key, _, _ in LEVELS:
            b = QRadioButton()
            b.setObjectName(f"forgeLevel_{key}")
            b.setEnabled(key in ("map", "world"))
            b.toggled.connect(lambda on, k=key: on and self._set_level(k))
            group.addButton(b)
            text = QLabel()
            text.setWordWrap(True)
            text.setIndent(22)
            layout.addWidget(b)
            layout.addWidget(text)
            self.level_buttons[key] = b
            self.level_texts[key] = text
        self.level_buttons["map"].setChecked(True)
        self.origin_label = QLabel()
        layout.addWidget(self.origin_label)
        self.origin_buttons: dict[str, QRadioButton] = {}
        og = QButtonGroup(w)
        for key, _ in ORIGINS:
            b = QRadioButton()
            b.setObjectName(f"forgeOrigin_{key}")
            b.toggled.connect(lambda on, k=key: on and self._set_origin(k))
            og.addButton(b)
            layout.addWidget(b)
            self.origin_buttons[key] = b
        self.origin_buttons["generate"].setChecked(True)
        self.target_label = QLabel()
        self.target_label.setObjectName("forgeTarget")
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        name_row = QHBoxLayout()
        self.name_label = QLabel()
        self.name_edit = QLineEdit(self.project_name)
        self.name_edit.setObjectName("forgeProjectName")
        self.name_edit.textChanged.connect(self._on_name)
        name_row.addWidget(self.name_label)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)
        self.saved_label = QLabel()
        layout.addWidget(self.saved_label)
        self.saved_list = QListWidget()
        self.saved_list.setObjectName("forgeSavedProjects")
        self.saved_list.setMaximumHeight(110)
        layout.addWidget(self.saved_list)
        row = QHBoxLayout()
        self.open_button = QPushButton()
        self.open_button.setObjectName("forgeOpenProject")
        self.open_button.setIcon(make_icon("folder_open"))
        self.open_button.clicked.connect(self.open_saved)
        self.quick_button = QPushButton()
        self.quick_button.setObjectName("forgeQuick")
        self.quick_button.setIcon(make_icon("refresh", "gold_light"))
        self.quick_button.clicked.connect(self.quick_generate)
        self.start_button = QPushButton()
        self.start_button.setObjectName("forgeStart")
        self.start_button.clicked.connect(lambda: self.go("canvas" if self.origin == "generate" else "import"))
        row.addWidget(self.open_button)
        row.addStretch(1)
        row.addWidget(self.start_button)
        row.addWidget(self.quick_button)
        layout.addLayout(row)
        self.install_label = QLabel()
        self.install_label.setObjectName("forgeInstall")
        self.install_label.setWordWrap(True)
        layout.addWidget(self.install_label)
        layout.addStretch(1)
        return w

    def _panel_canvas(self) -> QWidget:
        w, layout = self._panel("canvas")
        form = QFormLayout()
        self.size_label = QLabel()
        self.size_combo = QComboBox()
        self.size_combo.setObjectName("forgeSize")
        for W, H in SIZES:
            self.size_combo.addItem("", (W, H))
        self.size_combo.currentIndexChanged.connect(lambda _i: self._on_size())
        form.addRow(self.size_label, self.size_combo)
        layout.addLayout(form)
        self._form("canvas", layout)
        self.same_as_vanilla = QCheckBox()
        self.same_as_vanilla.setObjectName("forgeAutoTargets")
        self.same_as_vanilla.setChecked(True)
        self.same_as_vanilla.toggled.connect(self._on_auto_targets)
        layout.addWidget(self.same_as_vanilla)
        self.cells_label = QLabel()
        self.cells_label.setObjectName("forgeCells")
        self.cells_label.setWordWrap(True)
        layout.addWidget(self.cells_label)
        self.canvas_note = QLabel()
        self.canvas_note.setWordWrap(True)
        layout.addWidget(self.canvas_note)
        layout.addStretch(1)
        return w

    def _panel_relief(self) -> QWidget:
        w, layout = self._panel("relief")
        form = QFormLayout()
        self.template_label = QLabel()
        self.template_combo = QComboBox()
        self.template_combo.setObjectName("forgeTemplate")
        for name in FMG_TEMPLATES:
            self.template_combo.addItem("", name)
        self.template_combo.addItem("", "__custom__")
        self.template_combo.currentIndexChanged.connect(lambda _i: self._on_template())
        form.addRow(self.template_label, self.template_combo)
        layout.addLayout(form)
        self.template_edit = QPlainTextEdit()
        self.template_edit.setObjectName("forgeTemplateText")
        self.template_edit.setMaximumHeight(130)
        self.template_edit.textChanged.connect(self._on_template_text)
        layout.addWidget(self.template_edit)
        self.template_errors = QLabel()
        self.template_errors.setObjectName("forgeTemplateErrors")
        self.template_errors.setWordWrap(True)
        layout.addWidget(self.template_errors)
        self._form("relief", layout)
        self.tools_label = QLabel()
        layout.addWidget(self.tools_label)
        self.tool_group = QButtonGroup(w)
        tools = QGridLayout()
        tools.setSpacing(2)
        self.tool_buttons: dict[str, QToolButton] = {}
        for i, (key, _) in enumerate(TOOLS):
            b = QToolButton()
            b.setObjectName(f"forgeTool_{key}")
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.toggled.connect(lambda on, k=key: on and self._set_tool(k))
            self.tool_group.addButton(b)
            tools.addWidget(b, i // 4, i % 4)
            self.tool_buttons[key] = b
        self.tool_buttons["none"].setChecked(True)
        layout.addLayout(tools)
        bf = QFormLayout()
        self.radius_label = QLabel()
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setObjectName("forgeBrushRadius")
        self.radius_spin.setRange(0.005, 0.2)
        self.radius_spin.setSingleStep(0.005)
        self.radius_spin.setDecimals(3)
        self.radius_spin.setValue(0.03)
        self.radius_spin.valueChanged.connect(lambda _v: self._set_tool(self.tool))
        self.strength_label = QLabel()
        self.strength_spin = QSpinBox()
        self.strength_spin.setObjectName("forgeBrushStrength")
        self.strength_spin.setRange(1, 60)
        self.strength_spin.setValue(12)
        bf.addRow(self.radius_label, self.radius_spin)
        bf.addRow(self.strength_label, self.strength_spin)
        layout.addLayout(bf)
        self.tool = "none"
        layout.addStretch(1)
        return w

    def _panel_climate(self) -> QWidget:
        w, layout = self._panel("climate")
        self._form("climate", layout)
        layout.addStretch(1)
        return w

    def _panel_terrain(self) -> QWidget:
        w, layout = self._panel("terrain")
        self._form("terrain", layout)
        self.terrain_note = QLabel()
        self.terrain_note.setWordWrap(True)
        layout.addWidget(self.terrain_note)
        layout.addStretch(1)
        return w

    def _panel_import(self) -> QWidget:
        w, layout = self._panel("import")
        self.import_panel = ImportPanel(slots=panel_slots())
        self.import_panel.inspectRequested.connect(self.inspect_import)
        self.import_panel.buildRequested.connect(self.build_import)
        layout.addWidget(self.import_panel, 1)
        return w

    def _panel_provinces(self) -> QWidget:
        w, layout = self._panel("provinces")
        self._form("provinces", layout)
        self.provinces_stats = QLabel()
        self.provinces_stats.setObjectName("forgeProvinceStats")
        self.provinces_stats.setWordWrap(True)
        layout.addWidget(self.provinces_stats)
        self.provinces_note = QLabel()
        self.provinces_note.setWordWrap(True)
        layout.addWidget(self.provinces_note)
        layout.addStretch(1)
        return w

    def _panel_states(self) -> QWidget:
        w, layout = self._panel("states")
        self._form("states", layout)
        form = QFormLayout()
        self.continents_label = QLabel()
        self.continents_edit = QLineEdit()
        self.continents_edit.setObjectName("forgeContinents")
        self.continents_edit.editingFinished.connect(self._on_continents)
        form.addRow(self.continents_label, self.continents_edit)
        layout.addLayout(form)
        self.states_stats = QLabel()
        self.states_stats.setObjectName("forgeStateStats")
        self.states_stats.setWordWrap(True)
        layout.addWidget(self.states_stats)
        layout.addStretch(1)
        return w

    def _panel_owners(self) -> QWidget:
        w, layout = self._panel("owners")
        self.owners_buttons: dict[str, QRadioButton] = {}
        group = QButtonGroup(w)
        for mode in (Owners.EXISTING_TAGS, Owners.NONE):
            b = QRadioButton()
            b.setObjectName(f"forgeOwners_{mode.value}")
            b.toggled.connect(lambda on, m=mode: on and self._param_changed("owners", "owners", m))
            group.addButton(b)
            layout.addWidget(b)
            self.owners_buttons[mode.value] = b
        self.owners_buttons["existing_tags"].setChecked(True)
        self._form("owners", layout)
        self.owners_stats = QLabel()
        self.owners_stats.setObjectName("forgeOwnerStats")
        self.owners_stats.setWordWrap(True)
        layout.addWidget(self.owners_stats)
        # Galería de banderas de «Mundo» (las que escribirá la exportación).
        self.flags_label = QLabel()
        self.flags_label.setProperty("i18n", N_("forge.flags.title"))
        self.flags_label.setWordWrap(True)
        layout.addWidget(self.flags_label)
        self.flag_gallery = QListWidget()
        self.flag_gallery.setObjectName("forgeFlagGallery")
        self.flag_gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.flag_gallery.setIconSize(QSize(62, 43))
        self.flag_gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.flag_gallery.setMovement(QListWidget.Movement.Static)
        self.flag_gallery.setMinimumHeight(170)
        layout.addWidget(self.flag_gallery, 1)
        layout.addStretch(1)
        return w

    def _panel_economy(self) -> QWidget:
        w, layout = self._panel("economy")
        self._form("economy", layout)
        self.economy_stats = QLabel()
        self.economy_stats.setObjectName("forgeEconomyStats")
        self.economy_stats.setWordWrap(True)
        layout.addWidget(self.economy_stats)
        layout.addStretch(1)
        return w

    def _panel_names(self) -> QWidget:
        w, layout = self._panel("names")
        form = QFormLayout()
        self.source_label = QLabel()
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("forgeNameSource")
        self.source_combo.addItem("", "syllables")
        self.source_combo.addItem("", "custom")
        self.source_combo.currentIndexChanged.connect(self._on_name_source)
        form.addRow(self.source_label, self.source_combo)
        layout.addLayout(form)
        self.custom_names = QPlainTextEdit()
        self.custom_names.setObjectName("forgeCustomNames")
        self.custom_names.setMaximumHeight(70)
        self.custom_names.textChanged.connect(self._on_name_source)
        layout.addWidget(self.custom_names)
        self.names_table = NamesTable()
        self.names_table.renamed.connect(self.rename)
        layout.addWidget(self.names_table, 1)
        self.names_hint = QLabel()
        self.names_hint.setWordWrap(True)
        layout.addWidget(self.names_hint)
        return w

    def _panel_details(self) -> QWidget:
        w, layout = self._panel("details")
        self._form("details", layout)
        self.straits_table = StraitsTable()
        layout.addWidget(self.straits_table, 1)
        self.details_note = QLabel()
        self.details_note.setWordWrap(True)
        layout.addWidget(self.details_note)
        return w

    def _panel_review(self) -> QWidget:
        w, layout = self._panel("review")
        self.review = ReviewPanel()
        self.review.renderRequested.connect(self.render_final)
        self.review.fixRequested.connect(self.apply_fix)
        self.review.exportRequested.connect(self.export)
        layout.addWidget(self.review, 1)
        return w

    def _panel_done(self) -> QWidget:
        w, layout = self._panel("done")
        self.done_text = QLabel()
        self.done_text.setObjectName("forgeDoneText")
        self.done_text.setWordWrap(True)
        layout.addWidget(self.done_text)
        self.open_editor = QPushButton()
        self.open_editor.setObjectName("forgeOpenEditor")
        self.open_editor.setIcon(make_icon("map", "gold_light"))
        self.open_editor.clicked.connect(lambda: self.navigate_requested.emit("map:world"))
        # Sin exportar, la pantalla 13 no abre el editor (enseñaría el mapa de antes): lleva a «Exportar al mod».
        self.go_review = QPushButton()
        self.go_review.setObjectName("forgeGoReview")
        self.go_review.setIcon(make_icon("check", "gold_light"))
        self.go_review.clicked.connect(lambda: self.go("review"))
        self.keep_going = QPushButton()
        self.keep_going.setObjectName("forgeKeepGoing")
        self.keep_going.clicked.connect(lambda: self.go("canvas" if self.origin == "generate" else "import"))
        layout.addWidget(self.open_editor)
        layout.addWidget(self.go_review)
        layout.addWidget(self.keep_going)
        layout.addStretch(1)
        return w

    def _bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("forgeBottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 4, 0, 0)
        self.seed_label = QLabel()
        self.seed_spin = QSpinBox()
        self.seed_spin.setObjectName("forgeSeed")
        self.seed_spin.setRange(0, 2_000_000_000)
        self.seed_spin.setValue(self.params.seed)
        self.seed_spin.valueChanged.connect(self._on_seed)
        self.random_button = QPushButton()
        self.random_button.setObjectName("forgeRandomSeed")
        self.random_button.clicked.connect(lambda: self.seed_spin.setValue(random.randrange(1, 2_000_000_000)))
        self.regen_step = QPushButton()
        self.regen_step.setObjectName("forgeRegenStep")
        self.regen_step.clicked.connect(lambda: self.regenerate(only=True))
        self.regen_from = QPushButton()
        self.regen_from.setObjectName("forgeRegenFrom")
        self.regen_from.setIcon(make_icon("refresh"))
        self.regen_from.clicked.connect(lambda: self.regenerate())
        self.undo_button = QToolButton()
        self.undo_button.setObjectName("forgeUndo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QToolButton()
        self.redo_button.setObjectName("forgeRedo")
        self.redo_button.clicked.connect(self.redo)
        self.save_button = QPushButton()
        self.save_button.setObjectName("forgeSaveProject")
        self.save_button.clicked.connect(self.save_project)
        self.advanced_box = QCheckBox()
        self.advanced_box.setObjectName("forgeAdvanced")
        self.advanced_box.toggled.connect(self._on_advanced)
        for wgt in (self.seed_label, self.seed_spin, self.random_button, self.regen_step, self.regen_from,
                    self.undo_button, self.redo_button):
            row.addWidget(wgt)
        row.addStretch(1)
        row.addWidget(self.advanced_box)
        row.addWidget(self.save_button)
        return bar

    # --- textos -------------------------------------------------------------------------------------------

    def retranslate(self) -> None:
        for key, num, title_key, _ in SCREENS:
            getattr(self, f"title_{key}").setText(self._screen_help(key, num, title_key))
        for i, m in enumerate(MODES):
            self.mode_combo.setItemText(i, tr(MODE_LABELS[m]))
        self.mode_label.setText(tr("forge.preview.mode"))
        for label in self.findChildren(QLabel):
            key = label.property("i18n")
            if key:
                label.setText(tr(key))
        for key, title_key, text_key in LEVELS:
            self.level_buttons[key].setText(tr(title_key))
            self.level_texts[key].setText(tr(text_key))
        self.origin_label.setText(tr("forge.origin"))
        for key, label_key in ORIGINS:
            self.origin_buttons[key].setText(tr(label_key))
        self.name_label.setText(tr("forge.project_name"))
        self.saved_label.setText(tr("forge.saved_projects"))
        self.open_button.setText(tr("forge.open_project"))
        self.quick_button.setText(tr("forge.quick"))
        self.quick_button.setToolTip(tr("forge.quick.tooltip"))
        self.start_button.setText(tr("forge.start"))
        self.size_label.setText(tr("forge.param.size"))
        self.same_as_vanilla.setText(tr("forge.param.auto_targets"))
        self.canvas_note.setText(tr("forge.canvas.note"))
        self.template_label.setText(tr("forge.param.template"))
        self._show_install()
        for i in range(self.size_combo.count()):
            w_, h_ = self.size_combo.itemData(i)
            self.size_combo.setItemText(i, tr("forge.size.item", width=w_, height=h_))
        for i in range(self.template_combo.count() - 1):
            name = self.template_combo.itemData(i)
            self.template_combo.setItemText(i, tr(TEMPLATE_LABELS[name]) if name in TEMPLATE_LABELS else name)
        self.template_combo.setItemText(self.template_combo.count() - 1, tr("forge.template.custom"))
        self.tools_label.setText(tr("forge.tools"))
        for key, label_key in TOOLS:
            self.tool_buttons[key].setText(tr(label_key))
        self.radius_label.setText(tr("forge.brush.radius"))
        self.strength_label.setText(tr("forge.brush.strength"))
        self.terrain_note.setText(tr("forge.terrain.note"))
        self.provinces_note.setText(tr("forge.provinces.note"))
        self.continents_label.setText(tr("forge.param.continents"))
        self.owners_buttons["existing_tags"].setText(tr("forge.owners.existing"))
        self.owners_buttons["none"].setText(tr("forge.owners.none"))
        self.source_label.setText(tr("forge.param.name_source"))
        self.source_combo.setItemText(0, tr("forge.names.source.syllables"))
        self.source_combo.setItemText(1, tr("forge.names.source.custom"))
        self.custom_names.setPlaceholderText(tr("forge.names.custom_placeholder"))
        self.names_hint.setText(tr("forge.names.hint"))
        self.details_note.setText(tr("forge.details.note"))
        self.open_editor.setText(tr("forge.done.open_editor"))
        self.go_review.setText(tr("forge.done.go_review"))
        self.keep_going.setText(tr("forge.done.keep_going"))
        self.seed_label.setText(tr("forge.seed"))
        self.random_button.setText(tr("forge.seed.random"))
        self.regen_step.setText(tr("forge.regen.step"))
        self.regen_from.setText(tr("forge.regen.from"))
        self.undo_button.setText(tr("forge.undo"))
        self.redo_button.setText(tr("forge.redo"))
        self.cancel_button.setText(tr("forge.cancel"))
        self.save_button.setText(tr("forge.save_project"))
        self.save_button.setToolTip(tr("forge.save_project.tooltip"))
        self.advanced_box.setText(tr("forge.advanced"))
        self.names_table.retranslate()
        self.straits_table.retranslate()
        self.review.retranslate()
        self.import_panel.retranslate()
        self._refresh_all()
        self._on_mod_changed()

    def _screen_help(self, key: str, num: str, title_key: str) -> str:
        helps = {
            "start": N_("forge.help.start"), "canvas": N_("forge.help.canvas"), "relief": N_("forge.help.relief"),
            "climate": N_("forge.help.climate"), "terrain": N_("forge.help.terrain"),
            "import": N_("forge.help.import"), "provinces": N_("forge.help.provinces"),
            "states": N_("forge.help.states"), "owners": N_("forge.help.owners"),
            "economy": N_("forge.help.economy"), "names": N_("forge.help.names"),
            "details": N_("forge.help.details"), "review": N_("forge.help.review"), "done": N_("forge.help.done"),
        }
        return f"<b>{num}. {tr(title_key)}</b><br>{tr(helps[key])}"

    # --- navegación ---------------------------------------------------------------------------------------

    def current(self) -> str:
        item = self.steps.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else "start"

    def go(self, key: str) -> None:
        row = SCREEN_KEYS.index(key)
        if self.steps.currentRow() != row:
            self.steps.setCurrentRow(row)
        else:
            self._on_step_row(row)

    def _on_step_row(self, row: int) -> None:
        if row < 0:
            return
        key = SCREEN_KEYS[row]
        previous = getattr(self, "_screen", "start")
        if previous == "canvas" and key != "canvas" and self.params.lattice is None:
            self._fix_lattice()
        self._screen = key
        self.panels.setCurrentIndex(self._panel_index[key])
        self._fit_panels(key)
        self._set_tool(self.tool if key == "relief" else "none", keep=key == "relief")
        defaults = {"relief": "relief", "climate": "temperature", "terrain": "terrain", "provinces": "provinces",
                    "states": "states", "owners": "owners", "economy": "population", "names": "provinces",
                    "details": "provinces", "review": "problems", "import": "provinces", "canvas": "landsea"}
        if key in defaults:
            self.mode_combo.setCurrentIndex(MODES.index(defaults[key]))
        if key == "review" and self.world is not None and self.final is None and not self.client.busy:
            self.render_final()
        if key == "done":
            self._refresh_done()
        self._refresh_all()

    WIDE = ("import", "names", "details", "review")

    def _fit_panels(self, key: str) -> None:
        """Las pantallas con tablas (importación, nombres, estrechos y revisión) ensanchan la columna derecha."""
        total = max(900, self._split.width())
        left = self.steps.maximumWidth() if total > 1200 else self.steps.minimumWidth()
        right = int((total - left) * (0.56 if key in self.WIDE else 0.36))
        self._split.setSizes([left, total - left - right, right])

    def resizeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self._fit_panels(getattr(self, "_screen", "start"))

    def _fix_lattice(self) -> None:
        """La rejilla queda fija al salir del lienzo (§18.4): cambiar después la semilla o los objetivos no la mueve."""
        spec = self.params.lattice_spec()
        self.params = self.params.with_(lattice=LatticeSpec(spec.cells, spec.seed, spec.kind, spec.jitter,
                                                            spec.wrap_x))

    def _set_level(self, key: str) -> None:
        """«Solo mapa» o «Mundo»: el nivel cambia los dueños (TAG existentes o países nuevos) y lo que se exporta."""
        self.level = key
        level = Level(key)
        if self.params.level is not level:
            self.params = self.params.with_(level=level)
            if self.world is not None:
                self._schedule("owners")
        self._apply_level_visibility()
        self._refresh_steps()

    def _apply_level_visibility(self) -> None:
        advanced = self.advanced_box.isChecked() if hasattr(self, "advanced_box") else False
        world = self.params.level is Level.WORLD
        for b in getattr(self, "owners_buttons", {}).values():
            b.setVisible(not world)
        for w in (getattr(self, "flags_label", None), getattr(self, "flag_gallery", None)):
            if w is not None:
                w.setVisible(world)
        for (screen, field), w in self._widgets.items():
            want = LEVEL_FIELDS.get(field)
            on = want is None or (want == "world") == world
            if w in self._advanced:
                on = on and advanced
            w.setVisible(on)
            self._labels[(screen, field)].setVisible(on)

    def _fill_flags(self, world_data) -> None:
        """Una bandera por país de «Mundo», con su TAG y su nombre (vacía en «Solo mapa»)."""
        key = tuple((c["tag"], c["flag_seed"], tuple(c["color"])) for c in world_data["countries"]) \
            if world_data else ()
        if getattr(self, "_flags_key", None) == key:
            return
        self._flags_key = key
        self.flag_gallery.clear()
        from ...core.mapforge.nations import flag_preview
        from ..countries.flag_studio import to_pixmap

        for c in (world_data or {}).get("countries", []):
            item = QListWidgetItem(QIcon(to_pixmap(flag_preview(c))), c["tag"])
            item.setToolTip(f"{c['tag']} · {c['name']}")
            self.flag_gallery.addItem(item)

    def _set_origin(self, key: str) -> None:
        self.origin = key
        mapping = {"generate": Origin.GENERATE, "bitmaps": Origin.BITMAPS, "heightmap": Origin.HEIGHTMAP,
                   "fmg_json": Origin.FMG_JSON}
        self.params = self.params.with_(origin=mapping[key])
        if hasattr(self, "import_panel"):
            self._configure_import()
        self._refresh_steps()

    def _configure_import(self) -> None:
        slots = {"heightmap": ("heightmap",), "fmg_json": ("fmg_json",)}.get(self.origin)
        if slots is None:
            slots = tuple(s for s in panel_slots() if s != "fmg_json")
        panel = self.import_panel
        for r, slot in enumerate(panel.slots):
            panel.slot_table.setRowHidden(r, slots is not None and slot not in slots)

    # --- parámetros ---------------------------------------------------------------------------------------

    def _param_changed(self, screen: str, field: str, value) -> None:
        if getattr(self, "_loading", False):
            return
        if getattr(self.params, field) == value:
            return
        self.params = self.params.with_(**{field: value})
        for (scr, f), w in self._widgets.items():
            if f == field and scr != screen:
                w.blockSignals(True)
                w.setValue(value)
                w.blockSignals(False)
        if field in ("land_provinces", "sea_provinces"):
            self.same_as_vanilla.blockSignals(True)
            self.same_as_vanilla.setChecked(False)
            self.same_as_vanilla.blockSignals(False)
        step = dict((s[0], s[3]) for s in SCREENS).get(screen)
        if screen == "canvas" or self.world is None:
            step = None
        if screen == "details":
            step = "raster"
        self._schedule(step)
        self._refresh_all()

    def _schedule(self, step: str | None) -> None:
        if self.world is None and self.origin != "generate":
            return
        order = ("__all__",) + step_ids() + ("raster",)
        want = step or "__all__"
        cur = self._pending_step
        self._pending_step = want if cur is None else order[min(order.index(cur), order.index(want))]
        self._debounce.start()

    def _regenerate_pending(self) -> None:
        step, self._pending_step = self._pending_step, None
        if step is None:
            return
        if step == "__all__" or self.world is None:
            self.generate()
        elif step == "raster":
            self._run_preview(self.world)
        else:
            self.regenerate(step=step)

    def _load_params_into_widgets(self) -> None:
        self._loading = True
        try:
            for (_, field), w in self._widgets.items():
                v = getattr(self.params, field)
                if field == "land_provinces" and v is None:
                    v = self.params.land_target()
                if field == "sea_provinces" and v is None:
                    v = self.params.sea_target()
                w.setValue(v)
            idx = next((i for i, s in enumerate(SIZES) if s == tuple(self.params.size)), -1)
            if idx < 0:
                self.size_combo.addItem(tr("forge.size.item", width=self.params.width, height=self.params.height),
                                        tuple(self.params.size))
                idx = self.size_combo.count() - 1
            self.size_combo.setCurrentIndex(idx)
            t = self.template_combo.findData(self.params.template if not self.params.template_text else "__custom__")
            self.template_combo.setCurrentIndex(max(0, t))
            self.template_edit.setPlainText(self.params.template_text or FMG_TEMPLATES.get(self.params.template, ""))
            self.seed_spin.setValue(int(self.params.seed))
            self.owners_buttons[self.params.owners.value].setChecked(True)
            self.continents_edit.setText(", ".join(self.params.continents))
            if self.params.level.value in self.level_buttons:
                self.level_buttons[self.params.level.value].setChecked(True)
                self.level = self.params.level.value
        finally:
            self._loading = False
        self._apply_level_visibility()

    def _on_size(self) -> None:
        if getattr(self, "_loading", False):
            return
        size = self.size_combo.currentData()
        changes = {"size": tuple(size), "lattice": None}
        if self.same_as_vanilla.isChecked():
            changes.update(land_provinces=None, sea_provinces=None)
        self.params = self.params.with_(**changes)
        self._load_params_into_widgets()
        self.world = None
        self._schedule(None)
        self._refresh_all()

    def _on_auto_targets(self, on: bool) -> None:
        if on:
            self.params = self.params.with_(land_provinces=None, sea_provinces=None, lattice=None)
            self._load_params_into_widgets()
            self._schedule(None)

    def _on_seed(self, value: int) -> None:
        if getattr(self, "_loading", False) or value == self.params.seed:
            return
        self.params = self.params.with_(seed=int(value))
        self._schedule("relief" if self.world is not None and self.params.lattice is not None else None)

    def _on_template(self) -> None:
        if getattr(self, "_loading", False):
            return
        name = self.template_combo.currentData()
        if name == "__custom__":
            return
        self._loading = True
        self.template_edit.setPlainText(FMG_TEMPLATES[name])
        self._loading = False
        self.params = self.params.with_(template=name, template_text=None)
        self.template_errors.clear()
        self._schedule("relief")

    def _on_template_text(self) -> None:
        if getattr(self, "_loading", False):
            return
        text = self.template_edit.toPlainText()
        errors = fmg_template.validate(text)
        if errors:
            self.template_errors.setText("\n".join(tr("forge.template.error", line=e.line, column=e.column,
                                                     code=tr(TEMPLATE_ERRORS.get(e.code, TEMPLATE_ERRORS["missing"])))
                                                  for e in errors[:5]))
            return
        self.template_errors.clear()
        self.template_combo.blockSignals(True)
        self.template_combo.setCurrentIndex(self.template_combo.count() - 1)
        self.template_combo.blockSignals(False)
        self.params = self.params.with_(template_text=fmg_template.to_game(text))
        self._schedule("relief")

    def _on_continents(self) -> None:
        names = tuple(n.strip() for n in self.continents_edit.text().split(",") if n.strip())
        if names != tuple(self.params.continents):
            self._param_changed("states", "continents", names)

    def _on_name_source(self, *args) -> None:
        if getattr(self, "_loading", False):
            return
        src = self.source_combo.currentData()
        names = tuple(n.strip() for n in self.custom_names.toPlainText().splitlines() if n.strip())
        self.custom_names.setVisible(src == "custom")
        if (src, names) != (self.params.name_source, tuple(self.params.custom_names)):
            self.params = self.params.with_(name_source=src, custom_names=names)
            if src == "syllables" or names:
                self._schedule("names")

    def _on_name(self, text: str) -> None:
        self.project_name = "".join(ch for ch in text.strip() if ch.isalnum() or ch in "_-") or "mundo"

    def _on_advanced(self, on: bool) -> None:
        for w in self._advanced:
            w.setVisible(on)
        self._apply_level_visibility()

    # --- pinceles y ediciones -----------------------------------------------------------------------------

    def _set_tool(self, key: str, keep: bool = True) -> None:
        self.tool = key if keep else self.tool
        active = key if keep else "none"
        self.preview.brush_radius = self.radius_spin.value() if active != "none" else 0.0
        self.preview.update()

    def _on_stroke(self, x: float, y: float, first: bool) -> None:
        if first:
            self._stroke = []
        last = self._stroke[-1] if self._stroke else None
        if last is None or abs(last[0] - x) + abs(last[1] - y) > self.radius_spin.value() / 3:
            self._stroke.append([round(x, 4), round(y, 4)])

    def _on_stroke_finished(self) -> None:
        if not self._stroke or self.world is None or self.tool == "none":
            return
        r = round(self.radius_spin.value(), 4)
        if self.tool in ("land", "sea"):
            e = edit_ops.make("landsea_stroke", {"pts_norm": self._stroke, "r_norm": r, "to": self.tool})
        else:
            e = edit_ops.make("relief_stroke", {"tool": self.tool, "pts_norm": self._stroke, "r_norm": r,
                                                "strength": self.strength_spin.value()})
        self._stroke = []
        self.add_edit(e)

    def add_edit(self, edit) -> None:
        self._undo.append(tuple(self.world.edits))
        self._redo.clear()
        self.world = edit_ops.add(self.world, edit)
        self.regenerate(step=edit.step)

    def undo(self) -> None:
        if not self._undo or self.world is None:
            return
        self._redo.append(tuple(self.world.edits))
        self._restore_edits(self._undo.pop())

    def redo(self) -> None:
        if not self._redo or self.world is None:
            return
        self._undo.append(tuple(self.world.edits))
        self._restore_edits(self._redo.pop())

    def _restore_edits(self, edits: tuple) -> None:
        before = {e.uid for e in self.world.edits}
        after = {e.uid for e in edits}
        changed = [e for e in (*edits, *self.world.edits) if (e.uid in before) != (e.uid in after)]
        order = step_ids()
        step = min((e.step for e in changed), key=order.index, default="relief")
        self.world = self.world.evolve(edits=edits)
        self.regenerate(step=step)
        self._on_mod_changed()

    def _province_at(self, x: float, y: float) -> int:
        r = getattr(self.world, "raster", None)
        if r is None:
            return 0
        h, w = r.ids.shape
        return int(r.ids[min(h - 1, int(y * h)), min(w - 1, int(x * w))])

    def _on_hover(self, x: float, y: float) -> None:
        pid = self._province_at(x, y)
        r = getattr(self.world, "raster", None)
        if not pid or r is None:
            self.hover_label.clear()
            return
        name = r.names[pid] if r.names else ""
        self.hover_label.setText(tr("forge.hover", id=pid, name=name or "—",
                                    kind=tr("forge.hover.sea" if r.is_sea[pid] else "forge.hover.land")))

    def _on_rename_at(self, x: float, y: float) -> None:
        if self.current() != "names" or self.world is None:
            return
        pid = self._province_at(x, y)
        r = self.world.raster
        if not pid or r is None or r.is_sea[pid]:
            return
        name, ok = QInputDialog.getText(self, tr("forge.names.rename_title"), tr("forge.names.rename_label"),
                                        text=r.names[pid] or "")
        if ok and name.strip():
            self.rename("p", int(r.parent[pid]), name.strip())

    def rename(self, kind: str, provisional: int, name: str) -> None:
        if self.world is None or self.world.cells.province0 is None:
            return
        cells = np.flatnonzero(self.world.cells.province0 == provisional)
        if not cells.size:
            return
        self.add_edit(edit_ops.make("rename", {"uid": f"{kind}:{int(cells[0])}", "name": name}))

    # --- trabajos -----------------------------------------------------------------------------------------

    def _wait_install(self, then) -> bool:
        """Con un proyecto abierto, el mundo se genera con lo aprendido de su instalación: si aún no está, se pide
        y ``then`` se ejecuta al llegar."""
        if self.session.project is None or self.install is not None:
            return False
        self._deferred.append(then)
        self.learn_install()
        return True

    def _cmd_params(self) -> dict:
        return {"install": self.install, "scale": preview_scale(self.params.width), "with_textures": False}

    def generate(self) -> None:
        """Rejilla, etapa de celdas y vista previa con los parámetros actuales."""
        if self.origin in IMPORTED:
            return
        if self._wait_install(self.generate):
            return
        self._drop_final()
        args = {"params": self.params, **self._cmd_params()}
        if self.origin == "heightmap" and self.import_panel.files.get("heightmap") is not None:
            args["heightmap"] = self.import_panel.import_set().data("heightmap")
        self.client.run("generate", ForgeCommand("run_all", args))

    def quick_generate(self) -> None:
        """«Generación rápida»: todo con los valores por defecto y a la revisión."""
        self._quick = True
        if self.params.lattice is None:
            self._fix_lattice()
        self.generate()

    def regenerate(self, step: str | None = None, *, only: bool = False) -> None:
        if self.world is None:
            self.generate()
            return
        if step is None:
            step = dict((s[0], s[3]) for s in SCREENS).get(self.current()) or "relief"
        world = self.world.evolve(params=self.params) if hasattr(self.world, "evolve") else self.world
        self._drop_final()
        self.client.run("cells", ForgeCommand("run_cells", {"world": world, "from_step": step,
                                                            "until": step if only else None}))

    def _run_preview(self, world) -> None:
        self.client.run("preview", ForgeCommand("run_raster", {"world": world.evolve(params=self.params),
                                                               "scale": preview_scale(self.params.width),
                                                               "with_textures": False}))

    def render_final(self) -> None:
        if self.world is None:
            return
        self._final_for = (self.world, self.params)
        self.review.set_state(tr("forge.review.rendering"))
        if self.world.raster is not None and self.world.raster.scale == 1 and self.origin in IMPORTED:
            self._on_finished("final", type("R", (), {"world": self.world})())
            return
        self.client.run("final", ForgeCommand("run_raster", {"world": self.world.evolve(params=self.params),
                                                             "scale": 1, "with_textures": True}))

    def inspect_import(self) -> None:
        if self.origin == "heightmap":
            self.generate()
            return
        if self._wait_install(self.inspect_import):
            return
        self.client.run("inspect", ForgeCommand("import_bitmaps", {"files": self.import_panel.import_set(),
                                                                   "install": self.install, "build": False,
                                                                   "params": self.params}))

    def build_import(self) -> None:
        if self.origin == "heightmap":
            self.generate()
            return
        if self._wait_install(self.build_import):
            return
        self.client.run("import", ForgeCommand("import_bitmaps", {"files": self.import_panel.import_set(),
                                                                  "install": self.install, "build": True,
                                                                  "params": self.params}))

    def learn_install(self) -> None:
        project = self.session.project
        if project is None or self.install is not None or getattr(self, "_learning", False):
            return
        self._learning = True
        from ...core.mapforge.install import source_from_vfs

        self._show_install()
        self.client.run("install", ForgeCommand("learn_install", {"source": source_from_vfs(project.vfs)}))

    def _show_install(self) -> None:
        """Lo que se sabe de la instalación, en el idioma actual (también al cambiarlo)."""
        prof = self.install
        if prof is None:
            text = tr("forge.install.learning") if getattr(self, "_learning", False) else ""
        elif prof.synthetic:
            text = tr("forge.install.synthetic")
        else:
            text = tr("forge.install.ready", tags=len(prof.tags), dates=len(prof.pop_dates),
                      continents=len(prof.continents), climates=len(prof.climates))
        self.install_label.setText(text)

    def _on_progress(self, name: str, i: int, n: int) -> None:
        self.progress.setRange(0, max(1, n))
        self.progress.setValue(i + 1)
        self.progress.setFormat(tr("forge.progress", step=name, i=i + 1, n=n))

    def _on_busy(self, busy: bool) -> None:
        self.cancel_button.setEnabled(busy)
        if not busy:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat(tr("forge.progress.idle"))

    def _on_failed(self, tag: str, error: str) -> None:
        if tag == "install":
            from ...core.mapforge.install import synthetic_profile

            self._learning = False
            self.install = synthetic_profile()
            deferred, self._deferred = self._deferred, []
            for action in deferred:
                action()
        self.status_requested.emit(N_("forge.failed"), {"error": error})
        self.progress.setFormat(tr("forge.failed", error=error))
        if tag in ("final", "files") or self._export_not_ready():
            # La revisión no promete un render que ya no llega: dice qué falló («Render final» lo vuelve a pedir).
            self.review.set_state(tr("forge.failed", error=error))

    def _on_cancelled(self, tag: str) -> None:
        if tag == "install":
            self._learning = False
            self._deferred.clear()
        self.progress.setFormat(tr("forge.cancelled"))
        if tag in ("final", "files") or self._export_not_ready():
            # Cancelar no vuelve a lanzar trabajo por su cuenta: la revisión dice cómo prepararla otra vez.
            self.review.set_state(tr("forge.review.cancelled"))

    def _on_finished(self, tag: str, reply) -> None:
        if tag == "install":
            self._learning = False
            self.install = reply.report
            deferred, self._deferred = self._deferred, []
            for action in deferred:
                action()
            self._show_install()
            return
        if tag in ("generate", "preview"):
            self.world = reply.world
            if getattr(self, "_quick", False):
                self._quick = False
                self.go("review")
            self._refresh_all()
            return
        if tag == "cells":
            self._run_preview(reply.world)
            return
        if tag == "inspect":
            self.import_report = reply.report
            self.import_panel.set_report(reply.report)
            self._refresh_all()
            return
        if tag == "import":
            self.import_report = reply.report
            self.import_panel.set_report(reply.report)
            if reply.world is not None:
                self.world = reply.world
                self.params = reply.world.params
                self._load_params_into_widgets()
            self._refresh_all()
            return
        if tag == "final":
            if self._final_for is None or self._final_stale():
                # Un render pedido antes de cambiar el mundo o los parámetros (el trabajador va por detrás): no es
                # el mapa que se ve. Se pide otro si la revisión está a la vista.
                self._final_for = None
                self._ensure_final()
                return
            self.final = reply.world
            project = self.session.project
            from ...core.mapforge import export as ex

            self.inputs = ex.gather_inputs(project, self.final, index=getattr(self.session, "index", None)) \
                if project is not None else ex.ExportInputs()
            self.review.set_state(tr("forge.review.preparing"))
            self._files_for = self.final
            self.client.run("files", ForgeCommand("export_bytes", {"world": self.final, "inputs": self.inputs}))
            return
        if tag == "files":
            if self.final is None or self._files_for is not self.final:
                # Archivos de un final que ya se soltó (el mundo cambió mientras se preparaban): con el trabajador
                # libre, la revisión a la vista se vuelve a preparar para el mundo de ahora.
                self._ensure_final()
                return
            self.files = reply.files
            self._update_review(reply.report)
            return

    # --- revisión y exportación ---------------------------------------------------------------------------

    def _update_review(self, report=None) -> None:
        from ...core.mapforge import export as ex
        from ...core.mapforge.audit import DependencyAudit

        project = self.session.project
        world = self.final or self.world
        conflicts = edit_ops.conflicts(world) if world is not None else []
        issues = world_issues(world, self.inputs, conflicts=conflicts) if world is not None else []
        if project is not None and self.files is not None:
            from ...core.mapforge.nations import file_exists

            # Con lo sin guardar, como la exportación: si no, el plan y lo que se escribe podían no coincidir.
            plan = ex.export_plan(self.files, self.inputs, lambda rel: file_exists(project, rel), world=self.final)
            groups = DependencyAudit(project.vfs, world, self.inputs).run()
        else:
            plan, groups = [], []
        self.review.set_issues(issues)
        self.review.set_audit(groups)
        self.review.set_plan(plan)
        if project is None:
            self.review.set_state(tr("forge.review.no_project"))
        else:
            r = world.raster
            self.review.set_state(tr("forge.review.ready", provinces=r.count, land=r.land_count,
                                     sea=r.count - r.land_count, files=len(self.files or {})))
        self._refresh_preview()

    def apply_fix(self, issue, fix: str) -> None:
        new = fix_params(self.params, fix)
        if new is not None:
            self.params = new
            self._load_params_into_widgets()
            self.world = None
            self._drop_final()
            self.generate()
            return
        if fix == "discard_edit" and self.world is not None:
            uid = issue.args.get("uid")
            self._undo.append(tuple(self.world.edits))
            self._restore_edits(tuple(e for e in self.world.edits if e.uid != uid))
            return
        return

    def export(self) -> list[str]:
        """«Exportar al mod»: el mapa y sus recursos en **una** transacción. Si algo falla, la transacción ya se ha
        revertido entera (el mod queda como estaba) y se dice por qué en la revisión y en la barra de estado, en
        vez de perderse en la consola. Devuelve las rutas tocadas (vacío si no se exportó)."""
        project = self.session.project
        if project is None:
            return []
        if self.files is None or self.final is None or self._final_stale():
            # El mundo cambió después de la revisión (o aún se prepara): exportar ahora no haría nada o pondría un
            # mapa que ya no es el que se ve. Se vuelve a preparar y se dice, en vez de no hacer nada.
            if self._final_stale():
                self._drop_final()
            self.review.set_state(tr("forge.review.stale"))
            self._ensure_final()
            return []
        from ...core.mapforge import export as ex
        from ...core.mapforge.project import MapForgeProject, sha256

        hashes = {rel: sha256(data) for rel, data in self.files.items()}
        proj = MapForgeProject(self.project_name, self.params, edits=list(self.final.edits), exported=hashes)
        domain = None
        try:
            if self.final.params.level is Level.WORLD:
                from ..countries import domain_context

                domain = domain_context(self.session)
            touched = ex.apply_export(project, self.files, self.inputs, extra=proj.files(self.world),
                                      transaction=self.session.edit, world=self.final, domain=domain)
        except Exception as exc:  # noqa: BLE001 - la transacción ya se revirtió: se enseña el motivo
            log.exception("no se pudo exportar el mapa del taller")
            error = str(exc) or type(exc).__name__
            self.review.set_state(tr("forge.export.failed", error=error))
            self.status_requested.emit(N_("forge.export.failed"), {"error": error})
            return []
        if domain is not None and domain.loc is not None:
            domain.loc.invalidate()
        self.exported = touched
        self._exported_hashes = hashes
        self._exported_recipe = self._recipe(self.world, self.params)
        self._exported_counts = (len(self.files), self.final.raster.count if self.final.raster is not None else 0)
        self.go("done")
        return touched

    def save_project(self) -> None:
        """«Guardar proyecto»: los parámetros, los retoques y la etapa de celdas del taller (para seguir otro día).
        No toca el mapa del mod. Lo exportado se anota solo si lo que se guarda es el mapa que se exportó: si cambió
        después, el proyecto guardado no lo está (al volver a abrirlo, la pantalla 13 no dice «Hecho»)."""
        project = self.session.project
        if project is None or self.world is None:
            return
        from ...core.mapforge.project import MapForgeProject

        exported = dict(self._exported_hashes) if self._is_exported_world() else {}
        proj = MapForgeProject(self.project_name, self.params, edits=list(self.world.edits), exported=exported)
        with self.session.edit("undo.mapforge_save", name=self.project_name):
            proj.save(project.ws, self.world)
        self.status_requested.emit(N_("forge.saved"), {"name": self.project_name})
        self._refresh_saved()

    # --- pantalla 13 ---------------------------------------------------------------------------------------

    def map_state(self) -> str:
        """Dónde está el mapa de este proyecto del taller: ``MAP_NOT_IN_MOD`` (sin exportar, exportación deshecha
        o el mapa del mod cambiado después), ``MAP_CHANGED`` (el mod tiene lo exportado, pero el mapa del taller ha
        cambiado desde entonces), ``MAP_UNSAVED`` (exportado, sin guardar) o ``MAP_SAVED`` (escrito en el mod).
        Compara el ``map/provinces.bmp`` efectivo (con lo sin guardar) con la huella de lo exportado, y el mundo del
        taller con la receta del que se exportó."""
        project = self.session.project
        want = self._exported_hashes.get(EXPORTED_MAP)
        if project is None or not want:
            return MAP_NOT_IN_MOD
        from ...core.mapforge.project import sha256, workspace_reader
        from ...core.project.codecs import codec_for

        handle = project.ws.peek(EXPORTED_MAP)
        if handle is not None and handle.deleted:
            return MAP_NOT_IN_MOD
        if handle is not None:
            data, dirty = codec_for(handle.kind).snapshot(handle.model), bool(handle.dirty)
            if data is None:
                return MAP_NOT_IN_MOD
            memo = self._digest_memo           # el códec devuelve el mismo objeto mientras no cambia
            if memo is not None and memo[0] is data:
                digest = memo[1]
            else:
                digest = sha256(data)
                self._digest_memo = (data, digest)
        else:
            # Sin abrir (tras volver a abrir el mod): del disco, una vez por versión del archivo, no en cada edición.
            dirty = False
            stamp = _disk_stamp(project, EXPORTED_MAP)
            memo = self._disk_memo
            if stamp is not None and memo is not None and memo[0] == stamp:
                digest = memo[1]
            else:
                data = workspace_reader(project)(EXPORTED_MAP)
                if data is None:
                    return MAP_NOT_IN_MOD
                digest = sha256(data)
                self._disk_memo = (stamp, digest)
        if digest != want:
            return MAP_NOT_IN_MOD
        if not self._is_exported_world():
            return MAP_CHANGED
        return MAP_UNSAVED if dirty else MAP_SAVED

    def _recipe(self, world, params) -> tuple | None:
        """Lo que hace que un mapa del taller sea ese y no otro: parámetros, retoques y huellas de las celdas y de
        la tabla provisional (el ráster sale de ellos). No cambia con la vista previa ni al guardar y volver a abrir
        el proyecto; sí con cualquier cambio de verdad. None sin mundo."""
        if world is None:
            return None
        memo = self._recipe_memo
        if memo is not None and memo[0] is world and memo[1] is params:
            return memo[2]
        import json

        from ...core.mapforge.world import digest

        cells = world.cells
        # La rejilla libre (None) y la misma rejilla fijada al salir de «1. Lienzo» son el mismo mapa.
        fixed = params.with_(lattice=params.lattice_spec())
        recipe = (json.dumps(fixed.to_json(), ensure_ascii=False, sort_keys=True, default=str),
                  tuple(json.dumps(e.to_json(), ensure_ascii=False, sort_keys=True, default=str)
                        for e in world.edits),
                  world.cells_digest() if cells is not None and cells.h is not None else "",
                  world.world_digest())
        r = world.raster
        if params.origin.value in IMPORTED and r is not None and r.scale == 1:
            # Importado de bitmaps o de Azgaar: el ráster sale del archivo (cada píxel, los nombres, el terreno, los
            # ríos), no de las celdas. Dos importaciones con las mismas celdas no son el mismo mapa.
            recipe += (digest(r.ids, r.colors, r.terrain, r.rivers),
                       json.dumps(list(r.names or ()), ensure_ascii=False, default=str))
        self._recipe_memo = (world, params, recipe)
        return recipe

    def _is_exported_world(self) -> bool:
        """True si el mapa del taller de ahora es el que se exportó (en esta sesión o con el proyecto guardado)."""
        ref = self._exported_recipe
        return ref is not None and self._recipe(self.world, self.params) == ref

    def _refresh_done(self) -> None:
        """El texto y los botones de la pantalla 13 según ``map_state``: «Hecho» solo si el mapa está en el mod."""
        state = self.map_state()
        if state == MAP_NOT_IN_MOD:
            text = tr("forge.done.not_exported")
        elif state == MAP_CHANGED:
            text = tr("forge.done.changed")
        elif state == MAP_SAVED:
            text = tr("forge.done.saved", name=self.project_name)
        elif self._exported_counts is not None:
            # Las cifras de lo que se exportó, no las de la revisión de ahora (pueden ser de otro render).
            files, provinces = self._exported_counts
            text = tr("forge.done.text", files=files, name=self.project_name, provinces=provinces)
        else:
            text = tr("forge.done.unsaved", name=self.project_name)
        self.done_text.setText(text)
        in_mod = state in (MAP_UNSAVED, MAP_SAVED)
        self.open_editor.setVisible(in_mod)
        self.go_review.setVisible(not in_mod)

    def _on_mod_changed(self, *args) -> None:
        """Guardar, deshacer o rehacer la exportación, o un mundo nuevo en el taller, cambian lo que dice la pantalla
        13 si está a la vista. Con el taller oculto no se mira (al volver a enseñarlo, ``showEvent`` lo hace)."""
        if getattr(self, "_screen", "start") == "done" and self.isVisible():
            self._refresh_done()

    def open_saved(self) -> None:
        item = self.saved_list.currentItem()
        project = self.session.project
        if item is None or project is None:
            return
        from ...core.mapforge.project import MapForgeProject, workspace_reader

        name = item.text()
        proj, world, warnings = MapForgeProject.load(workspace_reader(project), name, self.install)
        self.project_name = name
        self.name_edit.setText(name)
        self.params = proj.params
        self._exported_hashes = dict(proj.exported)
        # Un proyecto guardado con lo exportado es el mapa que se exportó (``save_project`` no lo anota si cambió),
        # salvo si se importó: el proyecto no guarda el ráster del archivo y el de las celdas es otro mapa.
        imported = proj.params.origin.value in IMPORTED
        self._exported_recipe = self._recipe(world, proj.params) if proj.exported and not imported else None
        self._exported_counts = None
        self._load_params_into_widgets()
        self._undo.clear()
        self._redo.clear()
        if world is not None:
            self._run_preview(world)
            self.world = world
        if warnings:
            self.status_requested.emit("issue.forge_env_changed", {})
        self.go("canvas")

    # --- proyecto -----------------------------------------------------------------------------------------

    def on_project_opened(self, *args) -> None:
        """Al abrir un proyecto: olvida el mundo anterior. La instalación se aprende al enseñar el taller (o antes de
        generar), no al abrir: el resto de la aplicación no paga un proceso que quizá no se use."""
        self.install = None
        self._learning = False
        self.world = self.final = self.files = None
        self._final_for = self._files_for = None
        self._forget_export()
        self._refresh_saved()
        self._refresh_all()
        self._on_mod_changed()
        if self.isVisible():
            self.learn_install()

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().showEvent(event)
        if self.install is None and self.session.project is not None:
            self.learn_install()
        self._on_mod_changed()

    def on_project_closed(self, *args) -> None:
        self.client.cancel()
        self.install = None
        self.world = self.final = self.files = None
        self._final_for = self._files_for = None
        self._forget_export()
        self._refresh_saved()
        self._refresh_all()
        self._on_mod_changed()

    def _forget_export(self) -> None:
        """Otro mod (o ninguno): lo exportado por el taller en el anterior ya no cuenta."""
        self._exported_hashes, self._digest_memo, self._disk_memo = {}, None, None
        self._exported_recipe = self._exported_counts = self._recipe_memo = None

    def _refresh_saved(self) -> None:
        from ...core.mapforge.project import list_projects

        self.saved_list.clear()
        project = self.session.project
        if project is not None:
            for name in list_projects(project):
                self.saved_list.addItem(name)
        self.open_button.setEnabled(self.saved_list.count() > 0)

    # --- refresco -----------------------------------------------------------------------------------------

    def _final_stale(self) -> bool:
        """True si el render final se pidió para otro mundo u otros parámetros que los de ahora."""
        made = self._final_for
        return made is not None and (made[0] is not self.world or made[1] != self.params)

    def _drop_final(self) -> None:
        """Suelta el render final y sus archivos: la revisión deja de ofrecer «Exportar al mod» (su plan se vacía)
        hasta rehacerlos. Antes, el botón seguía activo con el plan viejo y no hacía nada."""
        had = self.final is not None or self.files is not None or bool(self.review.plan)
        self.final = self.files = None
        self._final_for = self._files_for = None
        if had:
            self.review.set_plan([])
            self.review.set_state(tr("forge.review.stale"))

    def _export_not_ready(self) -> bool:
        """True si hay mapa en el taller pero la revisión aún no tiene sus archivos (no se puede exportar)."""
        return self.world is not None and self.files is None

    def _ensure_final(self) -> None:
        """Con la revisión a la vista y sin render final al día, lo pide en cuanto el trabajador está libre."""
        if getattr(self, "_screen", "start") == "review" and self.world is not None and self.final is None \
                and self._final_for is None and not self.client.busy:
            self.render_final()

    def _refresh_all(self) -> None:
        if self._final_stale():
            self._drop_final()
        self._ensure_final()
        self._refresh_steps()
        self._refresh_preview()
        self._refresh_stats()
        self.undo_button.setEnabled(bool(self._undo))
        self.redo_button.setEnabled(bool(self._redo))
        self._on_mod_changed()                 # un mundo nuevo (o deshacer un retoque) cambia lo que dice la 13

    def _status_of(self, key: str) -> str | None:
        if key in ("start", "review", "done"):
            return None
        if key == "import":
            return "imported" if self.import_report is not None and self.world is not None else "pending"
        if self.world is None:
            return "pending"
        if self.origin in IMPORTED:
            matrix = self.import_report.matrix if self.import_report is not None else {}
            if key in ("provinces", "details") and str(matrix.get("provinces", "")).startswith("file"):
                return "imported"
        if key in ("canvas", "details"):
            return "computed"
        step = dict((s[0], s[3]) for s in SCREENS).get(key)
        st = self.world.steps.get(step)
        return st.status if st is not None else "pending"

    def _refresh_steps(self) -> None:
        for row, (key, num, title_key, _) in enumerate(SCREENS):
            item = self.steps.item(row)
            status = self._status_of(key)
            text = f"{num}. {tr(title_key)}"
            if status:
                text += f"  ·  {tr(STATUS_LABELS[status])}"
            item.setText(text)
            hidden = (key in GENERATED_ONLY and self.origin in IMPORTED) or \
                     (key == "import" and self.origin == "generate")
            item.setHidden(hidden)

    def _refresh_preview(self) -> None:
        world = self.final if self._screen_is_review() and self.final is not None else self.world
        mode = self.mode_combo.currentData() or "relief"
        problems = None
        if mode == "problems" and world is not None and world.raster is not None:
            problems = self._problem_ids(world)
        rgb = render(world, mode, problems=problems) if world is not None else None
        if rgb is not None:
            step = max(1, rgb.shape[1] // 1404)
            if step > 1:
                rgb = rgb[::step, ::step]
        self.preview.set_image(to_qimage(rgb) if rgb is not None else None)
        n = len(world_issues(world)) if world is not None else 0
        self.problems_label.setText(tr("forge.problems", count=n))

    def _screen_is_review(self) -> bool:
        return getattr(self, "_screen", "start") in ("review", "done")

    @staticmethod
    def _problem_ids(world) -> set[int]:
        r = world.raster
        deg = np.bincount(r.edges.ravel(), minlength=r.count + 1) if r.edges is not None and r.edges.size \
            else np.zeros(r.count + 1, np.int64)
        lonely = set((np.flatnonzero(deg[1:] == 0) + 1).tolist())
        area = np.bincount(r.ids.ravel(), minlength=r.count + 1)
        tiny = set((np.flatnonzero(area[1:] < 6) + 1).tolist())
        return lonely | tiny

    def _refresh_stats(self) -> None:
        p = self.params
        spec = p.lattice_spec()
        self.cells_label.setText(tr("forge.canvas.cells", cells=spec.cells, land=p.land_target(), sea=p.sea_target(),
                                    fixed=tr("forge.canvas.fixed" if p.lattice is not None else "forge.canvas.free")))
        project = self.session.project
        if project is None:
            self.target_label.setText(tr("forge.target.no_project"))
        else:
            from ...core.mapforge.export import REPLACED_FOLDERS
            from ...core.vfs.model import LayerKind

            n = 0
            for folder in REPLACED_FOLDERS:
                n += sum(1 for e in project.vfs.list(folder, "*", recursive=True) if e.layer.kind is LayerKind.MOD)
            self.target_label.setText(tr("forge.target.this_mod", mod=project.mod_root.name, trash=n))
        w = self.world
        r = getattr(w, "raster", None)
        if r is None:
            for label in (self.provinces_stats, self.states_stats, self.owners_stats, self.economy_stats):
                label.setText(tr("forge.stats.none"))
            self.names_table.fill(None)
            self.straits_table.fill(None)
            return
        area = np.bincount(r.ids.ravel(), minlength=r.count + 1)[1:r.land_count + 1] * (r.scale ** 2)
        self.provinces_stats.setText(tr("forge.stats.provinces", land=r.land_count, sea=r.count - r.land_count,
                                        median=int(np.median(area)) if area.size else 0,
                                        smallest=int(area.min()) if area.size else 0))
        n_states = int(r.state.max()) + 1 if r.state is not None and r.state.size and r.state.max() >= 0 else 0
        n_cont = len(w.entities.get("continent_names") or [])
        self.states_stats.setText(tr("forge.stats.states", states=n_states, continents=n_cont,
                                     names=", ".join(w.entities.get("continent_names") or [])))
        owners = w.entities.get("owners") or []
        owned = int((r.owner[1:r.land_count + 1] >= 0).sum()) if r.owner is not None else 0
        world_data = w.entities.get("world")
        self._fill_flags(world_data)
        if world_data:
            countries = world_data["countries"]
            self.owners_stats.setText(tr("forge.stats.world", countries=len(countries),
                                         civilized=sum(1 for c in countries if c["civilized"]),
                                         groups=len(world_data["groups"]), owned=owned, land=r.land_count,
                                         list=", ".join(f"{c['tag']} {c['name']}" for c in countries[:12])))
        else:
            self.owners_stats.setText(tr("forge.stats.owners", tags=len(owners), owned=owned, land=r.land_count,
                                         list=", ".join(owners[:12])))
        pop = int(np.asarray(r.population).sum()) if r.population is not None else 0
        dates = list(w.install.pop_dates) if w.install is not None and w.install.pop_dates else ["1836.1.1"]
        self.economy_stats.setText(tr("forge.stats.economy", population=f"{pop:,}".replace(",", " "),
                                      dates=", ".join(dates)))
        if self.current() == "names":
            self.names_table.fill(w)
        if self.current() == "details":
            self.straits_table.fill(w)

    def closeEvent(self, event) -> None:  # noqa: N802 - API de Qt
        self.client.close()
        super().closeEvent(event)


__all__ = ["ForgeWizard", "SCREENS", "SCREEN_KEYS", "preview_scale"]
