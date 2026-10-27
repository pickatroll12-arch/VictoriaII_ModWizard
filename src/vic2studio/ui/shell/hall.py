"""Una sala de la ventana principal: índice de secciones (``SectionRail``) y la sección a la vista (wizard §13.2).

``HallPage`` construye sus secciones a partir de las ``SectionSpec`` de su
paquete (``ui/halls/<sala>``): con ``factory``, el widget que esta devuelve; sin
ella, la tarjeta «en desarrollo» (``PlannedSectionPage``) con su iteración. Las
señales de las secciones que las tengan (``status_requested``,
``navigate_requested``, ``save_requested``) se reemiten para la ventana. Al
empezar se ve la primera sección que ya existe.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ...i18n import tr, translator
from ..halls.registry import HallSpec, SectionSpec
from ..pages.planned import PlannedSectionPage
from ..widgets import OrnateFrame, show_in_stack
from .section_rail import SectionRail


class HallPage(QWidget):
    """API: ``spec``, ``sections``, ``widgets``, ``set_current_section(índice o clave)``, ``section_widget(clave)``."""

    sectionChanged = Signal(int)
    status_requested = Signal(str, object)
    navigate_requested = Signal(str)   # «sala:sección» o la clave de una página
    save_requested = Signal()

    def __init__(self, spec: HallSpec, sections: list[SectionSpec], session, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(f"hall_{spec.key}")
        self.spec = spec
        self.sections = list(sections)
        self.session = session
        self._row = row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.rail = SectionRail()
        row.addWidget(self.rail)
        self.frame = OrnateFrame()
        self.frame.setObjectName("pageFrame")
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        frame_layout.addWidget(self.stack)
        row.addWidget(self.frame, 1)

        self.widgets: list[QWidget] = []
        for section in self.sections:
            widget = section.factory(session) if section.factory is not None else PlannedSectionPage(spec, section)
            self.widgets.append(widget)
            self.stack.addWidget(widget)
            self.rail.add_button(section.icon)
            for name in ("status_requested", "navigate_requested", "save_requested"):
                signal = getattr(widget, name, None)
                if signal is not None:
                    signal.connect(getattr(self, name))
        self.rail.currentChanged.connect(self._on_rail_changed)
        first = next((i for i, s in enumerate(self.sections) if not s.planned), 0)
        if self.widgets:
            self.rail.set_current_index(first)
            show_in_stack(self.stack, self.widgets[first])
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    # --- API -------------------------------------------------------------------------------------

    def current_section_index(self) -> int:
        return self.stack.currentIndex()

    def current_section(self) -> SectionSpec | None:
        index = self.current_section_index()
        return self.sections[index] if 0 <= index < len(self.sections) else None

    def current_widget(self) -> QWidget | None:
        return self.stack.currentWidget()

    def section_index(self, key: str) -> int:
        for index, section in enumerate(self.sections):
            if section.key == key:
                return index
        raise KeyError(f"{self.spec.key}:{key}")

    def section_widget(self, key: str) -> QWidget:
        return self.widgets[self.section_index(key)]

    def set_current_section(self, index_or_key: int | str) -> None:
        index = self.section_index(index_or_key) if isinstance(index_or_key, str) else index_or_key
        if not 0 <= index < len(self.widgets):
            raise IndexError(f"sección fuera de rango: {index}")
        if self.rail.current_index() != index:
            self.rail.set_current_index(index)  # emite currentChanged → _on_rail_changed
        elif self.stack.currentIndex() != index:
            self._on_rail_changed(index)

    def section_title(self, index: int | None = None) -> str:
        index = self.current_section_index() if index is None else index
        return tr(self.sections[index].title_key) if 0 <= index < len(self.sections) else ""

    def refresh_badges(self) -> None:
        for section, button in zip(self.sections, self.rail.buttons):
            button.set_badge(section.badge(self.session) if section.badge is not None else None)
        self.rail.update_strip()  # un contador ocupa sitio: puede que la franja ya no quepa en una línea

    def set_compact(self, compact: bool) -> None:
        """Ventana estrecha: el índice pasa a una franja encima de la sección (que conserva todo el ancho)."""
        self._row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self._row.setSpacing(0 if compact else 6)
        self.rail.set_compact(compact)

    def is_busy(self) -> bool:
        return any(getattr(widget, "is_busy", lambda: False)() for widget in self.widgets)

    def shutdown(self) -> None:
        for widget in self.widgets:
            shutdown = getattr(widget, "shutdown", None)
            if shutdown is not None:
                shutdown()

    def retranslate(self) -> None:
        self.rail.set_heading(tr(self.spec.title_key))
        self.rail.setToolTip(tr(self.spec.subtitle_key))
        for section, button in zip(self.sections, self.rail.buttons):
            title = tr(section.title_key)
            button.setText(title)
            button.set_tag(tr("rail.planned_tag", n=section.iteration) if section.planned else "")
            tip = tr("rail.planned_tooltip", name=title, n=section.iteration) if section.planned else title
            button.setToolTip(tip)
            button.setAccessibleName(title)
            button.updateGeometry()
        self.refresh_badges()

    # --- interno ---------------------------------------------------------------------------------

    def _on_rail_changed(self, index: int) -> None:
        if self.stack.currentIndex() != index:
            show_in_stack(self.stack, self.widgets[index])
        self.sectionChanged.emit(index)

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def focus_rail(self) -> None:
        index = max(self.rail.current_index(), 0)
        if self.rail.buttons:
            self.rail.buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
