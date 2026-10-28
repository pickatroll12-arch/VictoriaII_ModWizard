"""Proyecto y Archivos: rutas del juego base y del mod, explorador, vista previa y validación.

Al seleccionar un archivo del explorador la vista previa elige visor:

* scripts Clausewitz (``.txt``, ``.mod``, ``.gfx``, ``.gui``, ``.sfx``, ``.asset``):
  ``ClausewitzViewer`` (estructura, código fuente, diagnósticos y JSON);
* imágenes (``.tga``, ``.dds``, ``.bmp``, ``.png``, ``.jpg``, ``.gif``): ``ImageViewer``;
* el resto (y las carpetas): la ficha de metadatos ``FilePreview``.

Los ``.csv`` de ``localisation/`` se abren en la página de Localización: al hacer
clic en ellos (o con Intro / doble clic) se emite ``csv_requested(Path, línea |
None)``. Con el teclado, moverse por encima de un CSV solo muestra su ficha, para
que recorrer ``localisation/`` con las flechas no cambie de página a cada paso. Los
demás CSV (``map/definition.csv``…) no son de localización y muestran su ficha; abiertos
en una línea (Ctrl+K «549», un problema), el extracto de la ficha son las
``EXCERPT_LINES`` líneas que la rodean, con su numeración y esa línea marcada y centrada
(no las primeras: la provincia 549 está en la línea 550). Se eligió esto, y no un visor
de código del archivo entero, porque la ficha ya lee solo los primeros ``MAX_SCAN_BYTES``
en el hilo de la interfaz y el extracto acota lo que se maqueta (cualquier tamaño de
archivo cuesta lo mismo).

Con el teclado la vista previa espera a que la selección se asiente
(``SELECTION_DELAY_MS``) para no analizar cada archivo por el que se pasa; con el
ratón o al abrir un archivo desde otra parte se muestra en el acto.

«Validar mod» analiza en segundo plano todos los archivos Clausewitz y CSV del
mod (``core.modcheck``) y lista sus diagnósticos en la pestaña «Validación».

Otros puntos de extensión: ``file_activated(Path)``, ``set_preview_widget(widget)``
(``None`` restaura la vista por defecto), ``game_path_changed`` / ``mod_path_changed``.

La inspección de carpetas (``inspect_folder``, ``evaluate_game``, ``evaluate_mod``)
vive en ``core.vfs.guard`` (sin Qt) y se reexporta aquí.
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
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz import Severity
from ...core.clausewitz.diagnostics import ENCODING_CODES
from ...core.csvloc import is_localisation_csv
from ...core.encoding import GAME_UNREADABLE, count_lines, decode_bytes
from ...core.modfile import INSIDE, ModDescriptor, find_descriptor, read_descriptor
from ...core.vfs.guard import (
    EXPECTED_FOLDERS,
    FolderReport,
    evaluate_game,
    evaluate_mod,
    folder_key,
    inspect_folder,
    same_folder,
)
from ...core.vfs.guard import is_under as _is_under
from ...i18n import N_, tr, translator
from ...settings import app_settings
from .. import theme
from ..viewers import CLAUSEWITZ_SUFFIXES, IMAGE_SUFFIXES, ClausewitzViewer, ImageViewer, ValidationPanel
from ..viewers.code_view import CodeView, display_text
from ..viewers.common import ElidedLabel, file_stamp, format_seconds, format_size
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

SETTINGS_GAME = "project/game_path"
SETTINGS_MOD = "project/mod_path"
SETTINGS_ROOT = "project/explorer_root"
SETTINGS_SPLITTER = "project/splitter"
SETTINGS_LEFT_TAB = "project/left_tab"
# Por debajo de esta altura de página (1100x700 da ~490 px) se ocultan las líneas secundarias.
COMPACT_HEIGHT = 600
SELECTION_DELAY_MS = 150  # con el teclado, espera antes de cargar la vista previa del archivo seleccionado
REVEAL_TIMEOUT_MS = 5000  # como mucho, lo que se espera a que el explorador liste las carpetas de lo revelado
RESCROLL_SECONDS = 1.0    # tras listarlas, cada cambio de disposición vuelve a centrarlo durante este tiempo

# --- tipos de archivo ---------------------------------------------------------------------

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
ENCODING_KEYS = {
    "cp1252": N_("encoding.cp1252"), "utf-8": N_("encoding.utf8"), "utf-8-sig": N_("encoding.utf8_bom"),
    "utf-16": N_("encoding.utf16"), "utf-16-be-bom": N_("encoding.utf16_be_bom"), "utf-16-le": N_("encoding.utf16_le"),
    "utf-16-be": N_("encoding.utf16_be"),
}
MAX_SCAN_BYTES = 2 * 1024 * 1024
EXCERPT_LINES = 160
_LINE_RE = re.compile(r"\r\n|\r|\n")   # los saltos del juego y del índice (``str.splitlines`` parte en más)

PREVIEW_CLAUSEWITZ, PREVIEW_IMAGE, PREVIEW_CSV = "clausewitz", "image", "csv"


def preview_kind(path: str | os.PathLike) -> str | None:
    """Visor que corresponde a un archivo: ``clausewitz``, ``image``, ``csv`` (de localización) o ``None`` (ficha)."""
    suffix = Path(path).suffix.lower()
    if suffix in CLAUSEWITZ_SUFFIXES:
        return PREVIEW_CLAUSEWITZ
    if suffix in IMAGE_SUFFIXES:
        return PREVIEW_IMAGE
    if is_localisation_csv(path):  # el juego solo lee la localización de los CSV de localisation/
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
    stamp: tuple[int, int] | None = None  # ``file_stamp`` al leerlo: si cambia, la ficha está desfasada
    excerpt_first: int = 1                # número de la primera línea del extracto
    focus_line: int | None = None         # la línea pedida, si está en el extracto


def relative_text(path: Path, root: Path | None) -> str:
    """``path`` relativa a ``root`` (con ``/``) si cuelga de ella; si no, completa."""
    try:
        return path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        return path.as_posix()


def gather_facts(path: Path, root: Path | None, line: int | None = None) -> FileFacts:
    """Metadatos de la ficha; de los archivos de texto, también la codificación y un extracto: las primeras
    ``EXCERPT_LINES`` líneas o, si se pide ``line``, las que la rodean (``excerpt_first``, ``focus_line``)."""
    relative = relative_text(path, root)
    stat = path.stat()
    stamp = stat.st_mtime_ns, stat.st_size  # como ``file_stamp``
    if path.is_dir():
        try:
            entries = sum(1 for _ in os.scandir(path))
        except OSError:
            entries = None
        return FileFacts(path, relative, True, 0, stat.st_mtime, entries, stamp=stamp)
    facts = FileFacts(path, relative, False, stat.st_size, stat.st_mtime, stamp=stamp)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return facts  # las muestra ImageViewer
    with path.open("rb") as handle:
        data = handle.read(MAX_SCAN_BYTES)
    facts.partial = stat.st_size > len(data)
    if suffix in TEXT_SUFFIXES or b"\x00" not in data[:4096]:
        # De uno más largo solo se lee el principio: un carácter cortado al final no cambia la codificación.
        decoded = decode_bytes(data, partial=facts.partial)
        facts.encoding = decoded.encoding
        facts.lines = count_lines(decoded.text)
        lines = _LINE_RE.split(decoded.text)
        if lines and lines[-1] == "":
            lines.pop()   # el salto final no abre otra línea
        first = 1
        if line is not None and 1 <= line <= len(lines):
            first = max(1, min(line - EXCERPT_LINES // 2, len(lines) - EXCERPT_LINES + 1))
            facts.focus_line = line
        facts.excerpt_first = first
        facts.excerpt = "\n".join(lines[first - 1:first - 1 + EXCERPT_LINES])
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
                return "" if self.fs.isDir(source) else format_size(self.fs.size(source))
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
    """``"france; *.csv"`` -> ``["*france*", "*.csv"]``: patrones separados por ``;`` o ``,``.

    Los espacios forman parte del patrón (``400 - Dunkirk``). Solo ``*`` y ``?`` son
    comodines: los corchetes se buscan tal cual (en Qt abrirían una clase de caracteres).
    """
    patterns = []
    for token in re.split(r"[;,]", text):
        token = token.strip()
        if token:
            literal = "".join(f"[{c}]" if c in "[]" else c for c in token)
            patterns.append(literal if any(c in token for c in "*?") else f"*{literal}*")
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


# Marcadores dentro del texto traducido (sobreviven al escape HTML y a ``rich``): el enlace y los
# valores del descriptor, que se insertan después para que sus comillas invertidas no formen código.
_LINK_TOKEN = "\ue000"
_VALUE_TOKENS = {"name": "\ue001", "path": "\ue002", "user_dir": "\ue003"}


def syntax_error_count(diagnostics) -> int:
    """Errores de sintaxis de verdad: los de codificación (``ENCODING_CODES``, p. ej. un UTF-16) se cuentan aparte."""
    return sum(1 for d in diagnostics if d.severity is Severity.ERROR and d.code not in ENCODING_CODES)


def _descriptor_errors_text(descriptor: ModDescriptor) -> str:
    parts = [] if descriptor.game_readable else [tr("check.descriptor_unreadable")]
    errors = syntax_error_count(descriptor.errors)
    if errors:
        parts.append(tr("check.descriptor_errors_one" if errors == 1 else "check.descriptor_errors", count=errors))
    return " · ".join(parts)


def descriptor_html(descriptor: ModDescriptor) -> str:
    """Resumen del descriptor con su nombre de archivo como enlace (``href="descriptor"``)."""
    missing = tr("check.descriptor_missing_value")
    text = tr("check.descriptor", file=_LINK_TOKEN, **_VALUE_TOKENS)
    if descriptor.location == INSIDE:
        text += " " + tr("check.descriptor_inside")
    errors = _descriptor_errors_text(descriptor)
    if errors:
        text += " · " + errors
    anchor = (f'<a href="descriptor" style="color:{theme.PALETTE["velvet_light"]};">'
              f'{html.escape(descriptor.file.name)}</a>')
    result = rich(text, 9).replace(_LINK_TOKEN, anchor)
    for field, token in _VALUE_TOKENS.items():
        result = result.replace(token, html.escape(getattr(descriptor, field) or missing, quote=False))
    return result


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
        # En modo compacto la insignia se reduce a un icono dentro del campo; con descriptor, abre este.
        self.status_action = self.edit.addAction(make_icon("info", "ink_muted"), QLineEdit.ActionPosition.TrailingPosition)
        self.status_action.setVisible(False)
        self.status_action.triggered.connect(self._on_descriptor_link)
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
        layout.addWidget(self.descriptor)
        # Después de meterla en la fila: sin padre, setVisible(True) la mostraría como ventana suelta.
        self.descriptor.setVisible(kind == "mod")
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
        """Sin carpetas detectadas ni línea del descriptor: pasan a la ayuda emergente del icono de estado,
        y un clic en él abre el descriptor."""
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
                missing = tr("check.descriptor_missing_value")
                line = tr("check.compact_descriptor", file=d.file.name, name=d.name or missing,
                          path=d.path or missing, user_dir=d.user_dir or missing)
                errors = _descriptor_errors_text(d)
                hidden += [f"{line} · {errors}" if errors else line, tr("check.compact_descriptor_open")]
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

    def _on_descriptor_link(self, *args) -> None:
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
    """Ficha de lo que no tiene visor propio (carpetas, CSV y otros archivos): metadatos y extracto de texto."""

    ROW_KEYS = (
        ("path", N_("project.preview.path")), ("size", N_("project.preview.size")),
        ("modified", N_("project.preview.modified")), ("entries", N_("project.preview.entries")),
        ("encoding", N_("project.preview.encoding")), ("lines", N_("project.preview.lines")),
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
        # Recortado por el medio: un nombre largo sin espacios no puede partirse y ensancharía la ficha.
        self.name = mark_data(ElidedLabel())
        self.name.setFont(theme.font("body_bold", 13))
        self.name.setProperty("role", "title")
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
            # Preferred y no Fixed: con Fixed el alto se queda en el sizeHint y, con la vista previa estrecha, el
            # texto partido («UTF-16 BE con BOM (…) — el juego no puede leerlo») pierde sus últimas líneas.
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setWordWrap(True)
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
        self.excerpt_caption = QLabel()
        self.excerpt_caption.setProperty("role", "caption")
        self.excerpt_caption.setFont(theme.font("caption"))
        column.addWidget(self.excerpt_caption)
        # Con números de línea: abierto en una línea (Ctrl+K «549»), el extracto la rodea y la marca.
        self.excerpt = CodeView()
        self.excerpt.setObjectName("previewExcerpt")
        self.excerpt.setMinimumHeight(140)
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
        self.details_scroll = scroll

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
        name = facts.path.name or facts.relative  # la fila «Ruta» lo lleva entero
        self.name.set_text(name, name)
        self.csv_button.setVisible(not facts.is_dir and preview_kind(facts.path) == PREVIEW_CSV)
        self.excerpt.set_source(display_text(facts.excerpt or ""), highlight=False, first_line=facts.excerpt_first)
        if facts.focus_line is not None:
            self.excerpt.go_to_line(facts.focus_line)
        self.excerpt.setVisible(facts.excerpt is not None)
        self.excerpt_caption.setVisible(facts.excerpt is not None)
        self.details_stretch.setVisible(facts.excerpt is None)
        self.retranslate()
        if facts.focus_line is not None:
            # Con poca altura la ficha se desplaza: que el extracto, con su línea, quede a la vista.
            self.details_scroll.ensureWidgetVisible(self.excerpt, 0, 0)

    def shown_line(self) -> int | None:
        """La línea marcada en el extracto (la pedida al abrir), o None."""
        facts = self.facts
        if facts is None or facts.focus_line is None or not self.excerpt.isVisible():
            return None
        return self.excerpt.current_line()

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
            "size": None if facts.is_dir else format_size(facts.size) if facts.size < 1024 else tr(
                "project.preview.size_value", human=format_size(facts.size), bytes=locale.toString(facts.size)),
            "modified": locale.toString(QDateTime.fromSecsSinceEpoch(int(facts.modified)), "d MMM yyyy, HH:mm"),
            "entries": None if facts.entries is None else tr(
                "project.preview.entries_value_one" if facts.entries == 1 else "project.preview.entries_value",
                count=locale.toString(facts.entries)),
            "encoding": None if facts.encoding is None else tr(ENCODING_KEYS.get(facts.encoding, "encoding.other"),
                                                               name=facts.encoding),
            "lines": None if facts.lines is None else (
                locale.toString(facts.lines) + (" +" if facts.partial else "")),
        }
        for row_id, value in values.items():
            self.form.setRowVisible(self.form_values[row_id], value is not None)
            self.form_values[row_id].setText(value or "")
        if facts.focus_line is not None and facts.excerpt is not None:
            last = facts.excerpt_first + max(facts.excerpt.count("\n"), 0)
            self.excerpt_caption.setText(tr("project.preview.excerpt_at", first=locale.toString(facts.excerpt_first),
                                            last=locale.toString(last), line=locale.toString(facts.focus_line)))
        else:
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
    edit_requested = Signal(object)    # Path del script que se quiere editar como texto
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
        self._reveal_target: Path | None = None  # archivo revelado cuyas carpetas aún está listando el modelo
        self._reveal_waiting: set[str] = set()     # esas carpetas (``folder_key``)
        self._listed_folders: set[str] = set()     # carpetas que el modelo ya ha listado (``directoryLoaded``)
        self._revealing = False
        self._pending_selection: Path | None = None
        self._preview_path: Path | None = None  # lo que muestra la vista previa (archivo o carpeta)
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
        # Intro y doble clic llegan los dos por ``activated``, que es quien expande o contrae.
        self.tree.setExpandsOnDoubleClick(False)
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
        self.validation.validation_cancelled.connect(lambda: self.request_status("status.validation_cancelled"))
        self.validation.validation_failed.connect(
            lambda error: self.request_status("status.validation_failed", error=error))
        self.validation.busy_changed.connect(self._on_validation_busy)
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
        self.edit_button = QToolButton()
        self.edit_button.setObjectName("editScriptButton")
        self.edit_button.setIcon(make_icon("quill", "gold_light"))
        self.edit_button.setIconSize(QSize(16, 16))
        self.edit_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.edit_button.setVisible(False)
        self.edit_button.clicked.connect(self._request_edit)
        self.clausewitz_viewer.header.layout().addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignVCenter)
        # Al volver a la aplicación (p. ej. tras corregir el archivo en otro editor) se relee lo que se ve.
        QGuiApplication.instance().applicationStateChanged.connect(self._on_application_state)
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
        self._reveal_timeout = QTimer(self)
        self._reveal_timeout.setSingleShot(True)
        self._reveal_timeout.setInterval(REVEAL_TIMEOUT_MS)
        self._reveal_timeout.timeout.connect(self._settle_reveal)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(SELECTION_DELAY_MS)
        self._selection_timer.timeout.connect(self._show_pending_selection)

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
        self._retranslate_left_tabs()
        self._validate()
        self._refresh_explorer()
        self.request_status("status.mod_path_set" if self._mod_path else "status.mod_path_cleared")
        self.mod_path_changed.emit(self._mod_path)

    def set_explorer_root(self, which: str) -> None:
        """``"mod"`` o ``"game"``: qué carpeta muestra el explorador."""
        self.root_combo.setCurrentIndex(1 if which == "game" else 0)

    def set_preview_widget(self, widget: QWidget | None) -> None:
        """Muestra ``widget`` en el panel de vista previa; ``None`` vuelve a los metadatos.

        El widget anterior se retira del panel sin destruirlo. Un clic en el archivo seleccionado
        del explorador lo vuelve a mostrar.
        """
        self._preview_path = None  # ``_show_preview`` lo fija después de mostrar su visor
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

    def reload_preview_if_changed(self) -> bool:
        """Vuelve a leer el archivo (o la carpeta) de la vista previa si cambió en disco desde que se leyó;
        ``True`` si lo hace. Si no cambió no lee nada: solo consulta su fecha y su tamaño. Un archivo que
        no se pudo leer se reintenta siempre (``ClausewitzViewer.reload_if_changed``)."""
        widget = self.preview_stack.currentWidget()
        if widget is self.clausewitz_viewer:
            return self.clausewitz_viewer.reload_if_changed()
        if widget is self.image_viewer:
            return self.image_viewer.reload_if_changed()
        facts = self.preview.facts
        if widget is self.preview and facts is not None and facts.stamp != file_stamp(facts.path):
            self._show_preview(facts.path)
            return True
        return False

    def reveal_file(self, path: str | os.PathLike) -> bool:
        """Selecciona ``path`` en el explorador (expandiendo sus carpetas) si está bajo la raíz.

        Mientras el modelo lista esas carpetas, el archivo se mantiene centrado e ``is_busy()`` es ``True``.
        """
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
            self.model.fetchMore(parent)  # que se liste aunque la vista aún no se haya maquetado
            parent = parent.parent()
        # Hasta que el modelo liste las carpetas que llevan al archivo, cada fila nueva (y la ordenación
        # que hace después, en diferido) lo cambia de sitio: se vuelve a centrar hasta que estén todas.
        waiting, root_key = set(), folder_key(root)
        folder = target.parent
        while _is_under(folder, root):
            key = folder_key(folder)
            if key not in self._listed_folders:
                waiting.add(key)
            if key == root_key:
                break
            folder = folder.parent
        self._cancel_reveal()
        if waiting:
            self._reveal_target, self._reveal_waiting = target, waiting
            self._reveal_timeout.start()
        self._revealing = True  # se muestra en el acto, sin la espera de la navegación con teclado
        try:
            self.tree.setCurrentIndex(index)
        finally:
            self._revealing = False
        self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def open_file(self, path: str | os.PathLike, line: int | None = None, column: int | None = None,
                  tab: str | None = None) -> bool:
        """Abre ``path`` en el visor que le corresponda, en ``line`` si se indica.

        Lo selecciona también en el explorador cuando está bajo su raíz. Los CSV de
        ``localisation/`` se piden a la página de Localización (``csv_requested``).
        Devuelve ``False`` si el archivo no existe.
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

    def shown_location(self) -> tuple[Path, int | None] | None:
        """(archivo, línea con el cursor) de lo que muestra la vista previa: el script cargado o la ficha (con la
        línea marcada en su extracto, si se abrió en una); None si no hay archivo a la vista. Para las pruebas del
        criterio 7 de la iteración 3."""
        widget = self.preview_stack.currentWidget()
        if widget is self.clausewitz_viewer:
            load = self.clausewitz_viewer.current_load()
            return None if load is None else (load.path, self.clausewitz_viewer.code.current_line())
        if widget is self.preview and self.preview.facts is not None and not self.preview.facts.is_dir:
            return self.preview.facts.path, self.preview.shown_line()
        return None

    def validate_mod(self) -> bool:
        """Valida en segundo plano el mod (y su descriptor .mod); ``False`` si no hay mod válido."""
        self._validate()  # la carpeta y el descriptor pueden haber cambiado desde que se eligió el mod
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
        return (self._loading or self._reveal_target is not None or self._scroll_timer.isActive()
                or self._selection_timer.isActive()
                or self.clausewitz_viewer.is_busy() or self.image_viewer.is_busy() or self.validation.is_busy())

    def shutdown(self) -> None:
        self._selection_timer.stop()
        self.validation.cancel()
        self.clausewitz_viewer.clear()
        self.image_viewer.cancel()

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
        self.validate_button.setEnabled(self._can_validate() and not self.validation.is_busy())
        self.validation.set_run_enabled(self._can_validate())

    def _on_validation_busy(self, busy: bool) -> None:
        self._update_validate_button()
        self._retranslate_left_tabs()

    def _refresh_explorer(self) -> None:
        which = self.root_combo.currentData()
        root = self._mod_path if which == "mod" else self._game_path
        if root is None or not root.is_dir():
            self._explorer_root = None
            self._loading = False
            self._selection_timer.stop()
            self._cancel_reveal()
            show_in_stack(self.explorer_stack, self.explorer_empty)
            self.preview.show_facts(None)
            self.set_preview_widget(None)
            self._preview_path = None
            self._retranslate_explorer_empty()
            return
        if self._explorer_root is not None and same_folder(root, self._explorer_root):
            return
        self._explorer_root = root
        self._loading = True
        self._loading_timeout.start()
        # Nada queda resaltado en el explorador mientras la vista previa dice «Ningún archivo seleccionado».
        self._selection_timer.stop()
        self._cancel_reveal()
        self.tree.selectionModel().clear()
        source_root = self.fs.setRootPath(os.fspath(root))
        self.tree.setRootIndex(self.model.mapFromSource(source_root))
        show_in_stack(self.explorer_stack, self.tree)
        self.preview.show_facts(None)
        self.set_preview_widget(None)
        self._preview_path = self._last_emitted = None

    def _on_directory_loaded(self, directory: str) -> None:
        key = folder_key(directory)
        self._listed_folders.add(key)
        if self._explorer_root is not None and key == folder_key(self._explorer_root):
            self._finish_loading()
        if self._reveal_target is not None and key in self._reveal_waiting:
            self._reveal_waiting.discard(key)
            if self._reveal_waiting:
                self._scroll_timer.start()
            else:
                self._settle_reveal()

    def _settle_reveal(self) -> None:
        """Ya están listadas las carpetas del archivo revelado (o venció el plazo): se ordena ya lo que el
        modelo ordenaría en diferido (con la máquina cargada, quizá cuando ya nadie lo volviera a centrar)
        y se centra el archivo en su sitio definitivo. Durante ``RESCROLL_SECONDS`` cada cambio de
        disposición (otra carpeta que termina de cargar por encima) lo vuelve a centrar."""
        self._cancel_reveal()
        header = self.tree.header()
        self.model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())  # no hace nada si ya lo está
        self._rescroll_until = time.monotonic() + RESCROLL_SECONDS
        self._scroll_timer.start()

    def _cancel_reveal(self) -> None:
        self._reveal_timeout.stop()
        self._reveal_target = None
        self._reveal_waiting = set()

    def _rescroll_if_pending(self, *args) -> None:
        if self._reveal_target is not None or time.monotonic() < self._rescroll_until:
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
            self._cancel_reveal()  # el usuario eligió otra cosa: ya no hay que perseguir el archivo revelado
        if self._revealing or QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._select(path)
        else:
            self._pending_selection = path
            self._selection_timer.start()

    def _show_pending_selection(self) -> None:
        current = self.tree.currentIndex()
        if self._pending_selection is not None and current.isValid() \
                and self.model.file_path(current) == self._pending_selection:
            self._select(self._pending_selection)
        self._pending_selection = None

    def _select(self, path: Path) -> None:
        """Muestra en la vista previa ``path``, seleccionado en el explorador."""
        self._selection_timer.stop()
        self._pending_selection = None
        self._show_preview(path)
        if path != self._last_emitted:
            self._last_emitted = path
            self.request_status("status.file_selected", path=relative_text(path, self._explorer_root))
            if not path.is_dir():
                self.file_activated.emit(path)

    def _show_preview(self, path: Path, *, line: int | None = None, column: int | None = None,
                      tab: str | None = None) -> None:
        kind = None if path.is_dir() else preview_kind(path)
        self.edit_button.setVisible(kind == PREVIEW_CLAUSEWITZ)
        # Un análisis que ya no se va a ver deja libre su hilo, y también el JSON a medio generar. Si el
        # visor ya tiene su archivo cargado, lo conserva para no repetir el análisis al volver.
        viewer = self.clausewitz_viewer
        if kind != PREVIEW_CLAUSEWITZ:
            if viewer.is_busy() and viewer.current_load() is None:
                viewer.clear()
            else:
                viewer.cancel()
        if kind != PREVIEW_IMAGE:
            self.image_viewer.cancel()
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
            try:
                facts = gather_facts(path, self._explorer_root, line=line)
            except OSError:
                facts = None
            self.set_preview_widget(None)
            self.preview.show_facts(facts)   # ya a la vista: el extracto se cuelga y va a su línea en el acto
        self._preview_path = path

    def _request_edit(self) -> None:
        path = self._preview_path
        if path is not None and not path.is_dir() and preview_kind(path) == PREVIEW_CLAUSEWITZ:
            self.edit_requested.emit(path)

    def _on_application_state(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.reload_preview_if_changed()

    def _on_viewer_loaded(self, path: Path) -> None:
        if self.preview_stack.currentWidget() is not self.clausewitz_viewer:
            return  # terminó de analizarse cuando ya se mostraba otra cosa
        load = self.clausewitz_viewer.current_load()
        if load is not None and load.path == path:
            if load.result.encoding in GAME_UNREADABLE:
                self.request_status("status.file_unreadable", name=path.name)
                return
            errors = syntax_error_count(load.result.errors)
            if errors:
                self.request_status("status.file_errors_one" if errors == 1 else "status.file_errors",
                                    name=path.name, count=errors)

    def _csv_at(self, index: QModelIndex) -> Path | None:
        if not index.isValid() or self.fs.isDir(self.model.mapToSource(index)):
            return None
        path = self.model.file_path(index)
        return path if preview_kind(path) == PREVIEW_CSV else None

    def _on_clicked(self, index: QModelIndex) -> None:
        # Con la activación de un solo clic (p. ej. KDE) ese mismo clic emite también ``activated``.
        if not self.tree.style().styleHint(QStyle.StyleHint.SH_ItemView_ActivateItemOnSingleClick, None, self.tree):
            self._open_index(index)

    def _on_activated(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        index = index.siblingAtColumn(0)  # isExpanded solo responde por la primera columna
        if self.fs.isDir(self.model.mapToSource(index)):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
        self._open_index(index)

    def _open_index(self, index: QModelIndex) -> None:
        """Clic, doble clic o Intro: los CSV de localización van a su página; el resto se vuelve a mostrar si la
        vista previa enseñaba otra cosa (un archivo abierto desde fuera, otra raíz, otro widget…) y, si ya lo
        mostraba, se relee si cambió en disco (p. ej. corregido en otro editor)."""
        if not index.isValid():
            return
        csv = self._csv_at(index)
        if csv is not None:
            self.csv_requested.emit(csv, None)
            return
        path = self.model.file_path(index)
        if path != self._preview_path:
            self._select(path)
        else:
            self.reload_preview_if_changed()

    def _on_issue_activated(self, row) -> None:
        if row.path is not None and not self.open_file(row.path, line=row.line, column=row.column):
            self.request_status("status.file_missing", name=row.relative or row.path.name)

    def _on_validation_finished(self, report) -> None:
        self._retranslate_left_tabs()
        self.clausewitz_viewer.reload_if_changed()  # que el visor no contradiga a la validación
        # Invocables: la barra de estado los vuelve a formatear si cambia el idioma.
        self.request_status("status.validation_done", files=lambda: translator().locale().toString(report.files),
                            errors=len(report.files_with()), seconds=lambda: format_seconds(report.elapsed))
        self.validation_finished.emit(report)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.tree.indexAt(pos)
        if index.isValid():
            menu = self.context_menu(self.model.file_path(index))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            menu.deleteLater()

    def context_menu(self, path: Path) -> QMenu:
        """Menú contextual del explorador para ``path``: copiar la ruta y abrir la carpeta que lo contiene."""
        menu = QMenu(self)
        copy = QAction(make_icon("copy", "cream"), tr("project.explorer.copy_path"), menu)
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(os.fspath(path)))
        reveal = QAction(make_icon("external", "cream"), tr("project.explorer.open_folder"), menu)
        reveal.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(path.parent))))
        menu.addAction(copy)
        menu.addAction(reveal)
        return menu

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
        self.edit_button.setText(tr("editor.edit"))
        self.edit_button.setToolTip(tr("editor.edit_tooltip"))
        self._retranslate_left_tabs()
        self.model.retranslate()
        self._retranslate_explorer_empty()
        self.clausewitz_viewer.retranslate()
        self.image_viewer.retranslate()
        self.validation.retranslate()
        self.preview.retranslate()
