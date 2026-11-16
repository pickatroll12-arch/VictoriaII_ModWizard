"""Proyecto › Validación: el informe del validador con línea base, arreglos y explicador (wizard §11, §11.1, §13.9).

- **Tabla**: gravedad, mensaje, entidad, archivo y línea de cada ``Problem`` del último
  informe de la sesión. Los heredados del juego base o de las dependencias (I11) se
  ocultan; el conmutador «Mostrar heredados (n)» los enseña, en cursiva.
- **[Arreglar ▾]**: el SimpleFix del problema seleccionado (con su plan de cambios y
  confirmación; los que borran o sustituyen, con confirmación explícita); los demás
  arreglos, en el desplegable (``problems_dock.FixFlow``).
- **[¿Por qué?]**: el panel del explicador (``ExplainerPanel``): las capas en el orden
  en que las carga el juego, con su línea real y su veredicto, la frase de lo que verá
  el jugador y sus arreglos. Se explica en segundo plano (``Session.request_explanation``:
  algunos explicadores tardan décimas con VSM) y mientras tanto dice «Explicando…».
- **Doble clic**: abre el archivo en esa línea en Archivos (``open_requested``).
- «Validar mod» (F7) lanza ``Session.validate`` (en segundo plano, cancelable; cancelar lo
  dice en la barra de estado). Si los documentos cambian después de la instantánea del
  informe (un Ctrl+Z, una edición mientras validaba), un aviso lo dice hasta volver a
  validar. Sin línea base, el resumen dice por qué y ofrece reintentarla.

No escribe nada: arreglar es una transacción de la sesión, deshacible con Ctrl+Z.
"""

from __future__ import annotations

import html
from collections import Counter

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.clausewitz import Severity
from ....i18n import N_, tr
from ... import theme
from ...pages.base import BasePage
from ...shell.problems_dock import (
    FULL_COLUMNS,
    SEVERITY_FILTERS,
    FixButton,
    FixFlow,
    ProblemsModel,
    fixes_disabled_reason,
    problems_table,
)
from ...viewers.common import ElidedLabel, core_language, format_number, format_seconds
from ...widgets import EmptyState, ParchmentCard, StatusBadge, make_icon, mark_data, show_in_stack

FILTER_DELAY_MS = 200
VERDICT_COLORS = {"wins": "success", "loses": "ink_muted", "hidden": "warning", "not_loaded": "warning",
                  "missing": "danger"}
# Alto mínimo del área de las capas: unas tres a la vista aunque el panel sea bajo (1100×700 con «Problemas»).
MIN_STEPS_HEIGHT = 112


class ExplainerPanel(ParchmentCard):
    """El explicador de conflicto de un problema: título, capas (capa · veredicto · archivo:línea, y debajo su línea
    real), la frase de lo que verá el jugador y sus arreglos (un botón por arreglo, que lanza ``fix_requested``).

    Maquetación (revisión it3): el veredicto va en una columna fija antes de la ruta, así que nunca queda fuera del
    ancho; la ruta se recorta por el medio con «…» (entera en la ayuda emergente) y el extracto se parte en líneas, y
    ninguno ensancha el panel. Las capas tienen un alto mínimo (``MIN_STEPS_HEIGHT``) y se desplazan en su propia área, que pide solo ese
    mínimo y se queda con el alto que sobre. No hay fila de cabecera que le quite alto a las capas a 1100×700: el
    título («Por qué el país SIL no existe en el juego») ya lo dice, y el botón de cerrar flota en la esquina, siempre
    a la vista. El título, las capas, la frase final y los arreglos van en un área que se desplaza entera cuando el
    panel es más bajo que todo eso (con el panel «Problemas» abierto mide menos de 100 px), en vez de montarse unos
    sobre otros o cortar la frase.
    """

    fix_requested = Signal(str)       # clave del arreglo
    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        # El relleno de la tarjeta ya separa del filete: el layout no suma otro (eran 22 px arriba y abajo).
        super().__init__(padding=10, parent=parent)
        self.setObjectName("explainerPanel")
        self.problem = None
        self.explanation = None
        self.loading = False
        self.fix_specs: list = []
        self._fixes_enabled = True
        self._fixes_reason = ""         # clave del motivo si los arreglos están desactivados
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)
        self.scroll = _transparent_scroll(QScrollArea())
        self.scroll.setObjectName("explainerScroll")
        self.content = QWidget()
        self.content.setAutoFillBackground(False)
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self.close_button = QToolButton(self)   # flota en la esquina (resizeEvent), por encima del área
        self.close_button.setObjectName("explainerClose")
        self.close_button.setIcon(make_icon("error", "cream", "cream", "gold_pale"))  # sobre el botón de madera
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.clicked.connect(self.closed)
        self.title = mark_data(QLabel())
        self.title.setObjectName("explainerTitle")
        self.title.setProperty("role", "heading")
        self.title.setFont(theme.font("body_bold"))
        self.title.setWordWrap(True)
        # Sitio para el botón de cerrar a la derecha del título, y alto para que no baje hasta la primera capa.
        self.title.setContentsMargins(0, 0, self.close_button.sizeHint().width() + 6, 0)
        self.title.setMinimumHeight(self.close_button.sizeHint().height())
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        body.addWidget(self.title)
        self.steps_scroll = _transparent_scroll(_StepsScroll())
        self.steps_scroll.setObjectName("explainerSteps")
        self.step_rows: list[tuple[QLabel, ElidedLabel, QLabel, QLabel, object]] = []
        self._fill_steps(())
        body.addWidget(self.steps_scroll, 100)   # casi todo el alto que sobre, hasta lo que ocupan sus capas
        self.outcome = mark_data(QLabel())
        self.outcome.setObjectName("explainerOutcome")
        self.outcome.setWordWrap(True)
        self.outcome.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self.outcome)
        self.fixes_box = QWidget()
        self.fixes_box.setAutoFillBackground(False)
        self.fixes_row = QVBoxLayout(self.fixes_box)   # uno por fila: un rótulo largo no ensancha el panel
        self.fixes_row.setContentsMargins(0, 0, 0, 0)
        self.fixes_row.setSpacing(4)
        body.addWidget(self.fixes_box)
        body.addStretch(1)   # con pocas capas, la frase y los arreglos siguen a la última y el hueco queda debajo
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self.fix_buttons: list[QPushButton] = []
        self.close_button.raise_()
        self.scroll.verticalScrollBar().installEventFilter(self)   # aparece o se va: el botón se recoloca
        self.retranslate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_close()
        if self.step_rows and event.size().width() != event.oldSize().width():
            self._update_steps_height()   # con otro ancho, los extractos ocupan otras líneas

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Resize):
            self._place_close()
        return super().eventFilter(watched, event)

    def _place_close(self) -> None:
        """Arriba a la derecha, a la izquierda de la barra del área si se ve (no la tapa)."""
        button = self.close_button
        button.resize(button.sizeHint())
        bar = self.scroll.verticalScrollBar()
        right = self.scroll.geometry().right() - (bar.width() if bar.isVisible() else 0)
        button.move(right - button.width() + 1, self.scroll.geometry().top())

    # --- API -----------------------------------------------------------------------------------------

    def show_loading(self, problem) -> None:
        """«Explicando…» mientras el explicador trabaja en segundo plano (``Session.request_explanation``)."""
        self.problem = problem
        self.explanation = None
        self.loading = True
        self.fix_specs = []
        self._fill_steps(())
        self._fill_fixes()
        self.retranslate()

    def show_explanation(self, problem, explanation, fix_specs: list) -> None:
        self.problem = problem
        self.explanation = explanation
        self.loading = False
        self.fix_specs = [spec for spec in fix_specs if explanation is None or spec.key in explanation.fixes
                          or not explanation.fixes]
        self._fill_steps(explanation.steps if explanation is not None else ())
        self._fill_fixes()
        self.retranslate()

    def set_fixes_enabled(self, enabled: bool, reason: str = "") -> None:
        """Activa los botones de arreglo; si no, ``reason`` (una clave) va en su ayuda emergente (solo lectura,
        revalidando…)."""
        self._fixes_enabled = enabled
        self._fixes_reason = "" if enabled else reason
        self._retranslate_fixes()

    def step_texts(self) -> list[tuple[str, str, str, str]]:
        """(capa, archivo:línea, veredicto, extracto) de cada paso tal como se muestran (para las pruebas)."""
        return [(layer.text(), where.text(), verdict.text(), excerpt.text())
                for layer, where, verdict, excerpt, _ in self.step_rows]

    def layout_problems(self) -> list[str]:
        """Lo que se ve mal ahora mismo (vacío si nada): veredictos fuera del ancho o recortados, capas sin su alto
        mínimo, una frase final cortada o piezas montadas. Lo usan las pruebas y ``tools/screenshot.py --report``."""
        found = []
        if self.content.width() > self.scroll.viewport().width():
            found.append(f"el contenido ({self.content.width()} px) es más ancho que el panel "
                         f"({self.scroll.viewport().width()} px)")
        viewport = self.steps_scroll.viewport()
        for layer, _, verdict, excerpt, step in self.step_rows:
            right = verdict.mapTo(viewport, QPoint(verdict.width(), 0)).x()
            if right > viewport.width() + 1:
                found.append(f"veredicto fuera del ancho: {step.verdict}")
            if verdict.width() < verdict.sizeHint().width() or layer.width() < layer.sizeHint().width():
                found.append(f"capa o veredicto recortados: {step.layer} {step.verdict}")
            if excerpt.height() < excerpt.heightForWidth(excerpt.width()):
                found.append(f"extracto cortado: {step.rel}:{step.line}")
            if excerpt.geometry().top() - layer.geometry().bottom() > 8:
                found.append(f"extracto separado de su capa: {step.rel}:{step.line}")
        if self.step_rows and self.steps_scroll.verticalScrollBar().maximum() > 0 \
                and self.steps_scroll.height() < MIN_STEPS_HEIGHT:   # no caben todas y no se ve ni el mínimo
            found.append(f"capas en {self.steps_scroll.height()} px (mínimo {MIN_STEPS_HEIGHT})")
        for label in (self.title, self.outcome):
            if label.text() and label.height() < label.heightForWidth(label.width()):
                found.append(f"{label.objectName()} cortado: {label.height()} de {label.heightForWidth(label.width())} px")
        pieces = [widget for widget in (self.title, self.steps_scroll, self.outcome, self.fixes_box)
                  if not widget.isHidden()]
        for upper, lower in zip(pieces, pieces[1:]):
            if upper.geometry().bottom() >= lower.geometry().top():
                found.append(f"{upper.objectName() or 'pieza'} montado sobre {lower.objectName() or 'pieza'}")
        text_right = self.title.mapTo(self, QPoint(self.title.contentsRect().right(), 0)).x()
        if self.close_button.geometry().left() <= text_right:
            found.append("el botón de cerrar tapa el título")
        if self.steps_scroll.isVisible():
            steps_top = self.steps_scroll.mapTo(self, QPoint(0, 0)).y()
            if self.close_button.geometry().bottom() >= steps_top and self.scroll.verticalScrollBar().value() == 0:
                found.append("el botón de cerrar tapa la primera capa")
        bar = self.scroll.verticalScrollBar()
        if bar.isVisible() and self.close_button.geometry().intersects(QRect(bar.mapTo(self, QPoint(0, 0)), bar.size())):
            found.append("el botón de cerrar tapa la barra")
        return found

    # --- interno -------------------------------------------------------------------------------------

    def _fill_steps(self, steps) -> None:
        """Una cuadrícula nueva por explicación (la anterior la destruye ``setWidget``): vaciar una ``QGridLayout``
        deja sus filas, con su alto mínimo, al final."""
        box = QWidget()
        box.setAutoFillBackground(False)
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(1)
        grid.setColumnStretch(2, 1)
        self.steps_box, self.steps_grid = box, grid
        self.step_rows = []
        for number, step in enumerate(steps):
            row = 3 * number   # cabecera, extracto y un hueco que la separa de la siguiente
            layer = mark_data(QLabel())
            layer.setObjectName("explainerLayer")
            layer.setFont(theme.font("body_bold"))
            # Columna fija antes de la ruta: el veredicto se ve siempre, por estrecho que sea el panel.
            verdict = mark_data(QLabel())
            verdict.setObjectName("explainerVerdict")
            verdict.setFont(theme.font("body_bold"))
            where = mark_data(ElidedLabel())   # la ruta se recorta por el medio; la línea no se pierde
            where.setFont(theme.font("mono", 8.5))
            where.setProperty("role", "caption")
            # La línea entera, con ajuste de línea: en loc_copy_degraded lo que importa («Efficacit?fiscale») está al
            # final de la fila. Ignored en horizontal: nunca ensancha el panel (sin perder el alto por anchura).
            excerpt = mark_data(QLabel())
            excerpt.setObjectName("explainerExcerpt")
            excerpt.setFont(theme.font("mono", 8.5))
            excerpt.setTextFormat(Qt.TextFormat.PlainText)
            excerpt.setWordWrap(True)
            excerpt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            policy.setHeightForWidth(True)
            excerpt.setSizePolicy(policy)
            top = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            self.steps_grid.addWidget(layer, row, 0, top)
            self.steps_grid.addWidget(verdict, row, 1, top)
            self.steps_grid.addWidget(where, row, 2)
            self.steps_grid.addWidget(excerpt, row + 1, 0, 1, 3)
            self.steps_grid.setRowMinimumHeight(row + 2, 5)
            self.step_rows.append((layer, where, verdict, excerpt, step))
        # Lo que sobre de alto va al final: con una o dos capas, sus filas no se estiran ni se separan.
        self.steps_grid.setRowStretch(3 * len(self.step_rows), 1)
        self.steps_scroll.setWidget(box)
        self._update_steps_height()

    def _update_steps_height(self) -> None:
        """Las capas nunca bajan de ``MIN_STEPS_HEIGHT`` (unas tres) ni, si son menos, de lo que ocupan; y no crecen más
        que lo que ocupan con el ancho que tienen (los extractos se parten en líneas)."""
        if not self.step_rows:
            self.steps_scroll.setMinimumHeight(0)
            self.steps_scroll.setVisible(False)
            return
        width = self.steps_scroll.viewport().width()
        layout = self.steps_grid
        natural = layout.heightForWidth(width) if layout.hasHeightForWidth() and width > 0 else -1
        if natural <= 0:
            natural = self.steps_box.sizeHint().height()
        self.steps_scroll.setMinimumHeight(min(MIN_STEPS_HEIGHT, natural))
        self.steps_scroll.setMaximumHeight(natural + 2)
        self.steps_scroll.setVisible(True)

    def _fill_fixes(self) -> None:
        while self.fixes_row.count():
            item = self.fixes_row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()   # deleteLater espera al bucle: mientras, se pintaba bajo el botón nuevo
                item.widget().deleteLater()
        self.fix_buttons = []
        for spec in self.fix_specs:
            button = _FixButton()
            button.setObjectName(f"explainerFix_{spec.key}")
            button.setIcon(make_icon("wrench", "gold_light"))
            button.clicked.connect(lambda checked=False, k=spec.key: self.fix_requested.emit(k))
            self.fixes_row.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            self.fix_buttons.append(button)
        self.fixes_box.setVisible(bool(self.fix_buttons))

    def _retranslate_fixes(self) -> None:
        lang = core_language()
        for button, spec in zip(self.fix_buttons, self.fix_specs):
            button.setText(spec.label(self.problem, lang))
            button.setEnabled(self._fixes_enabled)
            button.setToolTip(tr(self._fixes_reason) if self._fixes_reason else spec.label(self.problem, lang))
        self.fixes_box.updateGeometry()

    def retranslate(self) -> None:
        lang = core_language()
        self.setAccessibleName(tr("checks.explain_heading"))   # «¿Por qué?»: el título ya lo dice en pantalla
        self.close_button.setToolTip(tr("checks.explain_close"))
        explanation = self.explanation
        if self.loading:
            self.title.setText(tr("checks.explaining"))
            self.outcome.setText("")
        elif explanation is None:
            self.title.setText(tr("checks.explain_none"))
            self.outcome.setText("")
        else:
            self.title.setText(explanation.title(lang))
            self.outcome.setText(f'<span style="color:{theme.PALETTE["velvet_text"]};">'
                                 f'{html.escape(explanation.outcome(lang))}</span>')
        self.outcome.setVisible(bool(self.outcome.text()))
        for layer, where, verdict, excerpt, step in self.step_rows:
            layer.setText(step.layer_text(lang))
            location = "" if step.rel is None else (f"{step.rel}:{step.line}" if step.line else str(step.rel))
            where.set_text(location, "" if step.rel is None else str(step.rel))
            where.setToolTip(location)
            verdict.setText(step.verdict_text(lang))
            color = VERDICT_COLORS.get(step.verdict, "ink_soft")
            verdict.setStyleSheet(f"color: {theme.PALETTE[color]};")
            excerpt.setText(step.excerpt or tr("checks.explain_no_line"))
            excerpt.setToolTip(step.excerpt or "")
        self._retranslate_fixes()
        if self.step_rows:
            self._update_steps_height()


class _FixButton(QPushButton):
    """Botón de un arreglo que no ensancha el explicador: si no cabe, recorta su rótulo con «…» al pintarlo
    («Recuperar las filas de vanilla de «text.csv» (3 430 filas)» medía más que el panel a 1100 px y cortaba por la
    derecha la frase final y los extractos). ``text()`` conserva el rótulo entero, que también va en la ayuda."""

    MIN_WIDTH = 96

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.MIN_WIDTH), hint.height())

    def displayed_text(self) -> str:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        room = contents.width() - (option.iconSize.width() + 6 if not option.icon.isNull() else 0)
        return self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, max(room, 0))

    def paintEvent(self, event) -> None:
        if self.width() >= self.sizeHint().width():
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self.displayed_text()
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class _StepsScroll(QScrollArea):
    """El área de las capas pide solo su alto mínimo y se queda con el que sobre (factor de estiramiento): si pidiera
    todo lo que ocupan sus capas, el área exterior del explicador se desplazaría entera antes de encogerla, y la
    frase final quedaría debajo del todo."""

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self.minimumHeight())


def _transparent_scroll(scroll: QScrollArea) -> QScrollArea:
    """Área de desplazamiento vertical sobre el pergamino: sin marco, sin fondo propio y sin barra horizontal."""
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.viewport().setAutoFillBackground(False)
    return scroll


class ValidationPage(BasePage):
    """Proyecto › Validación. ``open_requested(problema)`` lo atiende la ventana (abre el archivo en su línea)."""

    key = "project.validation"
    title_key = N_("section.project.validation")
    subtitle_key = N_("section.project.validation.intro")
    icon_name = "validate"

    open_requested = Signal(object)
    export_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        super().__init__(parent)
        session.problemsChanged.connect(self.refresh)
        session.validationStateChanged.connect(self._update_state)
        session.validationProgress.connect(self._on_progress)
        session.projectOpened.connect(self._on_project_changed)
        session.projectClosed.connect(self._on_project_changed)
        session.indexStateChanged.connect(self._update_state)
        session.reportStaleChanged.connect(self._update_state)
        session.explanationReady.connect(self._on_explanation_ready)
        session.explanationFailed.connect(self._on_explanation_failed)
        self.refresh()

    # --- construcción --------------------------------------------------------------------------------

    def build(self) -> None:
        self.exec_dialog = lambda dialog: dialog.exec()   # la ventana lo sustituye (y las pruebas)
        self._progress = (0, 0)
        self._announced = False   # la barra de estado dice «Validando…» por esta página: al terminar se dice
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("checksValidate")
        self.validate_button.setProperty("accent", True)
        self.validate_button.setIcon(make_icon("validate", "gold_pale"))
        self.validate_button.clicked.connect(self.validate)
        self.export_button = QPushButton()
        self.export_button.setObjectName("checksExport")
        self.export_button.setIcon(make_icon("save", "gold_pale"))
        self.export_button.clicked.connect(self.export_requested)
        self.header.trailing.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header.trailing.addWidget(self.validate_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stack = QStackedWidget()
        self.empty = EmptyState("validate")
        self.empty_validate = QPushButton()
        self.empty_validate.setObjectName("checksEmptyValidate")
        self.empty_validate.setProperty("accent", True)
        self.empty_validate.setIcon(make_icon("validate", "gold_pale"))
        self.empty_validate.clicked.connect(self.validate)
        self.empty.add_action(self.empty_validate)
        self.stack.addWidget(self.empty)

        self.running = QWidget()
        running = QVBoxLayout(self.running)
        running.setContentsMargins(24, 12, 24, 12)
        running.addStretch(1)
        self.running_title = QLabel()
        self.running_title.setProperty("role", "empty-title")
        self.running_title.setFont(theme.font("heading", 13))
        self.running_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        running.addWidget(self.running_title)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("checksProgress")
        self.progress_bar.setRange(0, 0)
        running.addWidget(self.progress_bar)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("checksCancel")
        self.cancel_button.setIcon(make_icon("error", "cream"))
        self.cancel_button.clicked.connect(self.cancel_validation)
        running.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        running.addStretch(2)
        self.stack.addWidget(self.running)

        self.results = QWidget()
        results = QVBoxLayout(self.results)
        results.setContentsMargins(0, 0, 0, 0)
        results.setSpacing(6)
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.summary = QLabel()
        self.summary.setObjectName("checksSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        summary_row.addWidget(self.summary, 1)
        self.retry_baseline_button = QPushButton()
        self.retry_baseline_button.setObjectName("checksRetryBaseline")
        self.retry_baseline_button.setIcon(make_icon("refresh", "gold_light"))
        self.retry_baseline_button.clicked.connect(self.retry_baseline)
        summary_row.addWidget(self.retry_baseline_button, 0, Qt.AlignmentFlag.AlignTop)
        results.addLayout(summary_row)
        self.stale_badge = StatusBadge()
        self.stale_badge.setObjectName("checksStale")
        results.addWidget(self.stale_badge)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.severity_combo = QComboBox()
        self.severity_combo.setObjectName("checksSeverity")
        self.severity_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for data, _, _ in SEVERITY_FILTERS:
            self.severity_combo.addItem("", data)
        self.severity_combo.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.severity_combo)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("checksFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DELAY_MS)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        filters.addWidget(self.filter_edit, 1)
        self.inherited_check = QCheckBox()
        self.inherited_check.setObjectName("checksInherited")
        self.inherited_check.toggled.connect(self._apply_filter)
        filters.addWidget(self.inherited_check)
        results.addLayout(filters)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)
        self.table_stack = QStackedWidget()
        self.model = ProblemsModel(self.session, FULL_COLUMNS, self)
        self.view = problems_table(self.model)
        self.view.setObjectName("checksTable")
        self.view.activated.connect(self._on_activated)
        self.view.selectionModel().currentRowChanged.connect(self._on_current_changed)
        self.table_stack.addWidget(self.view)
        self.clean = EmptyState("check")
        self.table_stack.addWidget(self.clean)
        table_layout.addWidget(self.table_stack, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.flow = FixFlow(self.session, self, lambda dialog: self.exec_dialog(dialog), self.request_status)
        self.flow.applied.connect(self._on_fix_applied)
        self.fix_button = FixButton(self.flow)
        actions.addWidget(self.fix_button)
        self.why_button = QPushButton()
        self.why_button.setObjectName("checksWhy")
        self.why_button.setIcon(make_icon("question", "gold_light"))
        self.why_button.clicked.connect(lambda: self.show_explanation(self.current_problem()))
        actions.addWidget(self.why_button)
        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        self.hint.setWordWrap(True)
        actions.addWidget(self.hint, 1)
        table_layout.addLayout(actions)
        self.splitter.addWidget(table_box)
        self.explainer = ExplainerPanel()
        self.explainer.fix_requested.connect(lambda key: self.flow.run(self.explainer.problem, key))
        self.explainer.closed.connect(self.hide_explanation)
        self.splitter.addWidget(self.explainer)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._splitter_placed = False
        results.addWidget(self.splitter, 1)
        self.stack.addWidget(self.results)
        self.body.addWidget(self.stack, 1)
        # Ya dentro de la página: sin padre, setVisible(False) no basta y mostrarlo luego lo sacaría como ventana.
        self.explainer.setVisible(False)
        self.stale_badge.setVisible(False)
        self.retry_baseline_button.setVisible(False)
        show_in_stack(self.stack, self.empty)

    # --- API -----------------------------------------------------------------------------------------

    def validate(self) -> bool:
        """«Validar mod» (F7): valida en segundo plano con el validador del núcleo."""
        if self.session.project is None:
            self.request_status("status.no_project")
            return False
        started = self.session.validate()
        if started:
            self.request_status("checks.status_started")
            self._announced = True
            self._announce_end()   # una validación que terminó ya (o falló) al pedirla
        return started

    def cancel_validation(self) -> None:
        """«Cancelar»: para la validación (y la revalidación pendiente tras un arreglo) y lo dice."""
        self.session.cancel_validation()
        self._announced = False
        self.request_status("checks.status_cancelled")

    def retry_baseline(self) -> bool:
        """Vuelve a calcular la línea base que falló (y valida con ella)."""
        if not self.session.retry_baseline():
            return False
        self.request_status("checks.status_started")
        self._announced = True
        self._announce_end()
        return True

    def _announce_end(self) -> None:
        """Cambia el «Validando…» de la barra de estado por el resultado cuando termina la validación que pidió
        esta página (las de después de un arreglo no lo pisan: el estado dice qué se arregló)."""
        state = self.session.validation_state()
        if not self._announced or state in ("busy", "waiting"):
            return
        self._announced = False
        if self.session.validation_cancelled():
            # El informe que se ve (si lo hay) es el anterior: no es «terminada».
            self.request_status("checks.status_cancelled")
        elif state == "failed":
            self.request_status("checks.status_failed", error=self.session.validation_error() or "")
        elif state == "ready" and self.session.report is not None:
            # Del informe, no del modelo de la tabla: problemsChanged llega después de este cambio de estado.
            own = Counter(p.severity for p in self.session.problems())
            errors, warnings, infos = own[Severity.ERROR], own[Severity.WARNING], own[Severity.INFO]
            elapsed = self.session.report.elapsed
            # Invocables: la barra de estado vuelve a traducir al cambiar de idioma, y las cifras también («0,01 s»
            # en español; formateadas aquí se quedaban en el idioma de cuando terminó, «0.01 s»).
            self.request_status("checks.status_done", errors=lambda: format_number(errors),
                                warnings=lambda: format_number(warnings), infos=lambda: format_number(infos),
                                seconds=lambda: format_seconds(elapsed))

    def refresh(self) -> None:
        current = self.current_problem()
        explained = self.explainer.problem if self.explainer.isVisible() else None
        self.model.refresh()
        row = self.model.row_of(current) if current is not None else None
        if row is not None:
            self.view.setCurrentIndex(self.model.index(row, 0))
        elif self.model.rowCount():
            self.view.setCurrentIndex(self.model.index(0, 0))
        if explained is not None and self.model.row_of(explained) is None:
            self.hide_explanation()   # el problema ya no está (se arregló)
        self._on_current_changed()
        self._update_state()

    def current_problem(self):
        return self.model.problem_at(self.view.currentIndex())

    def select_problem(self, problem) -> bool:
        row = self.model.row_of(problem)
        if row is None and problem is not None and problem.inherited and not self.inherited_check.isChecked():
            self.inherited_check.setChecked(True)
            row = self.model.row_of(problem)
        if row is None:
            return False
        self.view.setCurrentIndex(self.model.index(row, 0))
        return True

    def show_explanation(self, problem=None) -> bool:
        """[¿Por qué?]: abre el explicador del problema (el seleccionado si no se da). Se explica en segundo plano:
        el panel dice «Explicando…» hasta que llega (``Session.explanationReady``)."""
        problem = problem if problem is not None else self.current_problem()
        if problem is None:
            return False
        self.select_problem(problem)
        if not self.session.request_explanation(problem):
            self.request_status("checks.status_explain_failed", error=lambda: tr("checks.explain_no_report"))
            return False
        self.explainer.show_loading(problem)
        self._sync_explainer_fixes()
        if not self._splitter_placed:
            # La primera vez, 3:2 (el divisor, por sus tamaños sugeridos, le daba al explicador menos de 300 px a
            # 1100); después, lo que el usuario deje.
            self._splitter_placed = True
            self.explainer.setVisible(True)
            total = sum(self.splitter.sizes()) or self.splitter.width()
            self.splitter.setSizes([total - total * 2 // 5, total * 2 // 5])
        self.explainer.setVisible(True)
        return True

    def hide_explanation(self) -> None:
        if self.explainer.loading:
            self.session.cancel_explanation()
            self.explainer.loading = False
        self.explainer.setVisible(False)

    def is_busy(self) -> bool:
        return self._filter_timer.isActive()

    # --- interno -------------------------------------------------------------------------------------

    def _on_project_changed(self, *args) -> None:
        self.hide_explanation()
        self.refresh()

    def _on_explanation_ready(self, problem, explanation) -> None:
        explainer = self.explainer
        if not explainer.isVisible() or not explainer.loading or explainer.problem != problem:
            return   # se cerró o se pidió otro mientras tanto
        explainer.show_explanation(problem, explanation, self.flow.fixes(problem))
        self._sync_explainer_fixes()

    def _on_explanation_failed(self, problem, error: str) -> None:
        if self.explainer.problem is not None and problem is not None and self.explainer.problem != problem:
            return
        self.explainer.loading = False
        self.hide_explanation()
        self.request_status("checks.status_explain_failed", error=error)

    def _sync_explainer_fixes(self) -> None:
        """Los arreglos del explicador, como [Arreglar]: desactivados en solo lectura y hasta el informe nuevo."""
        reason = fixes_disabled_reason(self.session)
        self.explainer.set_fixes_enabled(reason is None, reason or "")

    def _on_activated(self, index) -> None:
        problem = self.model.problem_at(index)
        if problem is not None:
            self.open_requested.emit(problem)

    def _on_current_changed(self, *args) -> None:
        problem = self.current_problem()
        self.fix_button.set_problem(problem)
        self.why_button.setEnabled(problem is not None and self.session.validation_context is not None)

    def _on_fix_applied(self, key: str, problem) -> None:
        self.hide_explanation()

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self._retranslate_running()

    def _apply_filter(self, *args) -> None:
        self._filter_timer.stop()
        severities = SEVERITY_FILTERS[max(0, self.severity_combo.currentIndex())][2]
        self.model.set_filter(inherited=self.inherited_check.isChecked(), severities=severities,
                              text=self.filter_edit.text())
        if self.model.rowCount() and not self.view.currentIndex().isValid():
            self.view.setCurrentIndex(self.model.index(0, 0))
        self._on_current_changed()
        self._update_state()

    def _update_state(self, *args) -> None:
        session = self.session
        state = session.validation_state()
        has_project = session.project is not None
        self.validate_button.setEnabled(has_project and not session.is_validating())
        self.export_button.setEnabled(has_project)
        self.empty_validate.setEnabled(has_project and not session.is_validating())
        self.empty_validate.setVisible(has_project)
        # Los textos del estado vacío se ponen siempre, se vea o no: oculto también cambia de idioma.
        if not has_project:
            self.empty.set_texts(tr("checks.empty_no_project_title"), tr("checks.empty_no_project"))
        elif state == "failed":
            self.empty.set_texts(tr("checks.failed_title"), tr("checks.failed_text",
                                                               error=session.validation_error() or ""))
        else:
            self.empty.set_texts(tr("checks.empty_title"), tr("checks.empty_text"))
        if not has_project or state == "failed" or (session.report is None and state not in ("busy", "waiting")):
            show_in_stack(self.stack, self.empty)
        elif state in ("busy", "waiting"):
            if self.progress_bar.maximum() and state == "waiting":
                self.progress_bar.setRange(0, 0)
            show_in_stack(self.stack, self.running)
        else:
            show_in_stack(self.stack, self.results)
            show_in_stack(self.table_stack, self.view if self.model.rowCount() else self.clean)
        # Tras un arreglo, hasta el informe nuevo, [Arreglar] y los del explicador no se pueden pulsar.
        self.fix_button.set_problem(self.current_problem())
        self._sync_explainer_fixes()
        self._retranslate_running()
        self._retranslate_summary()
        self._announce_end()

    def _retranslate_running(self) -> None:
        done, total = self._progress
        waiting = self.session.validation_state() == "waiting"
        self.running_title.setText(tr("checks.waiting_index" if waiting else "checks.running"))
        self.progress_bar.setFormat(tr("checks.progress", done=format_number(done), total=format_number(total))
                                    if total and not waiting else "")

    def _retranslate_summary(self) -> None:
        session = self.session
        report = session.report
        inherited = self.model.inherited_count()
        self.inherited_check.setText(tr("checks.show_inherited", count=format_number(inherited)))
        baseline_error = session.baseline_error()
        self.retry_baseline_button.setVisible(report is not None and baseline_error is not None)
        self.retry_baseline_button.setEnabled(not session.is_validating())
        stale = report is not None and session.report_stale()
        self.stale_badge.setVisible(stale)
        if stale:
            self.stale_badge.set_status("warning", tr("checks.stale"))
        if report is None:
            self.summary.setText("")
            return
        counts = self.model.counts()
        text = tr("checks.summary", files=format_number(report.files), seconds=format_seconds(report.elapsed),
                  errors=format_number(counts["error"]), warnings=format_number(counts["warning"]),
                  infos=format_number(counts["info"]))
        if not report.baseline_ready:
            text += " " + (tr("checks.no_baseline_reason", error=baseline_error) if baseline_error
                           else tr("checks.no_baseline"))
        elif inherited and not self.inherited_check.isChecked():
            text += " " + tr("checks.inherited_hidden", count=format_number(inherited))
        shown = self.model.rowCount()
        visible = sum(1 for p in self.model.all_problems() if self.inherited_check.isChecked() or not p.inherited)
        if shown != visible:
            text += " " + tr("checks.shown", shown=format_number(shown))
        color = theme.PALETTE["danger" if counts["error"] else "warning" if counts["warning"] else "success"]
        self.summary.setText(f'<span style="color:{color}; font-weight:600;">{html.escape(text)}</span>')
        self.clean.set_texts(tr("checks.clean_title"), tr("checks.clean_text", files=format_number(report.files)))

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "model"):
            return
        self.validate_button.setText(tr("checks.validate"))
        self.validate_button.setToolTip(tr("checks.validate_tooltip"))
        self.export_button.setText(tr("checks.export"))
        self.export_button.setToolTip(tr("checks.export_tooltip"))
        self.empty_validate.setText(tr("checks.validate"))
        self.empty_validate.setToolTip(tr("checks.validate_tooltip"))
        self.cancel_button.setText(tr("checks.cancel"))
        self.retry_baseline_button.setText(tr("checks.retry_baseline"))
        self.retry_baseline_button.setToolTip(tr("checks.retry_baseline_tooltip"))
        for position, (_, key, _) in enumerate(SEVERITY_FILTERS):
            self.severity_combo.setItemText(position, tr(key))
        self.severity_combo.setToolTip(tr("checks.filter_tooltip"))
        self.filter_edit.setPlaceholderText(tr("checks.filter_placeholder"))
        self.inherited_check.setToolTip(tr("checks.show_inherited_tooltip"))
        self.why_button.setText(tr("checks.why"))
        self.why_button.setToolTip(tr("checks.why_tooltip"))
        self.hint.setText(tr("checks.hint"))
        self.model.retranslate()
        self.fix_button.retranslate()
        self.explainer.retranslate()
        self._update_state()
