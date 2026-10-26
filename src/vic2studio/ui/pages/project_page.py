"""Proyecto y Archivos: rutas del juego base y del mod, explorador, vista previa y validación.

Al seleccionar un archivo del explorador la vista previa elige visor:

* scripts Clausewitz (``.txt``, ``.mod``, ``.gfx``, ``.gui``, ``.sfx``, ``.asset``):
  ``ClausewitzViewer`` (estructura, código fuente, diagnósticos y JSON);
* imágenes (``.tga``, ``.dds``, ``.bmp``, ``.png``, ``.jpg``): ``ImageViewer``;
* el resto (y las carpetas): la ficha de metadatos ``FilePreview``.

Los ``.csv`` se abren en la página de Localización: al hacer clic en ellos (o
con Intro / doble clic) se emite ``csv_requested(Path, línea | None)``. Con el
teclado, moverse por encima de un CSV solo muestra su ficha, para que recorrer
``localisation/`` con las flechas no cambie de página a cada paso.

«Validar mod» analiza en segundo plano todos los archivos Clausewitz y CSV del
mod (``core.modcheck``) y lista sus diagnósticos en la pestaña «Validación».

Otros puntos de extensión: ``file_activated(Path)``, ``set_preview_widget(widget)``
(``None`` restaura la vista por defecto), ``game_path_changed`` / ``mod_path_changed``.

La inspección de carpetas (``inspect_folder``, ``evaluate_game``, ``evaluate_mod``)
no depende de Qt para poder reutilizarla en el futuro sistema de archivos virtual.
"""

from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QDateTime,
    QDir,
    QIdentityProxyModel,
    QLocale,
    QModelIndex,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PIL import Image
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFileSystemModel,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...core.encoding import decode_bytes
from ...core.modfile import INSIDE, ModDescriptor, find_descriptor, read_descriptor
from ...i18n import N_, tr, translator
from ...settings import app_settings
from .. import theme
from ..viewers import CLAUSEWITZ_SUFFIXES, ClausewitzViewer, ImageViewer, ValidationPanel
from ..viewers.image_viewer import IMAGE_SUFFIXES as IMAGE_VIEWER_SUFFIXES
from ..widgets import (
    Divider,
    EmptyState,
    FolderChip,
    IconWidget,
    StatusBadge,
    make_icon,
    mark_data,
    rich,
    show_in_stack,
)
from ..widgets.cards import LEVEL_COLORS, LEVEL_ICONS
from ..widgets.flow import FlowLayout
from .base import BasePage

__all__ = [
    "FileFacts", "FilePreview", "FolderReport", "ModDescriptor", "PathField", "ProjectPage", "evaluate_game",
    "evaluate_mod", "find_descriptor", "gather_facts", "inspect_folder", "name_filters", "preview_kind",
    "read_descriptor", "same_folder",
]

EXPECTED_FOLDERS = ("common", "history", "localisation", "map", "events", "decisions", "gfx", "interface")
GAME_EXECUTABLES = ("v2game.exe", "victoria2.exe")
GAME_DATA_MIN_FOLDERS = 5

SETTINGS_GAME = "project/game_path"
SETTINGS_MOD = "project/mod_path"
SETTINGS_ROOT = "project/explorer_root"
SETTINGS_SPLITTER = "project/splitter"
SETTINGS_LEFT_TAB = "project/left_tab"
# Por debajo de esta altura de página (1100x700 da ~490 px) se ocultan las líneas secundarias.
COMPACT_HEIGHT = 600

# --- inspección de carpetas (sin Qt) ------------------------------------------------------
# El descriptor .mod se lee con el parser Clausewitz (core.modfile).


@dataclass(frozen=True)
class FolderReport:
    path: Path | None
    exists: bool = False
    present: tuple[str, ...] = ()
    executable: str | None = None
    entries: int = 0
    descriptor: ModDescriptor | None = None

    @property
    def is_game(self) -> bool:
        return self.executable is not None


def inspect_folder(path: str | os.PathLike | None) -> FolderReport:
    if path is None or os.fspath(path) == "":
        return FolderReport(None)
    folder = Path(path)
    try:
        entries = {entry.name.lower(): entry for entry in os.scandir(folder)}
    except OSError:
        return FolderReport(folder)
    present = tuple(name for name in EXPECTED_FOLDERS if name in entries and entries[name].is_dir())
    executable = next((entries[name].name for name in GAME_EXECUTABLES
                       if name in entries and entries[name].is_file()), None)
    return FolderReport(folder, True, present, executable, len(entries), find_descriptor(folder))


def same_folder(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _is_under(path: Path, root: Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
    except ValueError:
        return False
    return True


def evaluate_game(report: FolderReport) -> tuple[str, str, dict]:
    """(nivel, clave de catálogo, formato) para la ruta del juego base."""
    if report.path is None:
        return "neutral", N_("check.not_set"), {}
    if not report.exists:
        return "error", N_("check.missing"), {}
    if report.is_game:
        return "ok", N_("check.game_ok"), {"exe": report.executable}
    if len(report.present) >= GAME_DATA_MIN_FOLDERS:
        return "warning", N_("check.game_no_exe"), {}
    return "error", N_("check.game_no_data"), {}


def evaluate_mod(report: FolderReport, game_path: Path | None) -> tuple[str, str, dict]:
    """El mod nunca puede ser el juego base: así jamás se escribe sobre el original."""
    if report.path is None:
        return "neutral", N_("check.not_set"), {}
    if not report.exists:
        return "error", N_("check.missing"), {}
    if report.is_game or same_folder(report.path, game_path):
        return "error", N_("check.mod_is_game"), {}
    if report.present:
        return "ok", N_("check.mod_ok"), {"count": len(report.present)}
    if report.entries == 0:
        return "warning", N_("check.mod_empty"), {}
    return "warning", N_("check.mod_unknown"), {}


# --- tipos de archivo ---------------------------------------------------------------------

IMAGE_SUFFIXES = {".bmp", ".tga", ".dds", ".png", ".jpg", ".jpeg", ".gif"}
TEXT_SUFFIXES = {".txt", ".csv", ".mod", ".lua", ".gui", ".gfx", ".sfx", ".asset", ".fx", ".fnt", ".bak", ".map", ".yml"}
FILE_TYPE_KEYS = {
    ".txt": N_("filetype.txt"), ".csv": N_("filetype.csv"), ".mod": N_("filetype.mod"), ".lua": N_("filetype.lua"),
    ".gui": N_("filetype.gui"), ".gfx": N_("filetype.gfx"), ".sfx": N_("filetype.sfx"), ".asset": N_("filetype.asset"),
    ".fx": N_("filetype.fx"), ".fnt": N_("filetype.fnt"), ".xac": N_("filetype.model"), ".xsm": N_("filetype.anim"),
    ".bak": N_("filetype.bak"), ".map": N_("filetype.map"),
}
FILE_ICONS = {
    ".txt": ("file_text", "ink_soft"), ".csv": ("file_table", "success"), ".mod": ("file_mod", "velvet_text"),
    ".lua": ("file_code", "ink_soft"), ".gui": ("file_code", "ink_soft"), ".gfx": ("file_code", "ink_soft"),
    ".fx": ("file_code", "ink_soft"), ".map": ("file_text", "ink_soft"),
}
ENCODING_KEYS = {"cp1252": N_("encoding.cp1252"), "utf-8": N_("encoding.utf8"), "utf-8-sig": N_("encoding.utf8_bom")}
MAX_SCAN_BYTES = 2 * 1024 * 1024
EXCERPT_LINES = 160
THUMBNAIL = QSize(520, 300)


PREVIEW_CLAUSEWITZ, PREVIEW_IMAGE, PREVIEW_CSV = "clausewitz", "image", "csv"
CSV_SUFFIX = ".csv"


def preview_kind(path: str | os.PathLike) -> str | None:
    """Visor que corresponde a un archivo: ``clausewitz``, ``image``, ``csv`` o ``None`` (ficha)."""
    suffix = Path(path).suffix.lower()
    if suffix in CLAUSEWITZ_SUFFIXES:
        return PREVIEW_CLAUSEWITZ
    if suffix in IMAGE_VIEWER_SUFFIXES:
        return PREVIEW_IMAGE
    if suffix == CSV_SUFFIX:
        return PREVIEW_CSV
    return None


def file_icon_spec(suffix: str) -> tuple[str, str]:
    if suffix in IMAGE_SUFFIXES:
        return "file_image", "velvet_text"
    return FILE_ICONS.get(suffix, ("file", "ink_soft"))


def file_type_text(path: Path, is_dir: bool) -> str:
    suffix = path.suffix.lower()
    if is_dir:
        return tr("filetype.folder")
    if suffix in IMAGE_SUFFIXES:
        return tr("filetype.image", format=suffix[1:].upper())
    if suffix in FILE_TYPE_KEYS:
        return tr(FILE_TYPE_KEYS[suffix])
    if suffix:
        return tr("filetype.other", ext=suffix)
    return tr("filetype.none")


@dataclass
class FileFacts:
    path: Path
    relative: str
    is_dir: bool
    size: int = 0
    modified: float = 0.0
    entries: int | None = None
    encoding: str | None = None
    lines: int | None = None
    excerpt: str | None = None
    partial: bool = False
    image: QImage | None = None
    image_size: QSize | None = None


def _load_image(path: Path) -> tuple[QImage | None, QSize | None]:
    """Miniatura y tamaño original. Se usa Pillow (TGA, DDS, BMP, PNG…): con archivos
    dañados falla limpiamente, mientras que los lectores de Qt llenan el registro de avisos."""
    try:
        with Image.open(path) as im:
            original = QSize(*im.size)
            im.thumbnail((THUMBNAIL.width(), THUMBNAIL.height()))
            rgba = im.convert("RGBA")
    except Exception:  # noqa: BLE001 - imagen ilegible: la vista previa queda sin miniatura
        return None, None
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, 4 * rgba.width, QImage.Format.Format_RGBA8888).copy(), original


def gather_facts(path: Path, root: Path | None) -> FileFacts:
    try:
        relative = path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        relative = path.as_posix()
    stat = path.stat()
    if path.is_dir():
        try:
            entries = sum(1 for _ in os.scandir(path))
        except OSError:
            entries = None
        return FileFacts(path, relative, True, 0, stat.st_mtime, entries)
    facts = FileFacts(path, relative, False, stat.st_size, stat.st_mtime)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        facts.image, facts.image_size = _load_image(path)
        return facts
    with path.open("rb") as handle:
        data = handle.read(MAX_SCAN_BYTES)
    facts.partial = stat.st_size > len(data)
    if suffix in TEXT_SUFFIXES or b"\x00" not in data[:4096]:
        decoded = decode_bytes(data)
        facts.encoding = decoded.encoding
        facts.lines = decoded.text.count("\n") + (0 if decoded.text.endswith("\n") or not decoded.text else 1)
        facts.excerpt = "\n".join(decoded.text.splitlines()[:EXCERPT_LINES])
    return facts


# --- modelo del explorador ----------------------------------------------------------------

class ExplorerModel(QIdentityProxyModel):
    """Proxy de ``QFileSystemModel`` con cabeceras traducidas e iconos propios.

    Los iconos se resuelven aquí (hilo de la interfaz) y no en el proveedor de
    iconos del modelo, que Qt invoca desde su hilo de recogida de datos.
    """

    HEADER_KEYS = (
        N_("project.explorer.col_name"), N_("project.explorer.col_size"),
        N_("project.explorer.col_type"), N_("project.explorer.col_modified"),
    )

    def __init__(self, source: QFileSystemModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSourceModel(source)
        self.fs = source
        self._folder_icon = make_icon("folder", "bronze", "gold_pale")
        self._file_icons: dict[str, object] = {}

    def file_path(self, index: QModelIndex) -> Path:
        return Path(self.fs.filePath(self.mapToSource(index)))

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole
                and 0 <= section < len(self.HEADER_KEYS)):
            return tr(self.HEADER_KEYS[section])
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.column() in (1, 3):
            # QFileSystemModel formatea con el locale del sistema; aquí se sigue el de la interfaz.
            source = self.mapToSource(index)
            locale = translator().locale()
            if index.column() == 1:
                return "" if self.fs.isDir(source) else locale.formattedDataSize(self.fs.size(source))
            return locale.toString(self.fs.lastModified(source), QLocale.FormatType.ShortFormat)
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            source = self.mapToSource(index)
            if self.fs.isDir(source):
                return self._folder_icon
            suffix = Path(self.fs.fileName(source)).suffix.lower()
            if suffix not in self._file_icons:
                name, tint = file_icon_spec(suffix)
                self._file_icons[suffix] = make_icon(name, tint, "cream")
            return self._file_icons[suffix]
        return super().data(index, role)

    def retranslate(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.HEADER_KEYS) - 1)
        # Los índices no cambian: solo se fuerza a las vistas a volver a pedir los textos.
        self.layoutAboutToBeChanged.emit()
        self.layoutChanged.emit()


def name_filters(text: str) -> list[str]:
    """``"france *.csv"`` -> ``["*france*", "*.csv"]``; admite comodines * y ?."""
    patterns = []
    for token in re.split(r"[\s;,]+", text.strip()):
        if token:
            patterns.append(token if any(c in token for c in "*?[") else f"*{token}*")
    return patterns


# --- widgets ------------------------------------------------------------------------------

def _group(object_name: str) -> tuple[QGroupBox, QWidget]:
    """QGroupBox con título en versalitas; el contenido recupera la fuente de cuerpo."""
    group = QGroupBox()
    group.setObjectName(object_name)
    group.setFont(theme.font("heading"))
    inner = QWidget()
    inner.setFont(theme.font("body"))
    layout = QVBoxLayout(group)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.addWidget(inner)
    return group, inner


class _VRule(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("verticalRule")
        self.setFixedWidth(1)


_LINK_TOKEN = ""  # marcador del enlace dentro del texto traducido (sobrevive al escape HTML)


def descriptor_html(descriptor: ModDescriptor) -> str:
    """Resumen del descriptor con su nombre de archivo como enlace (``href="descriptor"``)."""
    missing = tr("check.descriptor_missing_value")
    text = tr("check.descriptor", file=_LINK_TOKEN, name=descriptor.name or missing,
              path=descriptor.path or missing, user_dir=descriptor.user_dir or missing)
    if descriptor.location == INSIDE:
        text += " " + tr("check.descriptor_inside")
    errors = len(descriptor.errors)
    if errors:
        text += " · " + tr("check.descriptor_errors_one" if errors == 1 else "check.descriptor_errors", count=errors)
    anchor = (f'<a href="descriptor" style="color:{theme.PALETTE["velvet_light"]};">'
              f'{html.escape(descriptor.file.name)}</a>')
    return rich(text, 9).replace(_LINK_TOKEN, anchor)


class PathField(QWidget):
    """Campo de ruta con botón «Examinar…», insignia de validación y carpetas detectadas."""

    edited = Signal(object)  # Path | None
    descriptor_activated = Signal(object)  # Path del .mod

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self._path: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setProperty("role", "heading")
        self.caption.setFont(theme.font("body_bold"))
        head.addWidget(self.caption)
        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        head.addWidget(self.hint, 1)
        layout.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName(f"{kind}PathEdit")
        self.edit.setClearButtonEnabled(True)
        self.edit.editingFinished.connect(self._on_editing_finished)
        row.addWidget(self.edit, 1)
        self.browse = QPushButton()
        self.browse.setObjectName(f"{kind}BrowseButton")
        self.browse.setIcon(make_icon("folder_open", "gold_light"))
        self.browse.clicked.connect(self._on_browse)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.badge = StatusBadge()
        layout.addWidget(self.badge)
        # En modo compacto la insignia se reduce a un icono dentro del campo.
        self.status_action = self.edit.addAction(make_icon("info", "ink_muted"), QLineEdit.ActionPosition.TrailingPosition)
        self.status_action.setVisible(False)
        self.chips_box = QWidget()
        self.chip_layout = FlowLayout(self.chips_box, spacing=3)
        self.chips = [FolderChip(name) for name in EXPECTED_FOLDERS]
        for chip in self.chips:
            self.chip_layout.addWidget(chip)
        self.chips_box.setVisible(False)
        layout.addWidget(self.chips_box)
        self.descriptor = QLabel()
        self.descriptor.setObjectName(f"{kind}Descriptor")
        self.descriptor.setProperty("role", "caption")
        self.descriptor.setFont(theme.font("caption"))
        self.descriptor.setWordWrap(True)
        self.descriptor.setTextFormat(Qt.TextFormat.RichText)
        self.descriptor.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                                | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.descriptor.linkActivated.connect(self._on_descriptor_link)
        self.descriptor.setVisible(kind == "mod")
        layout.addWidget(self.descriptor)
        layout.addStretch(1)
        self._compact = False
        self._report = FolderReport(None)
        self._status: tuple[str, str, dict] = ("neutral", "check.not_set", {})

    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self.edit.setText(os.fspath(path) if path else "")

    def show_report(self, report: FolderReport, status: tuple[str, str, dict]) -> None:
        self._report = report
        self._status = status
        for chip in self.chips:
            chip.set_present(chip.folder in report.present)
        self._apply_compact()
        self.retranslate()

    def set_compact(self, compact: bool) -> None:
        """Sin carpetas detectadas ni línea del descriptor (pasan a la ayuda emergente de la insignia)."""
        if compact != self._compact:
            self._compact = compact
            self._apply_compact()
            self.retranslate()

    def _apply_compact(self) -> None:
        self.chips_box.setVisible(self._report.exists and not self._compact)
        self.descriptor.setVisible(self.kind == "mod" and not self._compact)
        self.badge.setVisible(not self._compact)
        self.status_action.setVisible(self._compact)

    def retranslate(self) -> None:
        game = self.kind == "game"
        self.caption.setText(tr("project.paths.game" if game else "project.paths.mod"))
        self.hint.setText(tr("project.paths.game_hint" if game else "project.paths.mod_hint"))
        self.edit.setPlaceholderText(tr("project.paths.game_placeholder" if game else "project.paths.mod_placeholder"))
        self.edit.setToolTip(tr("project.paths.edit_tooltip"))
        self.browse.setText(tr("project.paths.browse"))
        self.browse.setToolTip(tr("project.paths.browse_game_tooltip" if game else "project.paths.browse_mod_tooltip"))
        level, key, fmt = self._status
        self.badge.set_status(level, tr(key, **fmt))
        hidden = []
        if self._compact:
            hidden.append(self.badge.label.text())
            if self._report.exists:
                hidden.append(tr("check.compact_folders", folders=", ".join(self._report.present) or "—"))
            if self.kind == "mod" and self._report.descriptor is not None:
                d = self._report.descriptor
                hidden.append(tr("check.compact_descriptor", file=d.file.name, name=d.name or "—"))
            self.status_action.setIcon(make_icon(LEVEL_ICONS[level], LEVEL_COLORS[level]))
        self.status_action.setToolTip("\n".join(hidden))
        for chip in self.chips:
            present = chip.folder in self._report.present
            chip.setToolTip(tr("check.folder_present" if present else "check.folder_absent", folder=chip.folder))
        if self.kind == "mod":
            d = self._report.descriptor
            if d:
                self.descriptor.setText(descriptor_html(d))
                self.descriptor.setToolTip(tr("check.descriptor_tooltip", file=os.fspath(d.file)))
            elif self._report.exists:
                self.descriptor.setText(rich(tr("check.no_descriptor"), 9))
                self.descriptor.setToolTip("")
            else:
                self.descriptor.setText("")
                self.descriptor.setToolTip("")

    def descriptor_file(self) -> Path | None:
        d = self._report.descriptor
        return d.file if d else None

    def _on_descriptor_link(self, link: str) -> None:
        file = self.descriptor_file()
        if file is not None:
            self.descriptor_activated.emit(file)

    def _on_editing_finished(self) -> None:
        text = self.edit.text().strip()
        path = Path(os.path.expanduser(text)) if text else None
        if path != self._path:
            self._path = path
            self.edited.emit(path)

    def _on_browse(self) -> None:
        title = tr("project.paths.dialog_game" if self.kind == "game" else "project.paths.dialog_mod")
        start = os.fspath(self._path) if self._path and self._path.exists() else QDir.homePath()
        chosen = QFileDialog.getExistingDirectory(self, title, start)
        if chosen:
            self.set_path(Path(chosen))
            self.edited.emit(Path(chosen))


class FilePreview(QWidget):
    """Vista previa por defecto: metadatos, miniatura de imágenes o extracto de texto."""

    ROW_KEYS = (
        ("path", N_("project.preview.path")), ("size", N_("project.preview.size")),
        ("modified", N_("project.preview.modified")), ("entries", N_("project.preview.entries")),
        ("encoding", N_("project.preview.encoding")), ("lines", N_("project.preview.lines")),
        ("dimensions", N_("project.preview.dimensions")),
    )

    csv_requested = Signal(object)  # Path

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.facts: FileFacts | None = None
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.empty = EmptyState("file_text")
        self.stack.addWidget(self.empty)

        details = QWidget()
        column = QVBoxLayout(details)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon = IconWidget("file", 40)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = mark_data(QLabel())
        self.name.setFont(theme.font("body_bold", 13))
        self.name.setProperty("role", "title")
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.kind = QLabel()
        self.kind.setProperty("role", "caption")
        self.kind.setFont(theme.font("caption"))
        names.addWidget(self.name)
        names.addWidget(self.kind)
        head.addLayout(names, 1)
        column.addLayout(head)
        column.addWidget(Divider())
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(5)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form_labels: dict[str, QLabel] = {}
        self.form_values: dict[str, QLabel] = {}
        for row_id, _ in self.ROW_KEYS:
            label = QLabel()
            label.setProperty("role", "field")
            value = mark_data(QLabel())
            value.setProperty("role", "value")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.form.addRow(label, value)
            self.form_labels[row_id] = label
            self.form_values[row_id] = value
        column.addLayout(self.form)
        self.csv_button = QPushButton()
        self.csv_button.setObjectName("openInLocalisation")
        self.csv_button.setProperty("accent", True)
        self.csv_button.setIcon(make_icon("localisation", "gold_pale"))
        self.csv_button.clicked.connect(self._on_csv_clicked)
        self.csv_button.setVisible(False)
        column.addWidget(self.csv_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.thumbnail = QLabel()
        self.thumbnail.setObjectName("previewThumbnail")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.thumbnail)
        self.excerpt_caption = QLabel()
        self.excerpt_caption.setProperty("role", "caption")
        self.excerpt_caption.setFont(theme.font("caption"))
        column.addWidget(self.excerpt_caption)
        self.excerpt = QPlainTextEdit()
        self.excerpt.setObjectName("previewExcerpt")
        self.excerpt.setReadOnly(True)
        self.excerpt.setFont(theme.font("mono"))
        self.excerpt.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.excerpt.setMinimumHeight(140)
        mark_data(self.excerpt)
        column.addWidget(self.excerpt, 1)
        self.note = QLabel()
        self.note.setProperty("role", "caption")
        self.note.setFont(theme.font("caption"))
        self.note.setWordWrap(True)
        column.addWidget(self.note)
        self.details_stretch = QWidget()
        self.details_stretch.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        column.addWidget(self.details_stretch)
        # Con poca altura los detalles se desplazan en vez de comprimirse y solaparse.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        details.setAutoFillBackground(False)
        scroll.setWidget(details)
        self.stack.addWidget(scroll)
        self.details = details

    def show_facts(self, facts: FileFacts | None) -> None:
        self.facts = facts
        show_in_stack(self.stack, self.stack.widget(0 if facts is None else 1))
        if facts is None:
            self.retranslate()
            return
        if facts.is_dir:
            self.icon.set_icon("folder_open", "bronze")
        else:
            self.icon.set_icon(*file_icon_spec(facts.path.suffix.lower()))
        self.name.setText(facts.path.name or facts.relative)
        self.csv_button.setVisible(not facts.is_dir and preview_kind(facts.path) == PREVIEW_CSV)
        self.excerpt.setPlainText(facts.excerpt or "")
        self.excerpt.setVisible(facts.excerpt is not None)
        self.excerpt_caption.setVisible(facts.excerpt is not None)
        self.details_stretch.setVisible(facts.excerpt is None)
        if facts.image is not None:
            self.thumbnail.setPixmap(QPixmap.fromImage(facts.image))
            self.thumbnail.setVisible(True)
        else:
            self.thumbnail.clear()
            self.thumbnail.setVisible(False)
        self.retranslate()

    def retranslate(self) -> None:
        self.empty.set_texts(tr("project.preview.empty_title"), tr("project.preview.empty_text"))
        self.csv_button.setText(tr("project.preview.open_csv"))
        self.csv_button.setToolTip(tr("project.preview.open_csv_tooltip"))
        for row_id, key in self.ROW_KEYS:
            self.form_labels[row_id].setText(tr(key))
        facts = self.facts
        if facts is None:
            return
        locale = translator().locale()
        self.kind.setText(file_type_text(facts.path, facts.is_dir))
        values = {
            "path": facts.relative,
            "size": None if facts.is_dir else tr(
                "project.preview.size_value", human=locale.formattedDataSize(facts.size),
                bytes=locale.toString(facts.size)),
            "modified": locale.toString(QDateTime.fromSecsSinceEpoch(int(facts.modified)), "d MMM yyyy, HH:mm"),
            "entries": None if facts.entries is None else tr("project.preview.entries_value", count=facts.entries),
            "encoding": None if facts.encoding is None else tr(ENCODING_KEYS.get(facts.encoding, "encoding.other"),
                                                               name=facts.encoding),
            "lines": None if facts.lines is None else (
                locale.toString(facts.lines) + (" +" if facts.partial else "")),
            "dimensions": None if facts.image_size is None else
            f"{facts.image_size.width()} × {facts.image_size.height()} px",
        }
        for row_id, value in values.items():
            self.form.setRowVisible(self.form_values[row_id], value is not None)
            self.form_values[row_id].setText(value or "")
        self.excerpt_caption.setText(tr("project.preview.excerpt", count=EXCERPT_LINES))
        self.note.setText(tr("project.preview.note"))

    def _on_csv_clicked(self) -> None:
        if self.facts is not None:
            self.csv_requested.emit(self.facts.path)



class ProjectPage(BasePage):
    key = "project"
    title_key = N_("nav.project")
    subtitle_key = N_("page.project.subtitle")
    icon_name = "project"

    file_activated = Signal(object)    # Path del archivo seleccionado
    game_path_changed = Signal(object)  # Path | None
    mod_path_changed = Signal(object)   # Path | None
    explorer_loaded = Signal()
    csv_requested = Signal(object, object)  # Path del CSV, línea (int | None)
    validation_finished = Signal(object)   # core.modcheck.ModCheckReport

    ROOT_KEYS = (("mod", N_("project.explorer.root_mod")), ("game", N_("project.explorer.root_game")))
    LEFT_TABS = ("files", "validation")

    def build(self) -> None:
        settings = app_settings()
        self._game_path = self._stored_path(settings.value(SETTINGS_GAME, "", str))
        self._mod_path = self._stored_path(settings.value(SETTINGS_MOD, "", str))
        self._explorer_root: Path | None = None
        self._loading = False
        self._last_emitted: Path | None = None
        self._reveal_target: Path | None = None
        self._custom_preview: QWidget | None = None
        self._mod_report = FolderReport(None)
        self._mod_status: tuple[str, str, dict] = ("neutral", N_("check.not_set"), {})

        self.validate_button = QPushButton()
        self.validate_button.setObjectName("validateModButton")
        self.validate_button.setProperty("accent", True)
        self.validate_button.setIcon(make_icon("validate", "gold_pale"))
        self.validate_button.setIconSize(QSize(18, 18))
        self.validate_button.clicked.connect(self.validate_mod)
        self.header.trailing.addWidget(self.validate_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.paths_group, paths_inner = _group("pathsGroup")
        paths_row = QHBoxLayout(paths_inner)
        paths_row.setContentsMargins(2, 4, 2, 2)
        paths_row.setSpacing(12)
        self.game_field = PathField("game")
        self.mod_field = PathField("mod")
        self.game_field.edited.connect(self.set_game_path)
        self.mod_field.edited.connect(self.set_mod_path)
        self.mod_field.descriptor_activated.connect(self.open_file)
        paths_row.addWidget(self.game_field, 1)
        paths_row.addWidget(_VRule())
        paths_row.addWidget(self.mod_field, 1)
        self.body.addWidget(self.paths_group)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.explorer_group, explorer_inner = _group("explorerGroup")
        outer = QVBoxLayout(explorer_inner)
        outer.setContentsMargins(2, 2, 2, 2)
        self.left_tabs = QTabWidget()
        self.left_tabs.setObjectName("explorerTabs")
        self.left_tabs.tabBar().setExpanding(False)
        outer.addWidget(self.left_tabs)
        files_page = QWidget()
        explorer = QVBoxLayout(files_page)
        explorer.setContentsMargins(6, 8, 6, 6)
        explorer.setSpacing(6)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("explorerFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter_edit.textChanged.connect(self._apply_filter)
        tools.addWidget(self.filter_edit, 1)
        self.root_label = QLabel()
        self.root_label.setProperty("role", "field")
        tools.addWidget(self.root_label)
        self.root_combo = QComboBox()
        self.root_combo.setObjectName("explorerRoot")
        for data, _ in self.ROOT_KEYS:
            self.root_combo.addItem("", data)
        stored_root = settings.value(SETTINGS_ROOT, "mod", str)
        self.root_combo.setCurrentIndex(1 if stored_root == "game" else 0)
        self.root_combo.currentIndexChanged.connect(self._on_root_changed)
        tools.addWidget(self.root_combo)
        self.collapse_button = QToolButton()
        self.collapse_button.setObjectName("collapseButton")
        self.collapse_button.setIcon(make_icon("collapse", "gold_light"))
        self.collapse_button.setIconSize(QSize(18, 18))
        tools.addWidget(self.collapse_button)
        explorer.addLayout(tools)

        self.fs = QFileSystemModel(self)
        self.fs.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.fs.setNameFilterDisables(False)
        self.fs.setReadOnly(True)
        self.fs.directoryLoaded.connect(self._on_directory_loaded)
        self.model = ExplorerModel(self.fs, self)
        self.tree = QTreeView()
        self.tree.setObjectName("explorerTree")
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(False)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.hideSection(2)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.activated.connect(self._on_activated)
        self.tree.clicked.connect(self._on_clicked)
        self.collapse_button.clicked.connect(self.tree.collapseAll)

        self.explorer_stack = QStackedWidget()
        self.explorer_empty = EmptyState("folder_open")
        self.explorer_empty_button = QPushButton()
        self.explorer_empty_button.setProperty("accent", True)
        self.explorer_empty_button.setIcon(make_icon("folder_open", "gold_pale"))
        self.explorer_empty_button.clicked.connect(self._browse_for_root)
        self.explorer_empty.add_action(self.explorer_empty_button)
        self.explorer_stack.addWidget(self.explorer_empty)
        self.explorer_stack.addWidget(self.tree)
        explorer.addWidget(self.explorer_stack, 1)
        self.left_tabs.addTab(files_page, make_icon("folder", "bronze", "gold_pale"), "")
        self.validation = ValidationPanel()
        self.validation.run_requested.connect(self.validate_mod)
        self.validation.issue_activated.connect(self._on_issue_activated)
        self.validation.validation_finished.connect(self._on_validation_finished)
        self.validation.busy_changed.connect(lambda busy: self._update_validate_button())
        self.left_tabs.addTab(self.validation, make_icon("validate", "ink_soft"), "")
        stored_tab = settings.value(SETTINGS_LEFT_TAB, "files", str)
        self.left_tabs.setCurrentIndex(0 if stored_tab not in self.LEFT_TABS else self.LEFT_TABS.index(stored_tab))
        self.left_tabs.currentChanged.connect(
            lambda i: app_settings().setValue(SETTINGS_LEFT_TAB, self.LEFT_TABS[i]))
        self.splitter.addWidget(self.explorer_group)

        self.preview_group, preview_inner = _group("previewGroup")
        preview_layout = QVBoxLayout(preview_inner)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_stack = QStackedWidget()
        self.preview = FilePreview()
        self.preview.csv_requested.connect(lambda path: self.csv_requested.emit(path, None))
        self.preview_stack.addWidget(self.preview)
        self.clausewitz_viewer = ClausewitzViewer()
        self.image_viewer = ImageViewer()
        self.clausewitz_viewer.loaded.connect(self._on_viewer_loaded)
        self.image_viewer.loaded.connect(self._on_viewer_loaded)
        for viewer in (self.clausewitz_viewer, self.image_viewer):
            self.preview_stack.addWidget(viewer)
        show_in_stack(self.preview_stack, self.preview)
        preview_layout.addWidget(self.preview_stack)
        self.splitter.addWidget(self.preview_group)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        state = settings.value(SETTINGS_SPLITTER)
        if state is None or not self.splitter.restoreState(state):
            self.splitter.setSizes([560, 600])
        self.splitter.splitterMoved.connect(self._save_splitter)
        self.body.addWidget(self.splitter, 1)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(80)
        self._scroll_timer.timeout.connect(self._scroll_to_current)
        self._rescroll_until = 0.0
        self.model.layoutChanged.connect(self._rescroll_if_pending)
        self.model.rowsInserted.connect(self._rescroll_if_pending)
        self._loading_timeout = QTimer(self)
        self._loading_timeout.setSingleShot(True)
        self._loading_timeout.setInterval(5000)
        self._loading_timeout.timeout.connect(self._finish_loading)

        self.game_field.set_path(self._game_path)
        self.mod_field.set_path(self._mod_path)
        self._validate()
        self._refresh_explorer()

    # --- API pública ---------------------------------------------------------------------

    def game_path(self) -> Path | None:
        return self._game_path

    def mod_path(self) -> Path | None:
        return self._mod_path

    def explorer_root(self) -> Path | None:
        return self._explorer_root

    def set_game_path(self, path: str | os.PathLike | None) -> None:
        self._game_path = Path(path) if path else None
        self.game_field.set_path(self._game_path)
        app_settings().setValue(SETTINGS_GAME, os.fspath(self._game_path) if self._game_path else "")
        self._validate()
        self._refresh_explorer()
        self.request_status("status.game_path_set" if self._game_path else "status.game_path_cleared")
        self.game_path_changed.emit(self._game_path)

    def set_mod_path(self, path: str | os.PathLike | None) -> None:
        self._mod_path = Path(path) if path else None
        self.mod_field.set_path(self._mod_path)
        app_settings().setValue(SETTINGS_MOD, os.fspath(self._mod_path) if self._mod_path else "")
        self.validation.clear()
        self._validate()
        self._refresh_explorer()
        self.request_status("status.mod_path_set" if self._mod_path else "status.mod_path_cleared")
        self.mod_path_changed.emit(self._mod_path)

    def set_explorer_root(self, which: str) -> None:
        """``"mod"`` o ``"game"``: qué carpeta muestra el explorador."""
        self.root_combo.setCurrentIndex(1 if which == "game" else 0)

    def set_preview_widget(self, widget: QWidget | None) -> None:
        """Muestra ``widget`` en el panel de vista previa; ``None`` vuelve a los metadatos.

        El widget anterior se retira del panel sin destruirlo.
        """
        if self._custom_preview is not None and self._custom_preview is not widget:
            self.preview_stack.removeWidget(self._custom_preview)
            self._custom_preview.hide()
            self._custom_preview = None
        if widget is None:
            show_in_stack(self.preview_stack, self.preview)
            return
        if self.preview_stack.indexOf(widget) < 0:
            self.preview_stack.addWidget(widget)
        self._custom_preview = widget
        show_in_stack(self.preview_stack, widget)

    def preview_widget(self) -> QWidget | None:
        return self._custom_preview

    def reveal_file(self, path: str | os.PathLike) -> bool:
        """Selecciona ``path`` en el explorador (expandiendo sus carpetas) si está bajo la raíz."""
        target = Path(path)
        root = self._explorer_root
        if root is None or not target.exists():
            return False
        try:
            Path(os.path.realpath(target)).relative_to(os.path.realpath(root))
        except ValueError:
            return False
        source = self.fs.index(os.fspath(target))
        if not source.isValid():
            return False
        index = self.model.mapFromSource(source)
        parent = index.parent()
        while parent.isValid() and parent != self.tree.rootIndex():
            self.tree.expand(parent)
            parent = parent.parent()
        self._reveal_target = target
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def open_file(self, path: str | os.PathLike, line: int | None = None, column: int | None = None,
                  tab: str | None = None) -> bool:
        """Abre ``path`` en el visor que le corresponda, en ``line`` si se indica.

        Lo selecciona también en el explorador cuando está bajo su raíz. Los CSV
        se piden a la página de Localización (``csv_requested``). Devuelve
        ``False`` si el archivo no existe.
        """
        path = Path(path)
        if not path.is_file():
            return False
        if preview_kind(path) == PREVIEW_CSV:
            self.csv_requested.emit(path, line)
            return True
        self.reveal_file(path)
        self._show_preview(path, line=line, column=column, tab=tab)
        return True

    def validate_mod(self) -> bool:
        """Valida en segundo plano el mod (y su descriptor .mod); ``False`` si no hay mod válido."""
        if not self._can_validate():
            return False
        descriptor = self._mod_report.descriptor
        extra = [descriptor.file] if descriptor is not None else []
        self.left_tabs.setCurrentWidget(self.validation)
        self.validation.start(self._mod_path, extra)
        self.request_status("status.validation_started", path=self._mod_path.name)
        return True

    def validation_report(self):
        return self.validation.report()

    def set_compact(self, compact: bool) -> None:
        """Modo compacto (ventanas bajas): menos líneas en rutas, visor y validación."""
        self.game_field.set_compact(compact)
        self.mod_field.set_compact(compact)
        self.clausewitz_viewer.set_compact(compact)
        self.validation.set_compact(compact)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.set_compact(self.height() < COMPACT_HEIGHT)

    def is_busy(self) -> bool:
        return (self._loading or self._scroll_timer.isActive() or self.clausewitz_viewer.is_busy()
                or self.image_viewer.is_busy() or self.validation.is_busy())

    def shutdown(self) -> None:
        self.validation.cancel()
        self.clausewitz_viewer.clear()

    # --- interno -------------------------------------------------------------------------

    @staticmethod
    def _stored_path(value: str) -> Path | None:
        return Path(value) if value else None

    def _validate(self) -> None:
        game_report = inspect_folder(self._game_path)
        mod_report = inspect_folder(self._mod_path)
        self.game_field.show_report(game_report, evaluate_game(game_report))
        mod_status = evaluate_mod(mod_report, self._game_path)
        self.mod_field.show_report(mod_report, mod_status)
        self._mod_report = mod_report
        self._mod_status = mod_status
        self._update_validate_button()

    def _can_validate(self) -> bool:
        # Nunca se valida (ni se tratará como mod) la carpeta del juego base.
        return self._mod_path is not None and self._mod_report.exists and self._mod_status[0] != "error"

    def _update_validate_button(self) -> None:
        busy = self.validation.is_busy()
        self.validate_button.setEnabled(self._can_validate() and not busy)
        self.validation.set_run_enabled(self._can_validate())

    def _refresh_explorer(self) -> None:
        which = self.root_combo.currentData()
        root = self._mod_path if which == "mod" else self._game_path
        if root is None or not root.is_dir():
            self._explorer_root = None
            self._loading = False
            show_in_stack(self.explorer_stack, self.explorer_empty)
            self.preview.show_facts(None)
            self.set_preview_widget(None)
            self._retranslate_explorer_empty()
            return
        if self._explorer_root is not None and same_folder(root, self._explorer_root):
            return
        self._explorer_root = root
        self._loading = True
        self._loading_timeout.start()
        source_root = self.fs.setRootPath(os.fspath(root))
        self.tree.setRootIndex(self.model.mapFromSource(source_root))
        show_in_stack(self.explorer_stack, self.tree)
        self.preview.show_facts(None)
        self.set_preview_widget(None)
        self._last_emitted = None

    def _on_directory_loaded(self, directory: str) -> None:
        if self._explorer_root is not None and same_folder(Path(directory), self._explorer_root):
            self._finish_loading()
        if self._reveal_target is not None and same_folder(Path(directory), self._reveal_target.parent):
            # El modelo sigue insertando y ordenando filas tras cargar la carpeta: durante un
            # instante cada cambio de disposición vuelve a centrar el archivo seleccionado.
            self._reveal_target = None
            self._rescroll_until = time.monotonic() + 1.0
            self._scroll_timer.start()

    def _rescroll_if_pending(self, *args) -> None:
        if time.monotonic() < self._rescroll_until:
            self._scroll_timer.start()

    def _scroll_to_current(self) -> None:
        current = self.tree.currentIndex()
        if current.isValid():
            self.tree.scrollTo(current, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _finish_loading(self) -> None:
        self._loading_timeout.stop()
        if self._loading:
            self._loading = False
            self.explorer_loaded.emit()

    def _on_root_changed(self, index: int) -> None:
        app_settings().setValue(SETTINGS_ROOT, self.root_combo.currentData())
        self._explorer_root = None
        self._refresh_explorer()

    def _browse_for_root(self) -> None:
        field = self.game_field if self.root_combo.currentData() == "game" else self.mod_field
        field._on_browse()

    def _apply_filter(self, text: str) -> None:
        self.fs.setNameFilters(name_filters(text))

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if not current.isValid():
            return
        path = self.model.file_path(current)
        if self._reveal_target is not None and not same_folder(path, self._reveal_target):
            self._reveal_target = None
        try:
            facts = gather_facts(path, self._explorer_root)
        except OSError:
            facts = None
        self.preview.show_facts(facts)
        if facts is None or facts.is_dir:
            self.set_preview_widget(None)
            return
        self._show_preview(path)
        if path != self._last_emitted:
            self._last_emitted = path
            self.request_status("status.file_selected", path=facts.relative)
            self.file_activated.emit(path)

    def _show_preview(self, path: Path, *, line: int | None = None, column: int | None = None,
                      tab: str | None = None) -> None:
        kind = preview_kind(path)
        # Ruta mostrada en la cabecera del visor: relativa al explorador (o al mod) si cuelga de él.
        root = self._explorer_root or self._mod_path
        if root is None or not _is_under(path, root):
            root = path.parent
        if kind == PREVIEW_CLAUSEWITZ:
            self.set_preview_widget(self.clausewitz_viewer)
            self.clausewitz_viewer.load(path, root=root, line=line, column=column, tab=tab)
        elif kind == PREVIEW_IMAGE:
            self.set_preview_widget(self.image_viewer)
            self.image_viewer.load(path, root=root)
        else:
            self.set_preview_widget(None)

    def _on_viewer_loaded(self, path: Path) -> None:
        load = self.clausewitz_viewer.current_load()
        if load is not None and load.path == path:
            errors = len(load.result.errors)
            if errors:
                self.request_status("status.file_errors_one" if errors == 1 else "status.file_errors",
                                    name=path.name, count=errors)

    def _csv_at(self, index: QModelIndex) -> Path | None:
        if not index.isValid() or self.fs.isDir(self.model.mapToSource(index)):
            return None
        path = self.model.file_path(index)
        return path if preview_kind(path) == PREVIEW_CSV else None

    def _on_clicked(self, index: QModelIndex) -> None:
        csv = self._csv_at(index)
        if csv is not None:
            self.csv_requested.emit(csv, None)

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid() and self.fs.isDir(self.model.mapToSource(index)):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
            return
        csv = self._csv_at(index)
        if csv is not None:
            self.csv_requested.emit(csv, None)

    def _on_issue_activated(self, row) -> None:
        if row.path is not None:
            self.open_file(row.path, line=row.line, column=row.column)

    def _on_validation_finished(self, report) -> None:
        self._retranslate_left_tabs()
        # Invocables: la barra de estado los vuelve a formatear si cambia el idioma.
        self.request_status("status.validation_done", files=lambda: translator().locale().toString(report.files),
                            errors=len(report.files_with()),
                            seconds=lambda: translator().locale().toString(report.elapsed, "f", 1))
        self.validation_finished.emit(report)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        path = self.model.file_path(index)
        menu = QMenu(self)
        copy = QAction(make_icon("copy", "cream"), tr("project.explorer.copy_path"), menu)
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(os.fspath(path)))
        reveal = QAction(make_icon("external", "cream"), tr("project.explorer.open_folder"), menu)
        folder = path if path.is_dir() else path.parent
        reveal.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(folder))))
        menu.addAction(copy)
        menu.addAction(reveal)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _save_splitter(self, *args) -> None:
        app_settings().setValue(SETTINGS_SPLITTER, self.splitter.saveState())

    def _retranslate_left_tabs(self) -> None:
        self.left_tabs.setTabText(0, tr("project.tab.files"))
        self.left_tabs.setTabToolTip(0, tr("project.tab.files_tooltip"))
        report = self.validation.report()
        if report is None:
            self.left_tabs.setTabText(1, tr("project.tab.validation"))
            icon = make_icon("validate", "ink_soft")
        else:
            errors = len(report.files_with())
            self.left_tabs.setTabText(1, tr("project.tab.validation_count", count=errors) if errors
                                      else tr("project.tab.validation"))
            icon = make_icon("error", "danger") if errors else make_icon("check", "success")
        self.left_tabs.setTabIcon(1, icon)
        self.left_tabs.setTabToolTip(1, tr("project.tab.validation_tooltip"))

    def _retranslate_explorer_empty(self) -> None:
        game = self.root_combo.currentData() == "game"
        self.explorer_empty.set_texts(
            tr("project.explorer.empty_title"),
            tr("project.explorer.empty_game" if game else "project.explorer.empty_mod"),
        )
        self.explorer_empty_button.setText(tr("project.paths.browse"))
        self.explorer_empty_button.setToolTip(
            tr("project.paths.browse_game_tooltip" if game else "project.paths.browse_mod_tooltip"))

    def retranslate(self) -> None:
        super().retranslate()
        self.paths_group.setTitle(tr("project.paths.title"))
        self.explorer_group.setTitle(tr("project.explorer.title"))
        self.preview_group.setTitle(tr("project.preview.title"))
        self.game_field.retranslate()
        self.mod_field.retranslate()
        self.filter_edit.setPlaceholderText(tr("project.explorer.filter_placeholder"))
        self.filter_edit.setToolTip(tr("project.explorer.filter_tooltip"))
        self.root_label.setText(tr("project.explorer.root"))
        self.root_combo.setToolTip(tr("project.explorer.root_tooltip"))
        for i, (_, key) in enumerate(self.ROOT_KEYS):
            self.root_combo.setItemText(i, tr(key))
        self.collapse_button.setToolTip(tr("project.explorer.collapse"))
        self.validate_button.setText(tr("project.validate"))
        self.validate_button.setToolTip(tr("project.validate_tooltip"))
        self._retranslate_left_tabs()
        self.model.retranslate()
        self._retranslate_explorer_empty()
        self.clausewitz_viewer.retranslate()
        self.image_viewer.retranslate()
        self.validation.retranslate()
        self.preview.retranslate()
