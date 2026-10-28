"""Diálogos del editor de entidades: «Nuevo» (plantilla o «basar en…») y el borrado bloqueado con sus usos."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...core.schema.record import ident_problem
from ...i18n import N_, tr
from ..widgets import mark_data

IDENT_MESSAGES = {
    "empty": N_("entity.ident.empty"),
    "bad_chars": N_("entity.ident.bad_chars"),
    "taken": N_("entity.ident.taken"),
    "no_group": N_("entity.ident.no_group"),
}


class NewEntityDialog(QDialog):
    """Pide el id, la base (plantilla del esquema o un registro existente: «basar en…») y, en un grupo, el grupo.

    ``result_values()`` da ``(id, ref_base | None, grupo | None)``. El botón Aceptar solo se habilita con un id
    válido que no exista (la misma comprobación que ``Entities``, sin efectos)."""

    def __init__(self, schema, existing: list, groups: list[str], *, base=None, group: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("newEntityDialog")
        self.schema = schema
        self.existing = list(existing)
        self._taken = {ref.ident for ref in self.existing}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.ident_edit = QLineEdit()
        self.ident_edit.setObjectName("newIdent")
        self.ident_edit.textChanged.connect(self._validate)
        self.ident_label = QLabel()
        form.addRow(self.ident_label, self.ident_edit)
        self.template_radio = QRadioButton()
        self.template_radio.setObjectName("newFromTemplate")
        self.base_radio = QRadioButton()
        self.base_radio.setObjectName("newBasedOn")
        self.base_combo = mark_data(QComboBox())
        self.base_combo.setObjectName("newBase")
        for ref in self.existing:
            self.base_combo.addItem(ref.ident, ref)
        form.addRow(self.template_radio)
        form.addRow(self.base_radio, self.base_combo)
        self.group_label = QLabel()
        self.group_combo = mark_data(QComboBox())
        self.group_combo.setObjectName("newGroup")
        for name in groups:
            self.group_combo.addItem(name, name)
        if groups:
            form.addRow(self.group_label, self.group_combo)
            if group is not None and self.group_combo.findData(group) >= 0:
                self.group_combo.setCurrentIndex(self.group_combo.findData(group))
        else:
            self.group_label.hide()
            self.group_combo.hide()
        layout.addLayout(form)
        self.message = QLabel()
        self.message.setObjectName("newMessage")
        self.message.setProperty("role", "caption")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.base_radio.toggled.connect(self.base_combo.setEnabled)
        self.base_radio.toggled.connect(lambda on: self.group_combo.setEnabled(not on))
        has_template = schema.template is not None
        self.template_radio.setEnabled(has_template)
        if base is not None and self.base_combo.findText(base.ident) >= 0:
            self.base_combo.setCurrentIndex(self.base_combo.findText(base.ident))
            self.base_radio.setChecked(True)
        elif has_template:
            self.template_radio.setChecked(True)
            self.base_combo.setEnabled(False)
        else:
            self.base_radio.setChecked(True)
        if not self.existing:
            self.base_radio.setEnabled(False)
        self.retranslate()
        self._validate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("entity.new_title", kind=tr(f"schema.{self.schema.kind}.name")))
        self.ident_label.setText(tr("entity.new_ident"))
        self.template_radio.setText(tr("entity.new_template"))
        self.base_radio.setText(tr("entity.new_based_on"))
        self.group_label.setText(tr("entity.new_group"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("entity.new_create"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("entity.cancel"))

    def problem(self) -> str | None:
        ident = self.ident_edit.text().strip()
        code = ident_problem(self.schema, ident)
        if code is None and ident in self._taken:
            code = "taken"
        return code

    def _validate(self) -> None:
        code = self.problem()
        self.message.setText(tr(IDENT_MESSAGES.get(code, "entity.ident.bad_chars"), ident=self.ident_edit.text())
                             if code is not None and self.ident_edit.text() else "")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(code is None)

    def result_values(self):
        base = self.base_combo.currentData() if self.base_radio.isChecked() else None
        group = self.group_combo.currentData() if self.group_combo.isVisible() or self.group_combo.count() else None
        return self.ident_edit.text().strip(), base, group


class UsesDialog(QDialog):
    """El borrado está bloqueado: estos son los usos (archivo, línea y papel)."""

    def __init__(self, ident: str, uses: list, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("usesDialog")
        self.ident = ident
        self.uses = list(uses)
        layout = QVBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("usesList")
        for use in self.uses:
            self.list.addItem(f"{use.rel}:{use.line or 0} · {use.role}")
        layout.addWidget(self.list)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("entity.delete_blocked_title"))
        self.text.setText(tr("entity.delete_blocked", ident=self.ident, count=len(self.uses)))
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("entity.close"))


class UnitNamesDialog(QDialog):
    """Al crear una unidad naval: «¿Añadir su lista de nombres en estos países?» (compañero ``UnitNamesSlot``).
    ``chosen()`` da los archivos marcados."""

    def __init__(self, ident: str, rels: list, parent: QWidget | None = None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        super().__init__(parent)
        self.setObjectName("unitNamesDialog")
        self.ident = ident
        layout = QVBoxLayout(self)
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("unitNamesList")
        for rel in rels:
            item = QListWidgetItem(str(rel))
            item.setData(Qt.ItemDataRole.UserRole, rel)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.retranslate()

    def chosen(self) -> list:
        from PySide6.QtCore import Qt

        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def retranslate(self) -> None:
        self.setWindowTitle(tr("entity.unit_names_title"))
        self.text.setText(tr("entity.unit_names_text", ident=self.ident))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("entity.unit_names_add"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("entity.unit_names_skip"))
