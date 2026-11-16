"""Ficha de una unidad (wizard §14.4, §14.12): la pestaña **Unidad** del editor de entidades.

Tres bloques, los tres sobre el registro enlazado (``bind(ref)``):

- **Estadísticas comparadas**: cada campo numérico de la unidad junto al de otra (la «base» que se elija; por
  defecto, la primera del mismo ``unit_type``) y la diferencia. Solo lee.
- **Dónde se desbloquea**: las tecnologías e invenciones con ``activate_unit = <id>`` (del índice) y, para
  cambiarlo, «Activar en…» (añade la línea a otra) y «Quitar» (la borra del archivo elegido). Cada cambio es una
  transacción; el archivo de tecnología se copia al mod al guardar.
- **Modelo**: los actores de ``interface/*.gfx`` que la unidad puede nombrar en ``sprite``, con cuántas culturas
  gráficas lo tienen; elegir uno cambia solo ese campo.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.diagnostics import EditError
from ...core.schema import ActivateUnit, RecordRef
from ...core.schema.companions import EditContext
from ...core.schema.fields import Field, Section, field_text_key
from ...core.schema.types import Float, Int
from ...i18n import N_, tr, translator
from ..widgets import mark_data

_ROLE = Qt.ItemDataRole.UserRole
ACTIVATION_KINDS = ("technology", "invention")


def activate_unit(schema) -> ActivateUnit | None:
    return next((c for c in schema.companions if isinstance(c, ActivateUnit)), None)


def numeric_fields(schema, record) -> list[str]:
    """Claves numéricas (``Int``/``Float``) del esquema para ``record``: las comunes y las de su variante."""
    keys: list[str] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, Field):
                if isinstance(item.type, (Int, Float)) and item.key not in keys:
                    keys.append(item.key)
            elif isinstance(item, Section):
                walk(item.items)

    walk(schema.fields)
    if schema.variants is not None:
        walk(schema.variants.cases.get(record.get(schema.variants.field, None), ()))
    return keys


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _show(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(value)) if value == int(value) else f"{value:g}"


class UnitPanel(QWidget):
    """API: ``bind(ref)``, ``compare_with(ident)``, ``rows()``, ``sources()``, ``activate(kind, name)``,
    ``deactivate(rel)``, ``set_model(name)``."""

    status_requested = Signal(str, object)
    location_requested = Signal(object, object)

    def __init__(self, session, schema, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.schema = schema
        self.companion = activate_unit(schema)
        self.ref = None
        self._rows: list[tuple[str, float | None, float | None]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        compare_row = QHBoxLayout()
        self.compare_label = QLabel()
        compare_row.addWidget(self.compare_label)
        self.compare_combo = mark_data(QComboBox())
        self.compare_combo.setObjectName("unitCompare")
        self.compare_combo.activated.connect(lambda _i: self._fill_stats())
        compare_row.addWidget(self.compare_combo, 1)
        outer.addLayout(compare_row)
        self.stats = mark_data(QTableWidget(0, 4))
        self.stats.setObjectName("unitStats")
        self.stats.verticalHeader().hide()
        self.stats.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.stats, 3)

        self.unlock_title = QLabel()
        self.unlock_title.setProperty("role", "title")
        outer.addWidget(self.unlock_title)
        self.unlock_note = QLabel()
        self.unlock_note.setObjectName("unitUnlockNote")
        self.unlock_note.setProperty("role", "caption")
        self.unlock_note.setWordWrap(True)
        outer.addWidget(self.unlock_note)
        self.unlock_list = mark_data(QListWidget())
        self.unlock_list.setObjectName("unitUnlockList")
        self.unlock_list.setMaximumHeight(96)
        self.unlock_list.itemActivated.connect(self._on_source_activated)
        self.unlock_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        outer.addWidget(self.unlock_list)
        unlock_row = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("unitUnlockKind")
        self.kind_combo.activated.connect(lambda _i: self._fill_targets())
        unlock_row.addWidget(self.kind_combo)
        self.target_combo = mark_data(QComboBox())
        self.target_combo.setObjectName("unitUnlockTarget")
        self.target_combo.setEditable(True)
        self.target_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        unlock_row.addWidget(self.target_combo, 1)
        self.activate_button = QPushButton()
        self.activate_button.setObjectName("unitActivate")
        self.activate_button.clicked.connect(self._on_activate)
        unlock_row.addWidget(self.activate_button)
        self.deactivate_button = QPushButton()
        self.deactivate_button.setObjectName("unitDeactivate")
        self.deactivate_button.clicked.connect(self._on_deactivate)
        unlock_row.addWidget(self.deactivate_button)
        outer.addLayout(unlock_row)

        model_row = QHBoxLayout()
        self.model_label = QLabel()
        model_row.addWidget(self.model_label)
        self.model_combo = mark_data(QComboBox())
        self.model_combo.setObjectName("unitModel")
        self.model_combo.activated.connect(self._on_model)
        model_row.addWidget(self.model_combo, 1)
        self.model_note = QLabel()
        self.model_note.setObjectName("unitModelNote")
        self.model_note.setProperty("role", "caption")
        model_row.addWidget(self.model_note, 1)
        outer.addLayout(model_row)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    # --- textos -----------------------------------------------------------------------------------

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.compare_label.setText(tr("entity.unit.compare"))
        self.stats.setHorizontalHeaderLabels([tr("entity.unit.col.field"), tr("entity.unit.col.this"),
                                              tr("entity.unit.col.base"), tr("entity.unit.col.diff")])
        self.unlock_title.setText(tr("entity.unit.unlock"))
        self.activate_button.setText(tr("entity.unit.activate"))
        self.activate_button.setToolTip(tr("entity.unit.activate_tooltip"))
        self.deactivate_button.setText(tr("entity.unit.deactivate"))
        self.deactivate_button.setToolTip(tr("entity.unit.deactivate_tooltip"))
        self.model_label.setText(tr("entity.unit.model"))
        with QSignalBlocker(self.kind_combo):
            current = self.kind_combo.currentData()
            self.kind_combo.clear()
            for kind in ACTIVATION_KINDS:
                self.kind_combo.addItem(tr(f"entity.unit.kind.{kind}"), kind)
            self.kind_combo.setCurrentIndex(max(self.kind_combo.findData(current), 0))
        self._fill_stats()
        self._fill_unlock()
        self._fill_model()

    # --- enlace -----------------------------------------------------------------------------------

    def _entities(self):
        return getattr(self.session, "entities", None)

    def _record(self):
        entities = self._entities()
        if self.ref is None or entities is None:
            return None
        try:
            return entities.open(self.ref)
        except (KeyError, FileNotFoundError, OSError, RuntimeError):   # RuntimeError: proyecto ya cerrado
            return None

    def _ctx(self):
        entities = self._entities()
        return EditContext(entities.ws, entities.index, entities.loc)

    def bind(self, ref) -> None:
        self.ref = ref if ref is not None and ref.kind == self.schema.kind else None
        record = self._record()
        with QSignalBlocker(self.compare_combo):
            previous = self.compare_combo.currentData()
            self.compare_combo.clear()
            entities = self._entities()
            if record is not None and entities is not None:
                same_type, others = [], []
                wanted = record.get("unit_type", None)
                for summary in entities.list(self.schema.kind):
                    if summary.ref.ident == self.ref.ident:
                        continue
                    try:
                        other = entities.open(summary.ref)
                    except (KeyError, FileNotFoundError, OSError):
                        continue
                    (same_type if other.get("unit_type", None) == wanted else others).append(summary.ref.ident)
                for ident in same_type + others:
                    self.compare_combo.addItem(ident, ident)
                index = self.compare_combo.findData(previous)
                self.compare_combo.setCurrentIndex(index if index >= 0 else (0 if self.compare_combo.count() else -1))
        self._fill_stats()
        self._fill_unlock()
        self._fill_targets()
        self._fill_model()

    # --- estadísticas -----------------------------------------------------------------------------

    def compare_with(self, ident: str) -> bool:
        index = self.compare_combo.findData(ident)
        if index < 0:
            return False
        self.compare_combo.setCurrentIndex(index)
        self._fill_stats()
        return True

    def rows(self) -> list[tuple[str, float | None, float | None]]:
        """``(campo, valor de la unidad, valor de la base)`` de la tabla."""
        return list(self._rows)

    def _fill_stats(self) -> None:
        self._rows = []
        self.stats.setRowCount(0)
        record = self._record()
        if record is None:
            return
        base = None
        base_ident = self.compare_combo.currentData()
        if base_ident is not None:
            try:
                base = self._entities().open(RecordRef(self.schema.kind, base_ident))
            except (KeyError, FileNotFoundError, OSError):
                base = None
        keys = numeric_fields(self.schema, record)
        if base is not None:
            keys += [key for key in numeric_fields(self.schema, base) if key not in keys]
        for key in keys:
            mine = _number(record.get(key, None))
            theirs = None if base is None else _number(base.get(key, None))
            if mine is None and theirs is None:
                continue
            self._rows.append((key, mine, theirs))
            row = self.stats.rowCount()
            self.stats.insertRow(row)
            label_key = field_text_key(self.schema.kind, key)
            label = tr(label_key)
            self.stats.setItem(row, 0, QTableWidgetItem(key if label == label_key else f"{label} ({key})"))
            self.stats.setItem(row, 1, QTableWidgetItem(_show(mine)))
            self.stats.setItem(row, 2, QTableWidgetItem(_show(theirs)))
            diff = ""
            if mine is not None and theirs is not None and mine != theirs:
                diff = ("+" if mine > theirs else "−") + _show(abs(mine - theirs))
            self.stats.setItem(row, 3, QTableWidgetItem(diff))

    # --- desbloqueo -------------------------------------------------------------------------------

    def sources(self) -> list:
        record = self._record()
        if record is None or self.companion is None:
            return []
        return self.companion.sources(self._ctx(), record)

    def _fill_unlock(self) -> None:
        self.unlock_list.clear()
        record = self._record()
        sources = self.sources()
        seen = set()
        for use in sources:
            key = (use.rel.key, use.line)
            if key in seen:
                continue
            seen.add(key)
            item = QListWidgetItem(f"{use.rel}:{use.line or 0}")
            item.setData(_ROLE, (use.rel, use.line))
            self.unlock_list.addItem(item)
        if record is None:
            self.unlock_note.setText("")
        elif sources:
            self.unlock_note.setText(tr("entity.unit.unlock_some", count=self.unlock_list.count()))
        elif record.get("active", True) is False:
            self.unlock_note.setText(tr("entity.unit.unlock_never"))
        else:
            self.unlock_note.setText(tr("entity.unit.unlock_always"))
        self._update_buttons()

    def _fill_targets(self) -> None:
        entities = self._entities()
        with QSignalBlocker(self.target_combo):
            self.target_combo.clear()
            if entities is not None and entities.index is not None:
                for name in sorted(entities.index.names(self.kind_combo.currentData() or ACTIVATION_KINDS[0])):
                    self.target_combo.addItem(name, name)
        self._update_buttons()

    def _update_buttons(self) -> None:
        writable = (self.ref is not None and self.session.project is not None and not self.session.is_read_only()
                    and self.companion is not None)
        self.activate_button.setEnabled(writable and self.target_combo.count() > 0)
        self.deactivate_button.setEnabled(writable and self.unlock_list.currentItem() is not None)
        self.model_combo.setEnabled(writable and self.model_combo.count() > 0)

    def _on_source_activated(self, item) -> None:
        rel, line = item.data(_ROLE)
        self.location_requested.emit(rel, line)

    def _on_activate(self) -> None:
        name = self.target_combo.currentText().strip()
        if name:
            self.activate(self.kind_combo.currentData(), name)

    def _on_deactivate(self) -> None:
        item = self.unlock_list.currentItem()
        if item is not None:
            self.deactivate(item.data(_ROLE)[0])

    def activate(self, kind: str, name: str) -> bool:
        """Añade ``activate_unit = <id>`` a la tecnología o invención ``name`` (una transacción)."""
        record = self._record()
        if record is None or self.companion is None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(N_("entity.unit.activate_undo"), ident=self.ref.ident, name=name):
                self.companion.activate_in(self._ctx(), record, kind, name)
        except (KeyError, FileNotFoundError, OSError, PermissionError, EditError) as exc:
            self.status_requested.emit(N_("entity.unit.activate_failed"), {"name": name, "error": str(exc)})
            return False
        self.status_requested.emit(N_("entity.unit.activate_done"), {"ident": self.ref.ident, "name": name})
        return True

    def deactivate(self, rel) -> bool:
        """Quita ``activate_unit = <id>`` del archivo ``rel`` (una transacción)."""
        record = self._record()
        if record is None or self.companion is None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(N_("entity.unit.deactivate_undo"), ident=self.ref.ident, rel=str(rel)):
                removed = self.companion.deactivate_in(self._ctx(), record, rel)
        except (KeyError, FileNotFoundError, OSError, PermissionError, EditError) as exc:
            self.status_requested.emit(N_("entity.unit.activate_failed"), {"name": str(rel), "error": str(exc)})
            return False
        if removed:
            self.status_requested.emit(N_("entity.unit.deactivate_done"), {"ident": self.ref.ident, "rel": str(rel)})
        return bool(removed)

    # --- modelo -----------------------------------------------------------------------------------

    def _fill_model(self) -> None:
        from ...core.validate.rules.units import unit_models

        record = self._record()
        entities = self._entities()
        with QSignalBlocker(self.model_combo):
            self.model_combo.clear()
            current = None if record is None else record.get("sprite", None)
            if record is not None and entities is not None and entities.index is not None:
                for name, cultures in unit_models(entities.index):
                    self.model_combo.addItem(tr("entity.unit.model_item", name=name, count=cultures), name)
                index = -1
                if isinstance(current, str):
                    index = next((i for i in range(self.model_combo.count())
                                  if self.model_combo.itemData(i).casefold() == current.casefold()), -1)
                self.model_combo.setCurrentIndex(index)
            if record is None:
                self.model_note.setText("")
            elif self.model_combo.count() == 0:
                self.model_note.setText(tr("entity.unit.model_none"))
            elif self.model_combo.currentIndex() < 0 and current:
                self.model_note.setText(tr("entity.unit.model_unknown", sprite=str(current)))
            else:
                self.model_note.setText("")
        self._update_buttons()

    def _on_model(self, index: int) -> None:
        name = self.model_combo.itemData(index)
        if name is not None:
            self.set_model(name)

    def set_model(self, name: str) -> bool:
        """Cambia ``sprite`` por ``name`` (solo ese campo, una transacción)."""
        record = self._record()
        if record is None or self.session.is_read_only() or record.get("sprite", None) == name:
            return False
        try:
            with self.session.edit(N_("entity.unit.model_undo"), merge_key=f"unit.sprite.{self.ref.ident}",
                                   ident=self.ref.ident, sprite=name):
                self._entities().open(self.ref).set("sprite", name)
        except (KeyError, ValueError, EditError, PermissionError) as exc:
            self.status_requested.emit(N_("entity.unit.activate_failed"), {"name": name, "error": str(exc)})
            return False
        return True
