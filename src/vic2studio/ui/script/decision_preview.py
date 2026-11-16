"""Vista previa procedural de una decisión (wizard §13.8): la imagen de 95×95, el título, la descripción y
las condiciones y el efecto en frases (``core.script.phrases``). Sin recursos del juego salvo la imagen de
la propia decisión, leída de la instalación del usuario si existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ...i18n import N_, tr, translator
from .. import theme
from .event_preview import game_markup

PICTURE_SIZE = (95, 95)                          # la imagen de una decisión, en píxeles
WINDOW_WIDTH = 520


@dataclass(frozen=True)
class DecisionPreviewData:
    """Lo que pinta la vista previa; textos y frases en el idioma elegido."""

    ident: str
    title: str | None
    desc: str | None
    potential: str                               # «Aparece si: …»
    allow: str                                   # «Se puede tomar si: …»
    effect: str                                  # «Al tomarla: …»
    picture: Path | None = None                  # archivo de la imagen (DDS); None: no existe o sin arte
    picture_name: str = ""
    picture_image: QImage | None = None


def load_decision_data(session, ref, lang: str, *, game_art: bool = True) -> DecisionPreviewData | None:
    """Los datos de la vista previa de la decisión ``ref`` en ``lang`` (None si no se puede abrir)."""
    from ...core.script.phrases import phrase
    from .picture_picker import find_picture, image_from_bytes

    entities = getattr(session, "entities", None)
    if entities is None or ref is None:
        return None
    try:
        record = entities.open(ref)
    except (KeyError, FileNotFoundError, OSError):
        return None
    loc = getattr(session, "locsync", None)
    names = None
    finder = getattr(session, "_loc_for_search", None)
    if callable(finder):
        try:
            names = finder()
        except Exception:  # noqa: BLE001
            names = None
    index = getattr(session, "index", None)

    def text(key: str) -> str | None:
        if loc is None:
            return None
        return loc.text(key, lang) or loc.text(key, "en") or None

    def sentence(key: str) -> str:
        try:
            tree = record.script(key)
        except KeyError:
            tree = None
        if tree is None:
            return ""
        try:
            return phrase(tree, lang, index, names, lead=key)
        except Exception:  # noqa: BLE001
            return tree.root.source()

    picture_name = record.get("picture", None)
    shown = picture_name if isinstance(picture_name, str) and picture_name else ref.ident
    image = None
    if game_art:
        found = find_picture(session, "gfx/pictures/decisions", shown)
        image = image_from_bytes(found[1]) if found is not None else None
    return DecisionPreviewData(ident=ref.ident, title=text(f"{ref.ident}_title"), desc=text(f"{ref.ident}_desc"),
                               potential=sentence("potential"), allow=sentence("allow"), effect=sentence("effect"),
                               picture_name=shown, picture_image=image)


class DecisionCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("decisionCanvas")
        self.data: DecisionPreviewData | None = None
        self.game_art = True
        self.empty_text = ""
        self.setMinimumSize(320, 200)

    def _doc(self, markup: str, width: float, size: float, role: str = "body") -> QTextDocument:
        doc = QTextDocument()
        font = theme.font(role)
        font.setPointSizeF(size)
        doc.setDefaultFont(font)
        doc.setHtml(markup)
        doc.setTextWidth(width)
        return doc

    def _docs(self, width: int):
        data = self.data
        text_w = width - 36 - PICTURE_SIZE[0] - 14
        title = self._doc(game_markup(data.title or f"{data.ident}_title", base_color="#2a1a0c"), text_w, 13,
                          "heading")
        desc = self._doc(game_markup(data.desc or f"{data.ident}_desc",
                                     base_color="#2a1a0c" if data.desc else "#8f7c5c"), text_w, 10)
        lines = [self._doc(game_markup(text, base_color="#5b4126"), width - 48, 9.5)
                 for text in (data.potential, data.allow, data.effect) if text]
        return title, desc, lines

    def natural_height(self, width: int = WINDOW_WIDTH) -> int:
        if self.data is None:
            return 200
        title, desc, lines = self._docs(width)
        top = max(PICTURE_SIZE[1], title.size().height() + desc.size().height() + 6)
        return int(18 + top + 14 + sum(doc.size().height() + 8 for doc in lines) + 18)

    def sizeHint(self) -> QSize:
        return QSize(WINDOW_WIDTH, self.natural_height())

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
        window_w = min(width - 8, WINDOW_WIDTH) if width > 200 else WINDOW_WIDTH
        window_h = self.natural_height(window_w)
        x0, y0 = (width - window_w) / 2, max(4, (height - window_h) / 2)
        frame = QRectF(x0, y0, window_w, window_h)
        path = QPainterPath()
        path.addRoundedRect(frame, 8, 8)
        gradient = QLinearGradient(frame.topLeft(), frame.bottomLeft())
        gradient.setColorAt(0, theme.color("parchment_pale"))
        gradient.setColorAt(1, theme.color("parchment"))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(theme.color("bronze"), 2.5))
        painter.drawPath(path)
        picture = QRectF(x0 + 18, y0 + 18, *PICTURE_SIZE)
        image = data.picture_image if self.game_art else None
        if image is not None:
            painter.drawImage(picture, image)
        else:
            gradient = QLinearGradient(picture.topLeft(), picture.bottomRight())
            gradient.setColorAt(0, QColor("#8a6428"))
            gradient.setColorAt(1, QColor("#4a3214"))
            painter.fillRect(picture, gradient)
            painter.setPen(theme.color("gold_pale"))
            painter.setFont(theme.font("small"))
            painter.drawText(picture.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWrapAnywhere,
                             data.picture_name)
        painter.setPen(QPen(theme.color("bronze_dark"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(picture)
        title, desc, lines = self._docs(window_w)
        painter.save()
        painter.translate(picture.right() + 14, y0 + 16)
        title.drawContents(painter)
        painter.translate(0, title.size().height() + 6)
        desc.drawContents(painter)
        painter.restore()
        y = y0 + 18 + max(PICTURE_SIZE[1], title.size().height() + desc.size().height() + 6) + 14
        painter.setPen(QPen(theme.color("bronze"), 1))
        painter.drawLine(int(x0 + 18), int(y - 7), int(x0 + window_w - 18), int(y - 7))
        for doc in lines:
            painter.save()
            painter.translate(x0 + 24, y)
            doc.drawContents(painter)
            painter.restore()
            y += doc.size().height() + 8


class DecisionPreview(QWidget):
    """Vista previa de una decisión, con conmutador ES/EN."""

    EMPTY_KEY = N_("decisions.preview.empty")

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._ref = None
        self._lang = "es"
        self._manual = False
        self.setObjectName("decisionPreview")
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
        self.canvas = DecisionCanvas(self)
        outer.addWidget(self.canvas, 1)
        self.lang_buttons["es"].setChecked(True)
        if hasattr(session, "documentsChanged"):
            session.documentsChanged.connect(self._on_documents)
        if hasattr(session, "textsChanged"):
            session.textsChanged.connect(self._reload)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def bind(self, ref) -> None:
        """Enlaza con la decisión ``ref`` y se repinta con cada cambio suyo o de sus textos. None: vacío."""
        self._ref = ref
        self._manual = False
        self._reload()

    def _on_documents(self, _rels=None) -> None:
        self._reload()

    def _reload(self) -> None:
        if self._manual:
            return
        self.canvas.data = load_decision_data(self.session, self._ref, self._lang,
                                              game_art=self.canvas.game_art) if self._ref is not None else None
        self.canvas.updateGeometry()
        self.canvas.update()

    def set_data(self, data: DecisionPreviewData | None) -> None:
        self._manual = True
        self.canvas.data = data
        self.canvas.update()

    def data(self) -> DecisionPreviewData | None:
        return self.canvas.data

    def set_preview_language(self, lang: str) -> None:
        self._lang = lang if lang in ("es", "en") else "en"
        self.lang_buttons[self._lang].setChecked(True)
        self._reload()

    def set_game_art(self, enabled: bool) -> None:
        self.canvas.game_art = bool(enabled)
        self._reload()

    def render_image(self, width: int = 0) -> QImage:
        width = width or WINDOW_WIDTH + 16
        height = self.canvas.natural_height(min(width - 8, WINDOW_WIDTH)) + 16
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
        self.lang_buttons["es"].setText(tr(N_("decisions.preview.lang_es")))
        self.lang_buttons["en"].setText(tr(N_("decisions.preview.lang_en")))
        self.canvas.empty_text = tr(self.EMPTY_KEY)
        self.canvas.update()
