"""Páginas de grupos de provincias de la sala Mapa (wizard §16.4): «Regiones» (estados y regiones marítimas) y
«Continentes y climas».

Una página de grupos tiene a la izquierda un lienzo con el modo de mapa del grupo y a la derecha la lista de
grupos del archivo elegido, con cuántas provincias tiene cada uno, y los miembros del grupo elegido. Se puede:

- crear, renombrar y borrar un grupo (borrar solo si está vacío, §14.14);
- pintar provincias en el grupo con la brocha (un trazo, un paso de deshacer);
- elegir en el mapa los miembros exactos del grupo (``MapPickDialog`` con varias), o quitar los marcados.

Todo pasa por ``session.map`` (``set_group_members``, ``move_to_group``, ``group_edit``), que deja el resto del
archivo byte a byte (``core/map/groups.py``) y actualiza el mapa sin esperar al índice.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ....core.map.groups import GroupError
from ....i18n import N_, language, tr
from ...map.canvas import PICK_BRUSH, PICK_NONE, MapCanvas
from ...pages.base import BasePage
from ...pickers.province_picker import MapPickDialog
from ...session_map import RASTER_FAILED, RASTER_LOADING, RASTER_READY
from ...widgets import EmptyState, make_icon, show_in_stack

KIND_LABELS = {
    "region": N_("map.groups.kind.region"), "region_sea": N_("map.groups.kind.region_sea"),
    "continent": N_("map.groups.kind.continent"), "climate": N_("map.groups.kind.climate"),
}
KIND_MODES = {"region": "regions", "region_sea": "regions", "continent": "continents", "climate": "climates"}
GROUP_ERRORS = {
    "unknown_group": N_("map.groups.error.unknown_group"), "group_exists": N_("map.groups.error.group_exists"),
    "group_not_empty": N_("map.groups.error.group_not_empty"), "bad_name": N_("map.groups.error.bad_name"),
    "paired_layout": N_("map.groups.error.paired_layout"),
}
ROLE_GROUP = Qt.ItemDataRole.UserRole
ROLE_PROVINCE = Qt.ItemDataRole.UserRole + 1


class GroupsPage(BasePage):
    """Página de grupos para ``kinds`` (claves de ``MapSession.GROUP_KINDS``)."""

    kinds: tuple[str, ...] = ()

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.map = session.map
        self._group: str | None = None
        super().__init__(parent)
        self.map.rasterStateChanged.connect(self._update_state)
        self.map.factsChanged.connect(self._on_facts_changed)
        session.projectOpened.connect(self._reload)
        session.projectClosed.connect(self._reload)
        session.documentsChanged.connect(self._reload)
        self._reload()

    # --- construcción -----------------------------------------------------------------------------------

    def build(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.canvas = MapCanvas(self.map, follow=False)
        self.canvas.setMinimumSize(320, 240)
        self.canvas.provinceClicked.connect(self._on_clicked)
        self.canvas.strokeFinished.connect(self._on_stroke)
        self.canvas.provinceHovered.connect(self._on_hover)
        self.empty = EmptyState("map")
        self.load_button = QPushButton()
        self.load_button.setObjectName("groupsLoad")
        self.load_button.clicked.connect(lambda: self.map.load_raster(force=self.map.raster_state == RASTER_FAILED))
        self.empty.add_action(self.load_button)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas)
        left_layout.addWidget(self.stack, 1)
        self.hover_label = QLabel()
        left_layout.addWidget(self.hover_label)
        splitter.addWidget(left)

        right = QWidget()
        right.setMinimumWidth(380)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(6, 0, 0, 0)
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("groupsKind")
        for kind in self.kinds:
            self.kind_combo.addItem("", kind)
        self.kind_combo.currentIndexChanged.connect(self._on_kind)
        if len(self.kinds) <= 1:
            self.kind_combo.hide()
        layout.addWidget(self.kind_combo)
        self.groups_label = QLabel()
        layout.addWidget(self.groups_label)
        self.group_list = QListWidget()
        self.group_list.setObjectName("groupsList")
        self.group_list.currentItemChanged.connect(self._on_group_selected)
        layout.addWidget(self.group_list, 2)
        buttons = QHBoxLayout()
        self.new_button = self._button("groupNew", "plus", lambda: self._edit_group("create"))
        self.rename_button = self._button("groupRename", "quill", lambda: self._edit_group("rename"))
        self.delete_button = self._button("groupDelete", "trash", lambda: self._edit_group("delete"))
        for button in (self.new_button, self.rename_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.members_label = QLabel()
        self.members_label.setObjectName("groupMembersLabel")
        self.members_label.setWordWrap(True)
        layout.addWidget(self.members_label)
        self.members = QListWidget()
        self.members.setObjectName("groupMembers")
        self.members.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.members.itemDoubleClicked.connect(self._on_member_activated)
        layout.addWidget(self.members, 3)
        tools = QHBoxLayout()
        self.paint_button = QToolButton()
        self.paint_button.setObjectName("groupPaint")
        self.paint_button.setCheckable(True)
        self.paint_button.setIcon(make_icon("quill", "gold_light"))
        self.paint_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.paint_button.toggled.connect(self._on_paint_toggled)
        self.pick_button = self._button("groupPick", "map", self._pick_members)
        self.remove_button = self._button("groupRemoveMembers", "minus", self._remove_members)
        tools.addWidget(self.paint_button)
        tools.addWidget(self.pick_button)
        tools.addStretch(1)
        layout.addLayout(tools)
        tools_second = QHBoxLayout()
        tools_second.addWidget(self.remove_button)
        tools_second.addStretch(1)
        layout.addLayout(tools_second)
        self.status_label = QLabel()
        self.status_label.setObjectName("groupsStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.body.addWidget(splitter, 1)

    @staticmethod
    def _button(name: str, icon: str, slot) -> QPushButton:
        button = QPushButton()
        button.setObjectName(name)
        button.setIcon(make_icon(icon, "gold_light"))
        button.clicked.connect(slot)
        return button

    def retranslate(self) -> None:
        super().retranslate()
        for index in range(self.kind_combo.count()):
            self.kind_combo.setItemText(index, tr(KIND_LABELS[self.kind_combo.itemData(index)]))
        self.groups_label.setText(tr("map.groups.list"))
        self.new_button.setText(tr("map.groups.new"))
        self.rename_button.setText(tr("map.groups.rename"))
        self.delete_button.setText(tr("map.groups.delete"))
        self.paint_button.setText(tr("map.groups.paint"))
        self.paint_button.setToolTip(tr("map.groups.paint_tooltip"))
        self.pick_button.setText(tr("map.groups.pick"))
        self.remove_button.setText(tr("map.groups.remove"))
        self.load_button.setText(tr("map.load"))
        self._update_state()
        self._reload()

    # --- estado -------------------------------------------------------------------------------------------

    def kind(self) -> str:
        return self.kind_combo.currentData() or self.kinds[0]

    def _update_state(self, *args) -> None:
        state = self.map.raster_state
        if self.session.project is None:
            self.empty.set_texts(tr("map.empty.no_project"), tr("map.empty.no_project_text"))
            self.load_button.hide()
            show_in_stack(self.stack, self.empty)
        elif state == RASTER_READY:
            show_in_stack(self.stack, self.canvas)
            self.canvas.set_mode(KIND_MODES[self.kind()])
            self.canvas.set_selection(self._members())
        elif state == RASTER_LOADING:
            self.empty.set_texts(tr("map.empty.loading"), tr("map.empty.loading_text"))
            self.load_button.hide()
            show_in_stack(self.stack, self.empty)
        else:
            failed = state == RASTER_FAILED
            self.empty.set_texts(tr("map.empty.failed" if failed else "map.empty.idle"),
                                 tr(self.map.raster_error or "map.error.other") if failed
                                 else tr("map.empty.idle_text"))
            self.load_button.show()
            show_in_stack(self.stack, self.empty)

    def showEvent(self, event) -> None:  # noqa: N802 - API de Qt
        super().showEvent(event)
        if self.session.project is not None and self.map.raster_state not in (RASTER_READY, RASTER_LOADING,
                                                                               RASTER_FAILED):
            self.map.load_raster()
        if self.map.raster is not None and self.map.facts is None:
            self.map.refresh_facts()

    def is_busy(self) -> bool:
        return self.map.raster_state == RASTER_LOADING

    def _groups(self):
        if self.session.project is None:
            return None
        try:
            return self.map.groups(self.kind())
        except (KeyError, FileNotFoundError, OSError):
            return None

    def _group_of(self, pid: int) -> str | None:
        groups = self._groups()
        try:
            return None if groups is None else groups.group_of(pid)
        except (FileNotFoundError, OSError):
            return None

    def _members(self) -> list[int]:
        groups = self._groups()
        if groups is None or not self._group:
            return []
        try:
            return groups.members(self._group)
        except (GroupError, FileNotFoundError, OSError):
            return []

    def _display(self, gid: str) -> str:
        locsync = self.session.locsync
        text = None
        if locsync is not None:
            try:
                text = locsync.text(gid, language())
            except Exception:  # noqa: BLE001 - un texto que no se lee deja el nombre
                text = None
        return f"{text} ({gid})" if text and text != gid else gid

    def _reload(self, *args) -> None:
        groups = self._groups()
        self.group_list.blockSignals(True)
        try:
            self.group_list.clear()
            try:
                members = {} if groups is None else groups.all_members()
            except (FileNotFoundError, OSError):      # el archivo no existe en el mod ni en el juego
                members = {}
            for gid, ids in members.items():
                count = len(ids)
                item = QListWidgetItem(tr("map.groups.item", name=self._display(gid), count=count))
                item.setData(ROLE_GROUP, gid)
                self.group_list.addItem(item)
                if gid == self._group:
                    self.group_list.setCurrentItem(item)
            if self._group not in members:
                self._group = None
        finally:
            self.group_list.blockSignals(False)
        has_project = groups is not None
        for button in (self.new_button,):
            button.setEnabled(has_project)
        self._show_members()

    def _show_members(self) -> None:
        members = self._members()
        selected = self._group is not None
        for button in (self.rename_button, self.delete_button, self.pick_button, self.remove_button,
                       self.paint_button):
            button.setEnabled(selected)
        if not selected and self.paint_button.isChecked():
            self.paint_button.setChecked(False)
        self.members.clear()
        for pid in members:
            name = self.map.province_name(pid)
            item = QListWidgetItem(f"{pid} - {name}" if name else str(pid))
            item.setData(ROLE_PROVINCE, pid)
            self.members.addItem(item)
        if selected:
            self.members_label.setText(tr("map.groups.members", group=self._group, count=len(members)))
        else:
            self.members_label.setText(tr("map.groups.pick_group"))
        if self.map.raster is not None:
            self.canvas.set_selection(members)

    # --- reacciones ---------------------------------------------------------------------------------------

    def _on_kind(self, *args) -> None:
        self._group = None
        if self.map.raster is not None:
            self.canvas.set_mode(KIND_MODES[self.kind()])
        self._reload()

    def _on_group_selected(self, current, _previous) -> None:
        self._group = None if current is None else current.data(ROLE_GROUP)
        self._show_members()

    def select_group(self, gid: str) -> bool:
        for row in range(self.group_list.count()):
            item = self.group_list.item(row)
            if item.data(ROLE_GROUP) == gid:
                self.group_list.setCurrentItem(item)
                return True
        return False

    def _on_clicked(self, pid: int, modifiers) -> None:
        if not pid:
            return
        gid = self._group_of(pid)
        if gid:
            self.select_group(gid)
            self._select_member(pid)
        else:
            self.status_label.setText(tr("map.groups.no_group", id=pid))

    def _select_member(self, pid: int) -> None:
        for row in range(self.members.count()):
            item = self.members.item(row)
            if item.data(ROLE_PROVINCE) == pid:
                self.members.setCurrentItem(item)
                self.members.scrollToItem(item)
                return

    def _on_member_activated(self, item) -> None:
        pid = item.data(ROLE_PROVINCE)
        if pid:
            self.canvas.center_on_province(int(pid))

    def _on_hover(self, pid: int) -> None:
        if not pid:
            self.hover_label.setText("")
            return
        gid = self._group_of(pid)
        text = tr("map.hover", id=pid, name=self.map.province_name(pid) or "—")
        self.hover_label.setText(f"{text} · {gid}" if gid else text)

    def _on_facts_changed(self, pids) -> None:
        if self.map.raster is not None and self.stack.currentWidget() is not self.canvas:
            self._update_state()

    # --- ediciones ----------------------------------------------------------------------------------------

    def _fits(self, pid: int) -> bool:
        """Lo que la brocha y el diálogo admiten: tierra en los estados, mar en las regiones marítimas."""
        provinces = self.map.provinces
        if provinces is None:
            return False
        kind = self.kind()
        if kind == "region":
            return not provinces.is_sea(pid)
        if kind == "region_sea":
            return provinces.is_sea(pid)
        return True

    def _on_paint_toggled(self, on: bool) -> None:
        self.canvas.set_pick_mode(PICK_BRUSH if on else PICK_NONE)
        self.status_label.setText(tr("map.groups.paint_hint", group=self._group or "—") if on else "")

    def _on_stroke(self, pids) -> None:
        if not self._group:
            return
        wanted = [pid for pid in pids if self._fits(pid)]
        try:
            moved = self.map.move_to_group(self.kind(), wanted, self._group) if wanted else 0
        except GroupError as exc:
            self._error(exc)
            moved = 0
        self.status_label.setText(tr("map.groups.moved", count=moved, group=self._group))
        self._reload()

    def _pick_members(self) -> None:
        if not self._group:
            return
        chosen = MapPickDialog.pick(self.session, multiple=True, initial=self._members(), accepts=self._fits,
                                    parent=self)
        if chosen is None:
            return
        self.apply_members(chosen)

    def apply_members(self, pids) -> tuple[int, int]:
        """Deja el grupo elegido con ``pids`` exactamente (lo que hace «Elegir en el mapa» al aceptar)."""
        if not self._group:
            return 0, 0
        try:
            added, removed = self.map.set_group_members(self.kind(), self._group, pids)
        except GroupError as exc:
            self._error(exc)
            return 0, 0
        self.status_label.setText(tr("map.groups.applied", added=added, removed=removed))
        self._reload()
        return added, removed

    def _remove_members(self) -> None:
        if not self._group:
            return
        doomed = {item.data(ROLE_PROVINCE) for item in self.members.selectedItems()}
        if not doomed:
            self.status_label.setText(tr("map.groups.remove_none"))
            return
        self.apply_members([pid for pid in self._members() if pid not in doomed])

    def ask_name(self, title_key: str, current: str = "") -> str | None:
        """Pide el nombre de un grupo (sustituible en las pruebas)."""
        text, ok = QInputDialog.getText(self, tr(title_key), tr("map.groups.name"), text=current)
        return text.strip() if ok and text.strip() else None

    def edit_group(self, action: str, gid: str, new: str | None = None) -> bool:
        """``create``/``rename``/``delete`` sin diálogos; True si se hizo."""
        try:
            self.map.group_edit(self.kind(), action, gid, new)
        except GroupError as exc:
            self._error(exc)
            return False
        self._group = new if action == "rename" else (gid if action == "create" else None)
        self._reload()
        self.status_label.setText(tr(f"map.groups.done.{action}", group=gid, new=new or ""))
        return True

    def _edit_group(self, action: str) -> None:
        if action == "create":
            name = self.ask_name(N_("map.groups.new_title"))
            if name:
                self.edit_group("create", name)
        elif action == "rename" and self._group:
            name = self.ask_name(N_("map.groups.rename_title"), self._group)
            if name and name != self._group:
                self.edit_group("rename", self._group, name)
        elif action == "delete" and self._group:
            self.edit_group("delete", self._group)

    def _error(self, exc: GroupError) -> None:
        self.status_label.setText(tr(GROUP_ERRORS.get(exc.code, "map.groups.error.unknown_group"),
                                     group=exc.group))

    def focus_field(self, ref, field=()) -> bool:
        """Abre el grupo de ``ref`` (``region:<id>``, ``continent:<id>``…) en su archivo."""
        kind = getattr(ref, "kind", "")
        ident = str(getattr(ref, "ident", ref))
        if kind in self.kinds:
            index = self.kind_combo.findData(kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        return self.select_group(ident)


# Los textos ``map.groups.done.*`` se piden con f-string; aquí, literales para el catálogo.
DONE_KEYS = (N_("map.groups.done.create"), N_("map.groups.done.rename"), N_("map.groups.done.delete"))


class RegionsPage(GroupsPage):
    key = "regions"
    title_key = N_("section.map.regions")
    subtitle_key = N_("map.regions.subtitle")
    icon_name = "layers"
    kinds = ("region", "region_sea")


class ClimatesPage(GroupsPage):
    key = "climates"
    title_key = N_("section.map.climates")
    subtitle_key = N_("map.climates.subtitle")
    icon_name = "climate"
    kinds = ("continent", "climate")
