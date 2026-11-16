"""Vista previa procedural de un evento (wizard §13.8).

Dibuja con QPainter una ventana con las proporciones de la del juego: el título, la imagen de 521×203, la
descripción y un botón por opción. No usa ningún recurso del juego salvo la imagen del propio evento, que se
lee de la instalación del usuario cuando existe (``set_game_art(False)`` la sustituye por un marco
procedural: las capturas del repositorio van siempre así). Interpreta los códigos de color ``§Y…§W`` y deja
los ``$VARIABLE$`` como fichas. En la iteración 8 pasa a usar el renderizador ``.gui`` real.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ...i18n import N_, tr, translator
from .. import theme

PICTURE_SIZE = (521, 203)                        # la imagen de un evento, en píxeles
WINDOW_WIDTH = 580                               # ancho natural de la ventana dibujada
PROVINCE_WIDTH = 420                             # la de un evento de provincia es más estrecha y sin imagen

# Códigos de color de los textos del juego (§Y amarillo, §R rojo… §W y §! vuelven al color normal).
COLOR_CODES = {"Y": "#e8cc82", "R": "#e06c5c", "G": "#8fc07a", "B": "#7aa6d8", "W": None, "!": None,
               "b": "#2a1a0c", "L": "#c9a24a"}
_CODE = re.compile(r"§(.)")
_VARIABLE = re.compile(r"\$([A-Za-z0-9_]+)\$")


def game_markup(text: str, *, base_color: str) -> str:
    """HTML de un texto del juego: los ``§X`` como color, los ``$VAR$`` como fichas y ``\\n`` como salto."""
    out = []
    open_span = False
    position = 0
    for match in _CODE.finditer(text):
        out.append(_escape(text[position:match.start()]))
        code = match.group(1)
        if open_span:
            out.append("</span>")
            open_span = False
        color = COLOR_CODES.get(code)
        if color is not None:
            out.append(f'<span style="color:{color}">')
            open_span = True
        position = match.end()
    out.append(_escape(text[position:]))
    if open_span:
        out.append("</span>")
    body = "".join(out)
    return f'<div style="color:{base_color}">{body}</div>'


def _escape(text: str) -> str:
    escaped = html.escape(text).replace("\\n", "<br/>").replace("\n", "<br/>")
    return _VARIABLE.sub(lambda m: f'<span style="background:#5b3a20;color:#f6e7b4">&nbsp;{m.group(1)}&nbsp;</span>',
                         escaped)


@dataclass(frozen=True)
class EventPreviewData:
    """Lo que pinta la vista previa. Los textos ya vienen en el idioma elegido (``None``: la clave no tiene
    texto y se pinta la propia clave, atenuada)."""

    ident: str
    province: bool                               # province_event: la ventana pequeña, sin imagen grande
    title: str | None
    desc: str | None
    options: tuple[str | None, ...]
    picture: Path | None = None                  # archivo de la imagen (TGA); None: no existe o sin arte
    major: bool = False
    title_key: str = ""
    desc_key: str = ""
    option_keys: tuple[str, ...] = ()
    picture_name: str = ""
    picture_image: QImage | None = None          # la imagen ya leída (de memoria o de la VFS)


def load_event_data(session, ref, lang: str, *, game_art: bool = True) -> EventPreviewData | None:
    """Los datos de la vista previa del evento ``ref`` en ``lang`` (None si no se puede abrir)."""
    from .picture_picker import find_picture, image_from_bytes

    entities = getattr(session, "entities", None)
    if entities is None or ref is None:
        return None
    try:
        record = entities.open(ref)
    except (KeyError, FileNotFoundError, OSError):
        return None
    loc = getattr(session, "locsync", None)

    def text_of(value):
        if not isinstance(value, str) or not value:
            return None, ""
        if any(ch.isspace() for ch in value):
            return value, ""                    # un título en prosa (2 de vanilla) se respeta
        found = loc.text(value, lang) if loc is not None else None
        if not found and loc is not None:
            found = loc.text(value, "en")
        return (found or None), value

    title, title_key = text_of(record.get("title", None))
    desc, desc_key = text_of(record.get("desc", None))
    options, option_keys = [], []
    for view in record.groups("option"):
        text, key = text_of(view.get("name", None))
        options.append(text)
        option_keys.append(key)
    picture_name = record.get("picture", None)
    image = None
    if game_art and isinstance(picture_name, str) and picture_name:
        found = find_picture(session, "gfx/pictures/events", picture_name)
        image = image_from_bytes(found[1]) if found is not None else None
    return EventPreviewData(
        ident=ref.ident, province=(record.entity_key or "").lower() == "province_event", title=title, desc=desc,
        options=tuple(options), major=record.get("major", False) is True, title_key=title_key,
        desc_key=desc_key, option_keys=tuple(option_keys),
        picture_name=picture_name if isinstance(picture_name, str) else "", picture_image=image)


class EventCanvas(QWidget):
    """El lienzo que dibuja la ventana del evento."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("eventCanvas")
        self.data: EventPreviewData | None = None
        self.game_art = True
        self.current_option: int | None = None
        self.empty_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumSize(320, 240)

    def natural_width(self) -> int:
        return PROVINCE_WIDTH if self.data is not None and self.data.province else WINDOW_WIDTH

    def natural_height(self, width: int | None = None) -> int:
        return self._layout(width or self.natural_width())[-1]

    def sizeHint(self) -> QSize:
        width = self.natural_width()
        return QSize(width, self.natural_height(width))

    def _doc(self, markup: str, width: float, size: float, bold: bool = False) -> QTextDocument:
        doc = QTextDocument()
        font = theme.font("heading" if bold else "body")
        font.setPointSizeF(size)
        doc.setDefaultFont(font)
        doc.setHtml(markup)
        doc.setTextWidth(width)
        return doc

    def _layout(self, width: int):
        data = self.data
        margin = 18
        inner = width - 2 * margin
        if data is None:
            return None, None, [], 0, 200
        title = data.title or data.title_key or "—"
        title_doc = self._doc(game_markup(title, base_color="#f6e7b4"), inner, 15, bold=True)
        y = margin + title_doc.size().height() + 8
        picture_h = 0 if data.province else round(inner * PICTURE_SIZE[1] / PICTURE_SIZE[0])
        y += picture_h + (10 if picture_h else 0)
        desc = data.desc or data.desc_key or ""
        desc_color = "#2a1a0c" if data.desc else "#8f7c5c"
        desc_doc = self._doc(game_markup(desc, base_color=desc_color), inner - 16, 10.5)
        y += desc_doc.size().height() + 18
        option_docs = []
        for index, text in enumerate(data.options):
            shown = text or (data.option_keys[index] if index < len(data.option_keys) else "") or "—"
            color = "#f3e6c4" if text else "#cdb98f"
            option_docs.append(self._doc(game_markup(shown, base_color=color), inner - 40, 10.5))
        for doc in option_docs:
            y += max(30, doc.size().height() + 12) + 6
        return title_doc, desc_doc, option_docs, picture_h, int(y + margin)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_window(painter, self.width(), self.height())
        painter.end()

    def paint_window(self, painter: QPainter, width: int, height: int) -> None:
        painter.fillRect(QRectF(0, 0, width, height), theme.color("wood_dark"))
        data = self.data
        if data is None:
            painter.setPen(theme.color("cream"))
            painter.setFont(theme.font("body"))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.empty_text)
            return
        natural = self.natural_width()
        window_w = min(width - 8, natural) if width > 200 else natural
        title_doc, desc_doc, option_docs, picture_h, window_h = self._layout(window_w)
        x0 = (width - window_w) / 2
        y0 = max(4, (height - window_h) / 2)
        frame = QRectF(x0, y0, window_w, window_h)
        path = QPainterPath()
        path.addRoundedRect(frame, 10, 10)
        gradient = QLinearGradient(frame.topLeft(), frame.bottomLeft())
        gradient.setColorAt(0, theme.color("parchment_light"))
        gradient.setColorAt(1, theme.color("parchment_dark"))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(theme.color("bronze"), 3))
        painter.drawPath(path)
        margin = 18
        # Banda del título.
        band = QRectF(x0 + 6, y0 + 6, window_w - 12, title_doc.size().height() + 14)
        painter.fillRect(band, theme.color("velvet_dark" if data.major else "wood"))
        painter.save()
        painter.translate(x0 + margin, y0 + margin - 4)
        title_doc.drawContents(painter)
        painter.restore()
        y = y0 + margin + title_doc.size().height() + 8
        if picture_h:
            rect = QRectF(x0 + margin, y, window_w - 2 * margin, picture_h)
            self._paint_picture(painter, rect, data)
            y += picture_h + 10
        painter.save()
        painter.translate(x0 + margin + 8, y)
        desc_doc.drawContents(painter)
        painter.restore()
        y += desc_doc.size().height() + 18
        for index, doc in enumerate(option_docs):
            h = max(30, doc.size().height() + 12)
            button = QRectF(x0 + margin + 10, y, window_w - 2 * margin - 20, h)
            selected = self.current_option == index
            painter.setPen(QPen(theme.color("gold" if selected else "bronze_dark"), 3 if selected else 1.5))
            painter.setBrush(theme.color("velvet" if selected else "wood_light"))
            painter.drawRoundedRect(button, 6, 6)
            painter.save()
            painter.translate(button.left() + 12, button.top() + (h - doc.size().height()) / 2)
            doc.drawContents(painter)
            painter.restore()
            y += h + 6

    def _paint_picture(self, painter: QPainter, rect: QRectF, data: EventPreviewData) -> None:
        image = data.picture_image if self.game_art else None
        if image is None and self.game_art and data.picture is not None:
            loaded = QImage(str(data.picture))
            image = None if loaded.isNull() else loaded
        if image is not None:
            painter.drawImage(rect, image)
        else:
            # Marco procedural: un grabado de líneas cruzadas con el nombre de la imagen.
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#6e5233"))
            gradient.setColorAt(1, QColor("#3a2414"))
            painter.fillRect(rect, gradient)
            painter.save()
            painter.setClipRect(rect)
            painter.setPen(QPen(QColor(232, 204, 130, 40), 1))
            step = 12
            x = rect.left() - rect.height()
            while x < rect.right():
                painter.drawLine(QPointF(x, rect.bottom()), QPointF(x + rect.height(), rect.top()))
                x += step
            painter.restore()
            painter.setPen(theme.color("gold_light"))
            painter.setFont(theme.font("caption"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, data.picture_name or "")
        painter.setPen(QPen(theme.color("bronze_dark"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)


class EventPreview(QWidget):
    """Vista previa de un evento, con conmutador ES/EN."""

    EMPTY_KEY = N_("events.preview.empty")

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._ref = None
        self._lang = "es"
        self._manual = False
        self.setObjectName("eventPreview")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lang_group = QButtonGroup(self)
        self.lang_buttons = {}
        for lang in ("es", "en"):
            button = QPushButton()
            button.setObjectName(f"previewLang_{lang}")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, lang=lang: self.set_preview_language(lang))
            self.lang_group.addButton(button)
            self.lang_buttons[lang] = button
            bar.addWidget(button)
        bar.addStretch(1)
        outer.addLayout(bar)
        self.canvas = EventCanvas(self)
        outer.addWidget(self.canvas, 1)
        self.lang_buttons["es"].setChecked(True)
        if hasattr(session, "documentsChanged"):
            session.documentsChanged.connect(self._on_documents)
        if hasattr(session, "textsChanged"):
            session.textsChanged.connect(self._reload)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def bind(self, ref) -> None:
        """Enlaza con el evento ``ref`` y se repinta con cada cambio suyo o de sus textos. None: vacío."""
        self._ref = ref
        self._manual = False
        self._reload()

    def _on_documents(self, _rels=None) -> None:
        self._reload()

    def _reload(self) -> None:
        if self._manual:
            return
        self.canvas.data = load_event_data(self.session, self._ref, self._lang, game_art=self.canvas.game_art) \
            if self._ref is not None else None
        self.canvas.updateGeometry()
        self.canvas.update()

    def set_data(self, data: EventPreviewData | None) -> None:
        """Pinta ``data`` a mano, sin registro (pruebas y capturas)."""
        self._manual = True
        self.canvas.data = data
        self.canvas.updateGeometry()
        self.canvas.update()

    def data(self) -> EventPreviewData | None:
        return self.canvas.data

    def set_preview_language(self, lang: str) -> None:
        """Idioma de los textos del evento (no el de la interfaz)."""
        self._lang = lang if lang in ("es", "en") else "en"
        self.lang_buttons[self._lang].setChecked(True)
        self._reload()

    def preview_language(self) -> str:
        return self._lang

    def set_game_art(self, enabled: bool) -> None:
        self.canvas.game_art = bool(enabled)
        self._reload()

    def set_current_option(self, index: int | None) -> None:
        """Resalta una opción (la tarjeta con el foco)."""
        self.canvas.current_option = index
        self.canvas.update()

    def render_image(self, width: int = 0) -> QImage:
        """La vista previa como imagen (pruebas y capturas); ``width`` 0: el tamaño natural."""
        width = width or self.canvas.natural_width() + 16
        height = self.canvas.natural_height(min(width - 8, self.canvas.natural_width())) + 16
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.canvas.paint_window(painter, width, height)
        painter.end()
        return image

    def _on_language(self, _code: str = "") -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.lang_buttons["es"].setText(tr(N_("events.preview.lang_es")))
        self.lang_buttons["en"].setText(tr(N_("events.preview.lang_en")))
        self.canvas.empty_text = tr(self.EMPTY_KEY)
        self.canvas.update()
