"""Ventana principal (wizard §13.2): estandarte, las 7 salas con su índice, acciones globales y barra de estado.

Las salas se descubren en ``ui/halls`` (``discover_halls``) y cada placa de la
barra de navegación lleva a una (Ctrl+1..7). Acciones globales: Guardar (Ctrl+S,
con el número de archivos sin guardar), Deshacer (Ctrl+Z), Rehacer (Ctrl+Y y
Ctrl+Mayús+Z), Historial, Problemas, el buscador universal (Ctrl+K,
``CommandPalette``) y Validar el mod (F7, el validador del núcleo en Proyecto ›
Validación; el botón «Validar mod» de Archivos hace lo mismo). El título lleva «*»
si hay cambios sin guardar y cerrar pregunta antes de perderlos.

Abrir un problema o un resultado de Ctrl+K lleva a Archivos con el archivo en su
línea (``open_location``); una clave de localización, a Textos › Todos los textos.
Mayús+Intro en Ctrl+K abre el código (``open_symbol_code``): el script en la pestaña
Código, un CSV que no es de localización en su ficha con la línea a la vista, y una
clave de texto, su CSV en «Archivos CSV» en su línea. Lo que solo está en memoria (un
documento nuevo o con cambios sin guardar) no se abre en el archivo del disco, cuyas
líneas son otras: la barra de estado lo dice. Los diálogos de las secciones de la
iteración 3 (plan de un arreglo, «Añadir clave») pasan por ``exec_dialog``, que las
pruebas sustituyen.

Los contadores del índice lateral (``SectionSpec.badge``) se recalculan una vez por vuelta
del bucle de eventos (``_badge_timer``: una edición avisaba tres veces) y solo los de la
sala a la vista; las demás se ponen al día al mostrarse.

El mod abierto lo deciden las rutas de «Archivos» (``ProjectPage``, que las guarda
en las preferencias): al cambiar, la ventana abre el proyecto con ``Session`` (que
lo hace en segundo plano) y avisa antes si hay cambios sin guardar. Inicio le pide
las rutas a través de la ventana. Guardar sigue D13: la revisión previa solo sale
si hay copias del juego base o papelera, o si el guardado encuentra conflictos o
errores (``SaveReviewDialog``; los conflictos se resuelven con ``ConflictDialog``).

Compatibilidad con la navegación de 5 páginas de la iteración 1: ``page(key)``
devuelve también ``ProjectPage`` («Archivos») y ``LocalisationPage`` («Archivos
CSV»), y ``set_current_page``/``current_page_index`` usan los índices de
``pages.PAGE_KEYS``.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.clausewitz import SourceMismatchError
from ..core.encoding import UnencodableTextError
from ..core.vfs.guard import evaluate_mod, inspect_folder, same_folder
from ..i18n import N_, available_languages, language, set_language, tr, translator
from ..settings import app_settings
from . import theme
from .dialogs import KEEP, RELOAD, ConflictDialog, NewModDialog, RecoveryDialog, SaveReviewDialog, needs_review
from .dialogs.recovery import DISCARD, RESTORE
from .halls import discover_halls
from .pages import PAGE_KEYS, BasePage
from .session import Session
from .shell import HallPage, HistoryDock
from .shell.command_palette import CommandPalette
from .shell.pending_changes import write_label
from .shell.problems_dock import ProblemsDock
from .tasks import cancel_all
from .widgets import HeaderBanner, NavBar, TexturedPanel, emblem_pixmap, icons_extra, make_icon, mark_data
from .widgets.busy import busy

SETTINGS_GEOMETRY = "ui/geometry"
SETTINGS_LAST_HALL = "ui/last_hall"
SETTINGS_LAST_SECTION = "ui/last_section/{hall}"
MINIMUM_SIZE = QSize(1100, 700)
DEFAULT_SIZE = QSize(1440, 900)
# Por debajo de este ancho de ventana el índice de cada sala pasa a ser una franja encima de la sección.
COMPACT_RAIL_WIDTH = 1360
# Márgenes alrededor de las placas y la sala; con la franja, menos arriba y abajo para no robarle alto a la sección.
BODY_MARGINS = (14, 12, 14, 12)
COMPACT_BODY_MARGINS = (14, 8, 14, 6)
LANGUAGE_COMBO_WIDTH = 130   # el estandarte lo ciñe a «Español» si a 1100 px no cabe todo (_fit_banner)
LANGUAGE_GAP = 14            # entre «Guardar» y el idioma (6 cuando hay que ceñirlo)
# Dónde vive cada página de la iteración 1 (``page(key)`` y ``show_page(key)``).
PAGE_SECTIONS = {"project": ("project", "files"), "localisation": ("localisation", "csv")}
UNSAVED_SAVE, UNSAVED_DISCARD, UNSAVED_CANCEL = "save", "discard", "cancel"


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(emblem_pixmap(size))
    return icon


class MainWindow(QMainWindow):
    """API: ``session``, ``halls``, ``hall(key)``, ``set_current_hall(i | clave)``, ``current_hall_index()``,
    ``page(key)``, ``show_page(key)``, ``navigate("sala:sección")``, ``save_project()``, ``open_new_mod_dialog()``,
    ``is_busy()``; y, por compatibilidad, ``set_current_page(i)`` y ``current_page_index()`` (``PAGE_KEYS``)."""

    def __init__(self, parent: QWidget | None = None, *, session: Session | None = None):
        super().__init__(parent)
        icons_extra.load()
        self.setObjectName("mainWindow")
        self.setMinimumSize(MINIMUM_SIZE)
        self.setWindowIcon(app_icon())
        self._status: tuple[str, dict] = ("status.ready", {})
        self._project_state: tuple[str, dict] = ("", {})
        self._closed = False
        self._resolving = False
        self.session = session if session is not None else Session(self)
        if self.session.parent() is None:
            self.session.setParent(self)

        central = TexturedPanel("wood", vignette=0.45)
        central.setObjectName("centralPanel")
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.banner = HeaderBanner()
        column.addWidget(self.banner)
        self._build_banner_actions()
        self.banner.installEventFilter(self)  # _fit_banner con el ancho ya repartido

        self._body = body = QVBoxLayout()
        body.setContentsMargins(*BODY_MARGINS)
        body.setSpacing(2)
        self.nav = NavBar()
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        column.addLayout(body, 1)
        self.setCentralWidget(central)

        self.halls: list[HallPage] = []
        self._hall_actions: list[QAction] = []
        for index, (spec, sections) in enumerate(discover_halls()):
            hall = HallPage(spec, sections, self.session)
            self.halls.append(hall)
            self.stack.addWidget(hall)
            self.nav.add_button(spec.icon)
            hall.status_requested.connect(self.show_status)
            hall.navigate_requested.connect(self.navigate)
            hall.save_requested.connect(self.save_project)
            hall.sectionChanged.connect(lambda section, h=index: self._on_section_changed(h, section))
            action = QAction(self)
            action.setObjectName(f"goto_{spec.key}")
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda checked=False, i=index: self.set_current_hall(i))
            self.addAction(action)
            self._hall_actions.append(action)
        self._build_actions()

        self.status_label = QLabel()
        self.status_label.setObjectName("statusMessage")
        self.statusBar().addWidget(self.status_label, 1)
        self.project_label = QLabel()
        self.project_label.setObjectName("statusProject")
        self.statusBar().addPermanentWidget(self.project_label)
        self.version_label = QLabel()
        self.version_label.setObjectName("statusVersion")
        self.version_label.setProperty("role", "muted")
        self.statusBar().addPermanentWidget(self.version_label)
        self.statusBar().setSizeGripEnabled(True)

        self.history_dock = HistoryDock(self.session, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.history_dock)
        self.history_dock.hide()
        self.history_dock.visibilityChanged.connect(self.history_button.setChecked)
        self.problems_dock = ProblemsDock(self.session, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.problems_dock)
        self.problems_dock.hide()
        self.problems_dock.visibilityChanged.connect(self.problems_button.setChecked)
        self.palette = CommandPalette(self.session, self._palette_sections, central)

        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.setInterval(0)
        self._open_timer.timeout.connect(self._open_current_mod)
        # Contadores del índice lateral: una vez por vuelta del bucle (un cambio avisaba con tres señales seguidas).
        self._badge_timer = QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.setInterval(0)
        self._badge_timer.timeout.connect(self._refresh_badges_now)
        self._stale_badges: set[int] = set()   # salas ocultas cuyos contadores se ponen al día al mostrarse
        self._wire_sections()
        self._wire_session()

        self.nav.currentChanged.connect(self._on_hall_changed)
        self.language_combo.currentIndexChanged.connect(self._on_language_selected)
        translator().languageChanged.connect(self._on_language_changed)
        QGuiApplication.instance().applicationStateChanged.connect(self._on_application_state)

        self._sync_language_combo()
        self.retranslate()
        self._restore_state()
        self._update_project_actions()
        self._open_timer.start()  # el mod de las preferencias se abre ya con la ventana construida

    # --- construcción ----------------------------------------------------------------------------

    def _build_banner_actions(self) -> None:
        self.language_label = QLabel()
        self.language_label.setObjectName("languageLabel")
        self.language_label.setFont(theme.font("heading", 10.5))
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setMinimumWidth(LANGUAGE_COMBO_WIDTH)
        for code, name in available_languages():
            self.language_combo.addItem(name, code)
        mark_data(self.language_combo)  # endónimos: no se traducen
        self.language_label.setBuddy(self.language_combo)

        box = QWidget()
        box.setProperty("surface", "velvet")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.undo_button = QToolButton()
        self.undo_button.setObjectName("undoButton")
        self.undo_button.setIcon(make_icon("undo", "gold_light"))
        self.undo_button.setIconSize(QSize(20, 20))
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QToolButton()
        self.redo_button.setObjectName("redoButton")
        self.redo_button.setIcon(make_icon("redo", "gold_light"))
        self.redo_button.setIconSize(QSize(20, 20))
        self.redo_button.clicked.connect(self.redo)
        self.history_button = QToolButton()
        self.history_button.setObjectName("historyButton")
        self.history_button.setCheckable(True)
        self.history_button.setIcon(make_icon("history", "gold_light"))
        self.history_button.setIconSize(QSize(20, 20))
        self.history_button.toggled.connect(self._on_history_toggled)
        self.problems_button = QToolButton()
        self.problems_button.setObjectName("problemsButton")
        self.problems_button.setCheckable(True)
        self.problems_button.setIcon(make_icon("warning", "gold_light"))
        self.problems_button.setIconSize(QSize(20, 20))
        self.problems_button.toggled.connect(self._on_problems_toggled)
        self.search_button = QToolButton()
        self.search_button.setObjectName("searchButton")
        self.search_button.setIcon(make_icon("search", "gold_pale"))
        self.search_button.setIconSize(QSize(18, 18))
        self.search_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.search_button.clicked.connect(lambda: self.open_palette())
        self.save_button = QPushButton()
        self.save_button.setObjectName("saveButton")
        self.save_button.setProperty("accent", True)
        self.save_button.setIcon(make_icon("save", "gold_pale"))
        self.save_button.clicked.connect(self.save_project)
        row.addWidget(self.search_button)
        row.addSpacing(8)
        for widget in (self.undo_button, self.redo_button, self.history_button, self.problems_button):
            row.addWidget(widget)
        row.addSpacing(4)
        row.addWidget(self.save_button)
        row.addSpacing(LANGUAGE_GAP)
        self._language_gap = row.itemAt(row.count() - 1).spacerItem()
        row.addWidget(self.language_label)
        row.addWidget(self.language_combo)
        self._banner_box = box
        self.banner.add_trailing_widget(box)

    def _fit_banner(self) -> None:
        """Que el estandarte quepa en el ancho de la ventana (1100 px como mínimo, ES y EN).

        Se recoge por pasos, de lo menos a lo más útil, solo hasta que cabe: primero se oculta la etiqueta
        «Idioma» (el desplegable ya lo dice), después «Buscar… Ctrl+K» queda en su icono (el texto sigue en
        ``text()``, en la descripción emergente y para la accesibilidad), luego se oculta el lema y, si aún
        falta (``Guardar (128)``), el desplegable del idioma se ciñe a su texto.
        """
        steps = (
            lambda on: self.language_label.setVisible(not on),
            lambda on: self.search_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if on else Qt.ToolButtonStyle.ToolButtonTextBesideIcon),
            lambda on: self.banner.tagline_label.setVisible(not on),
            lambda on: self._tighten_language(on),
        )
        for step in steps:
            step(False)
        width = self.banner.width()
        for step in steps:
            if self._banner_minimum() <= width:
                return
            step(True)

    def _tighten_language(self, on: bool) -> None:
        self.language_combo.setMinimumWidth(0 if on else LANGUAGE_COMBO_WIDTH)
        gap = 6 if on else LANGUAGE_GAP
        self._language_gap.changeSize(gap, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self._banner_box.layout().invalidate()

    def _banner_minimum(self) -> int:
        """El ancho mínimo del estandarte con lo que está visible ahora.

        Se suma a mano: el ``QWidgetItem`` de la caja de botones en el estandarte guarda su tamaño mínimo
        hasta que el bucle de eventos reactiva el layout, y aquí hace falta el de este mismo instante.
        """
        box = self._banner_box.layout()
        box.invalidate()
        banner = self.banner
        titles = [banner.title_label] + ([banner.tagline_label] if not banner.tagline_label.isHidden() else [])
        margins = banner.layout().contentsMargins()
        emblem = banner.emblem.minimumSize().expandedTo(banner.emblem.sizeHint()).width()  # tamaño fijo
        return (margins.left() + margins.right() + emblem + 2 * banner.layout().spacing()
                + max(label.minimumSizeHint().width() for label in titles) + box.minimumSize().width())

    def _build_actions(self) -> None:
        def action(name: str, shortcuts: list[str], slot) -> QAction:
            act = QAction(self)
            act.setObjectName(name)
            act.setShortcuts([QKeySequence(s) for s in shortcuts])
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            act.triggered.connect(lambda checked=False: slot())
            self.addAction(act)
            return act

        self.save_action = action("saveAction", ["Ctrl+S"], self.save_project)
        self.undo_action = action("undoAction", ["Ctrl+Z"], self.undo)
        self.redo_action = action("redoAction", ["Ctrl+Y", "Ctrl+Shift+Z"], self.redo)
        self.validate_action = action("validateAction", ["F7"], self.validate_mod)
        self.palette_action = action("paletteAction", ["Ctrl+K"], self.open_palette)

    def _wire_sections(self) -> None:
        project, localisation, home = self.page("project"), self.page("localisation"), self.page("home")
        self.descriptor_page = self.page("descriptor")
        project.mod_path_changed.connect(localisation.set_mod_path)
        project.csv_requested.connect(self.open_in_localisation)
        project.game_path_changed.connect(self._on_paths_changed)
        project.mod_path_changed.connect(self._on_paths_changed)
        localisation.set_mod_path(project.mod_path())
        home.set_game_path(project.game_path())
        home.set_mod_path(project.mod_path())
        home.game_path_selected.connect(project.set_game_path)
        home.mod_selected.connect(self.select_mod)
        home.new_mod_requested.connect(self.open_new_mod_dialog)
        self.descriptor_page.new_mod_requested.connect(self.open_new_mod_dialog)
        # «Validar mod» de Archivos usa ya el validador del núcleo (Proyecto › Validación), como F7.
        project.validate_button.clicked.disconnect()
        project.validate_button.clicked.connect(self.validate_mod)
        self.validation_page = self.page("project:validation")
        self.validation_page.open_requested.connect(self.open_problem)
        self.problems_dock.open_requested.connect(self.open_problem)
        self.problems_dock.explain_requested.connect(self.explain_problem)
        self.problems_dock.validate_requested.connect(self.validate_mod)
        self.problems_dock.status_requested = self.show_status
        self.palette.symbol_activated.connect(self.open_symbol)
        self.palette.code_requested.connect(self.open_symbol_code)
        self.palette.section_activated.connect(self.navigate)
        # Los diálogos de las secciones nuevas pasan por exec_dialog (las pruebas lo sustituyen).
        for widget in (self.validation_page, self.page("localisation:all"), self.page("localisation:pending"),
                       self.problems_dock):
            widget.exec_dialog = lambda dialog: self.exec_dialog(dialog)

    def _wire_session(self) -> None:
        # Solo métodos: la sesión puede venir de fuera y vivir más que la ventana.
        session = self.session
        session.dirtyChanged.connect(self._on_dirty_changed)
        session.undoChanged.connect(self._update_project_actions)
        session.projectOpening.connect(self._on_project_opening)
        session.projectOpened.connect(self._on_project_opened)
        session.projectOpenFailed.connect(self._on_project_failed)
        session.projectClosed.connect(self._on_project_closed)
        session.saved.connect(self._on_saved)
        session.externalChanges.connect(self._on_external_changes)
        session.modCreated.connect(self._on_mod_created)
        session.problemsChanged.connect(self._on_problems_changed)
        session.textsChanged.connect(self._refresh_badges)

    # --- navegación ------------------------------------------------------------------------------

    def hall(self, key: str) -> HallPage:
        for hall in self.halls:
            if hall.spec.key == key:
                return hall
        raise KeyError(key)

    def current_hall_index(self) -> int:
        return self.stack.currentIndex()

    def current_hall(self) -> HallPage:
        return self.halls[self.current_hall_index()]

    def set_current_hall(self, index_or_key: int | str) -> None:
        index = index_or_key if isinstance(index_or_key, int) else self.halls.index(self.hall(index_or_key))
        if not 0 <= index < len(self.halls):
            raise IndexError(f"sala fuera de rango: {index}")
        self.nav.set_current_index(index)

    def sections(self) -> list[QWidget]:
        """Todas las secciones, sala a sala y en el orden del índice."""
        return [widget for hall in self.halls for widget in hall.widgets]

    def _locate(self, key: str) -> tuple[HallPage, int]:
        if key in PAGE_SECTIONS:
            hall_key, section = PAGE_SECTIONS[key]
            hall = self.hall(hall_key)
            return hall, hall.section_index(section)
        if ":" in key:
            hall_key, section = key.split(":", 1)
            hall = self.hall(hall_key)
            return hall, hall.section_index(section)
        for hall in self.halls:
            if hall.spec.key == key:
                return hall, max(hall.current_section_index(), 0)
        for hall in self.halls:
            for index, widget in enumerate(hall.widgets):
                if isinstance(widget, BasePage) and widget.key == key:
                    return hall, index
        raise KeyError(key)

    def page(self, key: str) -> QWidget:
        """La sección de ``key``: «project» (Archivos), «localisation» (Archivos CSV), la clave de su página
        («home», «descriptor», «pending», «map.world»...) o «sala:sección»."""
        hall, index = self._locate(key)
        return hall.widgets[index]

    def show_page(self, key: str) -> QWidget:
        """Pone a la vista la sala y la sección de ``key`` (como ``page``) y la devuelve."""
        hall, index = self._locate(key)
        self.set_current_hall(self.halls.index(hall))
        hall.set_current_section(index)
        return hall.widgets[index]

    def navigate(self, target: str) -> None:
        try:
            self.show_page(target)
        except KeyError:
            pass

    def current_page(self) -> QWidget | None:
        return self.current_hall().current_widget() if self.halls else None

    def current_page_key(self) -> str:
        """Clave de la sección a la vista: «project», «localisation» o «sala:sección»."""
        hall = self.current_hall()
        section = hall.current_section()
        key = f"{hall.spec.key}:{section.key}" if section is not None else hall.spec.key
        for page_key, (hall_key, section_key) in PAGE_SECTIONS.items():
            if key == f"{hall_key}:{section_key}":
                return page_key
        return key

    def current_page_index(self) -> int:
        """Compatibilidad: índice en ``PAGE_KEYS`` de la sección a la vista, o -1 si es otra."""
        key = self.current_page_key()
        return PAGE_KEYS.index(key) if key in PAGE_KEYS else -1

    def set_current_page(self, index: int) -> None:
        """Compatibilidad: muestra la página ``PAGE_KEYS[index]``."""
        if not 0 <= index < len(PAGE_KEYS):
            raise IndexError(f"página fuera de rango: {index}")
        self.show_page(PAGE_KEYS[index])

    def hall_actions(self) -> list[QAction]:
        return list(self._hall_actions)

    page_actions = hall_actions

    def open_in_localisation(self, path: str | os.PathLike, line: int | None = None) -> None:
        """Cambia a «Archivos CSV» y abre en ella un CSV (su mensaje de carga queda a la vista)."""
        self.show_page("localisation")
        self.page("localisation").open_file(path, line=line)

    def show_status(self, key: str, fmt: dict | None = None, **values) -> None:
        """Muestra un mensaje del catálogo; se re-traduce si cambia el idioma.

        El formato llega en ``fmt`` (como lo reemiten las secciones) o como argumentos con nombre; los valores
        invocables se evalúan en cada traducción.
        """
        self._status = (key, {**(fmt or {}), **values})
        self._render_status()

    def is_busy(self) -> bool:
        """True mientras alguna sección o la sesión trabajan en segundo plano (las capturas esperan): también el
        índice, la lectura de los textos, la validación, el explicador y los contadores pendientes."""
        return (self.session.is_busy() or self.session.is_working() or self._badge_timer.isActive()
                or any(hall.is_busy() for hall in self.halls))

    # --- proyecto --------------------------------------------------------------------------------

    def select_mod(self, path: Path) -> None:
        """Inicio eligió un mod: pasa a ser la carpeta del mod de «Archivos» (y se abre)."""
        self.page("project").set_mod_path(path)

    def _on_paths_changed(self, *args) -> None:
        self.page("home").set_game_path(self.page("project").game_path())
        self.page("home").set_mod_path(self.page("project").mod_path())
        if not self._closed:
            self._open_timer.start()

    def _wanted_project(self) -> tuple[Path | None, Path] | None:
        project = self.page("project")
        game, mod = project.game_path(), project.mod_path()
        if mod is None or evaluate_mod(inspect_folder(mod), game)[0] == "error":
            return None
        return game, mod

    @staticmethod
    def _same_target(a, b) -> bool:
        if a is None or b is None:
            return a is b
        same_game = (a[0] is None and b[0] is None) or same_folder(a[0], b[0])
        return same_game and same_folder(a[1], b[1])

    def _open_current_mod(self) -> None:
        if self._closed:
            return
        wanted = self._wanted_project()
        current = self.session.target
        if self._same_target(wanted, current):
            return
        self.commit_edits()
        discard = False
        if self.session.dirty_count():
            choice = self.ask_unsaved()
            if choice == UNSAVED_CANCEL or (choice == UNSAVED_SAVE and not self.save_project()):
                self._restore_paths(current)
                return
            discard = choice == UNSAVED_DISCARD
        # «Descartar» no deja autoguardado: al volver a este mod no se ofrecería recuperar lo que se tiró.
        self.session.close_project(discard=discard)
        if wanted is not None:
            self.session.open_project(*wanted)

    def _restore_paths(self, target) -> None:
        if target is None:
            return
        project = self.page("project")
        game, mod = target
        if not same_folder(project.game_path(), game) and game is not None:
            project.set_game_path(game)
        if not same_folder(project.mod_path(), mod):
            project.set_mod_path(mod)

    def commit_edits(self) -> None:
        """Lleva al documento lo que haya a medio teclear: los campos del descriptor confirman al perder el foco,
        y Ctrl+S o cerrar la ventana no lo quitan."""
        if self.session.project is not None:
            self.descriptor_page.commit_pending()

    def save_project(self) -> bool:
        """Guarda (Ctrl+S). Revisión previa solo con copias del juego base o papelera (D13); si el guardado
        encuentra conflictos o errores, los muestra sin tocar el disco y ofrece resolver los conflictos."""
        session = self.session
        self.commit_edits()
        if session.project is None:
            self.show_status("status.no_project")
            return False
        if session.is_read_only():
            self.show_status("status.read_only")
            return False
        for _ in range(3):
            try:
                changeset = session.changeset()
            except (UnencodableTextError, SourceMismatchError) as exc:
                self.show_error(tr("status.save_failed_title"), tr("status.save_render_error", error=str(exc)))
                return False
            if not changeset.writes:
                self.show_status("status.nothing_to_save")
                return True
            if needs_review(changeset) and self.exec_dialog(SaveReviewDialog(changeset, (), self)) \
                    != QDialog.DialogCode.Accepted:
                self.show_status("status.save_cancelled")
                return False
            try:
                # Síncrono (el diario y el Workspace son de este hilo): con muchas escrituras dura segundos.
                count = len(changeset.writes)
                self.show_status("status.saving_one" if count == 1 else "status.saving", count=count)
                with busy(self):
                    report = session.save()
            except OSError as exc:
                self.show_error(tr("status.save_failed_title"), tr("status.save_failed", error=str(exc)))
                return False
            if report.ok:
                return True
            conflicts: list = []
            dialog = SaveReviewDialog(changeset, report.problems, self)
            dialog.resolve_requested.connect(conflicts.extend)
            self.exec_dialog(dialog)
            if not conflicts or not self.resolve_conflicts([p.rel for p in conflicts]):
                self.show_status("status.save_blocked", count=len(report.problems))
                return False
        return False

    def resolve_conflicts(self, rels: list, deleted=()) -> bool:
        """Un ``ConflictDialog`` por archivo; True si todos se resolvieron (conservar o recargar).

        ``deleted``: los de ``rels`` que se borraron fuera (el diálogo lo dice y no ofrece recargar ni comparar).
        """
        project = self.session.project
        deleted = {str(rel) for rel in deleted}
        for rel in rels:
            handle = project.ws.peek(rel) if project is not None else None
            name = str(rel) if handle is None else write_label_for(handle, project)
            dialog = ConflictDialog(name, lambda r=rel: self.session.external_diff(r),
                                    dirty=handle is None or handle.dirty, deleted=str(rel) in deleted,
                                    parent=self)
            self.exec_dialog(dialog)
            if dialog.choice == KEEP:
                self.session.accept_external(rel)
            elif dialog.choice == RELOAD:
                self.session.reload(rel)
            else:
                return False
        return True

    def undo(self) -> None:
        step = self.session.undo()
        if step is not None:
            self.show_status("status.undone", step=lambda s=step: tr(s.label, **dict(s.fmt)))

    def redo(self) -> None:
        step = self.session.redo()
        if step is not None:
            self.show_status("status.redone", step=lambda s=step: tr(s.label, **dict(s.fmt)))

    def validate_mod(self) -> bool:
        """F7 y «Validar mod»: Proyecto › Validación con el validador del núcleo, en segundo plano."""
        page = self.show_page("project:validation")
        return page.validate()

    # --- buscador, problemas y navegación a un archivo ------------------------------------------

    def _palette_sections(self) -> list[tuple[str, str]]:
        return [(f"{hall.spec.key}:{section.key}", tr("shell.location", hall=tr(hall.spec.plate_key),
                                                      section=tr(section.title_key)))
                for hall in self.halls for section in hall.sections]

    def open_palette(self, text: str = "") -> None:
        """Ctrl+K: el buscador universal sobre la ventana."""
        self.palette.open(text)

    def open_location(self, rel, line: int | None = None, column: int | None = None, layer=None, *,
                      tab: str | None = None) -> bool:
        """Abre ``rel`` en Archivos en ``line`` (un CSV de localisation/, en «Archivos CSV»; otro CSV, en su ficha
        con esa línea a la vista); False si lo que se ve solo está en memoria (un documento nuevo, o con cambios
        sin guardar: el archivo del disco tiene otras líneas) o no existe. ``tab``: la pestaña del visor de
        scripts («source» para el código)."""
        if self._refuse_in_memory(rel, layer):
            return False
        path = self.session.location_path(rel, layer)
        if path is None:
            self.show_status("status.location_in_memory", name=str(rel))
            return False
        self.show_page("project")
        if not self.page("project").open_file(path, line=line, column=column, tab=tab):
            self.show_status("status.file_missing", name=str(rel))
            return False
        return True

    def _refuse_in_memory(self, rel, layer=None) -> bool:
        """True (y lo dice) si lo que se vería de ``rel`` solo está en memoria."""
        from .session import IN_MEMORY_MODIFIED

        state = self.session.in_memory(rel, layer)
        if state is None:
            return False
        self.show_status("status.location_unsaved" if state == IN_MEMORY_MODIFIED else "status.location_in_memory",
                         name=str(rel))
        return True

    def open_problem(self, problem) -> bool:
        """Doble clic en un problema: su archivo en su línea."""
        if problem is None or problem.rel is None:
            return False
        return self.open_location(problem.rel, problem.line, problem.column)

    def explain_problem(self, problem) -> bool:
        """[¿Por qué?] del panel de problemas: Proyecto › Validación con el explicador abierto."""
        page = self.show_page("project:validation")
        return page.show_explanation(problem)

    def open_symbol(self, symbol) -> bool:
        """Un resultado de Ctrl+K: una clave de localización, en Textos; lo demás, su archivo en su línea."""
        from ..core.index.model import KIND_LOC_KEY

        if symbol.kind == KIND_LOC_KEY:
            page = self.show_page("localisation:all")
            if page.select_key(symbol.name):
                return True
        return self.open_location(symbol.rel, symbol.line, layer=symbol.layer)

    def open_symbol_code(self, symbol) -> bool:
        """Mayús+Intro en Ctrl+K: el código del símbolo en su línea. Un script, en la pestaña Código; una clave de
        texto, su CSV en «Archivos CSV» en su fila (Intro la abre en Textos)."""
        from ..core.index.model import KIND_LOC_KEY

        if symbol.kind != KIND_LOC_KEY:
            return self.open_location(symbol.rel, symbol.line, layer=symbol.layer, tab="source")
        if self._refuse_in_memory(symbol.rel, symbol.layer):
            return False
        path = self.session.location_path(symbol.rel, symbol.layer)
        if path is None:
            self.show_status("status.location_in_memory", name=str(symbol.rel))
            return False
        self.open_in_localisation(path, line=symbol.line)
        return True

    def open_new_mod_dialog(self) -> int:
        game = self.page("project").game_path()
        return self.exec_dialog(NewModDialog(self.session, game, self))

    def _on_mod_created(self, descriptor) -> None:
        game = self.page("project").game_path()
        self.page("home").refresh()
        if game is not None and descriptor is not None and descriptor.path:
            self.select_mod(game / descriptor.path)
            self.show_page("descriptor")
            self.show_status("status.mod_created", name=descriptor.name)  # después: cambiar de sección lo pisaría

    # --- interacción modal (las pruebas la sustituyen) -----------------------------------------

    def exec_dialog(self, dialog: QDialog) -> int:
        try:
            return dialog.exec()
        finally:
            dialog.deleteLater()

    def ask_unsaved(self) -> str:
        """«Guardar», «Descartar» o «Cancelar» ante cambios sin guardar."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("shell.unsaved_title"))
        box.setText(tr("shell.unsaved_text", count=self.session.dirty_count()))
        box.setInformativeText(tr("shell.unsaved_info"))
        save = box.addButton(tr("shell.unsaved_save"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(tr("shell.unsaved_discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(tr("shell.unsaved_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        return UNSAVED_SAVE if clicked is save else UNSAVED_DISCARD if clicked is discard else UNSAVED_CANCEL

    def show_error(self, title: str, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Critical, title, text, QMessageBox.StandardButton.Ok, self)
        self.exec_dialog(box)

    # --- señales de la sesión --------------------------------------------------------------------

    def _on_project_opening(self, game, mod) -> None:
        self._project_state = (N_("shell.project_opening"), {"name": Path(mod).name})
        self._render_project()

    def _on_project_opened(self, project) -> None:
        self._project_state = ("", {})
        self._update_project_actions()
        if project.recovered or project.orphan_sessions:
            self._offer_recovery(project)

    def _on_project_failed(self, key: str, fmt) -> None:
        self._project_state = (N_("shell.project_failed"), {"reason": tr(key, **dict(fmt or {}))})
        self._render_project()

    def _on_project_closed(self) -> None:
        self._project_state = ("", {})
        self._update_project_actions()

    def _offer_recovery(self, project) -> None:
        dialog = RecoveryDialog(list(project.orphan_sessions), list(project.recovered), self)
        self.exec_dialog(dialog)
        for session_name, decision in dialog.decisions.items():
            if decision == RESTORE:
                restored = self.session.restore_session(session_name)
                self.show_status("status.recovery_restored", count=len(restored))
            elif decision == DISCARD:
                self.session.discard_recovery(session_name)

    def _on_saved(self, report) -> None:
        if report.result is not None:
            written = len(report.result.written) + len(report.result.trashed)
            warnings = [problem for problem in report.problems if not problem.blocking]
            if warnings:
                # El texto del núcleo se evalúa en cada traducción (cambiar de idioma lo re-traduce).
                self.show_status("status.saved_warning_one" if len(warnings) == 1 else "status.saved_warning",
                                 count=len(warnings), warning=lambda p=warnings[0]: p.message(language()))
            else:
                self.show_status("status.saved_one" if written == 1 else "status.saved", count=written)

    def _on_external_changes(self, changes) -> None:
        if self._resolving:
            return
        self._resolving = True
        try:
            # Workspace.check_external_changes ya releyó los limpios (y quitó los borrados): solo preguntan los sucios,
            # y el diálogo dice si el archivo se borró fuera.
            pending = [change.rel for change in changes if change.dirty]
            deleted = [change.rel for change in changes if change.dirty and change.kind == "deleted"]
            if pending:
                self.resolve_conflicts(pending, deleted)
        finally:
            self._resolving = False

    def _on_application_state(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive and not self._closed and self.session.project is not None:
            self.session.check_external_changes()

    # --- interno ---------------------------------------------------------------------------------

    def _on_dirty_changed(self, count: int) -> None:
        self._update_project_actions()

    def _on_problems_changed(self) -> None:
        self._refresh_badges()
        self._retranslate_problems_button()

    def _refresh_badges(self) -> None:
        """Pide los contadores del índice lateral para la próxima vuelta del bucle (una edición avisa con
        ``textsChanged``, ``dirtyChanged`` y ``undoChanged``: con VSM, contar los textos pendientes tres veces
        costaba 0,35–0,65 s)."""
        self._badge_timer.start()

    def _refresh_badges_now(self) -> None:
        """Los de la sala a la vista ya; los de las demás, al mostrarse (``_on_hall_changed``)."""
        self._badge_timer.stop()
        current = self.current_hall_index()
        for index, hall in enumerate(self.halls):
            if index == current:
                hall.refresh_badges()
                self._stale_badges.discard(index)
            else:
                self._stale_badges.add(index)

    def _retranslate_problems_button(self) -> None:
        from ..core.clausewitz import Severity

        report = self.session.report
        errors = 0 if report is None else report.count(Severity.ERROR)
        warnings = 0 if report is None else report.count(Severity.WARNING)
        self.problems_button.setText(tr("shell.problems"))
        self.problems_button.setToolTip(tr("shell.problems_tooltip", errors=errors, warnings=warnings)
                                        if report is not None else tr("shell.problems_tooltip_none"))

    def _update_project_actions(self) -> None:
        session = self.session
        has_project = session.project is not None
        count = session.dirty_count()
        writable = has_project and not session.is_read_only()
        self.save_button.setEnabled(writable and count > 0)
        self.save_action.setEnabled(has_project)
        self.undo_button.setEnabled(session.can_undo())
        self.redo_button.setEnabled(session.can_redo())
        self.undo_action.setEnabled(has_project)
        self.redo_action.setEnabled(has_project)
        self._refresh_badges()
        self._retranslate_project_actions()
        self._render_project()
        self._update_window_title()

    def _retranslate_project_actions(self) -> None:
        count = self.session.dirty_count()
        self.save_button.setText(tr("shell.save_count", count=count) if count else tr("shell.save"))
        self.save_button.setToolTip(tr("shell.save_tooltip", shortcut=self._shortcut_text("Ctrl+S")))
        history = self.session.history()
        if history:
            label, fmt = history[0]
            self.undo_button.setToolTip(tr("shell.undo_step", step=tr(label, **fmt),
                                           shortcut=self._shortcut_text("Ctrl+Z")))
        else:
            self.undo_button.setToolTip(tr("shell.undo_tooltip", shortcut=self._shortcut_text("Ctrl+Z")))
        self.redo_button.setToolTip(tr("shell.redo_tooltip", shortcut=self._shortcut_text("Ctrl+Y")))
        self.history_button.setToolTip(tr("shell.history_tooltip"))
        self.search_button.setText(tr("shell.search", shortcut=self._shortcut_text("Ctrl+K")))
        self.search_button.setToolTip(tr("shell.search_tooltip", shortcut=self._shortcut_text("Ctrl+K")))
        self.search_button.setAccessibleName(self.search_button.text())
        self.palette_action.setText(tr("palette.title"))
        self._retranslate_problems_button()
        self.save_action.setText(tr("shell.save"))
        self.undo_action.setText(tr("shell.undo"))
        self.redo_action.setText(tr("shell.redo"))
        self.validate_action.setText(tr("project.validate"))
        self._fit_banner()  # «Guardar (n)», el idioma y el lema cambian de ancho

    def _render_project(self) -> None:
        key, fmt = self._project_state
        project = self.session.project
        if key:
            self.project_label.setText(tr(key, **fmt))
        elif project is None:
            self.project_label.setText("")
        else:
            name = project.descriptor.name if project.descriptor is not None and project.descriptor.name \
                else project.mod_root.name
            parts = [tr("shell.project_name", name=name)]
            if project.read_only:
                parts.append(tr("shell.project_read_only"))
            dirty = project.ws.dirty()
            if dirty:
                parts.append(tr("shell.project_dirty_one" if len(dirty) == 1 else "shell.project_dirty",
                                count=len(dirty)))
                copies = sum(1 for handle in dirty if handle.copies_from_game)
                if copies:
                    parts.append(tr("shell.project_copies_one" if copies == 1 else "shell.project_copies",
                                    count=copies))
            self.project_label.setText(" · ".join(parts))

    @staticmethod
    def _shortcut_text(sequence: str) -> str:
        return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)

    def _render_status(self) -> None:
        key, fmt = self._status
        values = {name: value() if callable(value) else value for name, value in fmt.items()}
        self.status_label.setText(tr(key, **values))

    def _location_text(self, hall: HallPage) -> str:
        return tr("shell.location", hall=tr(hall.spec.plate_key), section=hall.section_title())

    def _on_hall_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        hall = self.halls[index]
        if index in self._stale_badges:
            self._stale_badges.discard(index)
            hall.refresh_badges()
        app_settings().setValue(SETTINGS_LAST_HALL, hall.spec.key)
        self._update_window_title()
        self.show_status("status.page", {"name": lambda h=hall: self._location_text(h)})

    def _on_section_changed(self, hall_index: int, section: int) -> None:
        hall = self.halls[hall_index]
        spec = hall.sections[section]
        app_settings().setValue(SETTINGS_LAST_SECTION.format(hall=hall.spec.key), spec.key)
        if hall_index == self.current_hall_index():
            self._update_window_title()
            self.show_status("status.page", {"name": lambda h=hall: self._location_text(h)})

    def _on_history_toggled(self, checked: bool) -> None:
        self.history_dock.setVisible(checked)

    def _on_problems_toggled(self, checked: bool) -> None:
        self.problems_dock.setVisible(checked)

    def _on_language_selected(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if code and code != language():
            set_language(code)

    def _on_language_changed(self, code: str) -> None:
        self._sync_language_combo()
        self.retranslate()

    def _sync_language_combo(self) -> None:
        index = self.language_combo.findData(language())
        if index >= 0 and index != self.language_combo.currentIndex():
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(index)
            self.language_combo.blockSignals(False)

    def _update_window_title(self) -> None:
        if not self.halls or not 0 <= self.current_hall_index() < len(self.halls):
            self.setWindowTitle(tr("app.name"))
            return
        title = tr("app.window_title", page=self._location_text(self.current_hall()))
        self.setWindowTitle(tr("shell.title_dirty", title=title) if self.session.dirty_count() else title)

    def retranslate(self) -> None:
        self.banner.set_texts(tr("app.name"), tr("app.tagline"))
        self.banner.emblem.setToolTip(tr("app.emblem_tooltip"))
        self.language_label.setText(tr("header.language"))
        self.language_combo.setToolTip(tr("header.language_tooltip"))
        for index, (hall, button) in enumerate(zip(self.halls, self.nav.buttons)):
            plate = tr(hall.spec.plate_key)
            shortcut = self._shortcut_text(f"Ctrl+{index + 1}")
            button.setText(plate)
            button.setToolTip(tr("nav.tooltip", name=tr(hall.spec.title_key), shortcut=shortcut))
            button.setAccessibleDescription(tr(hall.spec.subtitle_key))
            button.updateGeometry()
            self._hall_actions[index].setText(plate)
        self.version_label.setText(tr("status.version", version=__version__))
        self.history_button.setText(tr("shell.history"))
        self._retranslate_project_actions()
        self._render_project()
        self._update_window_title()
        self._render_status()

    def _restore_state(self) -> None:
        settings = app_settings()
        geometry = settings.value(SETTINGS_GEOMETRY)
        if not (isinstance(geometry, QByteArray) and self.restoreGeometry(geometry)):
            screen = QGuiApplication.primaryScreen()
            size = DEFAULT_SIZE
            if screen is not None:
                available = screen.availableGeometry().size()
                size = size.boundedTo(QSize(int(available.width() * 0.95), int(available.height() * 0.95)))
            self.resize(size.expandedTo(MINIMUM_SIZE))
        for hall in self.halls:
            section = settings.value(SETTINGS_LAST_SECTION.format(hall=hall.spec.key), "", str)
            if section and any(s.key == section for s in hall.sections):
                hall.set_current_section(section)
        last = settings.value(SETTINGS_LAST_HALL, self.halls[0].spec.key if self.halls else "", str)
        keys = [hall.spec.key for hall in self.halls]
        self.set_current_hall(keys.index(last) if last in keys else 0)
        self.show_status("status.ready")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        palette = getattr(self, "palette", None)
        if palette is not None and palette.isVisible():
            palette.place()
        compact = self.width() < COMPACT_RAIL_WIDTH
        self._body.setContentsMargins(*(COMPACT_BODY_MARGINS if compact else BODY_MARGINS))
        for hall in self.halls:
            hall.set_compact(compact)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "banner", None):
            self._fit_banner()
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        discard = False
        if not self._closed:
            self.commit_edits()
        if not self._closed and self.session.dirty_count():
            choice = self.ask_unsaved()
            if choice == UNSAVED_CANCEL or (choice == UNSAVED_SAVE and not self.save_project()):
                event.ignore()
                return
            discard = choice == UNSAVED_DISCARD
        self._closed = True
        self._open_timer.stop()
        app_settings().setValue(SETTINGS_GEOMETRY, self.saveGeometry())
        for hall in self.halls:
            hall.shutdown()
        # Suelta el bloqueo del proyecto y escribe la recuperación de lo que quede sin guardar (salvo «Descartar»).
        self.session.close_project(discard=discard)
        # Sin esperar: la ventana se cierra en el acto y app.main espera a que las tareas paren.
        cancel_all()
        super().closeEvent(event)


def write_label_for(handle, project) -> str:
    """Nombre de un documento para los diálogos (el del archivo, también para el descriptor)."""
    from ..core.project import PlannedWrite, WriteAction

    target = project.vfs.mod_target(handle.rel) if project is not None else Path(str(handle.rel))
    return write_label(PlannedWrite(handle.rel, target, WriteAction.MODIFY, None, None))
