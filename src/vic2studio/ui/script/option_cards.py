"""Opciones de un evento: una tarjeta por ``option`` (wizard §14.7).

Cada tarjeta lleva el texto de la opción en ES y EN (la clave es el valor de ``name``; el texto se edita con
``LocSync``, en la misma transacción), un ``EffectBuilder`` con el resto del bloque y un ``MtthEditor`` para
su ``ai_chance``. «Añadir opción» propone la siguiente clave libre ``EVTOPT<letra><id>``. En vanilla un
evento tiene de 1 a 5 opciones (987 de 1 064 tienen una o dos) y solo 72 de 1 655 llevan ``ai_chance``, así
que ese editor va plegado.

Quitar una opción conserva sus filas de texto: en vanilla 352 nombres de opción comparten clave con otro
evento, y una fila de más no rompe nada (la validación de textos huérfanos ya la señala).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.nodes import Scalar
from ...core.schema.fields import REST
from ...core.schema.record import option_letter
from ...core.script.mtth import AI_CHANCE_KEY
from ...i18n import N_, tr, translator
from ..widgets import make_icon, mark_data
from .effect_builder import EffectBuilder
from .mtth_editor import MtthEditor
from .phrase_view import PhraseView
from .trigger_builder import ScriptBinding

OPTION_KEY = "option"
NAME_KEY = "name"
LOC_AREA = "events"
LANGS = ("es", "en")
UNDO_KEYS = {"add": N_("events.option.undo.add"), "remove": N_("events.option.undo.remove"),
             "move": N_("events.option.undo.move"), "text": N_("events.option.undo.text")}


def _loc(session):
    return getattr(session, "locsync", None)


class OptionCard(QFrame):
    """Una opción. ``effects`` es su ``EffectBuilder``, ``ai_chance`` su ``MtthEditor`` y ``index`` su
    posición entre las opciones del evento."""

    index: int
    effects: object
    ai_chance: object
    text_changed = Signal(int)

    def __init__(self, session, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.index = index
        self._ref = None
        self._key: str | None = None
        self._read_only = False
        self.setObjectName(f"optionCard{index}")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("optionTitle")
        self.title.setProperty("role", "heading")
        self.key_label = mark_data(QLabel())
        self.key_label.setObjectName("optionKey")
        self.up_button = QPushButton()
        self.up_button.setObjectName("optionUp")
        self.up_button.setIcon(make_icon("chevron_up", "ink"))
        self.down_button = QPushButton()
        self.down_button.setObjectName("optionDown")
        self.down_button.setIcon(make_icon("chevron_down", "ink"))
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("optionRemove")
        self.remove_button.setIcon(make_icon("trash", "ink"))
        top.addWidget(self.title)
        top.addWidget(self.key_label, 1)
        for button in (self.up_button, self.down_button, self.remove_button):
            top.addWidget(button)
        outer.addLayout(top)
        form = QFormLayout()
        self.text_labels = {}
        self.text_edits: dict[str, QLineEdit] = {}
        for lang in LANGS:
            label = QLabel()
            edit = mark_data(QLineEdit())
            edit.setObjectName(f"optionText_{lang}")
            edit.editingFinished.connect(lambda lang=lang: self._commit_text(lang))
            self.text_labels[lang] = label
            self.text_edits[lang] = edit
            form.addRow(label, edit)
        outer.addLayout(form)
        self.effects_title = QLabel()
        outer.addWidget(self.effects_title)
        self.phrase = PhraseView()
        self.phrase.setObjectName("optionPhrase")
        self.phrase.edit_requested.connect(self._toggle_effects)
        outer.addWidget(self.phrase)
        self.effects = EffectBuilder(session)
        self.effects.setObjectName("optionEffects")
        self.effects.changed.connect(self._refresh_phrase)
        self.effects.hide()
        outer.addWidget(self.effects)
        self.ai_toggle = QPushButton()
        self.ai_toggle.setObjectName("optionAiToggle")
        self.ai_toggle.setCheckable(True)
        self.ai_toggle.toggled.connect(lambda on: self.ai_chance.setVisible(on))
        outer.addWidget(self.ai_toggle)
        self.ai_chance = MtthEditor(session, key=AI_CHANCE_KEY)
        self.ai_chance.hide()
        outer.addWidget(self.ai_chance)
        self.retranslate()

    # --- enlace -----------------------------------------------------------------------------------

    def bind(self, ref, record_view) -> None:
        """Enlaza con la opción ``index`` del evento ``ref``; ``record_view`` es su vista de grupo."""
        self._ref = ref
        name = record_view.get(NAME_KEY, None) if record_view is not None else None
        self._key = name if isinstance(name, str) and name else None
        self.key_label.setText(self._key or "")
        self.effects.bind(ScriptBinding(ref, (OPTION_KEY, self.index, REST)))
        self.ai_chance.bind(ref, (OPTION_KEY, self.index))
        has_ai = self.ai_chance.model() is not None
        self.ai_toggle.blockSignals(True)
        self.ai_toggle.setChecked(has_ai)
        self.ai_toggle.blockSignals(False)
        self.ai_chance.setVisible(has_ai)
        for lang, edit in self.text_edits.items():
            edit.setText(self.text(lang))
        self._refresh_phrase()

    def _refresh_phrase(self) -> None:
        index = getattr(self.session, "index", None)
        loc = None
        finder = getattr(self.session, "_loc_for_search", None)
        if callable(finder):
            try:
                loc = finder()
            except Exception:  # noqa: BLE001
                loc = None
        self.phrase.set_tree(self.effects.tree(), lead="option", index=index, loc=loc)
        self.phrase.set_problem_count(self.effects.problem_count())

    def _toggle_effects(self) -> None:
        self.effects.setVisible(not self.effects.isVisible())

    def name_key(self) -> str | None:
        """La clave de localización de la opción (el valor de ``name``); None si no tiene."""
        return self._key

    def text(self, lang: str) -> str:
        """El texto de la opción en ``lang`` (vacío si la clave no tiene texto)."""
        loc = _loc(self.session)
        if self._key is None or loc is None:
            return ""
        try:
            return loc.text(self._key, lang) or ""
        except Exception:  # noqa: BLE001
            return ""

    def set_text(self, lang: str, text: str) -> bool:
        """Cambia el texto en ``lang`` (un paso de deshacer)."""
        loc = _loc(self.session)
        if self._key is None or loc is None or self._read_only or text == self.text(lang):
            return False
        try:
            with self.session.edit(UNDO_KEYS["text"], merge_key=f"loc.{self._key}.{lang}", key=self._key,
                                   lang=lang):
                loc.set_text(self._key, lang, text, area=LOC_AREA)
        except (ValueError, KeyError, OSError) as exc:
            self.effects.status_requested.emit(N_("script_ui.rejected"), {"error": str(exc)})
            return False
        self.text_changed.emit(self.index)
        return True

    def _commit_text(self, lang: str) -> None:
        self.set_text(lang, self.text_edits[lang].text())

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        for edit in self.text_edits.values():
            edit.setReadOnly(self._read_only)
        for button in (self.up_button, self.down_button, self.remove_button):
            button.setEnabled(not self._read_only)
        self.effects.set_read_only(read_only)
        self.ai_chance.set_read_only(read_only)
        self.phrase.set_read_only(read_only)

    def commit_pending(self) -> None:
        for lang, edit in self.text_edits.items():
            if edit.hasFocus():
                self._commit_text(lang)
        self.effects.commit_pending()
        self.ai_chance.commit_pending()

    def _on_language(self, _code: str = "") -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.title.setText(tr(N_("events.option.title"), letter=option_letter(self.index)))
        for lang, label in self.text_labels.items():
            label.setText(tr(N_("events.option.text_es") if lang == "es" else N_("events.option.text_en")))
        self.effects_title.setText(tr(N_("events.option.effects")))
        self.ai_toggle.setText(tr(N_("events.option.ai_chance")))
        self.up_button.setToolTip(tr(N_("events.option.up")))
        self.down_button.setToolTip(tr(N_("events.option.down")))
        self.remove_button.setToolTip(tr(N_("events.option.remove")))


class OptionCards(QWidget):
    """Las tarjetas de las opciones del evento enlazado."""

    changed = Signal()                           # tras añadir, quitar, mover o editar una opción
    current_changed = Signal(int)                # la tarjeta con el foco (la vista previa la resalta)
    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._ref = None
        self._read_only = False
        self._applying = False
        self.cards: list[OptionCard] = []
        self.setObjectName("optionCards")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(6)
        outer.addLayout(self.cards_box)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("optionsEmpty")
        outer.addWidget(self.empty_label)
        self.add_button = QPushButton()
        self.add_button.setObjectName("optionAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(self.add_option)
        outer.addWidget(self.add_button)
        if hasattr(session, "documentsChanged"):
            session.documentsChanged.connect(self._on_documents)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def bind(self, ref) -> None:
        """Enlaza con las opciones del evento ``ref`` (None: vacío)."""
        self._ref = ref
        self._reload()

    def _record(self):
        entities = getattr(self.session, "entities", None)
        if entities is None or self._ref is None:
            return None
        try:
            return entities.open(self._ref)
        except (KeyError, FileNotFoundError, OSError):
            return None

    def _reload(self) -> None:
        record = self._record()
        views = record.groups(OPTION_KEY) if record is not None else []
        while len(self.cards) > len(views):
            card = self.cards.pop()
            self.cards_box.removeWidget(card)
            card.hide()
            card.setParent(None)
            card.deleteLater()
        while len(self.cards) < len(views):
            card = OptionCard(self.session, len(self.cards))
            card.up_button.clicked.connect(lambda _c=False, c=card: self.move_option(c.index, c.index - 1))
            card.down_button.clicked.connect(lambda _c=False, c=card: self.move_option(c.index, c.index + 1))
            card.remove_button.clicked.connect(lambda _c=False, c=card: self.remove_option(c.index))
            card.text_changed.connect(lambda _i: self.changed.emit())
            card.effects.changed.connect(self.changed)
            card.effects.status_requested.connect(self.status_requested)
            card.ai_chance.status_requested.connect(self.status_requested)
            card.ai_chance.changed.connect(self.changed)
            card.effects.current_changed.connect(lambda _node, c=card: self.current_changed.emit(c.index))
            self.cards_box.addWidget(card)
            self.cards.append(card)
        for card, view in zip(self.cards, views):
            card.bind(self._ref, view)
            card.set_read_only(self._read_only)
            card.up_button.setEnabled(not self._read_only and card.index > 0)
            card.down_button.setEnabled(not self._read_only and card.index < len(views) - 1)
        self.empty_label.setVisible(self._ref is not None and not views)
        self.add_button.setEnabled(self._ref is not None and not self._read_only)

    def _on_documents(self, _rels) -> None:
        if self._ref is not None and not self._applying:
            self._reload()

    def count(self) -> int:
        return len(self.cards)

    def card(self, index: int) -> OptionCard:
        return self.cards[index]

    def _apply(self, action: str, operation, **fmt) -> bool:
        if self._read_only or self._ref is None or getattr(self.session, "project", None) is None:
            return False
        self._applying = True
        try:
            with self.session.edit(UNDO_KEYS[action], **fmt):
                record = self.session.entities.open(self._ref)
                record._touch()
                operation(record)
        except (ValueError, KeyError, IndexError, RuntimeError, OSError) as exc:
            self.status_requested.emit(N_("script_ui.rejected"), {"error": str(exc)})
            return False
        finally:
            self._applying = False
        self._reload()
        self.changed.emit()
        return True

    def next_key(self) -> str:
        """La clave de la opción nueva: ``EVTOPT<letra><id>`` con la letra de su posición."""
        return f"EVTOPT{option_letter(len(self.cards))}{getattr(self._ref, 'ident', '')}"

    def add_option(self) -> bool:
        """Añade una opción al final con su clave ``EVTOPT<letra><id>`` y sus textos vacíos."""
        key = self.next_key()
        loc = _loc(self.session)

        def operation(record) -> None:
            from ...core.clausewitz.nodes import Block

            options = record.block.find_all(OPTION_KEY)
            block = Block.from_pairs([(NAME_KEY, Scalar(key, True))])
            if options:
                record.block.insert_after(options[-1], OPTION_KEY, block)
            else:
                record.block.append(OPTION_KEY, block)
            if loc is not None and not (loc.text(key, "en") or loc.text(key, "es")):
                loc.set_text(key, "en", "", area=LOC_AREA)

        return self._apply("add", operation, key=key)

    def remove_option(self, index: int) -> bool:
        """Quita la opción (su texto se borra solo si ningún otro evento usa la clave)."""
        def operation(record) -> None:
            record.block.remove_entry(record.block.find_all(OPTION_KEY)[index])

        return self._apply("remove", operation, index=index + 1)

    def move_option(self, index: int, to: int) -> bool:
        if not 0 <= to < len(self.cards) or to == index:
            return False

        def operation(record) -> None:
            options = record.block.find_all(OPTION_KEY)
            entry, target = options[index], options[to]
            position = record.block.entries.index(target)
            record.block.move(entry, position)

        return self._apply("move", operation, index=index + 1)

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        for card in self.cards:
            card.set_read_only(read_only)
        self.add_button.setEnabled(self._ref is not None and not self._read_only)

    def commit_pending(self) -> None:
        for card in self.cards:
            card.commit_pending()

    def _on_language(self, _code: str = "") -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.add_button.setText(tr(N_("events.option.add")))
        self.empty_label.setText(tr(N_("events.option.none")))
        for card in self.cards:
            card.retranslate()
