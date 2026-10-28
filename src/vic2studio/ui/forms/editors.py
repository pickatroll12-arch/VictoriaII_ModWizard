"""Editores de campo del formulario generado: uno por ``ValueType.widget`` (wizard §13.6).

``FieldEditor`` es la base: ``set_value(valor, estado)`` lo enseña sin confirmar nada, ``value()`` lo lee y
``value_committed(object)`` avisa cuando el usuario confirma (Intro, perder el foco, elegir, marcar). ``None``
es «sin valor»: el formulario quita la entrada y el juego usa su valor por defecto, que el editor muestra en
gris (``set_default``). ``EDITORS`` es el registro ``widget → clase``; ``editor_for`` elige el de un tipo.

Los números se escriben en una línea con validador (no en una ``QSpinBox``): así «vacío» es un estado real, y
teclear confirma tras una pausa con el mismo ``merge_key`` que el formulario funde en un solo paso de deshacer.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QLocale, QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QWidget

from ...i18n import tr, translator
from ..pickers import ColorField, DateEdit, NameListEditor, SpriteFramePicker, SymbolPicker
from ..widgets import mark_data

TYPING_COMMIT_MS = 600


class FieldState(NamedTuple):
    """Estado de un campo para pintarlo: origen (``vanilla``, ``mod``, ``new``, ``default``), fecha desde la que
    vale (historia, iteración 5) y sus problemas."""

    origin: str = "mod"
    since: object = None
    problems: tuple = ()


class FieldEditor(QWidget):
    """Base de los editores. Las subclases implementan ``_build``, ``value`` y ``_show``."""

    value_committed = Signal(object)

    def __init__(self, value_type, *, session=None, kind: str = "", key: str = "", ui: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.value_type = value_type
        self.session = session
        self.kind = kind
        self.key = key
        self.ui = ui
        self.state = FieldState()
        self.default = None
        self._last = None
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self._build()
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    # --- API --------------------------------------------------------------------------------------

    def set_value(self, value, state: FieldState | None = None) -> None:
        """Enseña ``value`` (None: sin valor) sin emitir ``value_committed``."""
        self._last = value
        self.state = state or FieldState()
        self._show(value)
        self.setProperty("problem", bool(self.state.problems))

    def set_default(self, default) -> None:
        """El valor que asume el juego si el campo falta: se muestra en gris (no se escribe)."""
        self.default = default
        self.retranslate()

    def value(self):
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        for child in self.findChildren(QWidget):
            child.setEnabled(not read_only)

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        """Textos de la interfaz del editor."""

    def commit_pending(self) -> None:
        """Confirma lo tecleado sin esperar (Ctrl+S, cambiar de registro)."""
        self._commit()

    # --- interno ----------------------------------------------------------------------------------

    def _build(self) -> None:
        raise NotImplementedError

    def _show(self, value) -> None:
        raise NotImplementedError

    def _commit(self, value=..., *, force: bool = False) -> None:
        value = self.value() if value is ... else value
        if value == self._last and not force:
            return
        self._last = value
        self.value_committed.emit(value)


class _TextLike(FieldEditor):
    """Una línea: confirma con Intro, al perder el foco o tras una pausa al teclear."""

    def _build(self) -> None:
        self.edit = mark_data(QLineEdit())
        self.edit.setObjectName(f"field_{self.key}")
        self.edit.editingFinished.connect(self._commit)
        self.edit.textEdited.connect(lambda _text: self._typing.start())
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_COMMIT_MS)
        self._typing.timeout.connect(self._commit)
        self._row.addWidget(self.edit, 1)

    def _parse(self, text: str):
        return text

    def _render(self, value) -> str:
        return "" if value is None else str(value)

    def value(self):
        text = self.edit.text().strip()
        if not text:
            return None
        return self._parse(text)

    def _show(self, value) -> None:
        with QSignalBlocker(self.edit):
            self.edit.setText(self._render(value))

    def retranslate(self) -> None:
        if self.default is not None:
            self.edit.setPlaceholderText(tr("forms.default_value", value=self._render(self.default)))
        else:
            self.edit.setPlaceholderText(tr("forms.no_value"))

    def _commit(self, value=..., *, force: bool = False) -> None:
        self._typing.stop()
        try:
            value = self.value() if value is ... else value
        except ValueError:
            self.edit.setProperty("invalid", True)
            return
        self.edit.setProperty("invalid", False)
        super()._commit(value, force=force)


class LineEditor(_TextLike):
    """``word``, ``text``, ``lockey``, ``picture`` y ``path``: el texto tal cual."""


class SpinEditor(_TextLike):
    """Enteros, con las cotas del ``Int`` si son números."""

    def _build(self) -> None:
        super()._build()
        low = self.value_type.min if isinstance(getattr(self.value_type, "min", None), int) else -2**31
        high = self.value_type.max if isinstance(getattr(self.value_type, "max", None), int) else 2**31 - 1
        self.edit.setValidator(QIntValidator(low, high, self.edit))

    def _parse(self, text: str):
        return int(text)


class DoubleSpinEditor(_TextLike):
    """Decimales; el punto como separador (el del juego), también si se teclea una coma."""

    def _build(self) -> None:
        super()._build()
        validator = QDoubleValidator(self.edit)
        validator.setLocale(QLocale.c())
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.edit.setValidator(validator)
        self.edit.textEdited.connect(self._dot)

    def _dot(self, text: str) -> None:
        if "," in text:
            with QSignalBlocker(self.edit):
                self.edit.setText(text.replace(",", "."))

    def _parse(self, text: str):
        return float(text)

    def _render(self, value) -> str:
        if value is None:
            return ""
        return f"{value:g}" if isinstance(value, float) else str(value)


class TriStateCheck(FieldEditor):
    """Sí / no / sin valor (casilla de tres estados): sin marcar del todo es el valor por defecto del juego."""

    def _build(self) -> None:
        self.check = QCheckBox()
        self.check.setObjectName(f"field_{self.key}")
        self.check.setTristate(True)
        self.check.stateChanged.connect(lambda _state: self._commit())
        self._row.addWidget(self.check)
        self._row.addStretch(1)

    def value(self):
        state = self.check.checkState()
        from PySide6.QtCore import Qt

        if state == Qt.CheckState.PartiallyChecked:
            return None
        return state == Qt.CheckState.Checked

    def _show(self, value) -> None:
        from PySide6.QtCore import Qt

        with QSignalBlocker(self.check):
            self.check.setCheckState(Qt.CheckState.PartiallyChecked if value is None else (
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked))
        self.retranslate()

    def retranslate(self) -> None:
        value = self.value()
        if value is None:
            default = self.default
            self.check.setText(tr("forms.bool_default", value=tr("forms.yes") if default else tr("forms.no"))
                               if default is not None else tr("forms.bool_unset"))
        else:
            self.check.setText(tr("forms.yes") if value else tr("forms.no"))

    def _commit(self, value=..., *, force: bool = False) -> None:
        self.retranslate()
        super()._commit(value, force=force)


class ComboEditor(FieldEditor):
    """Valores fijos (``Enum``): «sin valor» y cada valor con su etiqueta del esquema."""

    def _build(self) -> None:
        self.combo = QComboBox()
        self.combo.setObjectName(f"field_{self.key}")
        self.combo.activated.connect(lambda _index: self._commit())
        self._row.addWidget(self.combo, 1)

    def _label(self, value: str) -> str:
        from ...core.schema.fields import field_text_key

        snake = field_text_key(self.kind, self.key).rsplit(".", 1)[-1]
        key = f"schema.{self.kind}.enum.{snake}.{value}"
        if key not in translator().catalog():
            return value
        text = tr(key)
        return f"{text} ({value})" if text != value else value

    def retranslate(self) -> None:
        current = self.value()
        with QSignalBlocker(self.combo):
            self.combo.clear()
            self.combo.addItem(tr("forms.no_value"), None)
            for value in getattr(self.value_type, "values", ()):
                self.combo.addItem(self._label(value), value)
            self._show(current)

    def value(self):
        return self.combo.currentData()

    def _show(self, value) -> None:
        index = self.combo.findData(value)
        with QSignalBlocker(self.combo):
            self.combo.setCurrentIndex(max(index, 0))


class _Wrapped(FieldEditor):
    """Editor que envuelve un selector de ``ui/pickers`` (con su propio ``value_committed``)."""

    def _picker(self):
        raise NotImplementedError

    def _build(self) -> None:
        self.picker = self._picker()
        self.picker.value_committed.connect(lambda value: self._commit(value))
        self._row.addWidget(self.picker, 1)

    def value(self):
        return self.picker.value()

    def _show(self, value) -> None:
        self.picker.set_value(value)

    def commit_pending(self) -> None:
        pending = getattr(self.picker, "commit_pending", None)
        if pending is not None:
            pending()


class DateEditor(_Wrapped):
    def _picker(self):
        dates = []
        index = getattr(self.session, "index", None)
        if index is not None:
            for symbol in index.symbols("bookmark"):
                date = (getattr(symbol, "attrs", None) or {}).get("date")
                parsed = DateEdit.parse(str(date)) if date else None
                if parsed is not None:
                    dates.append(parsed)
        return DateEdit(dates)


class RefPicker(_Wrapped):
    def _picker(self):
        return SymbolPicker(self.session, self.value_type.kind, allow_new=self.value_type.allow_new)


class ColorEditor(_Wrapped):
    def _picker(self):
        return ColorField()


class ChipsEditor(_Wrapped):
    """Listas: los nombres de una cultura con ``NameListEditor``; el resto, valores separados por espacios."""

    def _picker(self):
        if self.ui == "names":
            return NameListEditor()
        return _SpaceList()


class SpriteEditor(_Wrapped):
    def _picker(self):
        frames = None
        frames_of = getattr(self.value_type, "frames", None)
        if frames_of is not None and getattr(self.session, "entities", None) is not None:
            try:
                frames = frames_of(self.session.entities.check_context())
            except Exception:  # noqa: BLE001 - sin índice no hay cuenta
                frames = None
        return SpriteFramePicker(frames)


class _SpaceList(QWidget):
    """Lista corta en una línea: ``1 2 3``."""

    value_committed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = mark_data(QLineEdit())
        self.edit.editingFinished.connect(lambda: self.value_committed.emit(self.value()))
        row.addWidget(self.edit)

    def value(self):
        return self.edit.text().split() or None

    def set_value(self, value) -> None:
        with QSignalBlocker(self.edit):
            self.edit.setText(" ".join(str(item) for item in (value or [])))


class CodeOnlyEditor(FieldEditor):
    """Bloques de guion y opacos: se editan como código (botón que abre la pestaña Código en su línea)."""

    code_requested = Signal(str)

    def _build(self) -> None:
        self.button = QPushButton()
        self.button.setObjectName(f"field_{self.key}")
        self.button.clicked.connect(lambda: self.code_requested.emit(self.key))
        self._row.addWidget(self.button)
        self._row.addStretch(1)

    def value(self):
        return self._last

    def _show(self, value) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.button.setText(tr("forms.edit_as_code") if self._last is not None else tr("forms.add_as_code"))


EDITORS: dict[str, type[FieldEditor]] = {
    "int": SpinEditor, "float": DoubleSpinEditor, "bool": TriStateCheck, "date": DateEditor, "word": LineEditor,
    "text": LineEditor, "enum": ComboEditor, "ref": RefPicker, "color": ColorEditor, "list": ChipsEditor,
    "path": LineEditor, "lockey": LineEditor, "sprite": SpriteEditor, "picture": LineEditor,
}


def editor_for(value_type, **kwargs) -> FieldEditor:
    """El editor del ``widget`` de ``value_type`` (``LineEditor`` si no hay uno propio)."""
    return EDITORS.get(getattr(value_type, "widget", "text"), LineEditor)(value_type, **kwargs)
