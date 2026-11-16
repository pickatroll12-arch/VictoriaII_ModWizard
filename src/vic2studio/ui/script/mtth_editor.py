"""Editor de MTTH, ``ai_chance`` y ``ai_will_do``: base, modificadores y resultado efectivo (wizard §14.7).

La base (meses, días o años en un MTTH; el factor en los otros dos) y una tarjeta por
``modifier = { factor = F <condiciones> }`` con su factor, su frase y el botón que abre el
``TriggerBuilder`` de sus condiciones. Cada modificador lleva una casilla «se cumple» que no escribe nada:
sirve para simular, y el pie enseña el tiempo efectivo (``core.script.mtth.effective`` y
``format_duration``): 6 meses × 0,75 × 0,95 = 4,3 meses.

Las ediciones tocan el bloque del CST de la vista del grupo (``Record._touch`` antes de mutar, como
``Record.script``): cambiar el factor cambia solo su línea.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.nodes import Block, Scalar
from ...core.script.mtth import (
    AI_CHANCE_KEY,
    AI_WILL_DO_KEY,
    FACTOR_KEY,
    MODIFIER_KEY,
    MTTH_KEY,
    UNITS,
    WeightModel,
    effective,
    format_duration,
    read_weights,
    to_months,
)
from ...i18n import N_, tr, translator
from ..widgets import make_icon, mark_data

TITLE_KEYS = {MTTH_KEY: N_("script_ui.mtth.title.mtth"), AI_CHANCE_KEY: N_("script_ui.mtth.title.ai_chance"),
              AI_WILL_DO_KEY: N_("script_ui.mtth.title.ai_will_do")}
UNIT_KEYS = {"months": N_("script_ui.mtth.unit.months"), "days": N_("script_ui.mtth.unit.days"),
             "years": N_("script_ui.mtth.unit.years")}
UNDO_KEYS = {"base": N_("script_ui.mtth.undo.base"), "add": N_("script_ui.mtth.undo.add"),
             "factor": N_("script_ui.mtth.undo.factor"), "remove": N_("script_ui.mtth.undo.remove")}


def number_text(value: float, *, integer: bool = False) -> str:
    """Cómo se escribe un número en el archivo: entero si lo es (``6``, ``70``), si no con sus decimales
    (``0.75``)."""
    if integer or float(value) == int(value):
        return str(int(round(float(value))))
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


class ModifierCard(QFrame):
    """Un ``modifier``: factor, «se cumple» (simulación), la frase de sus condiciones y sus botones."""

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName(f"mtthModifier{index}")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 4, 6, 4)
        column.setSpacing(2)
        row = QHBoxLayout()
        self.factor_label = QLabel()
        self.factor = QDoubleSpinBox()
        self.factor.setObjectName("mtthFactor")
        self.factor.setDecimals(3)
        self.factor.setRange(0.0, 1000.0)
        self.factor.setSingleStep(0.05)
        self.satisfied = QCheckBox()
        self.satisfied.setObjectName("mtthSatisfied")
        self.phrase = mark_data(QLabel())
        self.phrase.setObjectName("mtthPhrase")
        self.phrase.setWordWrap(True)
        self.conditions_button = QPushButton()
        self.conditions_button.setObjectName("mtthConditions")
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("mtthRemove")
        self.remove_button.setIcon(make_icon("trash", "ink"))
        row.addWidget(self.factor_label)
        row.addWidget(self.factor)
        row.addWidget(self.satisfied)
        row.addStretch(1)
        row.addWidget(self.conditions_button)
        row.addWidget(self.remove_button)
        column.addLayout(row)
        column.addWidget(self.phrase)

    def retranslate(self) -> None:
        self.factor_label.setText(tr(N_("script_ui.mtth.factor")))
        self.satisfied.setText(tr(N_("script_ui.mtth.satisfied")))
        self.conditions_button.setText(tr(N_("script_ui.mtth.conditions")))
        self.remove_button.setToolTip(tr(N_("script_ui.mtth.remove")))


class MtthEditor(QWidget):
    """Editor de un bloque de pesos (``WeightModel``)."""

    changed = Signal()                           # tras una edición aplicada
    effective_changed = Signal(float)            # el resultado simulado (meses, o peso) cambió
    conditions_requested = Signal(int)           # abrir el constructor del modificador N
    status_requested = Signal(str, object)

    def __init__(self, session, *, key: str = MTTH_KEY, parent: QWidget | None = None) -> None:
        """``key``: ``MTTH_KEY``, ``AI_CHANCE_KEY`` o ``AI_WILL_DO_KEY`` (cambia la base y los textos)."""
        super().__init__(parent)
        self.session = session
        self.key = key
        self._ref = None
        self._path: tuple = ()
        self._model: WeightModel | None = None
        self._manual = False
        self._read_only = False
        self._satisfied: dict[int, bool] = {}
        self._filling = False
        self._applying = False
        self.cards: list[ModifierCard] = []
        self.setObjectName(f"mtthEditor_{key}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("mtthTitle")
        self.title.setProperty("role", "heading")
        outer.addWidget(self.title)
        base = QHBoxLayout()
        self.base_label = QLabel()
        self.base = QDoubleSpinBox()
        self.base.setObjectName("mtthBase")
        self.base.setRange(0.0, 100000.0)
        self.base.setDecimals(0 if key == MTTH_KEY else 2)
        self.base.editingFinished.connect(self._on_base)
        self.unit = QComboBox()
        self.unit.setObjectName("mtthUnit")
        for unit in UNITS:
            self.unit.addItem("", unit)
        self.unit.currentIndexChanged.connect(self._on_unit)
        self.unit.setVisible(key == MTTH_KEY)
        self.add_button = QPushButton()
        self.add_button.setObjectName("mtthAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(lambda: self.add_modifier())
        base.addWidget(self.base_label)
        base.addWidget(self.base)
        base.addWidget(self.unit)
        base.addStretch(1)
        base.addWidget(self.add_button)
        outer.addLayout(base)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(3)
        outer.addLayout(self.cards_box)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("mtthEmpty")
        self.empty_label.setWordWrap(True)
        outer.addWidget(self.empty_label)
        self.result = mark_data(QLabel())
        self.result.setObjectName("mtthEffective")
        self.result.setProperty("role", "heading")
        outer.addWidget(self.result)
        if hasattr(session, "documentsChanged"):
            session.documentsChanged.connect(self._on_documents)
        translator().languageChanged.connect(lambda _code: self.retranslate())
        self.retranslate()

    # --- enlace -----------------------------------------------------------------------------------

    def bind(self, ref, path: tuple = ()) -> None:
        """Enlaza con el bloque ``key`` del registro ``ref``, o del grupo en ``path``
        (``("option", 1)`` para el ``ai_chance`` de la segunda opción). None: vacío."""
        if ref != self._ref or tuple(path) != self._path:
            self._satisfied = {}
        self._ref, self._path, self._manual = ref, tuple(path), False
        self._reload()

    def _owner(self, *, create: bool = False):
        from .trigger_builder import record_at

        entities = getattr(self.session, "entities", None)
        if entities is None or self._ref is None:
            return None
        return record_at(entities.open(self._ref), self._path, create=create)

    def _reload(self) -> None:
        model = None
        if self._ref is not None:
            try:
                owner = self._owner()
                model = read_weights(owner, self.key) if owner is not None else None
            except (KeyError, FileNotFoundError, OSError, ValueError):
                model = None
        self._show(model)

    def set_model(self, model) -> None:
        """Pone un ``WeightModel`` a mano, sin registro (pruebas)."""
        self._manual = True
        self._ref = None
        self._satisfied = {}
        self._show(model)

    def model(self):
        return self._model

    def _on_documents(self, _rels) -> None:
        if not self._manual and self._ref is not None and not self._applying:
            self._reload()

    # --- pintar -----------------------------------------------------------------------------------

    def _show(self, model) -> None:
        self._model = model
        self._filling = True
        try:
            for card in self.cards:
                self.cards_box.removeWidget(card)
                card.hide()
                card.setParent(None)
                card.deleteLater()
            self.cards = []
            has = model is not None
            self.base.setEnabled(has and not self._read_only)
            self.base.setValue(0 if not has or model.base is None else float(model.base))
            if has and self.key == MTTH_KEY:
                self.unit.setCurrentIndex(max(0, UNITS.index(model.unit) if model.unit in UNITS else 0))
            self.unit.setEnabled(has and not self._read_only)
            for index, modifier in enumerate(model.modifiers if has else ()):
                card = ModifierCard(index)
                card.retranslate()
                card.factor.setValue(float(modifier.factor))
                card.factor.setEnabled(not self._read_only)
                card.factor.editingFinished.connect(lambda i=index, c=card: self.set_factor(i, c.factor.value()))
                card.satisfied.setChecked(self._satisfied.get(index, True))
                card.satisfied.toggled.connect(lambda on, i=index: self.set_satisfied(i, on))
                card.conditions_button.clicked.connect(lambda _c=False, i=index: self.conditions_requested.emit(i))
                card.remove_button.clicked.connect(lambda _c=False, i=index: self.remove_modifier(i))
                card.remove_button.setEnabled(not self._read_only)
                card.phrase.setText(self._phrase(modifier))
                self.cards_box.addWidget(card)
                self.cards.append(card)
            self.add_button.setEnabled(not self._read_only and (has or self._ref is not None))
            self.empty_label.setVisible(not has)
        finally:
            self._filling = False
        self._render_result()

    def _phrase(self, modifier) -> str:
        from .trigger_builder import phrase_language

        tree = modifier.conditions
        if tree is None:
            return ""
        from ...core.script.phrases import phrase

        loc = None
        finder = getattr(self.session, "_loc_for_search", None)
        if callable(finder):
            try:
                loc = finder()
            except Exception:  # noqa: BLE001
                loc = None
        try:
            return phrase(tree, phrase_language(), getattr(self.session, "index", None), loc, lead="modifier")
        except Exception:  # noqa: BLE001
            return tree.root.source()

    def _render_result(self) -> None:
        value = self.effective()
        if value is None:
            self.result.setText("")
            return
        from .trigger_builder import phrase_language

        if self.key == MTTH_KEY:
            shown = format_duration(value, phrase_language())
            self.result.setText(tr(N_("script_ui.mtth.effective"), value=shown))
        else:
            self.result.setText(tr(N_("script_ui.mtth.effective_weight"), value=number_text(round(value, 3))))
        self.effective_changed.emit(float(value))

    # --- operaciones (cada una, un paso de deshacer) -------------------------------------------------

    def _apply(self, action: str, operation, *, create: bool = False, **fmt) -> bool:
        """``operation(weights)`` sobre la vista de grupo del bloque de pesos, en una transacción."""
        if self._read_only:
            return False
        if self._manual:
            return False
        if self._ref is None or getattr(self.session, "project", None) is None:
            return False
        self._applying = True
        try:
            with self.session.edit(UNDO_KEYS[action], key=self.key, **fmt):
                owner = self._owner(create=create)
                try:
                    weights = owner.group(self.key)
                except KeyError:
                    if not create:
                        raise
                    owner._touch()
                    base_key = "months" if self.key == MTTH_KEY else FACTOR_KEY
                    entry = owner._insert_in_order(self.key, Block.from_pairs([(base_key, Scalar("1"))]))
                    weights = owner.group(self.key, [e for e in owner.block.find_all(self.key)].index(entry))
                weights._touch()
                operation(weights)
        except (ValueError, KeyError, IndexError, RuntimeError, OSError) as exc:
            self.status_requested.emit(N_("script_ui.rejected"), {"error": str(exc)})
            return False
        finally:
            self._applying = False
        self._reload()
        self.changed.emit()
        return True

    def set_base(self, value: float | None, unit: str | None = None) -> bool:
        """Cambia la base; ``unit`` cambia además la clave (``months`` → ``days``) en un MTTH."""
        if value is None:
            return False
        if self.key == MTTH_KEY:
            unit = unit or (self._model.unit if self._model is not None else "months")
            if unit not in UNITS:
                return False
        else:
            unit = FACTOR_KEY
        if self._model is not None and self._model.base == float(value) and self._model.unit == unit:
            return False

        def operation(weights) -> None:
            block = weights.block
            text = number_text(value, integer=self.key == MTTH_KEY)
            keys = UNITS if self.key == MTTH_KEY else (FACTOR_KEY,)
            current = next((entry for entry in block.entries if entry.key is not None
                            and entry.key.text.lower() in keys), None)
            if current is None:
                block.insert(0, unit, Scalar(text))
            elif current.key.text.lower() == unit:
                current.value = Scalar(text)
            else:
                position = block.entries.index(current)
                block.remove_entry(current)
                block.insert(position, unit, Scalar(text))

        return self._apply("base", operation, create=True)

    def add_modifier(self, factor: float = 1.0) -> bool:
        def operation(weights) -> None:
            weights.block.append(MODIFIER_KEY, Block.from_pairs([(FACTOR_KEY, Scalar(number_text(factor)))]))

        return self._apply("add", operation, create=True)

    def set_factor(self, index: int, factor: float) -> bool:
        if self._filling:
            return False
        if self._model is not None and 0 <= index < len(self._model.modifiers) \
                and abs(self._model.modifiers[index].factor - float(factor)) < 1e-9:
            return False

        def operation(weights) -> None:
            modifier = weights.block.find_all(MODIFIER_KEY)[index].value
            entry = modifier.find(FACTOR_KEY, ignore_case=True)
            if entry is None:
                modifier.insert(0, FACTOR_KEY, Scalar(number_text(factor)))
            else:
                entry.value = Scalar(number_text(factor))

        return self._apply("factor", operation, index=index + 1)

    def remove_modifier(self, index: int) -> bool:
        def operation(weights) -> None:
            weights.block.remove_entry(weights.block.find_all(MODIFIER_KEY)[index])

        done = self._apply("remove", operation, index=index + 1)
        if done:
            self._satisfied = {i - (i > index): on for i, on in self._satisfied.items() if i != index}
            self._render_result()
        return done

    def _on_base(self) -> None:
        if not self._filling and self._model is not None:
            self.set_base(self.base.value())

    def _on_unit(self, _index: int) -> None:
        if self._filling or self._model is None or self.key != MTTH_KEY:
            return
        self.set_base(self.base.value(), self.unit.currentData())

    # --- simulación (no escribe nada) ---------------------------------------------------------------

    def set_satisfied(self, index: int, satisfied: bool) -> None:
        """Marca si el modificador ``index`` se cumple en la simulación."""
        self._satisfied[index] = bool(satisfied)
        if 0 <= index < len(self.cards) and self.cards[index].satisfied.isChecked() != bool(satisfied):
            self.cards[index].satisfied.blockSignals(True)
            self.cards[index].satisfied.setChecked(bool(satisfied))
            self.cards[index].satisfied.blockSignals(False)
        self._render_result()

    def effective(self) -> float | None:
        """El resultado con las casillas actuales: meses en un MTTH, peso en los otros; None sin base."""
        model = self._model
        if model is None or model.base is None:
            return None
        factors = [m.factor for m in model.modifiers]
        satisfied = [self._satisfied.get(i, True) for i in range(len(factors))]
        base = to_months(model.base, model.unit) if self.key == MTTH_KEY else model.base
        return effective(base, factors, satisfied)

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self._show(self._model)

    def commit_pending(self) -> None:
        if self._model is None or self._read_only:
            return
        if self.base.hasFocus():
            self._on_base()
        for index, card in enumerate(self.cards):
            if card.factor.hasFocus():
                self.set_factor(index, card.factor.value())

    def retranslate(self) -> None:
        self.title.setText(tr(TITLE_KEYS.get(self.key, TITLE_KEYS[MTTH_KEY])))
        self.base_label.setText(tr(N_("script_ui.mtth.base") if self.key == MTTH_KEY
                                   else N_("script_ui.mtth.factor_base")))
        for index, unit in enumerate(UNITS):
            self.unit.setItemText(index, tr(UNIT_KEYS[unit]))
        self.add_button.setText(tr(N_("script_ui.mtth.add_modifier")))
        self.empty_label.setText(tr(N_("script_ui.mtth.no_block"), key=self.key))
        for card in self.cards:
            card.retranslate()
        self._render_result()
