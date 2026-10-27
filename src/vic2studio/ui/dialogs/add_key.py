"""«Añadir clave» (sala Textos): una clave nueva con sus textos, en el archivo del área (wizard §8).

Pide la clave, el área (``countries``, ``events``… o ``overrides``) y los textos en
inglés y español (y en francés y alemán si se quiere). Dice en qué archivo irá
(``LocSync.target_file``) y no deja aceptar mientras la clave no valga: vacía, con
espacios, con «;», que empiece por «#» o que ya exista (en ese caso dice dónde). Los
textos tampoco pueden llevar «;» ni saltos de línea, y ni la clave ni los textos un
carácter que no quepa en Windows-1252 («Łódź»: el juego lee los CSV en cp1252 y
``LocSync.ensure`` lo rechazaría después de cerrar el diálogo, perdiendo lo tecleado).
El motivo sale en el idioma de la interfaz. Solo consulta ``LocSync``: crear la clave lo
hace quien abre el diálogo, dentro de una transacción.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.csvloc import InvalidFieldError
from ...core.csvloc.model import check_key, check_text
from ...core.encoding import GAME_ENCODING, UnencodableTextError, encode_text
from ...core.locsync import AREAS
from ...i18n import N_, tr
from .. import theme
from ..viewers.common import core_language
from ..widgets import StatusBadge, mark_data

LANGUAGES = (("en", "English"), ("es", "Español"), ("fr", "Français"), ("de", "Deutsch"))
AREA_KEYS = {area: f"texts.area.{area}" for area in AREAS}
DEFAULT_AREA = "misc"
# Las claves de las áreas, para la búsqueda estática de claves usadas (``AREA_KEYS`` se construye con f-string).
_AREA_LABELS = (N_("texts.area.countries"), N_("texts.area.events"), N_("texts.area.decisions"),
                N_("texts.area.cb"), N_("texts.area.governments"), N_("texts.area.units"),
                N_("texts.area.cultures"), N_("texts.area.map"), N_("texts.area.misc"), N_("texts.area.overrides"))


def unencodable_char(text: str) -> str | None:
    """El primer carácter de ``text`` que no cabe en la codificación del juego (cp1252), o None."""
    try:
        encode_text(text, GAME_ENCODING)
    except UnencodableTextError as exc:
        return exc.problems[0][3]
    return None


class AddKeyDialog(QDialog):
    """``values()`` da ``(clave, área, {idioma: texto})`` tras aceptar (solo los textos no vacíos)."""

    def __init__(self, locsync, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("addKeyDialog")
        self.locsync = locsync
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        layout.addWidget(self.title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        form = QFormLayout()
        form.setSpacing(8)
        self.key_label = QLabel()
        self.key_edit = mark_data(QLineEdit())
        self.key_edit.setObjectName("addKeyName")
        self.key_edit.textChanged.connect(self._validate)
        form.addRow(self.key_label, self.key_edit)
        self.area_label = QLabel()
        self.area_combo = QComboBox()
        self.area_combo.setObjectName("addKeyArea")
        for area in AREAS:
            self.area_combo.addItem("", area)
        self.area_combo.setCurrentIndex(AREAS.index(DEFAULT_AREA))
        self.area_combo.currentIndexChanged.connect(self._validate)
        form.addRow(self.area_label, self.area_combo)
        self.text_edits: dict[str, QLineEdit] = {}
        self.text_labels: dict[str, QLabel] = {}
        for code, endonym in LANGUAGES:
            label = QLabel(endonym)
            mark_data(label)
            edit = mark_data(QLineEdit())
            edit.setObjectName(f"addKeyText_{code}")
            edit.textChanged.connect(self._validate)
            form.addRow(label, edit)
            self.text_edits[code] = edit
            self.text_labels[code] = label
        layout.addLayout(form)
        self.target = QLabel()
        self.target.setObjectName("addKeyTarget")
        self.target.setProperty("role", "caption")
        self.target.setWordWrap(True)
        layout.addWidget(self.target)
        self.problem = StatusBadge()
        self.problem.setObjectName("addKeyProblem")
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox()
        self.ok_button = QPushButton()
        self.ok_button.setObjectName("addKeyOk")
        self.ok_button.setProperty("accent", True)
        self.ok_button.setDefault(True)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("addKeyCancel")
        self.buttons.addButton(self.ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._problem: tuple[str, dict] | None = None
        self.retranslate()

    def area(self) -> str:
        return self.area_combo.currentData()

    def values(self) -> tuple[str, str, dict[str, str]] | None:
        if self._problem is not None:
            return None
        texts = {code: edit.text() for code, edit in self.text_edits.items() if edit.text()}
        return self.key_edit.text(), self.area(), texts

    def problem_text(self) -> str:
        return "" if self._problem is None else tr(self._problem[0], **self._problem[1])

    def _check(self) -> tuple[str, dict] | None:
        key = self.key_edit.text()
        if not key:
            return N_("texts.add.need_key"), {}
        try:
            check_key(key)
        except InvalidFieldError as exc:
            return N_("texts.add.invalid"), {"error": exc.message(core_language())}
        char = unencodable_char(key)
        if char is not None:
            return N_("texts.add.unencodable_key"), {"char": char, "code": f"U+{ord(char):04X}"}
        where = self.locsync.where(key)
        if where is not None:
            return N_("texts.add.exists"), {"key": key, "file": str(where[0]), "line": where[1] or "?"}
        for code, edit in self.text_edits.items():
            try:
                check_text(edit.text())
            except InvalidFieldError as exc:
                return N_("texts.add.invalid_text"), {"language": dict(LANGUAGES)[code],
                                                     "error": exc.message(core_language())}
            char = unencodable_char(edit.text())
            if char is not None:
                return N_("texts.add.unencodable"), {"language": dict(LANGUAGES)[code], "char": char,
                                                    "code": f"U+{ord(char):04X}"}
        if not any(edit.text() for edit in self.text_edits.values()):
            return N_("texts.add.need_text"), {}
        return None

    def _validate(self, *args) -> None:
        self._problem = self._check()
        self.ok_button.setEnabled(self._problem is None)
        self.problem.setVisible(self._problem is not None)
        if self._problem is not None:
            self.problem.set_status("warning", self.problem_text())
        self.target.setText(tr("texts.add.target", file=str(self.locsync.target_file(self.area()))))

    def retranslate(self) -> None:
        self.setWindowTitle(tr("texts.add.title"))
        self.title.setText(tr("texts.add.title"))
        self.intro.setText(tr("texts.add.intro"))
        self.key_label.setText(tr("texts.add.key"))
        self.key_edit.setPlaceholderText(tr("texts.add.key_placeholder"))
        self.area_label.setText(tr("texts.add.area"))
        for position, area in enumerate(AREAS):
            self.area_combo.setItemText(position, tr(AREA_KEYS[area]))
        self.ok_button.setText(tr("texts.add.ok"))
        self.cancel_button.setText(tr("texts.add.cancel"))
        self._validate()
