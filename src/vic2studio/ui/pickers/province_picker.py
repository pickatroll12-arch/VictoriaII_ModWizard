"""Selector de provincia y diálogo «elegir en el mapa» (wizard §13.7, §16).

``ProvincePicker`` es el selector de formulario de un id de provincia, con la misma API que los de
``ui/pickers/fields.py`` (``value()``, ``set_value()``, ``value_committed``, ``retranslate()``): un campo para
escribir el id o buscar por nombre y un botón que abre ``MapPickDialog``. ``MapPickDialog`` muestra un
``MapCanvas`` auxiliar (``follow=False``) en modo de elegir y devuelve las provincias elegidas. Ninguno edita
nada: el valor lo escribe el formulario en su transacción.

Los usan los campos con ``ui="map_pick"`` de los esquemas (``continent.provinces``, ``default_map.sea_starts``,
``adjacency``), el editor de estrechos y, desde la iteración 6, los de capital y unidades.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QStringListModel, Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from ...core.index.model import KIND_PROVINCE, KIND_SEA_PROVINCE
from ...i18n import tr
from ..widgets import make_icon, mark_data, show_in_stack
from .fields import _Picker, _row

LAND, SEA, ANY = "land", "sea", "any"            # qué provincias admite un selector
_LEADING_ID = re.compile(r"^\s*(\d+)")


def _map(session):
    return getattr(session, "map", None)


def province_ids(session, allow: str = ANY) -> list[int]:
    """Los ids de provincia del índice que admite ``allow``, ordenados."""
    index = getattr(session, "index", None)
    if index is None:
        return []
    kinds = {LAND: (KIND_PROVINCE,), SEA: (KIND_SEA_PROVINCE,)}.get(allow, (KIND_PROVINCE, KIND_SEA_PROVINCE))
    found: set[int] = set()
    for kind in kinds:
        try:
            names = index.names(kind)
        except Exception:  # noqa: BLE001 - un índice falso puede no tener el tipo
            continue
        for name in names:
            if str(name).isdigit():
                found.add(int(name))
    return sorted(found)


def admits(session, pid: int, allow: str) -> bool:
    """Si ``pid`` es una provincia conocida que cumple ``allow``."""
    if allow == ANY:
        return pid in set(province_ids(session, ANY)) or _known_by_map(session, pid)
    return pid in set(province_ids(session, allow))


def _known_by_map(session, pid: int) -> bool:
    map_session = _map(session)
    raster = None if map_session is None else map_session.raster
    return raster is not None and 0 < pid <= getattr(raster, "max_id", 0)


def _name(session, pid: int) -> str:
    map_session = _map(session)
    if map_session is None:
        return ""
    try:
        return map_session.province_name(pid) or ""
    except Exception:  # noqa: BLE001 - sin nombre se muestra el id
        return ""


class ProvincePicker(_Picker):
    """Un id de provincia. ``value()`` es un ``int`` o None («sin valor»)."""

    def __init__(self, session, *, allow: str = ANY, parent: QWidget | None = None):
        """``allow``: ``LAND``, ``SEA`` o ``ANY``; un id que no cumple se marca como inválido y no se confirma."""
        super().__init__(parent)
        self.session = session
        self.allow = allow
        self._value: int | None = None
        row = _row(self)
        self.edit = mark_data(QLineEdit())
        self.edit.setObjectName("provincePicker")
        self.edit.editingFinished.connect(self._commit)
        self.name_label = QLabel()
        self.name_label.setObjectName("provincePickerName")
        self.button = QToolButton()
        self.button.setObjectName("provincePickerMap")
        self.button.setIcon(make_icon("map", "gold_light"))
        self.button.clicked.connect(self.pick_on_map)
        row.addWidget(self.edit, 1)
        row.addWidget(self.name_label)
        row.addWidget(self.button)
        self.reload()
        self.retranslate()

    def value(self) -> int | None:
        return self._value

    def set_value(self, value: int | None) -> None:
        """Pone el valor sin emitir ``value_committed``."""
        self._value = None if value in (None, "") else int(value)
        self._show()
        self._mark(True)

    def _show(self) -> None:
        with QSignalBlocker(self.edit):
            self.edit.setText("" if self._value is None else self._label(self._value))
        self.name_label.setText("")

    def _label(self, pid: int) -> str:
        name = _name(self.session, pid)
        return f"{pid} - {name}" if name else str(pid)

    def _mark(self, valid: bool) -> None:
        self.edit.setProperty("invalid", not valid)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)

    def parse(self, text: str) -> int | None | bool:
        """El id de ``text`` (``"549"``, ``"549 - Berlin"`` o un nombre exacto); None si está vacío; False si
        no se reconoce o no cumple ``allow``."""
        text = text.strip()
        if not text:
            return None
        match = _LEADING_ID.match(text)
        pid = int(match.group(1)) if match else None
        if pid is None:
            wanted = text.casefold()
            for candidate in province_ids(self.session, self.allow):
                if _name(self.session, candidate).casefold() == wanted:
                    pid = candidate
                    break
        if pid is None or not admits(self.session, pid, self.allow):
            return False
        return pid

    def _commit(self) -> None:
        pid = self.parse(self.edit.text())
        if pid is False:
            self._mark(False)
            self.edit.setToolTip(tr("pickers.province.invalid"))
            return
        self._mark(True)
        self.edit.setToolTip("")
        if pid == self._value:
            self._show()
            return
        self._value = pid
        self._show()
        self.value_committed.emit(pid)

    def pick_on_map(self) -> bool:
        """Abre ``MapPickDialog`` centrado en el valor actual; si se acepta, pone la provincia elegida y emite
        ``value_committed``. False si se cancela o el mapa no está disponible."""
        if _map(self.session) is None or getattr(self.session, "project", None) is None:
            return False
        initial = () if self._value is None else (self._value,)
        chosen = MapPickDialog.pick(self.session, initial=initial, allow=self.allow, parent=self)
        if not chosen:
            return False
        pid = chosen[0]
        if pid != self._value:
            self._value = pid
            self._show()
            self._mark(True)
            self.value_committed.emit(pid)
        return True

    def reload(self) -> None:
        """Relee los candidatos del índice (tras ``symbolsChanged``)."""
        labels = [self._label(pid) for pid in province_ids(self.session, self.allow)]
        completer = QCompleter(QStringListModel(labels), self.edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.edit.setCompleter(completer)
        self._show()

    def retranslate(self) -> None:
        self.edit.setPlaceholderText(tr("pickers.province.placeholder"))
        self.button.setToolTip(tr("pickers.province.on_map"))


class _DoubleClick(QObject):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - API de Qt
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self.callback()
            return True
        return False


class MapPickDialog(QDialog):
    """Diálogo modal para elegir una provincia o varias en el mapa."""

    def __init__(self, session, *, multiple: bool = False, initial: Iterable[int] = (), allow: str = ANY,
                 accepts: Callable[[int], bool] | None = None, parent: QWidget | None = None):
        """``multiple``: varias (clic añade o quita) en vez de una (clic elige y acepta con doble clic o
        Aceptar). ``initial``: las ya elegidas, resaltadas y centradas. ``accepts(id)`` descarta provincias
        además de ``allow``. Si el ráster de ``session.map`` no está listo, lo pide y espera mostrándolo."""
        super().__init__(parent)
        self.session = session
        self.multiple = multiple
        self.allow = allow
        self.accepts = accepts
        self._provinces: tuple[int, ...] = tuple(dict.fromkeys(int(pid) for pid in initial))
        self.setObjectName("mapPickDialog")
        self.setWindowTitle(tr("pickers.map.title_many" if multiple else "pickers.map.title_one"))
        self.resize(900, 620)
        from ..map.canvas import PICK_MULTI, PICK_SINGLE, MapCanvas

        layout = QVBoxLayout(self)
        self.hint = QLabel(tr("pickers.map.hint_many" if multiple else "pickers.map.hint_one"))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.stack = QStackedWidget()
        self.canvas = MapCanvas(_map(session), follow=False)
        self.canvas.setObjectName("mapPickCanvas")
        self.canvas.set_pick_mode(PICK_MULTI if multiple else PICK_SINGLE)
        self.canvas.provincePicked.connect(self._on_picked)
        self.canvas.provinceHovered.connect(self._on_hover)
        self._double = _DoubleClick(self._on_double)
        self.canvas.viewport().installEventFilter(self._double)
        waiting = QWidget()
        waiting_layout = QVBoxLayout(waiting)
        self.waiting_label = QLabel(tr("map.empty.loading_text"))
        self.waiting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waiting_bar = QProgressBar()
        self.waiting_bar.setRange(0, 0)
        waiting_layout.addStretch(1)
        waiting_layout.addWidget(self.waiting_label)
        waiting_layout.addWidget(self.waiting_bar)
        waiting_layout.addStretch(1)
        self.waiting = waiting
        self.stack.addWidget(waiting)
        self.stack.addWidget(self.canvas)
        layout.addWidget(self.stack, 1)
        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("mapPickStatus")
        self.hover = QLabel()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.hover)
        layout.addLayout(bottom)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("pickers.map.accept"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("entity.cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        map_session = _map(session)
        if map_session is not None:
            map_session.rasterStateChanged.connect(self._on_raster_state)
            if map_session.raster is None:
                map_session.load_raster()
            elif map_session.facts is None:
                map_session.refresh_facts()
        self.canvas.set_mode("political")
        self._on_raster_state()
        self._sync()

    # --- API ------------------------------------------------------------------------------------------

    def provinces(self) -> tuple[int, ...]:
        """Las elegidas, en el orden en que se eligieron (una como mucho sin ``multiple``)."""
        return self._provinces if self.multiple else self._provinces[-1:]

    def set_provinces(self, pids: Iterable[int]) -> None:
        chosen = tuple(dict.fromkeys(int(pid) for pid in pids if self.admits(int(pid))))
        self._provinces = chosen if self.multiple else chosen[-1:]
        self._sync()

    def admits(self, pid: int) -> bool:
        if not pid:
            return False
        if self.allow != ANY and not admits(self.session, pid, self.allow):
            return False
        return self.accepts is None or bool(self.accepts(pid))

    @staticmethod
    def pick(session, *, multiple: bool = False, initial: Iterable[int] = (), allow: str = ANY,
             accepts: Callable[[int], bool] | None = None, parent: QWidget | None = None) -> tuple[int, ...] | None:
        """Abre el diálogo y devuelve las provincias elegidas; None si se cancela."""
        dialog = MapPickDialog(session, multiple=multiple, initial=initial, allow=allow, accepts=accepts,
                               parent=parent)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            return dialog.provinces()
        finally:
            dialog.deleteLater()

    # --- interacción ----------------------------------------------------------------------------------

    def _on_raster_state(self, *args) -> None:
        map_session = _map(self.session)
        ready = map_session is not None and map_session.raster is not None
        show_in_stack(self.stack, self.canvas if ready else self.waiting)
        if ready and self._provinces:
            self.canvas.center_on_province(self._provinces[-1])

    def _on_picked(self, pid: int) -> None:
        if not self.admits(pid):
            self.status.setText(tr("pickers.map.rejected", id=pid))
            self.canvas.set_selection(self._provinces)
            return
        if self.multiple:
            current = list(self._provinces)
            if pid in current:
                current.remove(pid)
            else:
                current.append(pid)
            self._provinces = tuple(current)
        else:
            self._provinces = (pid,)
        self._sync()

    def _on_double(self) -> None:
        if not self.multiple and self._provinces:
            self.accept()

    def _on_hover(self, pid: int) -> None:
        if not pid:
            self.hover.setText("")
            return
        self.hover.setText(tr("map.hover", id=pid, name=_name(self.session, pid) or "—"))

    def _sync(self) -> None:
        self.canvas.set_selection(self._provinces)
        if self._provinces:
            shown = ", ".join(str(pid) for pid in self._provinces[:12])
            if len(self._provinces) > 12:
                shown += " …"
            self.status.setText(tr("pickers.map.chosen", count=len(self._provinces), ids=shown))
        else:
            self.status.setText(tr("pickers.map.none"))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(self.multiple or bool(self._provinces))
