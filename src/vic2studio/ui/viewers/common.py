"""Piezas compartidas por los visores: gravedades, idioma de los diagnósticos y cabecera de archivo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...i18n import N_, language, tr, translator
from .. import theme
from ..widgets import IconWidget, StatusBadge, make_icon, mark_data

ERROR, WARNING, INFO = "error", "warning", "info"
SEVERITY_RANK = {ERROR: 0, WARNING: 1, INFO: 2}
SEVERITY_ICON = {ERROR: "error", WARNING: "warning", INFO: "info"}
SEVERITY_COLOR = {ERROR: "danger", WARNING: "warning", INFO: "ink_soft"}
SEVERITY_KEYS = {ERROR: N_("severity.error"), WARNING: N_("severity.warning"), INFO: N_("severity.info")}
CORE_LANGUAGES = ("es", "en")


def severity_name(severity) -> str:
    """``"error"``/``"warning"``/``"info"`` a partir del Enum de clausewitz o de csvloc."""
    return getattr(severity, "value", severity)


def core_language() -> str:
    """Idioma para ``Diagnostic.message``: el de la interfaz si el núcleo lo tiene, si no inglés."""
    current = language()
    return current if current in CORE_LANGUAGES else "en"


def severity_icon(severity: str):
    return make_icon(SEVERITY_ICON[severity], SEVERITY_COLOR[severity], "cream")


def severity_label(severity: str) -> str:
    return tr(SEVERITY_KEYS[severity])


def summary_status(errors: int, warnings: int, infos: int = 0) -> tuple[str, str]:
    """(nivel, texto) del resumen de diagnósticos de un archivo."""
    if errors:
        return "error", tr("viewer.summary_errors_one" if errors == 1 else "viewer.summary_errors",
                           count=format_number(errors))
    if warnings:
        return "warning", tr("viewer.summary_warnings_one" if warnings == 1 else "viewer.summary_warnings",
                             count=format_number(warnings))
    if infos:
        return "neutral", tr("viewer.summary_infos_one" if infos == 1 else "viewer.summary_infos",
                             count=format_number(infos))
    return "ok", tr("viewer.summary_clean")


def format_size(size: int) -> str:
    return translator().locale().formattedDataSize(size)


def format_number(value: int) -> str:
    return translator().locale().toString(value)


def format_seconds(seconds: float) -> str:
    return translator().locale().toString(seconds, "f", 2)


class ElidedLabel(QLabel):
    """Una sola línea recortada con «…» si no cabe; ``text()`` conserva el texto completo."""

    def __init__(self, parent: QWidget | None = None, mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle):
        super().__init__(parent)
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:
        return QSize(16, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, rect.width())
        self.style().drawItemText(p, rect, int(self.alignment()), self.palette(), self.isEnabled(), text,
                                  self.foregroundRole())


class ViewerHeader(QWidget):
    """Icono, nombre del archivo, línea de detalles y resumen de diagnósticos."""

    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        self.icon = IconWidget(icon_name, 34)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.name = mark_data(QLabel())
        self.name.setObjectName("viewerName")
        self.name.setFont(theme.font("body_bold", 12.5))
        self.name.setProperty("role", "title")
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details = ElidedLabel()
        self.details.setObjectName("viewerDetails")
        self.details.setProperty("role", "caption")
        self.details.setFont(theme.font("caption"))
        texts.addWidget(self.name)
        texts.addWidget(self.details)
        row.addLayout(texts, 1)
        self.badge = StatusBadge()
        self.badge.setObjectName("viewerSummary")
        self.badge.label.setWordWrap(False)
        self.badge.setVisible(False)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)

    def set_file(self, path: Path | None, details: str = "") -> None:
        self.name.setText(path.name if path else "")
        self.set_details(details)

    def set_details(self, details: str) -> None:
        self.details.setText(details)
        self.details.setToolTip(details)

    def set_summary(self, level: str | None, text: str = "") -> None:
        self.badge.setVisible(level is not None)
        if level is not None:
            self.badge.set_status(level, text)
