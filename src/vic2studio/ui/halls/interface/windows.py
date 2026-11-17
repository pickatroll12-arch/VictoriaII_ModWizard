"""Sección «Ventanas» de la sala Interfaz (wizard §17.2, §17.4). Iteración 8.

Arriba se elige el ``.gui`` y su ventana, la resolución de la pantalla (1024×768, 1280×720 o 1920×1080), la
rejilla y el imán. Debajo, tres columnas: el árbol de elementos (``GuiTree``), el lienzo (``GuiCanvas``) y el
formulario de propiedades del elemento elegido, que genera su esquema (``core/schemas/gui_elements.py``).

Cada gesto es **un** paso de deshacer que cambia una sola línea del ``.gui``: arrastrar (``position``), el asa
(``size``) y «Ocultar» (lo lleva fuera de la pantalla en lugar de borrarlo, porque el ejecutable busca muchos
elementos por su nombre). Editar un ``.gui`` del juego lo copia entero al mod con el mismo nombre al guardar.
La página aloja los 13 esquemas ``gui_*``: un problema de un elemento la abre con ese elemento elegido.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QStackedWidget, QWidget,
)

from ....core.vfs.paths import VPath
from ....i18n import N_, tr
from ...interface import renderer_of, source_of
from ...interface.gui_canvas import GuiCanvas
from ...interface.gui_tree import GuiTree
from ...pages.base import BasePage
from ...session import replace_paths_touch
from ...widgets import make_icon, mark_data

GUI_FOLDER = "interface"
GUI_PATTERN = "*.gui"
ART_FOLDERS = ("interface/", "gfx/")


class WindowsPage(BasePage):
    key = "windows"
    title_key = N_("section.interface.windows")
    subtitle_key = N_("interface.windows.subtitle")
    icon_name = "window"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.files: list[VPath] = []
        self.rel: VPath | None = None
        self.document = None
        self.window_path: str | None = None
        self.element_path: str | None = None
        self.forms: dict[str, object] = {}
        self._stale = False
        self._pending: list[tuple] = []
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        session.replacePathsChanged.connect(self._on_replace_paths)
        self.reload()

    # --- construcción ------------------------------------------------------------------------------

    def build(self) -> None:
        from ....core.gui.render import SCREENS

        bar = QHBoxLayout()
        self.file_label = QLabel()
        self.file_combo = mark_data(QComboBox())
        self.file_combo.setObjectName("guiFile")
        self.file_combo.setMinimumWidth(220)
        self.file_combo.currentIndexChanged.connect(self._on_file)
        self.window_label = QLabel()
        self.window_combo = mark_data(QComboBox())
        self.window_combo.setObjectName("guiWindow")
        self.window_combo.setMinimumWidth(200)
        self.window_combo.currentIndexChanged.connect(self._on_window)
        self.screen_combo = mark_data(QComboBox())
        self.screen_combo.setObjectName("guiScreen")
        for width, height in SCREENS:
            self.screen_combo.addItem(f"{width}×{height}", f"{width}x{height}")
        self.screen_combo.currentIndexChanged.connect(self._on_screen)
        self.grid_check = QCheckBox()
        self.grid_check.setObjectName("guiGrid")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(lambda on: self.canvas.set_grid(on))
        self.zoom_check = QCheckBox()
        self.zoom_check.setObjectName("guiZoom")
        self.zoom_check.setChecked(True)
        self.zoom_check.toggled.connect(lambda on: self.canvas.set_zoom_to_window(on))
        self.snap_check = QCheckBox()
        self.snap_check.setObjectName("guiSnap")
        self.snap_check.toggled.connect(lambda on: self.canvas.set_snap(on))
        self.hide_button = QPushButton()
        self.hide_button.setObjectName("guiHide")
        self.hide_button.setIcon(make_icon("minus", "gold_light"))
        self.hide_button.clicked.connect(self.hide_selected)
        for widget in (self.file_label, self.file_combo, self.window_label, self.window_combo, self.screen_combo,
                       self.zoom_check, self.grid_check, self.snap_check):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(self.hide_button)
        self.body.addLayout(bar)
        self.info_label = QLabel()
        self.info_label.setObjectName("guiInfo")
        self.info_label.setWordWrap(True)
        self.body.addWidget(self.info_label)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = GuiTree()
        self.tree.selected.connect(self.select_element)
        self.canvas = GuiCanvas()
        self.canvas.zoom_to_window = True
        self.canvas.selected.connect(self.select_element)
        self.canvas.moved.connect(self._queue_move)
        self.canvas.resized.connect(self._queue_resize)
        self.properties = QStackedWidget()
        self.properties.setObjectName("guiProperties")
        self.empty_properties = QLabel()
        self.empty_properties.setObjectName("guiPropertiesEmpty")
        self.empty_properties.setWordWrap(True)
        self.empty_properties.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.properties.addWidget(self.empty_properties)
        split.addWidget(self.tree)
        split.addWidget(self.canvas)
        split.addWidget(self.properties)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 6)
        split.setStretchFactor(2, 3)
        split.setSizes([290, 720, 340])
        self.body.addWidget(split, 1)
        self.limits_label = QLabel()
        self.limits_label.setObjectName("guiLimits")
        self.limits_label.setWordWrap(True)
        self.limits_label.setProperty("role", "caption")
        self.body.addWidget(self.limits_label)

    def retranslate(self) -> None:
        super().retranslate()
        self.file_label.setText(tr(N_("interface.windows.file")))
        self.window_label.setText(tr(N_("interface.windows.window")))
        self.grid_check.setText(tr(N_("interface.windows.grid")))
        self.snap_check.setText(tr(N_("interface.windows.snap")))
        self.zoom_check.setText(tr(N_("interface.windows.zoom")))
        self.zoom_check.setToolTip(tr(N_("interface.windows.zoom_tip")))
        self.hide_button.setText(tr(N_("interface.windows.hide")))
        self.hide_button.setToolTip(tr(N_("interface.windows.hide_tip")))
        self.tree.set_headers(tr(N_("interface.windows.col.name")), tr(N_("interface.windows.col.type")))
        self.empty_properties.setText(tr(N_("interface.windows.no_element")))
        self.limits_label.setText(tr(N_("interface.windows.limits")))
        self._show_info()

    # --- datos -------------------------------------------------------------------------------------

    def _on_documents(self, rels) -> None:
        if rels is None or any(str(rel).lower().startswith(ART_FOLDERS) for rel in rels):
            self.reload()

    def _on_replace_paths(self, folders) -> None:
        """Otras ``replace_path``: los ``.gui`` (y el arte) del juego dejan de contar, o vuelven."""
        if replace_paths_touch(folders, *ART_FOLDERS):
            self.reload()

    def reload(self, *args) -> None:
        """Vuelve a leer la lista de ``.gui`` y la ventana elegida. Fuera de la vista solo se apunta."""
        if self.session.project is not None and not self.isVisible():
            self._stale = True
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

    def _reload_now(self) -> None:
        source = source_of(self.session)
        self.files = source.rels(GUI_FOLDER, GUI_PATTERN) if source is not None else []
        wanted = self.rel
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for rel in self.files:
            self.file_combo.addItem(rel.name, str(rel))
        index = next((i for i, rel in enumerate(self.files) if wanted is not None and rel.key == wanted.key), 0)
        if self.files:
            self.file_combo.setCurrentIndex(index)
        self.file_combo.blockSignals(False)
        self._load_file(self.files[index] if self.files else None)

    def _load_file(self, rel: VPath | None) -> None:
        from ....core.gui import GuiDocument, element_path

        source = source_of(self.session)
        raw = source.document(rel) if source is not None and rel is not None else None
        if rel is None or raw is None:
            self.rel, self.document = None, None
        else:
            if self.rel is None or self.rel.key != rel.key:
                self.window_path = None
                self.element_path = None
            self.rel, self.document = rel, GuiDocument(raw)
        tops = self.document.windows() if self.document is not None else []
        paths = [element_path(top) for top in tops]
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        for top, path in zip(tops, paths):
            self.window_combo.addItem(f"{top.name or top.type} · {top.entry.key.text}", path)
        if self.window_path not in paths:
            self.window_path = paths[0] if paths else None
        if self.window_path is not None:
            self.window_combo.setCurrentIndex(paths.index(self.window_path))
        self.window_combo.blockSignals(False)
        self._show_window()

    def _show_window(self) -> None:
        window = self.current_window()
        if window is None:
            self.canvas.scene().clear()
            self.canvas.items_by_path = {}
            self.tree.set_window([])
            self.element_path = None
            self._bind_properties(None)
            self._show_info()
            return
        renderer = renderer_of(self.session)
        self.canvas.show_window(renderer, self.document, window, self.screen())
        self.canvas.fit()
        self.tree.set_window([window])
        if self.element_path is not None and self.element_path not in self.canvas.items_by_path:
            self.element_path = None
        self._select(self.element_path)
        self._show_info()

    def _show_info(self) -> None:
        if not hasattr(self, "info_label"):
            return
        if self.session.project is None:
            self.info_label.setText(tr(N_("interface.no_project")))
            return
        if self.rel is None:
            self.info_label.setText(tr(N_("interface.windows.no_files")))
            return
        ws = self.session.project.ws
        handle = ws.peek(self.rel)
        entry = ws.vfs.resolve(self.rel)
        if handle is not None and handle.copies_from_game:
            key = N_("interface.windows.copied")
        elif (handle is not None and handle.is_new) or (entry is not None and entry.layer.kind.name == "MOD"):
            key = N_("interface.windows.from_mod")
        else:
            key = N_("interface.windows.from_game")
        count = sum(1 for _ in self.current_window().walk()) if self.current_window() is not None else 0
        self.info_label.setText(tr(key, file=str(self.rel), count=count))

    def current_window(self):
        if self.document is None or not self.window_path:
            return None
        try:
            return self.document.find(self.window_path)
        except KeyError:
            return None

    def current_element(self):
        if self.document is None or not self.element_path:
            return None
        try:
            return self.document.find(self.element_path)
        except KeyError:
            return None

    def screen(self) -> tuple[int, int]:
        width, _, height = str(self.screen_combo.currentData() or "1024x768").partition("x")
        return int(width), int(height)

    # --- elección ----------------------------------------------------------------------------------

    def _on_file(self, index: int) -> None:
        rel = self.file_combo.itemData(index)
        self._load_file(VPath.of(rel) if rel else None)

    def _on_window(self, index: int) -> None:
        self.window_path = self.window_combo.itemData(index)
        self.element_path = None
        self._show_window()

    def _on_screen(self, _index: int) -> None:
        self._show_window()

    def select_file(self, rel) -> bool:
        self._ensure_loaded()
        rel = VPath.of(rel)
        for index, candidate in enumerate(self.files):
            if candidate.key == rel.key:
                self.file_combo.setCurrentIndex(index)
                if self.rel is None or self.rel.key != candidate.key:
                    self._load_file(candidate)
                return True
        return False

    def select_window(self, path: str) -> bool:
        self._ensure_loaded()
        index = self.window_combo.findData(path)
        if index < 0:
            return False
        self.window_combo.setCurrentIndex(index)
        if self.window_path != path:
            self._on_window(index)
        return True

    def select_screen(self, screen: tuple[int, int]) -> None:
        index = self.screen_combo.findData(f"{int(screen[0])}x{int(screen[1])}")
        if index >= 0:
            self.screen_combo.setCurrentIndex(index)

    def select_element(self, path: str | None) -> None:
        self._select(path)

    def _select(self, path: str | None) -> None:
        self.element_path = path
        self.canvas.select_path(path)
        self.tree.select_path(path)
        self._bind_properties(self.current_element())
        self.hide_button.setEnabled(path is not None and self.session.project is not None
                                    and not self.session.is_read_only() and path != self.window_path)

    def _bind_properties(self, element) -> None:
        from ....core.schema import RecordRef, registry
        from ....core.schemas.gui_elements import KIND_OF_TYPE
        from ...forms.form import EntityForm

        kind = KIND_OF_TYPE.get(element.type) if element is not None else None
        if kind is None:
            self.properties.setCurrentWidget(self.empty_properties)
            return
        form = self.forms.get(kind)
        if form is None:
            form = EntityForm(self.session, registry.get(kind))
            form.setObjectName(f"guiForm_{kind}")
            form.status_requested.connect(self.status_requested)
            self.forms[kind] = form
            self.properties.addWidget(form)
        form.bind(RecordRef(kind, self.element_path, self.rel))
        self.properties.setCurrentWidget(form)

    def current_form(self):
        widget = self.properties.currentWidget()
        return None if widget is self.empty_properties else widget

    # --- ediciones ---------------------------------------------------------------------------------

    def _queue_move(self, path: str, dx: int, dy: int) -> None:
        # El lienzo emite desde el ``mouseReleaseEvent`` del elemento: rehacer la escena ahí lo borraría bajo
        # el ratón, así que la edición espera a la siguiente vuelta del bucle de eventos.
        self._pending.append(("move", path, dx, dy))
        QTimer.singleShot(0, self._flush)

    def _queue_resize(self, path: str, width: int, height: int) -> None:
        self._pending.append(("resize", path, width, height))
        QTimer.singleShot(0, self._flush)

    def _flush(self) -> None:
        pending, self._pending = self._pending, []
        for action, path, a, b in pending:
            if action == "move":
                self.move_element(path, a, b)
            else:
                self.resize_element(path, a, b)

    def _apply(self, label: str, path: str, change) -> bool:
        """Un paso de deshacer sobre el elemento ``path`` del ``.gui`` elegido. ``change(documento, elemento)``."""
        from ....core.gui import GuiDocument

        if self.session.project is None or self.rel is None or self.session.is_read_only():
            return False
        source = source_of(self.session)
        rel = source.find(self.rel) or self.rel
        try:
            with self.session.edit(label, element=path):
                ws = self.session.project.ws
                handle = ws.open(rel)
                ws.touch(handle)
                document = GuiDocument(source.document(rel))
                change(document, document.find(path))
        except (KeyError, ValueError, OSError, PermissionError) as exc:
            self.request_status(N_("interface.windows.edit_failed"), element=path, error=str(exc))
            return False
        self.element_path = path
        if self._stale or self.document is None:
            self._reload_now()
        self._select(path)
        return True

    def move_element(self, path: str, dx: int, dy: int) -> bool:
        """Desplaza el elemento ``(dx, dy)`` píxeles: solo cambia su línea ``position``."""
        if not dx and not dy:
            return False

        def change(document, element) -> None:
            x, y = element.position
            document.set_position(element, x + int(dx), y + int(dy))

        done = self._apply("undo.gui_move", path, change)
        if done:
            self.request_status(N_("interface.windows.moved"), element=path, dx=dx, dy=dy)
        return done

    def resize_element(self, path: str, width: int, height: int) -> bool:
        """Cambia el tamaño del elemento: solo su línea ``size``."""
        done = self._apply("undo.gui_resize", path,
                           lambda document, element: document.set_size(element, int(width), int(height)))
        if done:
            self.request_status(N_("interface.windows.resized"), element=path, w=width, h=height)
        return done

    def hide_selected(self) -> bool:
        """«Ocultar»: el elemento elegido sale de la pantalla (no se borra: el juego lo busca por su nombre)."""
        path = self.element_path
        if not path or path == self.window_path:
            return False
        done = self._apply("undo.gui_hide", path, lambda document, element: document.hide(element))
        if done:
            self.request_status(N_("interface.windows.hidden"), element=path)
        return done

    # --- navegación --------------------------------------------------------------------------------

    def focus_field(self, ref, field=()) -> bool:
        """Abre el elemento de ``ref`` (``kind`` ``gui_*``, ``ident`` su ruta) en su archivo y su ventana."""
        from ....core.gui import element_path

        self._ensure_loaded()
        rel = getattr(ref, "rel", None)
        ident = str(getattr(ref, "ident", ref))
        if rel is not None and not self.select_file(rel):
            return False
        if self.document is None:
            return False
        try:
            element = self.document.find(ident)
        except KeyError:
            return False
        top = element
        while top.parent is not None:
            top = top.parent
        if not self.select_window(element_path(top)):
            return False
        self.select_element(ident)
        form = self.current_form()
        if form is not None and field:
            form.focus_field(tuple(field))
        return True

    def element_at_line(self, line: int) -> str | None:
        """La ruta del elemento del ``.gui`` elegido en el que cae la línea ``line`` (None si va antes de todos)."""
        from ....core.gui import element_path

        if self.document is None:
            return None
        # Los elementos van en orden de archivo: el último que empieza antes de la línea es el más interior.
        candidates = [element for element in self.document.elements() if element.line <= line]
        best = candidates[-1] if candidates else None
        return element_path(best) if best is not None else None

    def open_location(self, rel, line: int) -> bool:
        """Abre el ``.gui`` ``rel`` con el elemento de la línea ``line`` elegido (los usos de un sprite)."""
        if not self.select_file(rel):
            return False
        path = self.element_at_line(int(line))
        if path is None:
            return True
        from ....core.schema import RecordRef
        from ....core.schemas.gui_elements import KIND_OF_TYPE

        element = self.document.find(path)
        return self.focus_field(RecordRef(KIND_OF_TYPE.get(element.type, "gui_window"), path, self.rel))
