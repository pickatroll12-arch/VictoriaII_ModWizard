"""Ventana principal: estandarte, selector de idioma, navegación entre módulos y barra de estado."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..i18n import available_languages, language, set_language, tr, translator
from ..settings import app_settings
from . import theme
from .pages import PAGE_CLASSES, PAGE_KEYS, BasePage
from .tasks import cancel_all
from .widgets import HeaderBanner, NavBar, OrnateFrame, TexturedPanel, emblem_pixmap, mark_data

SETTINGS_GEOMETRY = "ui/geometry"
SETTINGS_LAST_PAGE = "ui/last_page"
MINIMUM_SIZE = QSize(1100, 700)
DEFAULT_SIZE = QSize(1440, 900)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(emblem_pixmap(size))
    return icon


class MainWindow(QMainWindow):
    """API: ``pages``, ``current_page_index()``, ``set_current_page(i)``, ``page(key)``."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setMinimumSize(MINIMUM_SIZE)
        self.setWindowIcon(app_icon())
        self._status: tuple[str, dict] = ("status.ready", {})

        central = TexturedPanel("wood", vignette=0.45)
        central.setObjectName("centralPanel")
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.banner = HeaderBanner()
        column.addWidget(self.banner)

        self.language_label = QLabel()
        self.language_label.setObjectName("languageLabel")
        self.language_label.setFont(theme.font("heading", 10.5))
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setMinimumWidth(130)
        for code, name in available_languages():
            self.language_combo.addItem(name, code)
        mark_data(self.language_combo)  # endónimos: no se traducen
        self.language_label.setBuddy(self.language_combo)
        language_box = QWidget()
        language_box.setProperty("surface", "velvet")
        language_row = QHBoxLayout(language_box)
        language_row.setContentsMargins(0, 0, 0, 0)
        language_row.setSpacing(8)
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_combo)
        self.banner.add_trailing_widget(language_box)

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(2)
        self.nav = NavBar()
        body.addWidget(self.nav)
        self.frame = OrnateFrame()
        self.frame.setObjectName("pageFrame")
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        frame_layout.addWidget(self.stack)
        body.addWidget(self.frame, 1)
        column.addLayout(body, 1)
        self.setCentralWidget(central)

        self.pages: list[BasePage] = []
        self._page_actions: list[QAction] = []
        for index, cls in enumerate(PAGE_CLASSES):
            page = cls()
            self.pages.append(page)
            self.stack.addWidget(page)
            self.nav.add_button(page.icon_name)
            page.status_requested.connect(self.show_status)
            action = QAction(self)
            action.setObjectName(f"goto_{page.key}")
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda checked=False, i=index: self.set_current_page(i))
            self.addAction(action)
            self._page_actions.append(action)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusMessage")
        self.statusBar().addWidget(self.status_label, 1)
        self.version_label = QLabel()
        self.version_label.setObjectName("statusVersion")
        self.version_label.setProperty("role", "muted")
        self.statusBar().addPermanentWidget(self.version_label)
        self.statusBar().setSizeGripEnabled(True)

        project = self.page("project")
        localisation = self.page("localisation")
        project.mod_path_changed.connect(localisation.set_mod_path)
        project.csv_requested.connect(self.open_in_localisation)
        localisation.set_mod_path(project.mod_path())

        self.nav.currentChanged.connect(self._on_page_changed)
        self.language_combo.currentIndexChanged.connect(self._on_language_selected)
        translator().languageChanged.connect(self._on_language_changed)

        self._sync_language_combo()
        self.retranslate()
        self._restore_state()

    # --- API pública ---------------------------------------------------------------------

    def current_page_index(self) -> int:
        return self.stack.currentIndex()

    def current_page(self) -> BasePage:
        return self.pages[self.current_page_index()]

    def set_current_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            raise IndexError(f"página fuera de rango: {index}")
        self.nav.set_current_index(index)

    def page(self, key: str) -> BasePage:
        try:
            return self.pages[PAGE_KEYS.index(key)]
        except ValueError:
            raise KeyError(key) from None

    def page_actions(self) -> list[QAction]:
        return list(self._page_actions)

    def open_in_localisation(self, path: str | os.PathLike, line: int | None = None) -> None:
        """Cambia a la página de Localización y abre en ella un CSV (su mensaje de carga queda a la vista)."""
        self.set_current_page(PAGE_KEYS.index("localisation"))
        self.page("localisation").open_file(path, line=line)

    def show_status(self, key: str, fmt: dict | None = None) -> None:
        """Muestra un mensaje del catálogo; se re-traduce si cambia el idioma.

        Los valores invocables de ``fmt`` se evalúan en cada traducción.
        """
        self._status = (key, dict(fmt or {}))
        self._render_status()

    # --- interno -------------------------------------------------------------------------

    def _render_status(self) -> None:
        key, fmt = self._status
        values = {name: value() if callable(value) else value for name, value in fmt.items()}
        self.status_label.setText(tr(key, **values))

    def _on_page_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        app_settings().setValue(SETTINGS_LAST_PAGE, PAGE_KEYS[index])
        self._update_window_title()
        page = self.pages[index]
        self.show_status("status.page", {"name": page.title})

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
        index = self.current_page_index()
        if 0 <= index < len(self.pages):
            self.setWindowTitle(tr("app.window_title", page=self.pages[index].title()))
        else:
            self.setWindowTitle(tr("app.name"))

    def retranslate(self) -> None:
        self.banner.set_texts(tr("app.name"), tr("app.tagline"))
        self.banner.emblem.setToolTip(tr("app.emblem_tooltip"))
        self.language_label.setText(tr("header.language"))
        self.language_combo.setToolTip(tr("header.language_tooltip"))
        for index, (page, button) in enumerate(zip(self.pages, self.nav.buttons)):
            title = page.title()
            shortcut = QKeySequence(f"Ctrl+{index + 1}").toString(QKeySequence.SequenceFormat.NativeText)
            button.setText(title)
            button.setToolTip(tr("nav.tooltip", name=title, shortcut=shortcut))
            button.setAccessibleDescription(tr(page.subtitle_key))
            button.updateGeometry()
            self._page_actions[index].setText(title)
        self.version_label.setText(tr("status.version", version=__version__))
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
        last = settings.value(SETTINGS_LAST_PAGE, PAGE_KEYS[0], str)
        self.set_current_page(PAGE_KEYS.index(last) if last in PAGE_KEYS else 0)
        self.show_status("status.ready")

    def closeEvent(self, event: QCloseEvent) -> None:
        app_settings().setValue(SETTINGS_GEOMETRY, self.saveGeometry())
        for page in self.pages:
            page.shutdown()
        # Sin esperar: la ventana se cierra en el acto y app.main espera a que las tareas paren.
        cancel_all()
        super().closeEvent(event)
