"""Piezas compartidas por los visores: gravedades, idioma de los diagnósticos, errores al leer y cabecera."""

from __future__ import annotations

import os
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
# Lo que tiene que tardar una carga para que el visor muestre que está cargando: un reintento que falla
# otra vez, o un archivo pequeño, responde antes y no hace parpadear la vista.
LOADING_DELAY_MS = 150
# Mensaje de cada error del sistema al abrir un archivo; los demás usan «file_error.generic».
OS_ERROR_KEYS = (
    ((FileNotFoundError, NotADirectoryError), N_("file_error.not_found")),
    (PermissionError, N_("file_error.permission")),
    (IsADirectoryError, N_("file_error.not_file")),
)


def severity_name(severity) -> str:
    """``"error"``/``"warning"``/``"info"`` a partir del Enum de clausewitz o de csvloc."""
    return getattr(severity, "value", severity)


def core_language() -> str:
    """Idioma para ``Diagnostic.message``: el de la interfaz si el núcleo lo tiene, si no inglés."""
    current = language()
    return current if current in CORE_LANGUAGES else "en"


def file_stamp(path: str | os.PathLike) -> tuple[int, int] | None:
    """(modificación en ns, tamaño) de ``path``, o ``None`` si no se puede consultar."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def describe_os_error(error: BaseException) -> tuple[str, str]:
    """(motivo traducido, detalle del sistema) de un error al leer un archivo.

    ``strerror`` es el texto de la libc o del CRT, siempre en inglés: solo sirve de detalle.
    """
    detail = getattr(error, "strerror", None) or str(error) or type(error).__name__
    key = next((key for kinds, key in OS_ERROR_KEYS if isinstance(error, kinds)), None)
    return (tr(key) if key else tr("file_error.generic", detail=detail)), detail


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
    """«1,5 KiB», «12 bytes»… y «1 byte» (``formattedDataSize`` no tiene singular)."""
    return tr("size.one_byte") if size == 1 else translator().locale().formattedDataSize(size)


def format_number(value: int) -> str:
    return translator().locale().toString(value)


def format_seconds(seconds: float) -> str:
    return translator().locale().toString(seconds, "f", 2)


class ElidedLabel(QLabel):
    """Una sola línea recortada con «…» si no cabe; ``text()`` conserva el texto completo.

    ``set_text(text, shrink)`` recorta primero ``shrink``, una parte de ``text`` (una ruta): así lo que la
    sigue (la codificación, el tamaño…) no se pierde en medio del recorte.
    """

    def __init__(self, parent: QWidget | None = None, mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle):
        super().__init__(parent)
        self._mode = mode
        self._shrink = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_text(self, text: str, shrink: str = "") -> None:
        self._shrink = shrink
        self.setText(text)
        self.update()  # ``setText`` no repinta si el texto es el mismo y solo cambia lo que se recorta

    def minimumSizeHint(self) -> QSize:
        return QSize(16, super().minimumSizeHint().height())

    def displayed_text(self) -> str:
        """Lo que se pinta con el ancho actual."""
        text, mode, metrics = self.text(), self._mode, self.fontMetrics()
        width = self.contentsRect().width()
        part = self._shrink
        if part and part in text and metrics.horizontalAdvance(text) > width:
            before, _, after = text.partition(part)
            # Un par de píxeles de margen: el ancho del texto unido puede no ser la suma exacta de sus trozos.
            room = width - metrics.horizontalAdvance(before + after) - 2
            text = before + (metrics.elidedText(part, Qt.TextElideMode.ElideMiddle, room) or "…") + after
            mode = Qt.TextElideMode.ElideRight  # si ni así cabe, se pierde el final y no lo de en medio
        return metrics.elidedText(text, mode, width)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        self.style().drawItemText(p, self.contentsRect(), int(self.alignment()), self.palette(), self.isEnabled(),
                                  self.displayed_text(), self.foregroundRole())


class ViewerHeader(QWidget):
    """Icono, nombre del archivo con el resumen de diagnósticos a su derecha y, debajo, la línea de detalles.

    La insignia solo comparte fila con el nombre: la línea de detalles (ruta, codificación, líneas, tamaño)
    tiene todo el ancho. El nombre se recorta por el medio si no cabe, en vez de ensanchar la vista previa.
    """

    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        self.icon = IconWidget(icon_name, 34)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.name = mark_data(ElidedLabel())
        self.name.setObjectName("viewerName")
        self.name.setFont(theme.font("body_bold", 12.5))
        self.name.setProperty("role", "title")
        self.details = ElidedLabel()
        self.details.setObjectName("viewerDetails")
        self.details.setProperty("role", "caption")
        self.details.setFont(theme.font("caption"))
        self.badge = StatusBadge()
        self.badge.setObjectName("viewerSummary")
        self.badge.label.setWordWrap(False)
        self.badge.setVisible(False)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.name, 1)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        texts.addLayout(top)
        texts.addWidget(self.details)
        row.addLayout(texts, 1)

    def set_file(self, path: Path | None, details: str = "", shown_path: str = "") -> None:
        # Sin ayuda emergente propia: la de la línea de detalles ya lleva la ruta entera (y un texto crudo en una
        # ayuda emergente lo tomarían por un texto sin traducir las pruebas de pseudolocalización).
        name = path.name if path else ""
        self.name.set_text(name, name)
        self.set_details(details, shown_path)

    def set_details(self, details: str, shown_path: str = "") -> None:
        """``shown_path``, la ruta tal como aparece en ``details``, es lo primero que se recorta si no cabe."""
        self.details.set_text(details, shown_path)
        self.details.setToolTip(details)

    def set_summary(self, level: str | None, text: str = "", tooltip: str = "") -> None:
        self.badge.setVisible(level is not None)
        if level is not None:
            self.badge.set_status(level, text)
        self.badge.setToolTip(tooltip)
