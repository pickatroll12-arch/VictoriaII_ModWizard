"""Base común de las páginas de módulo: cabecera con medallón, título y subtítulo traducidos."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import tr, translator
from .. import theme
from ..widgets import Divider, Medallion


class PageHeader(QWidget):
    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.medallion = Medallion(icon_name, 48)
        row.addWidget(self.medallion)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title"))
        self.subtitle = QLabel()
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setProperty("role", "subtitle")
        self.subtitle.setFont(theme.font("subtitle"))
        self.subtitle.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row.addLayout(texts, 1)
        self.trailing = QHBoxLayout()
        self.trailing.setSpacing(8)
        row.addLayout(self.trailing)
        outer.addLayout(row)
        outer.addWidget(Divider())

    def set_texts(self, title: str, subtitle: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)


class BasePage(QWidget):
    """Página de un módulo. Las subclases definen las claves y construyen su contenido en ``build``.

    ``retranslate`` se invoca al crearla y cada vez que cambia el idioma; las
    subclases la amplían (llamando a ``super()``) para rellenar sus propios textos.
    """

    key = ""
    title_key = ""
    subtitle_key = ""
    icon_name = "info"

    # (clave de catálogo, argumentos de formato); los valores invocables se evalúan al mostrar.
    status_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(f"page_{self.key}")
        self.setProperty("surface", "parchment")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 2)
        layout.setSpacing(10)
        self.header = PageHeader(self.icon_name)
        layout.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        layout.addLayout(self.body, 1)
        self.build()
        self.retranslate()
        translator().languageChanged.connect(self._on_language_changed)

    def build(self) -> None:
        """Construye el contenido de la página dentro de ``self.body``."""

    def title(self) -> str:
        return tr(self.title_key)

    def retranslate(self) -> None:
        self.header.set_texts(tr(self.title_key), tr(self.subtitle_key))

    def is_busy(self) -> bool:
        """``True`` mientras haya cargas asíncronas en curso (las capturas esperan)."""
        return False

    def shutdown(self) -> None:
        """Cancela las tareas en segundo plano de la página (al cerrar la ventana)."""

    def request_status(self, key: str, **fmt) -> None:
        self.status_requested.emit(key, fmt)

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()
