"""Los seis selectores básicos (ver ``ui/pickers/__init__.py``)."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.nodes import ClausewitzDate
from ...i18n import tr, translator
from ..widgets import mark_data


class _Picker(QWidget):
    """Base: ``value_committed`` y el cambio de idioma."""

    value_committed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        translator().languageChanged.connect(self._on_language)

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        """Textos de la interfaz del selector (los datos no se traducen)."""


def _row(parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout(parent)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    return row


class SymbolPicker(_Picker):
    """Un símbolo del índice (``kind``): desplegable editable con búsqueda por id y por nombre localizado.

    ``names`` da los candidatos (por defecto, los de ``session.index``). Con ``allow_new`` se acepta un id que
    aún no existe; sin él, uno desconocido se marca como inválido y no se confirma. Vacío es «sin valor».
    """

    def __init__(self, session, kind: str, *, allow_new: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.kind = kind
        self.allow_new = allow_new
        row = _row(self)
        self.combo = mark_data(QComboBox())
        self.combo.setObjectName("symbolPicker")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.lineEdit().editingFinished.connect(self._commit)
        self.combo.activated.connect(lambda _index: self._commit())
        row.addWidget(self.combo, 1)
        self._last: str | None = None
        self.reload()
        self.retranslate()

    def names(self) -> list[str]:
        index = getattr(self.session, "index", None)
        if index is None:
            return []
        try:
            return sorted(index.names(self.kind))
        except Exception:  # noqa: BLE001 - un índice falso puede no tener el tipo
            return []

    def _label(self, name: str) -> str:
        index = getattr(self.session, "index", None)
        if index is None:
            return name
        try:
            symbol = index.get(self.kind, name)
            return self.session.display(symbol) if symbol is not None else name
        except Exception:  # noqa: BLE001
            return name

    def reload(self) -> None:
        current = self.value()
        with QSignalBlocker(self.combo):
            self.combo.clear()
            for name in self.names():
                self.combo.addItem(self._label(name), name)
            completer = QCompleter(QStringListModel([self.combo.itemText(i) for i in range(self.combo.count())]))
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.combo.setCompleter(completer)
            self._show(current)

    def retranslate(self) -> None:
        self.combo.lineEdit().setPlaceholderText(tr("pickers.symbol.placeholder"))

    def _show(self, name: str | None) -> None:
        index = self.combo.findData(name) if name else -1
        if index >= 0:
            self.combo.setCurrentIndex(index)
        else:
            self.combo.setCurrentIndex(-1)
            self.combo.setEditText(name or "")

    def value(self) -> str | None:
        text = self.combo.currentText().strip()
        if not text:
            return None
        index = self.combo.findText(text)
        if index >= 0 and self.combo.itemData(index):
            return self.combo.itemData(index)
        data = self.combo.currentData()
        if data and self.combo.itemText(self.combo.currentIndex()) == text:
            return data
        return text

    def is_valid(self) -> bool:
        value = self.value()
        return value is None or self.allow_new or value in self.names()

    def set_value(self, value) -> None:
        self._last = value if value else None
        with QSignalBlocker(self.combo):
            self._show(self._last)
        self.combo.setProperty("invalid", False)

    def _commit(self) -> None:
        value = self.value()
        valid = self.is_valid()
        self.combo.setProperty("invalid", not valid)
        if not valid or value == self._last:
            return
        self._last = value
        self.value_committed.emit(value)


class DateEdit(_Picker):
    """Fecha del juego ``año.mes.día`` (sin 29 de febrero: el juego no lo tiene) con botones para las fechas de
    inicio (``dates``). Una fecha mal escrita se marca y no se confirma."""

    def __init__(self, dates=(), parent: QWidget | None = None):
        super().__init__(parent)
        row = _row(self)
        self.edit = mark_data(QLineEdit())
        self.edit.setObjectName("dateEdit")
        self.edit.editingFinished.connect(self._commit)
        row.addWidget(self.edit, 1)
        self.quick = QHBoxLayout()
        self.quick.setSpacing(4)
        row.addLayout(self.quick)
        self._buttons: list[QToolButton] = []
        self._last: ClausewitzDate | None = None
        self.set_dates(dates)
        self.retranslate()

    def set_dates(self, dates) -> None:
        for button in self._buttons:
            button.deleteLater()
        self._buttons = []
        for date in sorted(set(dates)):
            button = mark_data(QToolButton())
            button.setText(str(date))
            button.setProperty("date", str(date))
            button.clicked.connect(lambda checked=False, d=date: self._pick(d))
            self.quick.addWidget(button)
            self._buttons.append(button)

    def retranslate(self) -> None:
        self.edit.setPlaceholderText(tr("pickers.date.placeholder"))

    def _pick(self, date: ClausewitzDate) -> None:
        self.edit.setText(str(date))
        self._commit()

    @staticmethod
    def parse(text: str) -> ClausewitzDate | None:
        """La fecha de ``text`` o None si no es una fecha del juego (``1836.2.29`` no lo es)."""
        try:
            return ClausewitzDate.parse(text.strip())
        except ValueError:
            return None

    def value(self) -> ClausewitzDate | None:
        return self.parse(self.edit.text())

    def is_valid(self) -> bool:
        return not self.edit.text().strip() or self.value() is not None

    def set_value(self, value) -> None:
        self._last = value if isinstance(value, ClausewitzDate) else None
        with QSignalBlocker(self.edit):
            self.edit.setText("" if value is None else str(value))
        self.edit.setProperty("invalid", False)

    def _commit(self) -> None:
        valid = self.is_valid()
        self.edit.setProperty("invalid", not valid)
        value = self.value()
        if not valid or value == self._last:
            return
        self._last = value
        self.value_committed.emit(value)


def similar_colors(color: tuple, others: dict, *, threshold: int = 24) -> list[str]:
    """Nombres de ``others`` (``{nombre: (r, g, b)}``) cuyo color se parece a ``color`` (distancia máxima por
    componente ≤ ``threshold``): el aviso de colores repetidos de §14.13."""
    if color is None:
        return []
    found = []
    for name, other in others.items():
        if other is None or len(other) != 3:
            continue
        if max(abs(int(a) - int(b)) for a, b in zip(color, other)) <= threshold:
            found.append(name)
    return sorted(found)


class ColorField(_Picker):
    """Color ``{ r g b }`` de 0 a 255: tres casillas y una muestra que abre el selector de color. ``others``
    (``{nombre: color}``) da los colores con los que no conviene confundirse: si se parece a alguno, lo avisa."""

    def __init__(self, others: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(6)
        outer.addLayout(row)
        self.spins: list[QSpinBox] = []
        for name in ("r", "g", "b"):
            spin = QSpinBox()
            spin.setObjectName(f"color_{name}")
            spin.setRange(0, 255)
            spin.editingFinished.connect(self._commit)
            row.addWidget(spin)
            self.spins.append(spin)
        self.swatch = QPushButton()
        self.swatch.setObjectName("colorSwatch")
        self.swatch.setFixedWidth(44)
        self.swatch.clicked.connect(self._choose)
        row.addWidget(self.swatch)
        row.addStretch(1)
        self.warning = QLabel()
        self.warning.setObjectName("colorWarning")
        self.warning.setProperty("role", "caption")
        self.warning.setWordWrap(True)
        self.warning.hide()
        outer.addWidget(self.warning)
        self.others = dict(others or {})
        self._last: tuple | None = None
        self._empty = True
        self.retranslate()

    def retranslate(self) -> None:
        self.swatch.setToolTip(tr("pickers.color.choose"))
        self._update_warning()

    def value(self) -> tuple | None:
        if self._empty:
            return None
        return tuple(spin.value() for spin in self.spins)

    def set_value(self, value) -> None:
        self._empty = value is None
        self._last = tuple(value) if value is not None else None
        for spin, part in zip(self.spins, value or (0, 0, 0)):
            with QSignalBlocker(spin):
                spin.setValue(int(part))
        self._paint()

    def set_others(self, others: dict) -> None:
        self.others = dict(others)
        self._update_warning()

    def _paint(self) -> None:
        color = self.value() or (0, 0, 0)
        self.swatch.setStyleSheet(f"background-color: rgb({color[0]}, {color[1]}, {color[2]});")
        self._update_warning()

    def _update_warning(self) -> None:
        similar = similar_colors(self.value(), self.others)
        self.warning.setText(tr("pickers.color.similar", names=", ".join(similar[:5])) if similar else "")
        self.warning.setVisible(bool(similar))

    def _choose(self) -> None:
        current = self.value() or (128, 128, 128)
        chosen = QColorDialog.getColor(QColor(*current), self, tr("pickers.color.choose"))
        if chosen.isValid():
            self.set_from((chosen.red(), chosen.green(), chosen.blue()))

    def set_from(self, color: tuple) -> None:
        """Pone el color y lo confirma (como si se eligiera en el diálogo)."""
        self._empty = False
        for spin, part in zip(self.spins, color):
            with QSignalBlocker(spin):
                spin.setValue(int(part))
        self._commit()

    def _commit(self) -> None:
        self._empty = False
        value = self.value()
        self._paint()
        if value == self._last:
            return
        self._last = value
        self.value_committed.emit(value)


class GoodsAmountsField(_Picker):
    """Bienes y cantidades (``build_cost = { small_arms = 10 … }``): una fila por bien, con «Añadir» y «Quitar».
    ``value()`` es un dict ``{bien: cantidad}``; una cantidad vacía o cero quita el bien al confirmar."""

    def __init__(self, goods=(), parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.table = mark_data(QTableWidget(0, 2))
        self.table.setObjectName("goodsTable")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(lambda _item: self._commit())
        outer.addWidget(self.table)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.good_combo = mark_data(QComboBox())
        self.good_combo.setObjectName("goodsCombo")
        row.addWidget(self.good_combo, 1)
        self.add_button = QPushButton()
        self.add_button.setObjectName("goodsAdd")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("goodsRemove")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        outer.addLayout(row)
        self._last: dict = {}
        self._filling = False
        self.set_goods(goods)
        self.retranslate()

    def set_goods(self, goods) -> None:
        self.good_combo.clear()
        for name in sorted(goods):
            self.good_combo.addItem(name, name)

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels([tr("pickers.goods.good"), tr("pickers.goods.amount")])
        self.add_button.setText(tr("pickers.goods.add"))
        self.remove_button.setText(tr("pickers.goods.remove"))

    def value(self) -> dict:
        result = {}
        for row in range(self.table.rowCount()):
            good = self.table.item(row, 0)
            amount = self.table.item(row, 1)
            if good is None or amount is None:
                continue
            try:
                number = float(amount.text().replace(",", "."))
            except ValueError:
                continue
            result[good.text()] = number
        return result

    def set_value(self, value) -> None:
        self._filling = True
        try:
            self.table.setRowCount(0)
            for good, amount in (value or {}).items():
                self._append(good, amount)
        finally:
            self._filling = False
        self._last = dict(value or {})

    def _append(self, good: str, amount) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(good)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item)
        text = f"{float(amount):g}" if isinstance(amount, (int, float)) else str(amount)
        self.table.setItem(row, 1, QTableWidgetItem(text))

    def _add(self) -> None:
        good = self.good_combo.currentData()
        if not good or good in self.value():
            return
        self._filling = True
        try:
            self._append(good, 1)
        finally:
            self._filling = False
        self._commit()

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        self._commit()

    def _commit(self) -> None:
        if self._filling:
            return
        value = self.value()
        if value == self._last:
            return
        self._last = dict(value)
        self.value_committed.emit(value)


class NameListEditor(_Picker):
    """Lista de nombres (``first_names``): uno por línea (se puede pegar una lista separada por espacios entre
    comillas o por saltos), «Quitar repetidos» y aviso de los que no caben en cp1252 (el juego los mostraría
    rotos). Confirma al perder el foco."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.edit = mark_data(QPlainTextEdit())
        self.edit.setObjectName("nameList")
        self.edit.setFixedHeight(96)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(self._check)
        outer.addWidget(self.edit)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.count_label = QLabel()
        self.count_label.setProperty("role", "caption")
        row.addWidget(self.count_label, 1)
        self.dedupe_button = QPushButton()
        self.dedupe_button.setObjectName("nameDedupe")
        self.dedupe_button.clicked.connect(self.remove_duplicates)
        row.addWidget(self.dedupe_button)
        outer.addLayout(row)
        self.warning = QLabel()
        self.warning.setObjectName("nameWarning")
        self.warning.setProperty("role", "caption")
        self.warning.setWordWrap(True)
        self.warning.hide()
        outer.addWidget(self.warning)
        self._last: list | None = None
        self.retranslate()

    @staticmethod
    def split(text: str) -> list[str]:
        """Nombres de un texto pegado: una línea por nombre; si una línea trae varios entre comillas o separados
        por espacios (como en el archivo del juego), se separan (lo que va entre comillas queda junto)."""
        import shlex

        names: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if '"' in line:
                try:
                    names.extend(part for part in shlex.split(line, posix=True) if part)
                    continue
                except ValueError:
                    pass
            names.append(line)
        return names

    def value(self) -> list[str]:
        return self.split(self.edit.toPlainText())

    def set_value(self, value) -> None:
        self._last = list(value or [])
        with QSignalBlocker(self.edit):
            self.edit.setPlainText("\n".join(str(name) for name in self._last))
        self._check()

    def invalid_names(self) -> list[str]:
        bad = []
        for name in self.value():
            try:
                name.encode("cp1252")
            except UnicodeEncodeError:
                bad.append(name)
        return bad

    def remove_duplicates(self) -> None:
        seen, unique = set(), []
        for name in self.value():
            if name not in seen:
                seen.add(name)
                unique.append(name)
        with QSignalBlocker(self.edit):
            self.edit.setPlainText("\n".join(unique))
        self._check()
        self._commit()

    def retranslate(self) -> None:
        self.dedupe_button.setText(tr("pickers.names.dedupe"))
        self._check()

    def _check(self) -> None:
        names = self.value()
        self.count_label.setText(tr("pickers.names.count", count=len(names)))
        bad = self.invalid_names()
        self.warning.setText(tr("pickers.names.not_cp1252", names=", ".join(bad[:5])) if bad else "")
        self.warning.setVisible(bool(bad))

    def eventFilter(self, watched, event) -> bool:
        from PySide6.QtCore import QEvent

        if watched is self.edit and event.type() == QEvent.Type.FocusOut:
            self._commit()
        return super().eventFilter(watched, event)

    def commit_pending(self) -> None:
        self._commit()

    def _commit(self) -> None:
        value = self.value()
        if value == self._last or self.invalid_names():
            return
        self._last = list(value)
        self.value_committed.emit(value)


class SpriteFramePicker(_Picker):
    """Fotograma de un sprite (``sprite_index``): un número de 0 a ``frames`` (si el índice sabe cuántos tiene el
    sprite) y la cuenta al lado."""

    def __init__(self, frames: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        row = _row(self)
        self.edit = mark_data(QLineEdit())
        self.edit.setObjectName("spriteFrame")
        self.edit.setValidator(QIntValidator(0, 9999, self.edit))
        self.edit.setMaximumWidth(80)
        self.edit.editingFinished.connect(self._commit)
        row.addWidget(self.edit)
        self.of_label = QLabel()
        self.of_label.setProperty("role", "caption")
        row.addWidget(self.of_label)
        row.addStretch(1)
        self.frames = frames
        self._last: int | None = None
        self.retranslate()

    def retranslate(self) -> None:
        self.of_label.setText(tr("pickers.sprite.of", count=self.frames) if self.frames else "")
        self.edit.setPlaceholderText(tr("pickers.sprite.placeholder"))

    def value(self) -> int | None:
        text = self.edit.text().strip()
        return int(text) if text else None

    def is_valid(self) -> bool:
        value = self.value()
        return value is None or self.frames is None or value <= self.frames

    def set_value(self, value) -> None:
        self._last = value if isinstance(value, int) else None
        with QSignalBlocker(self.edit):
            self.edit.setText("" if self._last is None else str(self._last))

    def _commit(self) -> None:
        valid = self.is_valid()
        self.edit.setProperty("invalid", not valid)
        value = self.value()
        if not valid or value == self._last:
            return
        self._last = value
        self.value_committed.emit(value)


__all__ = ["ColorField", "DateEdit", "GoodsAmountsField", "NameListEditor", "SpriteFramePicker", "SymbolPicker",
           "similar_colors"]
