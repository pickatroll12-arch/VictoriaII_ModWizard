"""Frase legible de un bloque de guion, bajo cada constructor y en el formulario (wizard §12.3, §13.6).

``PhraseView`` enseña la frase de ``core.script.phrases`` en una línea que se despliega por niveles
(``phrase_lines``), marca los nodos crudos y los problemas, y lleva el botón «Editar condiciones…» /
«Editar efectos…». En el formulario generado es el editor de un campo ``Script`` (el gancho de ``ui/forms``
sustituye al botón «Editar como código…» de la iteración 4, que queda como alternativa).

La frase sale del catálogo y de los nombres del mod (países, gobiernos, provincias): son datos y se marcan
como tales (``mark_data``); los botones y la insignia pasan por ``tr``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ...core.script.scopes import ScriptKind
from ...i18n import N_, tr, translator
from ..widgets import mark_data

_PATH = Qt.ItemDataRole.UserRole


class PhraseView(QWidget):
    """La frase de un ``ScriptTree`` (o un texto ya hecho)."""

    edit_requested = Signal()                    # el botón que abre el constructor
    node_activated = Signal(object)              # tuple[int, ...]: clic en una línea de la frase desplegada

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("phraseView")
        self._tree = None
        self._lead = None
        self._index = None
        self._loc = None
        self._text = ""
        self._problems = 0
        self._expanded = False
        self._read_only = False
        self._manual_text: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        self.label = mark_data(QLabel())
        self.label.setObjectName("phraseText")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("phraseProblems")
        self.badge.setProperty("role", "badge")
        row.addWidget(self.badge)
        self.expand_button = QPushButton()
        self.expand_button.setObjectName("phraseExpand")
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self.set_expanded)
        row.addWidget(self.expand_button)
        self.edit_button = QPushButton()
        self.edit_button.setObjectName("phraseEdit")
        self.edit_button.clicked.connect(self.edit_requested)
        row.addWidget(self.edit_button)
        outer.addLayout(row)
        self.lines = mark_data(QListWidget())
        self.lines.setObjectName("phraseLines")
        self.lines.setMaximumHeight(160)
        self.lines.itemActivated.connect(lambda item: self.node_activated.emit(item.data(_PATH)))
        self.lines.hide()
        outer.addWidget(self.lines)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def _lang(self) -> str:
        from .trigger_builder import phrase_language

        return phrase_language()

    def set_tree(self, tree, *, lead: str | None = None, index=None, loc=None) -> None:
        """Enseña la frase de ``tree`` (None: «sin bloque»). ``lead``: uno de ``phrases.LEADS``."""
        self._tree, self._lead, self._index, self._loc = tree, lead, index, loc
        self._manual_text = None
        if tree is not None:
            count = 0
            for node in tree.walk():
                try:
                    count += len(node.issues())
                except Exception:  # noqa: BLE001
                    pass
            self._problems = count
        else:
            self._problems = 0
        self._render()

    def set_text(self, text: str) -> None:
        """Enseña un texto ya hecho (pruebas, vistas previas)."""
        self._tree = None
        self._manual_text = text
        self._render()

    def text(self) -> str:
        """La frase en una línea, tal como se ve."""
        return self._text

    def set_problem_count(self, count: int) -> None:
        """Cuántos problemas tiene el bloque (insignia junto al botón)."""
        self._problems = max(0, int(count))
        self._render_badge()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        if self.expand_button.isChecked() != self._expanded:
            self.expand_button.blockSignals(True)
            self.expand_button.setChecked(self._expanded)
            self.expand_button.blockSignals(False)
        self._render_lines()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self.retranslate()

    def _render(self) -> None:
        if self._manual_text is not None:
            self._text = self._manual_text
        elif self._tree is None:
            self._text = tr(N_("script_ui.phrase.no_block"))
        else:
            from ...core.script.phrases import phrase

            try:
                self._text = phrase(self._tree, self._lang(), self._index, self._loc, lead=self._lead)
            except Exception:  # noqa: BLE001 - una frase que falla se ve como el código del bloque
                self._text = self._tree.root.source()
        self.label.setText(self._text)
        self.expand_button.setVisible(self._tree is not None and bool(self._tree.root.children))
        self._render_badge()
        self._render_lines()

    def _render_badge(self) -> None:
        self.badge.setText(tr(N_("script_ui.phrase.problems"), count=self._problems))
        self.badge.setVisible(self._problems > 0)

    def _render_lines(self) -> None:
        self.lines.clear()
        show = self._expanded and self._tree is not None
        self.lines.setVisible(show)
        if not show:
            return
        from ...core.script.phrases import phrase_lines

        try:
            lines = phrase_lines(self._tree, self._lang(), self._index, self._loc)
        except Exception:  # noqa: BLE001
            lines = []
        for line in lines:
            prefix = "    " * max(0, int(getattr(line, "depth", 0)))
            item = QListWidgetItem(prefix + str(getattr(line, "text", "")))
            item.setData(_PATH, tuple(getattr(line, "path", ()) or ()))
            self.lines.addItem(item)

    def _on_language(self, _code: str = "") -> None:
        self.retranslate()

    def retranslate(self) -> None:
        kind = getattr(self._tree, "kind", None)
        effects = kind == ScriptKind.EFFECT
        if self._read_only:
            key = N_("script_ui.phrase.view")
        else:
            key = N_("script_ui.phrase.edit_effects") if effects else N_("script_ui.phrase.edit_conditions")
        self.edit_button.setText(tr(key))
        self.expand_button.setText(tr(N_("script_ui.phrase.expand")))
        self._render()
