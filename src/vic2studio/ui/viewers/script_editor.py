"""Editor de texto de los scripts Clausewitz de Proyecto › Archivos.

El documento del ``Workspace`` es la única verdad (I7): aquí no se lee ni se
escribe el disco. Cada pausa al teclear aplica el texto en una transacción con
``merge_key`` (un Ctrl+Z quita lo tecleado de una vez) y ``splice_text`` conserva
byte a byte las líneas que no se tocaron, con sus saltos mezclados (I3).

Deshacer, rehacer y los cambios de fuera llegan por ``Session``: el widget
recarga el documento abierto y conserva línea, columna y posición del scroll.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QKeySequence, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

from ...core.clausewitz import Severity
from ...core.encoding import (
    UnencodableTextError,
    decode_bytes,
    detect_newline,
    display_name,
    encode_text,
    match_bom,
    split_bom,
)
from ...core.project.codecs import codec_for, kind_for
from ...core.project.model import (
    READ_ONLY_PARSE_ERRORS,
    READ_ONLY_UNREADABLE,
    DocKind,
)
from ...core.project.workspace import ReadOnlyDocumentError
from ...core.textsplice import normalize_newlines, splice_text
from ...core.vfs.model import LayerKind
from ...core.vfs.paths import VPath
from ...i18n import N_, language, tr, translator
from .. import theme
from ..widgets import mark_data
from .diagnostics import DiagnosticRow

MAX_EDIT_BYTES = 8 * 2**20
COMMIT_DELAY_MS = 500
TAB_WIDTH = 4
# Motivos de solo lectura que sí permiten sustituir el texto entero (D17).
TEXT_EDITABLE = frozenset({None, READ_ONLY_PARSE_ERRORS, READ_ONLY_UNREADABLE})


class ScriptEditor(QWidget):
    """Editor de un script; ``open_document`` carga del ``Workspace`` y ``commit_pending`` aplica lo tecleado."""

    back_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._rel: VPath | None = None
        self._original = ""
        self._view = ""
        self._encoding = "cp1252"
        self._newline = "\n"
        self._read_only = True
        self._applying = False
        self._loading = False
        self._last_applied: bytes | None = None
        self._first_error = None
        self._error_count = 0
        self._layer: tuple[str, dict] | None = None
        self._status: tuple[str, dict] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        bar = QWidget()
        bar.setObjectName("scriptEditorBar")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(6, 4, 6, 0)
        bar_layout.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.name_label = mark_data(QLabel())
        self.name_label.setObjectName("scriptEditorName")
        self.name_label.setProperty("role", "title")
        self.name_label.setFont(theme.font("body_bold", 12.5))
        title_row.addWidget(self.name_label, 1)
        self.back_button = QToolButton()
        self.back_button.setObjectName("scriptEditorBack")
        self.back_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.back_button.clicked.connect(self.back_requested)
        title_row.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.addLayout(title_row)
        self.layer_label = QLabel()
        self.layer_label.setObjectName("scriptEditorLayer")
        self.layer_label.setProperty("role", "caption")
        self.layer_label.setWordWrap(True)
        bar_layout.addWidget(self.layer_label)
        self.syntax_label = QLabel()
        self.syntax_label.setObjectName("scriptEditorSyntax")
        self.syntax_label.setProperty("role", "caption")
        self.syntax_label.setWordWrap(True)
        bar_layout.addWidget(self.syntax_label)
        self.status_label = QLabel()
        self.status_label.setObjectName("scriptEditorStatus")
        self.status_label.setProperty("role", "caption")
        self.status_label.setWordWrap(True)
        bar_layout.addWidget(self.status_label)
        layout.addWidget(bar)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("scriptEditorText")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(theme.font("mono"))
        self.editor.setTabStopDistance(QFontMetricsF(self.editor.font()).horizontalAdvance(" ") * TAB_WIDTH)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setReadOnly(True)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.installEventFilter(self)
        layout.addWidget(self.editor, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COMMIT_DELAY_MS)
        self._timer.timeout.connect(self._commit)

        session.documentsChanged.connect(self._on_documents_changed)
        session.projectClosed.connect(self._on_project_closed)
        session.projectOpened.connect(self._on_project_opened)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    # --- API pública ---------------------------------------------------------------------

    def open_document(self, rel) -> bool:
        """Abre ``rel`` desde el ``Workspace``; False si no se puede leer (y lo explica en la barra)."""
        self._timer.stop()
        if self._rel is not None:
            self._commit()  # no perder lo tecleado del documento anterior
        try:
            rel = VPath.of(rel)
        except (TypeError, ValueError) as exc:
            self._fail(N_("editor.open_failed"), reason=str(exc))
            return False
        project = self.session.project
        if project is None:
            self._fail(N_("editor.no_project"))
            return False
        try:
            handle, data = self._read(project, rel)
        except FileNotFoundError:
            self._fail(N_("editor.open_failed"), reason=tr("file_error.not_found"))
            return False
        except PermissionError:
            self._fail(N_("editor.open_failed"), reason=tr("file_error.permission"))
            return False
        except OSError as exc:
            self._fail(N_("editor.open_failed"), reason=tr("file_error.generic", detail=str(exc)))
            return False
        try:
            decoded = decode_bytes(data, getattr(handle.model, "encoding", None))
            text, encoding = split_bom(decoded.text, match_bom(data, decoded.encoding))
        except (LookupError, UnicodeError) as exc:
            self._fail(N_("editor.open_failed"), reason=str(exc))
            return False
        self._load(handle, rel, data, text, encoding)
        self.editor.setFocus()
        return True

    def current_rel(self) -> VPath | None:
        return self._rel

    def is_editable(self) -> bool:
        return self._rel is not None and not self._read_only

    def commit_pending(self) -> bool:
        """Aplica ya lo tecleado sin esperar al temporizador (Ctrl+S, deshacer, cerrar, volver)."""
        self._timer.stop()
        if not self.is_editable():
            return False
        return self._commit()

    def retranslate(self) -> None:
        self.name_label.setText("" if self._rel is None else self._rel.name)
        self.name_label.setToolTip("" if self._rel is None else str(self._rel))
        self.back_button.setText(tr("editor.back"))
        self.back_button.setToolTip(tr("editor.back_tooltip"))
        if self._layer is None:
            self.layer_label.clear()
            self.layer_label.setVisible(False)
        else:
            key, fmt = self._layer
            self.layer_label.setText(tr(key, **fmt))
            self.layer_label.setVisible(True)
        self._render_syntax()
        self._render_status()

    # --- carga ---------------------------------------------------------------------------

    @staticmethod
    def _read(project, rel: VPath):
        """(handle, bytes) del documento efectivo, también si está borrado sin guardar."""
        handle = project.ws.peek(rel)
        if handle is not None and handle.deleted:
            return handle, codec_for(handle.kind).snapshot(handle.model)
        handle = project.ws.open(rel)
        return handle, codec_for(handle.kind).snapshot(handle.model)

    def _load(self, handle, rel: VPath, data: bytes, text: str, encoding: str, *,
              cursor: tuple[int, int, int] | None = None) -> None:
        self._rel = rel
        self._original = text
        self._encoding = encoding
        self._newline = detect_newline(text)
        self._view = normalize_newlines(text)
        self._last_applied = data
        self._layer = self._layer_note(handle)
        self._read_only, self._status = self._read_only_state(handle, rel, data, text)
        self._update_syntax(handle)
        self._fill_editor(self._view, cursor)
        self.retranslate()
        self.editor.setReadOnly(self._read_only)

    def _read_only_state(self, handle, rel: VPath, data: bytes, text: str):
        """(solo_lectura, (clave, formato) del motivo); editable si el motivo no está en ``TEXT_EDITABLE``."""
        if self.session.is_read_only():
            return True, (N_("editor.read_only_project"), {})
        if kind_for(rel) is not DocKind.CLAUSEWITZ:
            return True, (N_("editor.read_only_kind"), {})
        if handle.deleted:
            return True, (N_("editor.read_only_deleted"), {})
        reason = handle.read_only_reason
        if reason not in TEXT_EDITABLE:
            key = N_("editor.read_only_binary") if reason == "binary" else (
                N_("editor.read_only_locked") if reason == "locked" else N_("editor.read_only_reason"))
            return True, (key, {})
        if "\x00" in text:
            return True, (N_("editor.read_only_nul"), {})
        if len(data) > MAX_EDIT_BYTES:
            return True, (N_("editor.read_only_too_large"), {})
        return False, None

    def _layer_note(self, handle) -> tuple[str, dict] | None:
        origin = handle.origin
        if origin is None or origin.layer.kind is not LayerKind.MOD:
            return (N_("editor.layer_game"), {})
        project = self.session.project
        if project is not None and any(entry.layer.kind is LayerKind.GAME
                                       for entry in project.vfs.stack(handle.rel)):
            return (N_("editor.layer_mod_copy"), {})
        return None

    def _fill_editor(self, text: str, cursor: tuple[int, int, int] | None = None) -> None:
        self._loading = True
        try:
            self.editor.setPlainText(text)
            if cursor is not None:
                line, column, scroll = cursor
                block = self.editor.document().findBlockByNumber(min(line, max(0, self.editor.blockCount() - 1)))
                position = block.position() + min(column, max(0, block.length() - 1))
                text_cursor = QTextCursor(block)
                text_cursor.setPosition(position)
                self.editor.setTextCursor(text_cursor)
                self.editor.verticalScrollBar().setValue(scroll)
        finally:
            self._loading = False
        self.editor.document().setModified(False)

    def _update_syntax(self, handle) -> None:
        errors = [diag for diag in handle.diagnostics if diag.severity is Severity.ERROR]
        self._error_count = len(errors)
        self._first_error = DiagnosticRow.of(errors[0]) if errors else None

    def _render_syntax(self) -> None:
        if self._rel is None:
            self.syntax_label.clear()
            self.syntax_label.setVisible(False)
            return
        if not self._first_error:
            self.syntax_label.setText(tr("editor.syntax_clean"))
        else:
            self.syntax_label.setText(tr(
                "editor.syntax_errors_one" if self._error_count == 1 else "editor.syntax_errors",
                count=self._error_count,
                line=self._first_error.line or 0,
                message=self._first_error.message(language()),
            ))
        self.syntax_label.setVisible(True)

    def _render_status(self) -> None:
        if self._status is None:
            self.status_label.clear()
            self.status_label.setVisible(False)
            return
        key, fmt = self._status
        self.status_label.setText(tr(key, **fmt))
        self.status_label.setVisible(True)

    def _set_status(self, key: str, **fmt) -> None:
        self._status = (key, fmt)
        self._render_status()

    def _fail(self, key: str, **fmt) -> None:
        self._timer.stop()
        self._rel = None
        self._original = ""
        self._view = ""
        self._read_only = True
        self._last_applied = None
        self._layer = None
        self._first_error = None
        self._error_count = 0
        self._loading = True
        try:
            self.editor.clear()
        finally:
            self._loading = False
        self.editor.setReadOnly(True)
        self._set_status(key, **fmt)
        self.retranslate()

    # --- edición -------------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        if not self._loading and not self._read_only and self._rel is not None:
            self._timer.start()

    def _commit(self) -> bool:
        if self._rel is None or self._read_only:
            return False
        new_view = self.editor.document().toRawText().replace("\u2029", "\n").replace("\u2028", "\n")
        if new_view == self._view:
            return False
        try:
            new_text = splice_text(self._original, self._view, new_view, self._newline)
        except ValueError:
            self._set_status(N_("editor.apply_failed"))
            return False
        if normalize_newlines(new_text) != new_view:
            self._set_status(N_("editor.apply_failed"))
            return False
        try:
            data = encode_text(new_text, self._encoding)
        except UnencodableTextError as exc:
            _, line, column, char = exc.problems[0]
            self._set_status(N_("editor.unencodable"), char=char, encoding=display_name(self._encoding),
                             line=line, column=column)
            return False
        project = self.session.project
        if project is None:
            self._set_status(N_("editor.no_project"))
            return False
        rel = self._rel
        self._applying = True
        try:
            with self.session.edit(N_("editor.undo_edit"), merge_key=f"editor.{rel.key}", file=rel.name):
                handle = project.ws.open(rel)
                project.ws.replace_text(handle, data)
        except ReadOnlyDocumentError:
            self._set_status(N_("editor.read_only_project"))
            return False
        except FileNotFoundError:
            self._set_status(N_("editor.read_only_deleted"))
            return False
        except OSError:
            self._set_status(N_("editor.apply_failed"))
            return False
        finally:
            self._applying = False
        self._original = new_text
        self._view = new_view
        self._last_applied = data
        self._status = None
        self._update_syntax(handle)
        self._render_syntax()
        self._render_status()
        return True

    def _on_documents_changed(self, rels) -> None:
        if self._rel is None or self._applying:
            return
        if self._rel.key not in {getattr(rel, "key", rel) for rel in rels}:
            return
        self._timer.stop()
        self._reload()

    def _reload(self) -> None:
        rel = self._rel
        project = self.session.project
        if rel is None or project is None:
            return
        cursor = self.editor.textCursor()
        block = cursor.block()
        position = (block.blockNumber() if block.isValid() else 0, cursor.positionInBlock(),
                    self.editor.verticalScrollBar().value())
        try:
            handle, data = self._read(project, rel)
            if data == self._last_applied:
                return
            decoded = decode_bytes(data, getattr(handle.model, "encoding", None))
            text, encoding = split_bom(decoded.text, match_bom(data, decoded.encoding))
        except (OSError, LookupError, UnicodeError):
            self._set_status(N_("editor.open_failed"), reason=tr("file_error.not_found"))
            return
        self._load(handle, rel, data, text, encoding, cursor=position)

    def _on_project_opened(self, project) -> None:
        self._clear_document(closed=False)

    def _on_project_closed(self) -> None:
        self._clear_document(closed=True)

    def _clear_document(self, *, closed: bool) -> None:
        self._timer.stop()
        self._rel = None
        self._original = ""
        self._view = ""
        self._read_only = True
        self._last_applied = None
        self._first_error = None
        self._error_count = 0
        self._layer = None
        self._status = (N_("editor.no_project"), {}) if closed else None
        self._loading = True
        try:
            self.editor.clear()
        finally:
            self._loading = False
        self.editor.setReadOnly(True)
        self.retranslate()

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    # --- atajos --------------------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        if watched is self.editor:
            if event.type() == QEvent.Type.ShortcutOverride:
                if event.matches(QKeySequence.StandardKey.Undo) or event.matches(QKeySequence.StandardKey.Redo):
                    event.ignore()  # el atajo es de la ventana (deshacer de la aplicación), no del widget
                    return False
            elif event.type() == QEvent.Type.KeyPress:
                # Si el evento llega sin pasar por el mapa de atajos (pruebas con QTest, plataformas que lo
                # entregan directamente), se ejecuta la acción de la ventana: el deshacer sigue siendo el de la
                # aplicación, no el del QPlainTextEdit (que además está desactivado).
                if event.matches(QKeySequence.StandardKey.Undo):
                    return self._trigger_window_action("undo_action", "undo")
                if event.matches(QKeySequence.StandardKey.Redo):
                    return self._trigger_window_action("redo_action", "redo")
        return super().eventFilter(watched, event)

    def _trigger_window_action(self, action_name: str, method_name: str) -> bool:
        window = self.window()
        action = getattr(window, action_name, None)
        if action is not None and action.isEnabled():
            action.trigger()
            return True
        method = getattr(window, method_name, None)
        if callable(method):
            method()
            return True
        return False
