"""Revisión adversarial de la interfaz de la iteración 3: una prueba por hallazgo corregido (números del revisor).

Contra el ``Project`` real con el índice, la validación y la línea base falsos de ``_fake_index`` (y, en las que lo
dicen, con los motores reales del núcleo sobre el minijuego). Las medidas con VSM y las capturas están en el informe
de la ronda; aquí queda lo que se puede comprobar sin el corpus.
"""

import gc
import sys
import threading
import unittest
import weakref
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_index import (  # noqa: E402
    FakeExplainStep,
    FakeExplanation,
    FakeFixSpec,
    FakeIndexEngine,
    FakeProblem,
    fake_engines,
)
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402
from test_ui_loc_edit import MOD_TEXTS, TextsWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.project import ChangeSet, PlannedWrite, WriteAction  # noqa: E402
from vic2studio.core.project.diffing import TRUNCATION_LINE  # noqa: E402
from vic2studio.core.validate.model import (  # noqa: E402
    ACTION_MODIFY,
    LAYER_GAME,
    LAYER_MOD,
    VERDICT_LOSES,
    VERDICT_MISSING,
    VERDICT_WINS,
    ChangePlan,
    PlannedChange,
)
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.dialogs.add_key import AddKeyDialog  # noqa: E402
from vic2studio.ui.dialogs.fix_plan import FixPlanDialog  # noqa: E402
from vic2studio.ui.halls.project.validation import MIN_STEPS_HEIGHT  # noqa: E402
from vic2studio.ui.shell.pending_changes import PendingChangesPanel  # noqa: E402
from vic2studio.ui.shell.section_rail import RailButton  # noqa: E402
from vic2studio.ui.widgets.busy import is_busy_cursor  # noqa: E402

SIL_REL = "history/countries/SIL - Silesia.txt"
MOD = {SIL_REL: "capital = 1\r\n"}
COPIES = ["common/cb_types.txt"]
GC_OBJECTS = 300_000


class ReviewCase(TextsWindowCase):
    def open_checks(self, **options):
        options.setdefault("mod_files", MOD)
        options.setdefault("mod_copies", COPIES)
        return self.open_window(**options)

    def page(self):
        return self.window.page("project:validation")

    def validate(self):
        self.assertTrue(self.window.validate_mod())
        self.assertTrue(_qt.wait_until(lambda: self.window.session.validation_state() == "ready"
                                       and not self.window.is_busy(), 5000), "la validación no terminó")
        return self.page()

    def select(self, page, code: str):
        for row, item in enumerate(page.model.problems()):
            if item.code == code:
                page.view.setCurrentIndex(page.model.index(row, 0))
                return item
        self.fail(f"no está el problema {code}")

    def apply_register(self, page):
        self.select(page, "tag_not_registered")
        self.dialogs.handlers[FixPlanDialog] = lambda dialog: dialog.apply_button.click()
        page.fix_button.click()

    def settle(self, timeout: int = 5000) -> None:
        self.assertTrue(_qt.wait_until(lambda: not self.window.is_busy(), timeout), "la ventana sigue ocupada")


def long_explanation(rel: str, steps: int) -> FakeExplanation:
    """Como el explicador de SIL en VSM: muchas capas con rutas y líneas largas."""
    made = []
    for number in range(steps):
        layer, verdict = (LAYER_MOD, VERDICT_WINS) if number % 3 == 0 else (LAYER_GAME, VERDICT_LOSES)
        if number == steps - 1:
            layer, verdict = LAYER_GAME, VERDICT_MISSING
        made.append(FakeExplainStep(layer, VPath.of(f"history/provinces/germany/{682 + number} - Provincia muy "
                                                    f"larga de Silesia {number}.txt"), 1 + number,
                                    "owner = SIL # " + "un comentario larguísimo que no cabe " * 4, verdict))
    return FakeExplanation("explain.title.generic", tuple(made), "explain.outcome.tag_not_registered",
                           MappingProxyType({"rel": rel, "tag": "SIL"}), ("register_tag",))


def degraded_explanation() -> FakeExplanation:
    """Como el de ``loc_copy_degraded``: dos filas de CSV sin espacios, mucho más anchas que el panel."""
    row = "LEDGER_COUNTRY_NAME;Country;Pays;Land;;Pa" + "?s;Pa?s;" * 12 + "x"
    game = row.replace("?", "í")
    steps = (FakeExplainStep(LAYER_MOD, VPath.of("localisation/text.csv"), 12_177, row, VERDICT_WINS),
             FakeExplainStep(LAYER_GAME, VPath.of("localisation/text.csv"), 12_177, game, VERDICT_LOSES))
    return FakeExplanation("explain.title.generic", steps, "explain.outcome.generic",
                           MappingProxyType({"rel": "localisation/text.csv"}), ())


# --- 3 y 14: el explicador se ve entero --------------------------------------------------------------------


class ExplainerLayoutTests(ReviewCase):
    """3 (alta): a 1100×700 el área de las capas medía 65 px, los veredictos quedaban fuera del ancho (un QLabel
    sin recorte en un área sin barra horizontal) y la frase final se cortaba. 14: con «Problemas» abierto, la
    cabecera y el título se montaban."""

    def check_layout(self, page, *, label: str) -> None:
        explainer = page.explainer
        _qt.process_events(60)
        viewport = explainer.steps_scroll.viewport()
        for layer, where, verdict, excerpt, step in explainer.step_rows:
            right = verdict.mapTo(viewport, QPoint(verdict.width(), 0)).x()
            self.assertLessEqual(right, viewport.width() + 1, f"{label}: veredicto «{verdict.text()}» fuera del ancho")
            self.assertGreaterEqual(verdict.width(), verdict.sizeHint().width(), f"{label}: veredicto recortado")
            self.assertLess(verdict.mapTo(viewport, QPoint(0, 0)).x(), where.mapTo(viewport, QPoint(0, 0)).x(),
                            f"{label}: el veredicto va antes de la ruta")
            self.assertLessEqual(excerpt.mapTo(viewport, QPoint(excerpt.width(), 0)).x(), viewport.width() + 1,
                                 f"{label}: el extracto ensancha el panel")
            gap = excerpt.geometry().top() - layer.geometry().bottom()
            self.assertLessEqual(gap, 8, f"{label}: el extracto se separa {gap} px de su capa (filas estiradas)")
        if explainer.step_rows:
            steps = explainer.steps_scroll
            if steps.verticalScrollBar().maximum() > 0:   # no caben todas: al menos el mínimo a la vista
                self.assertGreaterEqual(steps.height(), MIN_STEPS_HEIGHT, f"{label}: capas sin su alto mínimo")
            else:
                last = explainer.step_rows[-1][3]
                bottom = last.mapTo(steps.viewport(), QPoint(0, last.height())).y()
                self.assertLessEqual(bottom, steps.viewport().height() + 1, f"{label}: sin barra, la última capa se corta")
                # Y el área no es más alta que sus capas: la frase final sigue a la última, sin un hueco en medio.
                self.assertLessEqual(steps.viewport().height() - bottom, 10, f"{label}: hueco bajo las capas")
        outcome = explainer.outcome
        if outcome.text():
            self.assertGreaterEqual(outcome.height(), outcome.heightForWidth(outcome.width()),
                                    f"{label}: frase final cortada")
        title = explainer.title
        self.assertGreaterEqual(title.height(), title.heightForWidth(title.width()), f"{label}: título cortado")
        title_bottom = title.mapTo(explainer, QPoint(0, title.height())).y()
        steps_top = explainer.steps_scroll.mapTo(explainer, QPoint(0, 0)).y()
        self.assertLessEqual(title_bottom, steps_top, f"{label}: el título se monta sobre las capas")
        close = explainer.close_button
        self.assertTrue(close.isVisible())
        text_right = title.mapTo(explainer, QPoint(title.contentsRect().right(), 0)).x()
        self.assertGreater(close.geometry().left(), text_right, f"{label}: el botón de cerrar tapa el título")
        self.assertTrue(explainer.rect().contains(close.geometry()), f"{label}: el botón de cerrar, a la vista")
        self.assertLessEqual(explainer.content.width(), explainer.scroll.viewport().width(),
                             f"{label}: algo ensancha el contenido y se corta por la derecha")
        for button in explainer.fix_buttons:
            self.assertLessEqual(button.mapTo(explainer.content, QPoint(button.width(), 0)).x(),
                                 explainer.content.width(), f"{label}: el arreglo se sale del panel")
        self.assertEqual(explainer.layout_problems(), [], label)

    def test_verdicts_steps_and_outcome_fit_at_both_sizes_in_both_languages(self):
        window = self.open_checks()
        page = self.validate()
        problem = self.select(page, "tag_not_registered")
        # Un rótulo como el de «Recuperar las filas de vanilla de «text.csv» (3 430 filas)», más ancho que el panel.
        base = page.flow.fixes(problem)[0]
        long = FakeFixSpec(base.key, "Recuperar las filas de vanilla de «localisation/text.csv» (3 430 filas)",
                           base.safe, base.plan, base.apply)
        specs = [long]
        for size in ((1100, 700), (1920, 1080)):
            window.resize(*size)
            for lang in ("es", "en"):
                set_language(lang)
                for name, explanation in (("SIL", long_explanation(SIL_REL, 12)),
                                          ("loc_copy_degraded", degraded_explanation()),
                                          ("una capa", long_explanation(SIL_REL, 1))):
                    with self.subTest(size=size, lang=lang, explanation=name):
                        page.explainer.show_explanation(problem, explanation, specs)
                        page.explainer.setVisible(True)
                        self.check_layout(page, label=f"{size} {lang} {name}")
                        # Sin «Problemas» abierto, título, capas (con su mínimo), frase y arreglos caben sin desplazar.
                        self.assertEqual(page.explainer.scroll.verticalScrollBar().maximum(), 0,
                                         f"{size} {lang} {name}: hay que desplazar el explicador")
                        self.assertTrue(all(text for _, _, text, _ in page.explainer.step_texts()))
                        visible = [b for b in page.explainer.fixes_box.findChildren(QPushButton) if b.isVisible()]
                        self.assertEqual(visible, page.explainer.fix_buttons, "sin botones de la explicación anterior")
                        if size[0] == 1100:
                            button = page.explainer.fix_buttons[0]
                            self.assertEqual(button.text(), long.label_key, "el rótulo entero se conserva")
                            self.assertTrue(button.displayed_text().endswith("…"), "y se recorta al pintarlo")
                            self.assertEqual(button.toolTip(), long.label_key)
        set_language("es")

    def test_with_the_problems_dock_open_at_1100_nothing_overlaps(self):
        window = self.open_checks()
        window.resize(1100, 700)
        page = self.validate()
        window.problems_button.click()
        problem = self.select(page, "tag_not_registered")
        page.explainer.show_explanation(problem, long_explanation(SIL_REL, 12), page.flow.fixes(problem))
        page.explainer.setVisible(True)
        self.check_layout(page, label="1100×700 con Problemas")

    def test_the_excerpt_wraps_and_shows_its_whole_line(self):
        """En loc_copy_degraded lo que importa («Pa?s» frente a «País») está al final de la fila."""
        window = self.open_checks()
        window.resize(1100, 700)
        page = self.validate()
        problem = self.select(page, "tag_not_registered")
        row = "BUDGET_BASE_TAX;Base tax efficiency: §Y$VAL$§W%;Efficacit?fiscale de base : §Y$VAL$§W%;;;Eficacia " \
              "de los impuestos: §Y$VAL$§W%;;;;;;;;x"
        steps = (FakeExplainStep(LAYER_MOD, VPath.of("localisation/text.csv"), 90, row, VERDICT_WINS),)
        page.explainer.show_explanation(problem, FakeExplanation("explain.title.generic", steps,
                                                                 "explain.outcome.generic",
                                                                 MappingProxyType({"rel": "text.csv"}), ()), [])
        page.explainer.setVisible(True)
        _qt.process_events(60)
        excerpt = page.explainer.step_rows[0][3]
        self.assertEqual(excerpt.text(), row)
        self.assertEqual(excerpt.toolTip(), row)
        self.assertGreater(excerpt.height(), 2 * excerpt.fontMetrics().height(), "más ancho que el panel: se parte")
        self.assertGreaterEqual(excerpt.height(), excerpt.heightForWidth(excerpt.width()), "y no se corta")
        self.assertLessEqual(page.explainer.content.width(), page.explainer.scroll.viewport().width())
        self.assertEqual(page.explainer.layout_problems(), [])


# --- 4: Ctrl+K abre un CSV que no es de localización en su línea ----------------------------------------------


class CsvLineTests(ReviewCase):
    """4 (alta, criterio 7): «549» y «Berlín» abrían map/definition.csv:550 en una ficha con las primeras 160
    líneas: la línea no se veía."""

    def definition(self) -> str:
        return "province;red;green;blue;x;x\r\n" + "".join(f"{i};{i % 256};{(3 * i) % 256};{(7 * i) % 256};"
                                                          f"Prov{i};x\r\n" for i in range(1, 700))

    def test_a_non_localisation_csv_opens_with_its_line_visible_and_marked(self):
        window = self.open_checks(game_files={"map/definition.csv": self.definition()})
        window.resize(1100, 700)
        self.assertTrue(window.open_location("map/definition.csv", 550))
        _qt.process_events(60)
        files = window.page("project")
        path, line = files.shown_location()
        self.assertEqual((path.name, line), ("definition.csv", 550))
        excerpt = files.preview.excerpt
        self.assertIn("549;", excerpt.textCursor().block().text(), "la fila de la provincia 549")
        self.assertEqual(excerpt.first_line() + excerpt.textCursor().blockNumber(), 550)
        cursor = excerpt.cursorRect()
        self.assertTrue(excerpt.viewport().rect().contains(cursor.center()), "la línea está a la vista")
        caption = files.preview.excerpt_caption.text()
        self.assertIn("550", caption)
        self.assertNotEqual(caption, tr("project.preview.excerpt", count=160))
        self.assertTrue(files.preview.details_scroll.viewport().rect().intersects(
            excerpt.geometry().translated(files.preview.details.mapTo(files.preview.details_scroll.viewport(),
                                                                       QPoint(0, 0)))),
            "el extracto, dentro de la ficha que se desplaza, también a la vista")


# --- 5 y 6: cancelar ---------------------------------------------------------------------------------------


class CancelTests(ReviewCase):
    def test_cancelling_the_revalidation_after_an_edit_does_not_start_it_again(self):
        """5: cancel_validation no limpiaba _revalidate y la validación volvía a arrancar sola."""
        window = self.open_checks()
        self.validate()
        session = window.session
        with session.edit("pending.undo_revert", name="x"):
            handle = session.project.ws.open("common/cb_types.txt")
            session.project.ws.replace_text(handle, b"peace_order = { }\r\n")
        self.assertTrue(window.validate_mod())
        self.assertEqual(session.validation_state(), "waiting", "espera a que el índice tenga la edición")
        self.page().cancel_button.click()
        before = self.engines["validation"].validations
        _qt.process_events(800)   # más que REINDEX_DELAY_MS: el reindexado termina
        self.settle()
        self.assertEqual(self.engines["validation"].validations, before, "volvió a validar sola")
        self.assertEqual(session.validation_state(), "ready")
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))

    def test_cancelling_says_so_with_and_without_a_previous_report(self):
        """6: la barra decía «terminada…» con el informe viejo, o «Validando…» para siempre."""
        gate = threading.Event()
        self.addCleanup(gate.set)
        window = self.open_checks(engines={"validation": {"gate": gate}})
        page = self.page()
        window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 3000))
        page.cancel_button.click()
        self.assertEqual(window.session.validation_state(), "idle")
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))
        gate.set()
        self.validate()
        self.assertTrue(window.status_label.text().startswith("Validación terminada"))
        gate.clear()
        self.engines["validation"].started.clear()
        window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 3000))
        page.cancel_button.click()
        self.assertEqual(window.session.validation_state(), "ready")
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))
        gate.set()
        _qt.process_events(100)
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))

    def test_cancelling_the_revalidation_after_a_fix_says_so(self):
        """La revalidación tras un arreglo no la anuncia la página (la barra dice el arreglo): cancelarla también
        tiene que decirlo, o la barra seguiría con «Arreglo aplicado»."""
        gate = threading.Event()
        gate.set()
        self.addCleanup(gate.set)
        window = self.open_checks(engines={"validation": {"gate": gate}})
        page = self.validate()
        gate.clear()
        self.engines["validation"].started.clear()
        self.apply_register(page)
        self.assertTrue(window.status_label.text().startswith("Arreglo aplicado"))
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 5000))
        self.assertIs(page.stack.currentWidget(), page.running)
        page.cancel_button.click()
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))
        self.assertFalse(window.session.fixes_blocked())

    def test_a_cancellation_from_elsewhere_is_announced_too(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        window = self.open_checks(engines={"validation": {"gate": gate}})
        window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 3000))
        window.session.cancel_validation()
        self.assertEqual(window.status_label.text(), tr("checks.status_cancelled"))


# --- 7 y 18: el informe desfasado y los arreglos mientras se revalida ------------------------------------------


class StaleReportTests(ReviewCase):
    def test_undoing_a_fix_revalidates_and_the_stale_report_is_marked_meanwhile(self):
        """7: tras Ctrl+Z de un arreglo, la tabla y las insignias seguían diciendo que estaba arreglado."""
        window = self.open_checks()
        page = self.validate()
        self.apply_register(page)
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2, 5000))
        self.settle()
        self.assertNotIn("tag_not_registered", [p.code for p in page.model.problems()])
        self.assertFalse(page.stale_badge.isVisible())
        window.undo()
        self.assertTrue(window.session.report_stale(), "el informe es de antes de deshacer")
        _qt.process_events(10)
        self.assertTrue(page.stale_badge.isVisible(), "la página lo dice")
        self.assertEqual(page.stale_badge.label.text(), tr("checks.stale"))
        self.assertIn(tr("checks.dock_stale"), window.problems_dock.summary.text())
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 3, 5000),
                        "deshacer un arreglo revalida, como aplicarlo")
        self.settle()
        self.assertIn("tag_not_registered", [p.code for p in page.model.problems()])
        self.assertFalse(window.session.report_stale())
        self.assertFalse(page.stale_badge.isVisible())
        hall = window.hall("project")
        self.assertEqual(hall.rail.buttons[hall.section_index("validation")].badge, 1, "la insignia vuelve")
        window.redo()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 4, 5000), "rehacer también")

    def test_an_ordinary_undo_marks_the_report_stale_without_revalidating(self):
        window = self.open_checks()
        self.validate()
        session = window.session
        with session.edit("pending.undo_revert", name="x"):
            handle = session.project.ws.open("common/cb_types.txt")
            session.project.ws.replace_text(handle, b"peace_order = { }\r\n")
        _qt.process_events(10)
        self.assertTrue(session.report_stale())
        self.assertTrue(self.page().stale_badge.isVisible())
        window.undo()
        _qt.process_events(800)
        self.settle()
        self.assertEqual(self.engines["validation"].validations, 1, "solo los arreglos revalidan solos")

    def test_editing_while_validating_leaves_the_report_stale(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        window = self.open_checks(engines={"validation": {"gate": gate}})
        session = window.session
        window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 3000))
        with session.edit("pending.undo_revert", name="x"):
            handle = session.project.ws.open("common/cb_types.txt")
            session.project.ws.replace_text(handle, b"peace_order = { }\r\n")
        gate.set()
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready", 5000))
        _qt.process_events(10)
        self.assertTrue(session.report_stale(), "el informe es de la instantánea de antes de la edición")
        self.assertTrue(self.page().stale_badge.isVisible())

    def test_fix_buttons_wait_for_the_new_report(self):
        """18: mientras se revalida, [Arreglar] dejaba pulsar sobre un problema ya arreglado."""
        gate = threading.Event()
        gate.set()
        window = self.open_checks(engines={"validation": {"gate": gate}})
        page = self.validate()
        window.problems_button.click()
        dock = window.problems_dock
        gate.clear()
        self.engines["validation"].started.clear()
        self.apply_register(page)
        item = next(p for p in dock.model.problems() if p.code == "tag_not_registered")
        dock.view.setCurrentIndex(dock.model.index(dock.model.row_of(item), 0))
        self.assertTrue(window.session.fixes_blocked())
        self.assertFalse(dock.fix_button.isEnabled(), "el panel aún lista el problema arreglado")
        self.assertEqual(dock.fix_button.toolTip(), tr("checks.fix_wait_tooltip"))
        self.assertFalse(page.fix_button.isEnabled())
        self.assertFalse(dock.flow.run(item), "ni por código")
        self.assertEqual(window.status_label.text(), tr("checks.status_fix_wait"))
        gate.set()
        self.assertTrue(_qt.wait_until(lambda: window.session.validation_state() == "ready"
                                       and not window.session.fixes_blocked(), 5000))
        self.settle()
        dock.view.setCurrentIndex(dock.model.index(0, 0))
        if dock.flow.fixes(dock.current_problem()):
            self.assertTrue(dock.fix_button.isEnabled(), "con el informe nuevo, se puede")
        self.assertEqual(len(window.session.history()), 1, "el arreglo se aplicó una sola vez")


# --- 8: cuentas de líneas del cambio entero --------------------------------------------------------------------


class LineCountTests(ReviewCase):
    """8: el plan y «Cambios pendientes» contaban sobre el diff recortado (+134 −134 en vez de +3 438 −3 438) y la
    línea de recorte salía en inglés."""

    def truncated_diff(self) -> str:
        lines = ["--- a/localisation/text.csv", "+++ b/localisation/text.csv", "@@ -1,134 +1,134 @@"]
        lines += [f"-KEY{i};Pa?s" for i in range(134)] + [f"+KEY{i};País" for i in range(134)]
        return "\n".join(lines[:400] + [TRUNCATION_LINE.format(12_177)])

    def test_the_fix_plan_counts_the_whole_change_and_translates_the_cut(self):
        window = self.open_checks()
        page = self.validate()
        problem = self.select(page, "tag_not_registered")
        spec = page.flow.fixes(problem)[0]
        plan = ChangePlan("register_tag", (PlannedChange(VPath.of("localisation/text.csv"), ACTION_MODIFY,
                                                         self.truncated_diff(), (3438, 3438)),))
        for lang in ("es", "en"):
            set_language(lang)
            dialog = FixPlanDialog(spec, problem, plan, window)   # la ventana lo destruye con ella
            self.assertEqual(dialog.tree.topLevelItem(0).text(2),
                             tr("pending.lines", added=_number(3438), removed=_number(3438)))
            text = dialog.diff.toPlainText()
            self.assertTrue(text.endswith(tr("pending.diff_more", count=_number(12_177))), text[-80:])
            self.assertNotIn("lines)", text)
        set_language("es")

    def test_pending_changes_counts_the_whole_change(self):
        self.open_checks()
        panel = PendingChangesPanel()
        self.addCleanup(panel.deleteLater)
        write = PlannedWrite(VPath.of("localisation/text.csv"), Path("/x/text.csv"), WriteAction.MODIFY, b"a", None,
                             diff=self.truncated_diff(), lines=(3438, 3438))
        panel.set_changeset(ChangeSet((write,)))
        self.assertEqual(panel.tree.topLevelItem(0).text(2), tr("pending.lines", added=_number(3438),
                                                                removed=_number(3438)))
        self.assertTrue(panel.diff.toPlainText().endswith(tr("pending.diff_more", count=_number(12_177))))


def _number(value: int) -> str:
    from vic2studio.ui.viewers.common import format_number

    return format_number(value)


# --- 10: símbolos y problemas de un documento sin guardar --------------------------------------------------------


class InMemoryTests(ReviewCase):
    """10: abrir un símbolo o un problema de un documento sin guardar llevaba al archivo del juego en una línea que
    no era la suya."""

    def test_a_symbol_of_an_unsaved_copy_says_it_is_only_in_memory(self):
        window = self.open_checks()
        page = self.validate()
        self.apply_register(page)
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2, 5000))
        self.settle()
        session = window.session
        symbol = next(s for s in session.search("SIL") if s.kind == "tag")
        self.assertIs(symbol.layer, LayerKind.MOD)
        files = window.page("project")
        before = files.shown_location()
        self.assertIsNone(session.location_path(symbol.rel, symbol.layer))
        self.assertFalse(window.open_symbol(symbol))
        self.assertEqual(window.status_label.text(), tr("status.location_in_memory", name="common/countries.txt"))
        self.assertEqual(files.shown_location(), before, "no se abrió el countries.txt del juego")

    def test_a_problem_of_a_modified_file_asks_to_save_first(self):
        window = self.open_checks(mod_files={**MOD, "common/countries.txt": "AAA = \"countries/Aland.txt\"\r\n"})
        session = window.session
        with session.edit("pending.undo_revert", name="x"):
            handle = session.project.ws.open("common/countries.txt")
            session.project.ws.replace_text(handle, b"# nuevo\r\nAAA = \"countries/Aland.txt\"\r\n")
        problem = FakeProblem("loc_key_missing", Severity.WARNING, VPath.of("common/countries.txt"), 2, None,
                              ("tag", "AAA"), (), MappingProxyType({"key": "AAA"}), False, ())
        self.assertFalse(window.open_problem(problem))
        self.assertEqual(window.status_label.text(), tr("status.location_unsaved", name="common/countries.txt"))
        session.save()
        self.assertTrue(window.open_problem(problem), "guardado, ya se abre en su línea")


# --- 11: el explicador en un hilo; plan, aplicar y guardar dicen que trabajan ------------------------------------


class BackgroundExplainTests(ReviewCase):
    def test_explaining_runs_off_the_interface_thread_and_says_so(self):
        """11: explain corría en el hilo de la interfaz (0,3–0,5 s con tag_not_registered en VSM)."""
        window = self.open_checks()
        page = self.validate()
        engine = self.engines["validation"]
        gate, threads = threading.Event(), []
        original = engine.explain

        def slow(problem, context):
            threads.append(threading.current_thread() is threading.main_thread())
            gate.wait(5)
            return original(problem, context)

        engine.explain = slow
        self.addCleanup(gate.set)
        self.select(page, "tag_not_registered")
        page.why_button.click()
        self.assertTrue(page.explainer.isVisible())
        self.assertEqual(page.explainer.title.text(), tr("checks.explaining"))
        self.assertTrue(window.is_busy())
        gate.set()
        self.settle()
        self.assertEqual(threads, [False], "en un hilo de tarea")
        self.assertEqual(page.explainer.title.text(), f"Por qué {SIL_REL} da este problema")
        self.assertEqual(len(page.explainer.step_rows), 2)

    def test_a_failing_explainer_says_why(self):
        window = self.open_checks()
        page = self.validate()

        def broken(problem, context):
            raise ValueError("explicador roto")

        self.engines["validation"].explain = broken
        self.select(page, "tag_not_registered")
        page.why_button.click()
        self.settle()
        self.assertFalse(page.explainer.isVisible())
        self.assertIn("explicador roto", window.status_label.text())

    def test_planning_and_applying_show_a_wait_cursor_and_say_what_they_do(self):
        window = self.open_checks()
        page = self.validate()
        engine = self.engines["validation"]
        seen = []
        plan, apply = engine.plan_fix, engine.apply_fix

        def planning(*args, **kwargs):
            seen.append(("plan", window.status_label.text(), is_busy_cursor()))
            return plan(*args, **kwargs)

        def applying(*args, **kwargs):
            seen.append(("apply", window.status_label.text(), is_busy_cursor()))
            return apply(*args, **kwargs)

        engine.plan_fix, engine.apply_fix = planning, applying
        self.apply_register(page)
        label = "Registrar SIL en countries.txt"
        self.assertEqual(seen, [("plan", tr("checks.status_planning", fix=label), True),
                                ("apply", tr("checks.status_applying", fix=label), True)])
        self.assertFalse(is_busy_cursor(), "el cursor vuelve al terminar")

    def test_saving_says_how_many_files_with_a_wait_cursor(self):
        window = self.open_checks()
        session = window.session
        with session.edit("pending.undo_revert", name="x"):
            handle = session.project.ws.open(SIL_REL)
            session.project.ws.replace_text(handle, b"capital = 2\r\n")
        seen, save = [], session.save

        def saving(*args, **kwargs):
            seen.append((window.status_label.text(), is_busy_cursor()))
            return save(*args, **kwargs)

        session.save = saving
        self.assertTrue(window.save_project())
        self.assertEqual(seen, [(tr("status.saving_one", count=1), True)])
        self.assertFalse(is_busy_cursor())


# --- 12: lo que entregan las tareas sigue vigilado mientras se usa ------------------------------------------------


class _BigIndexEngine(FakeIndexEngine):
    """Un índice con muchos objetos vivos (como el de VSM): ui/tasks.py lo congela al entregarlo."""

    def build(self, snapshot, overrides, *, progress=None, cancelled=None):
        index = super().build(snapshot, overrides, progress=progress, cancelled=cancelled)
        index.payload = [[i] for i in range(GC_OBJECTS)]
        return index


class CollectorTests(ReviewCase):
    def test_the_index_stays_frozen_while_the_session_holds_it(self):
        """12: la sesión soltaba el _Outcome (solo guardaba .value) y gc.unfreeze() devolvía el índice a la generación
        más vieja: pasadas de 0,5 s en el hilo de la interfaz con VSM."""
        from vic2studio.ui import tasks

        gc.collect()
        gc.unfreeze()
        # El estado del recolector es del proceso: que no cuenten resultados vigilados de otras pruebas (si alguno
        # siguiera vivo, no se descongelaría nada y la prueba pasaría también sin el arreglo).
        with tasks._gc_lock:
            tasks._gc_watched.clear()
        engines = fake_engines()
        engines["index"] = _BigIndexEngine()
        window = self.open_checks(engines={"ready": engines})
        self.settle()
        _qt.process_events(50)
        self.assertGreaterEqual(gc.get_freeze_count(), GC_OBJECTS, "el índice volvió a la generación más vieja")
        index = weakref.ref(window.session.index)
        window.session.close_project(discard=True)
        _qt.process_events(50)
        self.assertIsNone(index(), "cerrado el proyecto, el índice se suelta")
        gc.unfreeze()


# --- 13 y 23: Textos sin recorrer las claves de más ----------------------------------------------------------------


class TextsCostTests(ReviewCase):
    def test_an_edit_counts_once_and_refreshes_the_badges_and_the_visible_page_once(self):
        """13: el contador de «Pendientes» recorría entries() 2–3 veces por edición (0,35–0,65 s con VSM), y las dos
        páginas de la sala se refrescaban aunque una estuviera oculta."""
        from vic2studio.ui.halls.localisation import texts as texts_module

        window = self.open_window(mod_files=MOD_TEXTS)
        page = self.texts()
        hidden = window.page("localisation:pending")
        hall = window.hall("localisation")
        refreshes, listed, counted = [], [], []
        original = hall.refresh_badges
        hall.refresh_badges = lambda: (refreshes.append(1), original())[1]
        set_entries = hidden.model.set_entries
        hidden.model.set_entries = lambda entries: (listed.append(1), set_entries(entries))[1]
        locsync = window.session.locsync
        untranslated = locsync.untranslated
        locsync.untranslated = lambda entry: (counted.append(1), untranslated(entry))[1]
        self.addCleanup(lambda: locsync.__dict__.pop("untranslated", None))
        self.edit_cell(page, "AAA", "en", "Ahvenanmaa")
        self.assertEqual(len(refreshes), 1, "una vez por vuelta del bucle, no una por señal")
        self.assertEqual(listed, [], "la página oculta no se refresca hasta mostrarse")
        self.assertEqual(hall.rail.buttons[hall.section_index("pending")].badge, 1)
        counted.clear()
        self.assertEqual(texts_module.pending_count(locsync), 1)
        self.assertEqual(counted, [], "con la misma lista de claves, el recuento guardado")
        self.texts("pending")
        self.assertEqual(listed, [1], "al mostrarse, se pone al día")

    def test_texts_are_not_listed_while_the_hall_is_hidden(self):
        """23: al terminar de leer los textos, las dos páginas de Textos (ocultas) y su contador recorrían todas las
        claves en el hilo de la interfaz."""
        from unittest import mock

        from vic2studio.core.locsync import LocSync

        calls = []
        original = LocSync.entries

        def counting(self, *args, **kwargs):
            calls.append(1)
            return original(self, *args, **kwargs)

        with mock.patch.object(LocSync, "entries", counting):
            window = self.open_window(mod_files=MOD_TEXTS)
            self.assertTrue(window.session.texts_ready())
            self.assertNotEqual(window.current_page_key().split(":")[0], "localisation")
            self.assertEqual(calls, [], "con Textos oculta no hace falta la lista")
            page = self.texts("pending")
            self.assertEqual(page.visible_keys(), ["BBB"], "al mostrarse se pone al día")
        hall = window.hall("localisation")
        self.assertEqual(hall.rail.buttons[hall.section_index("pending")].badge, 1)

    def test_closing_the_project_releases_its_locsync(self):
        """Sospecha: tras cerrar, TextsPage.model.pending_check retenía la LocSync vieja."""
        window = self.open_window(mod_files=MOD_TEXTS)
        self.texts("all")
        self.texts("pending")
        ref = weakref.ref(window.session.locsync)
        window.session.close_project(discard=True)
        _qt.process_events(30)
        gc.collect()
        for section in ("all", "pending"):
            self.assertIsNone(window.page(f"localisation:{section}").model.pending_check)
        self.assertIsNone(ref(), "alguien retiene la LocSync del proyecto cerrado")


# --- 15: Ctrl+K y el filtro de problemas piden la localización una vez -----------------------------------------


class SearchCostTests(ReviewCase):
    def test_a_search_asks_for_the_effective_localisation_once(self):
        """15: Session.display recalculaba la localización por resultado (Ctrl+K «a», 180–270 ms con VSM)."""
        window = self.open_window(mod_files={"localisation/00_TESTMOD_countries.csv":
                                             "AAA;Aland;;;;Alandia;;;;;;;;x\r\nBBB;Borland;;;;;;;;;;;;x\r\n"})
        locsync = window.session.locsync
        calls = []
        original = locsync.localisation_db
        locsync.localisation_db = lambda: (calls.append(1), original())[1]
        self.addCleanup(lambda: locsync.__dict__.pop("localisation_db", None))
        window.open_palette("a")
        self.assertGreater(len(window.palette.results()), 3)
        window.palette.edit.setText("b")
        window.palette.search()
        self.assertLessEqual(len(calls), 1, "una vez, y se guarda hasta que cambian los textos")
        page = self.texts()
        self.edit_cell(page, "AAA", "es", "Ahvenanmaa")
        window.open_palette("ahvenan")
        self.assertIn(("tag", "AAA"), [(r.symbol.kind, r.symbol.name) for r in window.palette.results()],
                      "tras editar un texto, la búsqueda usa el nuevo")
        self.assertEqual(len(calls), 2)


# --- 16 y 22: teclado de Ctrl+K -----------------------------------------------------------------------------------


class PaletteKeyboardTests(ReviewCase):
    def open_palette(self, text: str):
        window = self.window
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        QTest.keyClick(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(20)
        palette = window.palette
        QTest.keyClicks(palette.edit, text)
        palette.search()
        return palette

    def test_shift_enter_opens_the_code(self):
        """16: Mayús+Intro hacía lo mismo que Intro, aunque la ayuda decía «ver el código»."""
        window = self.open_window(mod_files=MOD_TEXTS)
        palette = self.open_palette("CCC")
        row = next(i for i, r in enumerate(palette.results()) if (r.symbol.kind, r.symbol.name) == ("tag", "CCC"))
        palette.list.setCurrentRow(row)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        viewer = window.page("project").clausewitz_viewer
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                       and viewer.code.current_line() == 3, 5000))
        self.assertEqual(viewer.current_tab(), "source", "en la pestaña Código")
        palette = self.open_palette("free_people")
        row = next(i for i, r in enumerate(palette.results()) if r.symbol.kind == "loc_key")
        symbol = palette.results()[row].symbol
        palette.list.setCurrentRow(row)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(window.current_page_key(), "localisation", "una clave de texto: su CSV")
        csv = window.page("localisation")
        self.assertTrue(_qt.wait_until(lambda: csv.editor.current_load() is not None and not window.is_busy(), 5000))
        self.assertEqual(csv.editor.current_load().path.name, symbol.rel.name)
        self.assertEqual(csv.editor.selected_line(), symbol.line)

    def test_escape_gives_the_focus_back(self):
        """22: Esc dejaba el foco en el botón Buscar del estandarte."""
        window = self.open_window()
        page = window.show_page("project:validation")
        window.validate_mod()
        self.settle()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        page.filter_edit.setFocus()
        _qt.process_events(10)
        self.assertTrue(page.filter_edit.hasFocus())
        palette = self.open_palette("abc")
        self.assertTrue(palette.edit.hasFocus())
        QTest.keyClick(palette.edit, Qt.Key.Key_Escape)
        self.assertFalse(palette.isVisible())
        self.assertTrue(page.filter_edit.hasFocus(), f"el foco está en {window.focusWidget()}")


# --- 17: «Añadir clave» y Windows-1252 ------------------------------------------------------------------------------


class AddKeyEncodingTests(ReviewCase):
    def test_text_or_key_outside_cp1252_disable_ok_with_the_reason_in_the_ui_language(self):
        """17: «Añadir clave» aceptaba «Łódź» (LocSync.ensure lo rechazaba después, con el mensaje en español y sin
        lo tecleado)."""
        self.open_window()
        for lang, language in (("es", "Español"), ("en", "Español")):
            set_language(lang)
            dialog = AddKeyDialog(self.window.session.locsync, self.window)   # la ventana lo destruye con ella
            dialog.key_edit.setText("NEW_KEY")
            dialog.text_edits["es"].setText("Łódź")
            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertEqual(dialog.problem_text(), tr("texts.add.unencodable", language=language, char="Ł",
                                                       code="U+0141"))
            self.assertIsNone(dialog.values())
            self.assertEqual(dialog.text_edits["es"].text(), "Łódź", "lo tecleado sigue ahí")
            dialog.text_edits["es"].setText("Lodz")
            self.assertTrue(dialog.ok_button.isEnabled())
            dialog.key_edit.setText("KEY_Ł")
            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertEqual(dialog.problem_text(), tr("texts.add.unencodable_key", char="Ł", code="U+0141"))
        set_language("es")

    def test_a_refused_key_is_reported_in_the_ui_language(self):
        """texts.py:596 usaba str(exc) (en español) si ensure rechazaba el texto."""
        window = self.open_window()
        page = self.texts()
        set_language("en")

        def fill(dialog):
            dialog.key_edit.setText("NEW_KEY")
            dialog.text_edits["en"].setText("ok")
            dialog._problem = None
            dialog.values = lambda: ("NEW_KEY", "misc", {"en": "Łódź"})   # como si el diálogo lo dejara pasar
            dialog.accept()

        self.dialogs.handlers[AddKeyDialog] = fill
        page.add_button.click()
        self.assertEqual(window.status_label.text(), tr("texts.status_unencodable", char="Ł", code="U+0141"))
        self.assertEqual(window.session.dirty_count(), 0)
        set_language("es")


# --- 19: «99+» ---------------------------------------------------------------------------------------------------


class BadgeTests(unittest.TestCase):
    def test_a_three_figure_badge_fits_in_its_pill(self):
        """19: «99+» no cabía en su círculo de 18 px."""
        from PySide6.QtGui import QFontMetricsF

        from vic2studio.ui import theme

        for horizontal in (False, True):
            button = RailButton("validate")
            self.addCleanup(button.deleteLater)
            button.setText("Validación")
            button.set_horizontal(horizontal)
            button.resize(200, button.height_hint())
            button.set_badge(7)
            small = button.badge_rect()
            self.assertEqual(small.width(), small.height(), "con una cifra, un círculo")
            button.set_badge(1234)
            rect = button.badge_rect()
            text = QFontMetricsF(theme.font("badge", 8.5)).horizontalAdvance("99+")
            self.assertGreaterEqual(rect.width(), text + 8, "el texto cabe con margen")
            self.assertLessEqual(button.text_rect().right(), rect.left(), "el nombre no se monta sobre el contador")
            self.assertGreaterEqual(rect.left(), button.plate().left())


# --- 20: la línea base que falla -------------------------------------------------------------------------------


class BaselineTests(ReviewCase):
    def test_a_failed_baseline_says_why_is_not_retried_on_every_f7_and_can_be_retried(self):
        """20: baseline_error() no se usaba y la línea base se recalculaba (y fallaba) en cada F7."""
        error = PermissionError(13, "Permiso denegado", "/cache/baseline")
        self.open_checks(engines={"baseline": {"error": error}})
        for _ in range(3):
            page = self.validate()
        engine = self.engines["baseline"]
        self.assertEqual(engine.computed, 0, "fallar es lanzar antes de contar")
        calls = []
        original = engine.compute
        engine.compute = lambda *a, **k: (calls.append(1), original(*a, **k))[1]
        self.validate()
        self.validate()
        self.assertEqual(calls, [], "no se reintenta en cada F7")
        reason = self.window.session.baseline_error()
        self.assertIn("Permiso denegado", reason)
        self.assertIn(tr("checks.no_baseline_reason", error=reason), page.summary.text())
        self.assertTrue(page.retry_baseline_button.isVisible())
        engine.error = None
        page.retry_baseline_button.click()
        self.assertTrue(_qt.wait_until(lambda: self.window.session.validation_state() == "ready"
                                       and not self.window.is_busy(), 5000))
        self.assertEqual(calls, [1])
        self.assertIsNone(self.window.session.baseline_error())
        self.assertFalse(page.retry_baseline_button.isVisible())
        self.assertGreater(page.model.inherited_count(), 0, "con línea base, los del juego salen heredados")


# --- 21: solo lectura -----------------------------------------------------------------------------------------------


class ReadOnlyTests(ReviewCase):
    def test_the_explainer_fix_buttons_are_disabled_in_a_read_only_project(self):
        """21: en solo lectura, los botones de arreglo del explicador seguían activos."""
        window = self.open_checks(read_only=True)
        page = self.validate()
        self.select(page, "tag_not_registered")
        page.why_button.click()
        self.settle()
        self.assertTrue(page.explainer.fix_buttons)
        for button in page.explainer.fix_buttons:
            self.assertFalse(button.isEnabled())
            self.assertEqual(button.toolTip(), tr("checks.fix_read_only_tooltip"))
        self.assertFalse(page.fix_button.isEnabled())
        self.assertEqual(window.session.dirty_count(), 0)


# --- sospechas: una tarea que lanza no deja la interfaz esperando -------------------------------------------------


class _Boom(BaseException):
    """Algo que las tareas no atrapan (no es ``Exception``): llega como ``TaskRunner.failed``."""


class FailedTaskTests(ReviewCase):
    def test_an_index_that_raises_leaves_a_failed_state(self):
        engines = fake_engines(index={"error": _Boom("índice roto")})
        with self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            window = self.open_checks(engines={"ready": engines}, wait_texts=False)
            self.assertTrue(_qt.wait_until(lambda: window.session.index_state() == "failed", 5000))
        self.assertIn("índice roto", window.session.index_error())

    def test_a_validation_that_raises_ends_as_failed(self):
        engines = fake_engines(validation={"error": _Boom("regla rota")})
        window = self.open_checks(engines={"ready": engines})
        with self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            window.validate_mod()
            self.assertTrue(_qt.wait_until(lambda: window.session.validation_state() == "failed", 5000))
        self.assertIn("regla rota", window.session.validation_error())
        self.assertFalse(window.session.is_validating())

    def test_reading_texts_that_raises_says_why_in_texts(self):
        from unittest import mock

        def broken(entries, cancelled=None):
            raise _Boom("CSV roto")

        with mock.patch("vic2studio.ui.session.read_localisation", broken), \
                self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            window = self.open_window(mod_files=MOD_TEXTS, wait_texts=False)
            self.assertTrue(_qt.wait_until(lambda: window.session.texts_error() is not None, 5000))
        page = self.texts()
        self.assertIs(page.stack.currentWidget(), page.empty)
        self.assertEqual(page.empty.title.text(), tr("texts.failed_title"))
        self.assertIn("CSV roto", page.empty.text.text())


if __name__ == "__main__":
    unittest.main()
