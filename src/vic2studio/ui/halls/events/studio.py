"""Event Studio y editor de decisiones: las secciones Eventos y Decisiones de la sala Eventos (wizard §14.5,
§14.7). Iteración 7.

Las dos páginas son el editor genérico de entidades (``EntityEditorPage``: lista, Formulario, Textos, Usos,
Código y Otros campos) con una pestaña más, la primera, **Studio**: a la izquierda las tarjetas del guion
(cabecera con la imagen, condiciones con su frase y el constructor TODAS/ALGUNA/NINGUNA, MTTH con sus
modificadores, efectos inmediatos y opciones en eventos; requisitos, efecto e interés de la IA en
decisiones) y a la derecha la vista previa procedural con su conmutador ES/EN.

- **Eventos.** Un filtro (todos, de país, de provincia) sobre la misma lista: los dos tipos comparten
  archivos e ids. «Nuevo» crea con el primer id libre del rango del proyecto (criterio 3) y, con el filtro
  de provincia, un ``province_event``. Un id repetido se rechaza proponiendo el siguiente libre.
- **Archivos rotos (D17).** Si el archivo del registro solo se puede editar como texto, una franja dice por
  qué (los diagnósticos con su línea) y ofrece el arreglo «Añadir } al final» cuando basta; los
  constructores quedan de solo lectura hasta que el archivo se lee entero.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.schema.fields import REST
from ....core.script.mtth import AI_WILL_DO_KEY, MODIFIER_KEY, MTTH_KEY
from ....i18n import N_, tr
from ...entity.editor_page import EntityEditorPage
from ...script.decision_preview import DecisionPreview
from ...script.effect_builder import EffectBuilder
from ...script.event_preview import EventPreview
from ...script.mtth_editor import MtthEditor
from ...script.option_cards import OptionCards
from ...script.phrase_view import PhraseView
from ...script.picture_picker import DECISION_PICTURE, EVENT_PICTURE, PicturePicker
from ...script.trigger_builder import ScriptBinding, TriggerBuilder, phrase_language
from ...widgets import mark_data

TAB_STUDIO = "studio"
FILTERS = (("all", None, N_("events.filter.all")), ("country", "country", N_("events.filter.country")),
           ("province", "province", N_("events.filter.province")))


class StudioCard(QFrame):
    """Una tarjeta del Studio: título y contenido."""

    def __init__(self, name: str, title_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"studioCard_{name}")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.title_key = title_key
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)
        self.title = QLabel()
        self.title.setProperty("role", "heading")
        outer.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))


class TextOnlyBanner(QFrame):
    """La franja de un archivo que solo se puede editar como texto (D17)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("textOnlyBanner")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("tone", "warning")
        self.state = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        self.title = QLabel()
        self.title.setObjectName("textOnlyTitle")
        self.title.setProperty("role", "heading")
        self.title.setWordWrap(True)
        outer.addWidget(self.title)
        self.details = mark_data(QLabel())
        self.details.setObjectName("textOnlyDetails")
        self.details.setWordWrap(True)
        outer.addWidget(self.details)
        row = QHBoxLayout()
        self.fix_button = QPushButton()
        self.fix_button.setObjectName("textOnlyFix")
        self.code_button = QPushButton()
        self.code_button.setObjectName("textOnlyCode")
        row.addWidget(self.fix_button)
        row.addWidget(self.code_button)
        row.addStretch(1)
        outer.addLayout(row)
        self.hide()

    def set_state(self, state) -> None:
        self.state = state
        self.setVisible(state is not None)
        if state is None:
            return
        lang = phrase_language()
        lines = [f"{state.rel}:{d.line}:{d.column} · {d.message(lang)}" for d in state.diagnostics]
        self.details.setText("\n".join(lines))
        self.fix_button.setVisible(bool(state.fixes))
        self.retranslate()

    def retranslate(self) -> None:
        rel = "" if self.state is None else str(self.state.rel)
        self.title.setText(tr(N_("events.text_only.title"), file=rel))
        self.fix_button.setText(tr(N_("events.text_only.fix")))
        self.code_button.setText(tr(N_("events.text_only.code")))


class ScriptStudioPage(EntityEditorPage):
    """Base de las dos páginas: la pestaña Studio delante de las del editor genérico."""

    schema_kind = ""
    preview_class = EventPreview

    def __init__(self, session, parent: QWidget | None = None):
        from ....core.schema import registry

        self.cards: list[StudioCard] = []
        self.builders: list[TriggerBuilder] = []
        self.text_only = None
        super().__init__(session, registry.get(self.schema_kind), parent=parent)

    # --- construcción -----------------------------------------------------------------------------

    def build(self) -> None:
        super().build()
        self.studio = QWidget()
        self.studio.setObjectName("studioTab")
        row = QHBoxLayout(self.studio)
        row.setContentsMargins(0, 4, 0, 0)
        self.studio_splitter = QSplitter(Qt.Orientation.Horizontal)
        scroll = QScrollArea()
        scroll.setObjectName("studioScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.column = QVBoxLayout(content)
        self.column.setContentsMargins(0, 0, 6, 0)
        self.column.setSpacing(8)
        self.banner = TextOnlyBanner()
        self.banner.fix_button.clicked.connect(self.apply_text_fix)
        self.banner.code_button.clicked.connect(lambda: self.show_code())
        self.column.addWidget(self.banner)
        self.build_studio()
        self.column.addStretch(1)
        scroll.setWidget(content)
        self.studio_scroll = scroll
        self.studio_splitter.addWidget(scroll)
        self.preview = self.preview_class(self.session)
        self.studio_splitter.addWidget(self.preview)
        self.studio_splitter.setStretchFactor(0, 3)
        self.studio_splitter.setStretchFactor(1, 2)
        self.studio_splitter.setSizes([620, 440])
        self.navigator.setMaximumWidth(310)
        row.addWidget(self.studio_splitter)
        self._tab_keys.insert(0, TAB_STUDIO)
        self.tabs.insertTab(0, self.studio, "")
        self.tabs.setCurrentIndex(0)

    def build_studio(self) -> None:
        """Las tarjetas de la pestaña Studio (las subclases)."""

    def scroll_to(self, name: str) -> None:
        """Lleva la columna del Studio a la tarjeta ``name`` (``trigger``, ``mtth``, ``options``…)."""
        for card in self.cards:
            if card.objectName() == f"studioCard_{name}":
                self.studio_scroll.verticalScrollBar().setValue(card.y())
                return

    def card(self, name: str, title_key: str) -> StudioCard:
        card = StudioCard(name, title_key)
        self.cards.append(card)
        self.column.addWidget(card)
        return card

    def script_block(self, card: StudioCard, builder_class, path: tuple, lead: str):
        """Frase + constructor de un campo de guion dentro de ``card``."""
        phrase = PhraseView()
        phrase.setObjectName(f"phrase_{path[-1]}")
        builder = builder_class(self.session)
        builder.setObjectName(f"builder_{path[-1]}")
        builder.path = path
        builder.lead = lead
        builder.phrase = phrase
        phrase.edit_requested.connect(lambda b=builder: b.setVisible(not b.isVisible()))
        phrase.node_activated.connect(lambda node_path, b=builder: (b.show(), b.select(node_path)))
        builder.changed.connect(lambda b=builder: self._refresh_phrase(b))
        builder.status_requested.connect(self.status_requested)
        builder.code_requested.connect(lambda node: self.show_code())
        card.body.addWidget(phrase)
        card.body.addWidget(builder)
        self.builders.append(builder)
        return phrase, builder

    def _names(self):
        loc = None
        finder = getattr(self.session, "_loc_for_search", None)
        if callable(finder):
            try:
                loc = finder()
            except Exception:  # noqa: BLE001
                loc = None
        return getattr(self.session, "index", None), loc

    def _refresh_phrase(self, builder) -> None:
        index, loc = self._names()
        builder.phrase.set_tree(builder.tree(), lead=builder.lead, index=index, loc=loc)
        builder.phrase.set_problem_count(builder.problem_count())

    def _tab_names(self) -> dict[str, str]:
        names = super()._tab_names()
        names[TAB_STUDIO] = N_("events.tab.studio")
        return names

    def retranslate(self) -> None:
        for card in getattr(self, "cards", ()):
            card.retranslate()
        if getattr(self, "banner", None) is not None:
            self.banner.retranslate()
        super().retranslate()

    # --- enlace -----------------------------------------------------------------------------------

    def _bind_details(self) -> None:
        super()._bind_details()
        record = self.form.record()
        ref = self._current if record is not None and self._current is not None \
            and self._current.kind == self.schema.kind else None
        self.bind_studio(ref)

    def bind_studio(self, ref) -> None:
        state = None
        if ref is not None:
            from ....core.script.textonly import text_only_of

            try:
                state = text_only_of(self.session.entities, ref)
            except (KeyError, FileNotFoundError, OSError):
                state = None
        self.text_only = state
        self.banner.set_state(state)
        read_only = state is not None or self.session.is_read_only()
        for builder in self.builders:
            builder.bind(ScriptBinding(ref, builder.path) if ref is not None else None)
            builder.set_read_only(read_only)
            builder.phrase.set_read_only(read_only)
            self._refresh_phrase(builder)
        self.bind_extra(ref, read_only)
        self.preview.bind(ref)

    def bind_extra(self, ref, read_only: bool) -> None:
        """Lo que no es un constructor (imagen, MTTH, opciones): las subclases."""

    def apply_text_fix(self) -> bool:
        """El arreglo de la franja (``add_closing_brace``): una transacción, un Ctrl+Z."""
        state = self.text_only
        if state is None or not state.fixes or state.problem is None:
            return False
        try:
            self.session.apply_fix(state.fixes[0], state.problem)
        except Exception as exc:  # noqa: BLE001 - el arreglo rechazado se cuenta en la barra de estado
            self.request_status(N_("events.text_only.failed"), error=str(exc))
            return False
        self.request_status(N_("events.text_only.fixed"), file=str(state.rel))
        self.refresh()
        return True

    def set_picture(self, value) -> bool:
        ref = self._current
        if ref is None or self.text_only is not None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(N_("events.undo.picture"), ident=ref.ident):
                record = self.session.entities.open(ref)
                if value:
                    record.set("picture", value)
                else:
                    record.remove("picture")
        except (ValueError, KeyError, OSError) as exc:
            self.request_status(N_("script_ui.rejected"), error=str(exc))
            return False
        return True

    def commit_pending(self) -> None:
        super().commit_pending()
        for builder in self.builders:
            builder.commit_pending()


class EventStudioPage(ScriptStudioPage):
    """Eventos › Eventos: el Event Studio."""

    schema_kind = "event"
    preview_class = EventPreview

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(session, parent)
        self.key = "events"
        self.setObjectName("page_events")

    def build_studio(self) -> None:
        header = self.card("header", N_("events.card.header"))
        self.kind_label = mark_data(QLabel())
        self.kind_label.setObjectName("eventKind")
        header.body.addWidget(self.kind_label)
        self.picture = PicturePicker(EVENT_PICTURE, self.session)
        self.picture.value_committed.connect(self.set_picture)
        header.body.addWidget(self.picture)
        conditions = self.card("trigger", N_("events.card.trigger"))
        self.trigger_phrase, self.trigger = self.script_block(conditions, TriggerBuilder, ("trigger",), "trigger")
        mtth = self.card("mtth", N_("events.card.mtth"))
        self.mtth = MtthEditor(self.session, key=MTTH_KEY)
        self.mtth.title.hide()                      # la tarjeta ya lo titula
        self.mtth.status_requested.connect(self.status_requested)
        self.mtth.conditions_requested.connect(self.open_modifier)
        mtth.body.addWidget(self.mtth)
        self.modifier_title = mark_data(QLabel())
        self.modifier_title.setObjectName("mtthModifierTitle")
        mtth.body.addWidget(self.modifier_title)
        self.modifier_builder = TriggerBuilder(self.session)
        self.modifier_builder.setObjectName("mtthModifierBuilder")
        self.modifier_builder.status_requested.connect(self.status_requested)
        self.modifier_builder.changed.connect(lambda: self.mtth.bind(self._current, ()))
        self.modifier_builder.hide()
        self.modifier_title.hide()
        mtth.body.addWidget(self.modifier_builder)
        immediate = self.card("immediate", N_("events.card.immediate"))
        self.immediate_phrase, self.immediate = self.script_block(immediate, EffectBuilder, ("immediate",),
                                                                  "immediate")
        self.immediate.hide()
        options = self.card("options", N_("events.card.options"))
        self.options = OptionCards(self.session)
        self.options.status_requested.connect(self.status_requested)
        self.options.current_changed.connect(lambda index: self.preview.set_current_option(index))
        options.body.addWidget(self.options)
        self.modifier_index: int | None = None

    def build(self) -> None:
        super().build()
        self.filter = QComboBox()
        self.filter.setObjectName("eventsFilter")
        for key, _view, _label in FILTERS:
            self.filter.addItem("", key)
        self.filter.currentIndexChanged.connect(self._on_filter)
        self.header.trailing.addWidget(self.filter)

    def retranslate(self) -> None:
        if getattr(self, "filter", None) is not None:
            for index, (_key, _view, label) in enumerate(FILTERS):
                self.filter.setItemText(index, tr(label))
        super().retranslate()
        if getattr(self, "kind_label", None) is not None:
            self._render_kind()

    def _on_filter(self, index: int) -> None:
        self.navigator.view = FILTERS[index][1] if 0 <= index < len(FILTERS) else None
        self.refresh()

    def filter_view(self) -> str | None:
        return self.navigator.view

    def set_filter(self, view: str | None) -> None:
        for index, (_key, value, _label) in enumerate(FILTERS):
            if value == view:
                self.filter.setCurrentIndex(index)
                return

    def _template_values(self) -> dict:
        from ....core.schemas.event import PROVINCE_EVENT, TYPE_FIELD

        return {TYPE_FIELD: PROVINCE_EVENT} if self.navigator.view == "province" else {}

    def next_free_id(self) -> str | None:
        entities = getattr(self.session, "entities", None)
        if entities is None:
            return None
        try:
            return str(entities.id_allocator("event").next_free())
        except ValueError:
            return None

    def ask_new(self, base=None) -> bool:
        """«Nuevo» y «Duplicar»: el primer id libre del rango del proyecto, sin preguntar (criterio 3)."""
        ident = self.next_free_id()
        if ident is None:
            self.request_status(N_("events.new.exhausted"))
            return False
        return self.create(ident, base)

    def bind_extra(self, ref, read_only: bool) -> None:
        record = self.form.record() if ref is not None else None
        self.picture.set_value(record.get("picture", None) if record is not None else None)
        self.picture.set_read_only(read_only or ref is None)
        self.mtth.bind(ref, ())
        self.mtth.set_read_only(read_only)
        self.options.bind(ref)
        self.options.set_read_only(read_only)
        if self.modifier_index is not None and ref is not None and self.mtth.model() is not None \
                and self.modifier_index < len(self.mtth.model().modifiers):
            self.open_modifier(self.modifier_index)
        else:
            self.modifier_index = None
            self.modifier_builder.bind(None)
            self.modifier_builder.hide()
            self.modifier_title.hide()
        self.modifier_builder.set_read_only(read_only)
        self._render_kind()

    def _render_kind(self) -> None:
        record = self.form.record() if self._current is not None else None
        if record is None:
            self.kind_label.setText("")
            return
        province = (record.entity_key or "").lower() == "province_event"
        self.kind_label.setText(tr(N_("events.kind.province") if province else N_("events.kind.country"),
                                   ident=self._current.ident, file=str(record.handle.rel)))

    def open_modifier(self, index: int) -> None:
        """Enseña el constructor de las condiciones del modificador ``index`` del MTTH."""
        if self._current is None:
            return
        self.modifier_index = index
        self.modifier_builder.bind(ScriptBinding(self._current, (MTTH_KEY, MODIFIER_KEY, index, REST)))
        self.modifier_title.setText(tr(N_("events.mtth.modifier"), index=index + 1))
        self.modifier_title.show()
        self.modifier_builder.show()


class DecisionStudioPage(ScriptStudioPage):
    """Eventos › Decisiones: requisitos, efecto e interés de la IA con su vista previa."""

    schema_kind = "decision"
    preview_class = DecisionPreview

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(session, parent)
        self.key = "decisions"
        self.setObjectName("page_decisions")

    def build_studio(self) -> None:
        header = self.card("header", N_("decisions.card.header"))
        self.picture = PicturePicker(DECISION_PICTURE, self.session)
        self.picture.value_committed.connect(self.set_picture)
        header.body.addWidget(self.picture)
        potential = self.card("potential", N_("decisions.card.potential"))
        self.potential_phrase, self.potential = self.script_block(potential, TriggerBuilder, ("potential",),
                                                                  "potential")
        allow = self.card("allow", N_("decisions.card.allow"))
        self.allow_phrase, self.allow = self.script_block(allow, TriggerBuilder, ("allow",), "allow")
        effect = self.card("effect", N_("decisions.card.effect"))
        self.effect_phrase, self.effect = self.script_block(effect, EffectBuilder, ("effect",), "effect")
        ai = self.card("ai", N_("decisions.card.ai"))
        self.ai = MtthEditor(self.session, key=AI_WILL_DO_KEY)
        self.ai.title.hide()
        self.ai.status_requested.connect(self.status_requested)
        self.ai.conditions_requested.connect(self.open_modifier)
        ai.body.addWidget(self.ai)
        self.modifier_builder = TriggerBuilder(self.session)
        self.modifier_builder.setObjectName("aiModifierBuilder")
        self.modifier_builder.status_requested.connect(self.status_requested)
        self.modifier_builder.changed.connect(lambda: self.ai.bind(self._current, ()))
        self.modifier_builder.hide()
        ai.body.addWidget(self.modifier_builder)

    def bind_extra(self, ref, read_only: bool) -> None:
        record = self.form.record() if ref is not None else None
        self.picture.set_default_name(ref.ident if ref is not None else None)
        self.picture.set_value(record.get("picture", None) if record is not None else None)
        self.picture.set_read_only(read_only or ref is None)
        self.ai.bind(ref, ())
        self.ai.set_read_only(read_only)
        self.modifier_builder.bind(None)
        self.modifier_builder.hide()
        self.modifier_builder.set_read_only(read_only)

    def open_modifier(self, index: int) -> None:
        if self._current is None:
            return
        self.modifier_builder.bind(ScriptBinding(self._current, (AI_WILL_DO_KEY, MODIFIER_KEY, index, REST)))
        self.modifier_builder.show()
