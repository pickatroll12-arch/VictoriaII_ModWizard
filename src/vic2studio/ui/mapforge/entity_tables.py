"""Tablas del taller (wizard §18.2, pantallas 10 y 11): nombres de provincias y estados, y estrechos sugeridos.

La tabla de nombres marca los repetidos y los que no caben en cp1252 (el juego lee la localización en cp1252); al
editar un nombre emite ``renamed(clase, índice provisional, nombre)`` y el asistente lo guarda como una edición
``rename`` ligada a una celda, que sobrevive a regenerar los pasos anteriores.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from ...core.mapforge.names import cp1252_ok
from ...i18n import N_, tr

NAME_COLUMNS = (N_("forge.names.col.id"), N_("forge.names.col.kind"), N_("forge.names.col.name"),
                N_("forge.names.col.area"), N_("forge.names.col.state"), N_("forge.names.col.owner"),
                N_("forge.names.col.check"))
STRAIT_COLUMNS = (N_("forge.straits.col.from"), N_("forge.straits.col.to"), N_("forge.straits.col.through"),
                  N_("forge.straits.col.gap"))
ROLE = Qt.ItemDataRole.UserRole
WARN = QColor(200, 70, 40)


class NamesTable(QTableWidget):
    renamed = Signal(str, int, str)        # ("p" | "s", índice provisional, nombre)

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(NAME_COLUMNS), parent)
        self.setObjectName("forgeNames")
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.itemChanged.connect(self._on_changed)
        self._filling = False
        self.world = None

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([tr(k) for k in NAME_COLUMNS])
        self.fill(self.world)

    def fill(self, world) -> None:
        self.world = world
        self._filling = True
        try:
            self.setRowCount(0)
            r = getattr(world, "raster", None)
            if r is None:
                return
            pn = list(world.entities.get("province_names") or [])
            sn = list(world.entities.get("state_names") or [])
            owners = list(world.entities.get("owners") or [])
            dup = Counter([n for n in pn if n] + [n for n in sn if n])
            areas = np.bincount(r.ids.ravel(), minlength=r.count + 1)
            rows = []
            for pid in range(1, r.land_count + 1):
                par = int(r.parent[pid]) if r.parent is not None else pid - 1
                name = r.names[pid] if r.names and r.names[pid] else (pn[par] if 0 <= par < len(pn) else "")
                st = int(r.state[pid]) if r.state is not None else -1
                ow = int(r.owner[pid]) if r.owner is not None else -1
                rows.append(("p", par, str(pid), name, int(areas[pid]),
                             sn[st] if 0 <= st < len(sn) else "—", owners[ow] if 0 <= ow < len(owners) else "—"))
            seen_states = set()
            for pid in range(1, r.land_count + 1):
                st = int(r.state[pid]) if r.state is not None else -1
                if st < 0 or st in seen_states or st >= len(sn):
                    continue
                seen_states.add(st)
                rows.append(("s", int(r.parent[pid]) if r.parent is not None else pid - 1, f"S{st + 1}", sn[st],
                             int(areas[r.state == st].sum()) if r.state is not None else 0, "—", "—"))
            self.setRowCount(len(rows))
            for i, (kind, par, ident, name, area, state, owner) in enumerate(rows):
                problems = []
                if not cp1252_ok(name):
                    problems.append(tr("forge.names.not_cp1252"))
                if dup[name] > 1:
                    problems.append(tr("forge.names.duplicate"))
                kind_text = tr("forge.names.kind.province" if kind == "p" else "forge.names.kind.state")
                vals = (ident, kind_text, name, str(area), state, owner, ", ".join(problems))
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if c != 2:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if problems and c in (2, 6):
                        item.setForeground(QBrush(WARN))
                    item.setData(ROLE, (kind, par))
                    self.setItem(i, c, item)
        finally:
            self._filling = False

    def _on_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 2:
            return
        kind, par = item.data(ROLE)
        name = item.text().strip()
        if name:
            self.renamed.emit(kind, int(par), name)


class StraitsTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(0, len(STRAIT_COLUMNS), parent)
        self.setObjectName("forgeStraits")
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.world = None

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([tr(k) for k in STRAIT_COLUMNS])

    def fill(self, world) -> None:
        self.world = world
        r = getattr(world, "raster", None)
        straits = r.straits if r is not None and r.straits is not None else np.zeros((0, 4), np.int64)
        self.setRowCount(len(straits))
        names = r.names if r is not None else None
        for i, row in enumerate(np.asarray(straits).tolist()):
            a, b, t, gap = (int(v) for v in row[:4])
            vals = (f"{a} {names[a] or ''}" if names else str(a), f"{b} {names[b] or ''}" if names else str(b),
                    str(t), tr("forge.straits.gap_px", px=gap * (r.scale if r is not None else 1)))
            for c, v in enumerate(vals):
                self.setItem(i, c, QTableWidgetItem(v))


__all__ = ["NamesTable", "StraitsTable"]
