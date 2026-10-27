"""Proyecto › Validación y panel de problemas (wizard §11, §11.1, §13.9), contra el ``Project`` real.

El validador, el índice y la línea base son los falsos de ``_fake_index`` (los reales son del agente A): F7 y el
botón «Validar mod» de Archivos, la tabla (gravedad, mensaje, entidad, archivo y línea), los heredados ocultos con
su conmutador, [Arreglar ▾] con el plan de cambios y la confirmación (explícita si el arreglo borra), [¿Por qué?]
con el explicador, el doble clic que abre el archivo en su línea, los estados (esperando al índice, fallo, sin
línea base, cancelar) y el cambio de idioma. Al final, lo mismo con los motores reales del núcleo (``RealCoreTests``;
el recorrido completo con un ``Project`` real está en ``test_e2e_it3``).
"""

import sys
import threading
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_index import FIXES_OF, SEVERITIES, FakeProblem, problem  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_ui_loc_edit import TextsWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.project import WriteAction  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.dialogs.fix_plan import FixPlanDialog  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.shell.problems_dock import (  # noqa: E402
    COL_ENTITY,
    COL_FILE,
    COL_LINE,
    COL_MESSAGE,
    COL_SEVERITY,
    MESSAGE_MIN_WIDTH,
)

SIL_REL = "history/countries/SIL - Silesia.txt"
MOD = {SIL_REL: "capital = 1\r\n"}
COPIES = ["common/cb_types.txt"]
COLUMNS = (COL_SEVERITY, COL_MESSAGE, COL_ENTITY, COL_FILE, COL_LINE)


class ValidationCase(TextsWindowCase):
    def open_checks(self, **options):
        options.setdefault("mod_files", MOD)
        options.setdefault("mod_copies", COPIES)
        return self.open_window(**options)

    def page(self):
        return self.window.page("project:validation")

    def validate(self, *, via_key: bool = False):
        window = self.window
        if via_key:
            window.activateWindow()
            QTest.qWaitForWindowActive(window, 2000)
            QTest.keyClick(window, Qt.Key.Key_F7)
        else:
            self.assertTrue(window.validate_mod())
        self.assertTrue(_qt.wait_until(lambda: window.session.validation_state() == "ready"
                                       and not window.is_busy(), 5000), "la validación no terminó")
        return self.page()

    def rows(self, page) -> list[list[str]]:
        model = page.model
        return [[model.index(r, c).data() for c in range(len(model.columns))] for r in range(model.rowCount())]

    def select(self, page, code: str):
        for row, item in enumerate(page.model.problems()):
            if item.code == code:
                page.view.setCurrentIndex(page.model.index(row, 0))
                return item
        self.fail(f"no está el problema {code}")


class TableTests(ValidationCase):
    def test_f7_validates_and_lists_the_mod_problems_without_the_inherited_ones(self):
        window = self.open_checks()
        page = self.validate(via_key=True)
        self.assertIs(window.current_page(), page)
        self.assertEqual(page.model.columns, COLUMNS)
        headers = [page.model.headerData(i, Qt.Orientation.Horizontal) for i in range(5)]
        self.assertEqual(headers, ["Gravedad", "Mensaje", "Entidad", "Archivo", "Línea"])
        self.assertEqual(self.rows(page), [
            ["Error", "El país SIL tiene historia pero no está en common/countries.txt.", "SIL", SIL_REL, "1"],
            ["Nota", "common/cb_types.txt es idéntico al del juego base.", "", "common/cb_types.txt", ""],
        ])
        self.assertEqual(page.inherited_check.text(), tr("checks.show_inherited", count="3"))
        self.assertIn(tr("checks.inherited_hidden", count="3"), page.summary.text())
        hall = window.hall("project")
        self.assertEqual(hall.rail.buttons[hall.section_index("validation")].badge, 1, "errores sin heredados")
        self.assertIn("1", window.problems_button.toolTip())

    def test_the_inherited_ones_show_in_italics_with_the_switch(self):
        self.open_checks()
        page = self.validate()
        page.inherited_check.setChecked(True)
        self.assertEqual(page.model.rowCount(), 5)
        inherited = [r for r, item in enumerate(page.model.problems()) if item.inherited]
        self.assertEqual(len(inherited), 3)
        self.assertTrue(page.model.index(inherited[0], 1).data(Qt.ItemDataRole.FontRole).italic())
        self.assertIn(tr("checks.inherited_tooltip"), page.model.index(inherited[0], 1).data(Qt.ItemDataRole.ToolTipRole))
        page.inherited_check.setChecked(False)
        self.assertEqual(page.model.rowCount(), 2)

    def test_filters_by_severity_and_text(self):
        self.open_checks()
        page = self.validate()
        page.severity_combo.setCurrentIndex(1)   # solo errores
        self.assertEqual([item.code for item in page.model.problems()], ["tag_not_registered"])
        page.severity_combo.setCurrentIndex(0)
        page.filter_edit.setText("cb_types")
        page._apply_filter()
        self.assertEqual([item.code for item in page.model.problems()], ["mod_shadow_identical"])
        self.assertIn(tr("checks.shown", shown="1"), page.summary.text())

    def test_the_files_validate_button_uses_the_new_validator(self):
        window = self.open_checks()
        files = window.show_page("project")
        self.assertTrue(files.validate_button.isEnabled())
        files.validate_button.click()
        self.assertTrue(_qt.wait_until(lambda: window.session.validation_state() == "ready", 5000))
        self.assertEqual(self.engines["validation"].validations, 1)
        self.assertEqual(window.current_page_key(), "project:validation")
        self.assertIsNone(files.validation_report(), "la validación de sintaxis de la iteración 1 no corre")

    def test_double_click_opens_the_file_at_its_line(self):
        window = self.open_checks()
        page = self.validate()
        self.select(page, "tag_not_registered")
        page.view.activated.emit(page.view.currentIndex())
        files = window.page("project")
        self.assertEqual(window.current_page_key(), "project")
        viewer = files.clausewitz_viewer
        target = self.game.mod(SIL_REL)
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                       and viewer.current_load().path == target, 5000), "no se abrió el archivo")
        self.assertTrue(_qt.wait_until(lambda: viewer.code.current_line() == 1, 3000))

    def test_the_page_follows_the_language(self):
        self.open_checks()
        page = self.validate()
        set_language("en")
        self.assertEqual(page.model.index(0, 1).data(), "Country SIL has a history but is not in common/countries.txt.")
        self.assertEqual(page.model.headerData(2, Qt.Orientation.Horizontal), "Entity")
        self.assertEqual(page.fix_button.text(), "Fix")
        self.assertEqual(page.inherited_check.text(), "Show inherited from the base game (3)")


class FixTests(ValidationCase):
    def test_fix_shows_the_plan_and_applies_it_on_accept_then_revalidates(self):
        window = self.open_checks()
        page = self.validate()
        item = self.select(page, "tag_not_registered")
        seen = []

        def review(dialog: FixPlanDialog):
            changes = [(dialog.tree.topLevelItem(i).text(0), dialog.tree.topLevelItem(i).text(1))
                       for i in range(dialog.tree.topLevelItemCount())]
            seen.append((dialog.title.text(), changes, dialog.diff.toPlainText(), dialog.apply_button.isEnabled(),
                         dialog.confirm.isVisible()))
            self.assertEqual(window.session.history(), [], "el plan no cambia nada")
            dialog.apply_button.click()

        self.dialogs.handlers[FixPlanDialog] = review
        self.assertEqual(page.fix_button.text(), tr("checks.fix"))
        page.fix_button.click()
        (title, changes, diff, enabled, confirm), = seen
        self.assertEqual(title, "Registrar SIL en countries.txt")
        self.assertEqual(changes, [("common/countries.txt", tr("pending.action.copy"))])
        self.assertIn('+SIL = "countries/SIL.txt"', diff.splitlines())
        self.assertTrue(enabled)
        self.assertFalse(confirm, "un arreglo seguro no pide confirmación explícita")
        self.assertEqual(self.engines["validation"].applied, [("register_tag", item)])
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2
                                       and window.session.validation_state() == "ready", 5000), "no revalidó")
        self.assertNotIn("tag_not_registered", [p.code for p in page.model.problems()], "revalidar quita el error")
        self.assertEqual(len(window.session.history()), 1)
        window.undo()
        self.assertEqual(window.session.dirty_count(), 0, "Ctrl+Z deshace el arreglo en un paso")

    def test_the_status_bar_says_when_the_validation_ends(self):
        """«Validando el mod en segundo plano…» no se queda tras terminar; tras un arreglo, el estado dice el
        arreglo (la revalidación no lo pisa)."""
        window = self.open_checks()
        self.validate()
        self.assertTrue(_qt.wait_until(lambda: window.status_label.text() != tr("checks.status_started"), 3000))
        self.assertRegex(window.status_label.text(),
                         r"^Validación terminada en [\d,]+ s — errores: 1 · avisos: 0 · notas: 1$")
        page = self.page()
        self.select(page, "tag_not_registered")
        self.dialogs.handlers[FixPlanDialog] = lambda dialog: dialog.apply_button.click()
        page.fix_button.click()
        applied = window.status_label.text()
        self.assertTrue(applied.startswith("Arreglo aplicado"), applied)
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2
                                       and window.session.validation_state() == "ready", 5000))
        _qt.process_events(30)
        self.assertEqual(window.status_label.text(), applied)

    def test_a_cancelled_fix_changes_nothing(self):
        window = self.open_checks()
        page = self.validate()
        self.select(page, "tag_not_registered")
        self.dialogs.handlers[FixPlanDialog] = lambda dialog: dialog.cancel_button.click()
        page.fix_button.click()
        self.assertEqual(self.dialogs.types(), [FixPlanDialog])
        self.assertEqual(window.session.dirty_count(), 0)
        self.assertEqual(window.session.history(), [])
        self.assertEqual(window.status_label.text(), tr("checks.status_fix_cancelled"))

    def test_an_unsafe_fix_needs_explicit_confirmation(self):
        window = self.open_checks()
        page = self.validate()
        self.select(page, "mod_shadow_identical")
        states = []

        def confirm(dialog: FixPlanDialog):
            states.append((dialog.apply_button.isEnabled(), dialog.warning.isVisibleTo(dialog),
                           dialog.diff.toPlainText()))
            dialog.confirm.setChecked(True)
            states.append(dialog.apply_button.isEnabled())
            dialog.apply_button.click()

        self.dialogs.handlers[FixPlanDialog] = confirm
        page.fix_button.click()
        (enabled, warning, diff), enabled_after = states
        self.assertFalse(enabled, "hasta confirmar, no se puede aplicar")
        self.assertTrue(warning)
        self.assertEqual(diff, tr("fixplan.trash_note", file="common/cb_types.txt"))
        self.assertTrue(enabled_after)
        (write,) = window.session.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("common/cb_types.txt", WriteAction.TRASH))

    def test_the_dropdown_offers_the_other_fixes(self):
        self.open_checks()
        page = self.validate()
        both = FakeProblem("tag_not_registered", Severity.ERROR, VPath.of(SIL_REL), 1, None, ("tag", "SIL"), (),
                           MappingProxyType({"tag": "SIL", "key": "SIL"}), False, ("register_tag", "add_loc_key"))
        page.fix_button.set_problem(both)
        page.fix_button._fill_menu()
        labels = [action.text() for action in page.fix_button.menu_.actions()]
        self.assertEqual(labels, ["Registrar SIL en countries.txt", "Añadir la clave SIL"])
        self.assertIn("Registrar SIL en countries.txt", page.fix_button.toolTip())
        page.fix_button.set_problem(None)
        self.assertFalse(page.fix_button.isEnabled())


class ExplainerTests(ValidationCase):
    def test_why_opens_the_explainer_with_layers_lines_verdicts_outcome_and_fixes(self):
        window = self.open_checks()
        page = self.validate()
        item = self.select(page, "tag_not_registered")
        page.why_button.click()
        self.assertTrue(page.explainer.isVisible())
        self.assertTrue(_qt.wait_until(lambda: not page.explainer.loading and not window.is_busy(), 3000),
                        "la explicación no llegó")
        self.assertEqual(self.engines["validation"].explained, [item])
        self.assertEqual(page.explainer.title.text(), f"Por qué {SIL_REL} da este problema")
        self.assertEqual(page.explainer.step_texts(), [
            ("Mod", f"{SIL_REL}:1", "gana", "capital = 1"),
            ("Juego base", "common/countries.txt", "falta", tr("checks.explain_no_line")),
        ])
        self.assertIn("SIL no existirá", page.explainer.outcome.text())
        self.assertEqual([b.text() for b in page.explainer.fix_buttons], ["Registrar SIL en countries.txt"])
        self.dialogs.handlers[FixPlanDialog] = lambda dialog: dialog.apply_button.click()
        page.explainer.fix_buttons[0].click()
        self.assertEqual(self.engines["validation"].applied[0][0], "register_tag")
        self.assertTrue(_qt.wait_until(lambda: not page.explainer.isVisible(), 3000), "arreglado, se cierra")
        set_language("en")
        self.assertEqual(window.problems_button.text(), "Problems")

    def test_with_the_explainer_open_at_1100_px_the_message_keeps_its_width(self):
        window = self.open_checks()
        window.resize(1100, 700)
        page = self.validate()
        _qt.process_events(30)
        view, message = page.view, COLUMNS.index(COL_MESSAGE)
        self.assertEqual(view.folded_columns(), [], "sin el explicador caben todas las columnas")
        self.select(page, "tag_not_registered")
        page.why_button.click()
        _qt.process_events(30)
        self.assertGreaterEqual(view.columnWidth(message), MESSAGE_MIN_WIDTH)
        self.assertIn(COL_LINE, view.folded_columns(), "se pliega primero la línea")
        self.assertNotIn(COL_ENTITY, view.folded_columns(), "y solo lo que hace falta")
        tooltip = page.model.index(view.currentIndex().row(), message).data(Qt.ItemDataRole.ToolTipRole)
        self.assertIn(SIL_REL, tooltip, "lo plegado sigue en la ayuda emergente")
        page.explainer.close_button.click()
        _qt.process_events(30)
        self.assertFalse(page.explainer.isVisible())
        self.assertEqual(view.folded_columns(), [])

    def test_the_problems_dock_counts_and_navigates(self):
        window = self.open_checks()
        self.validate()
        window.problems_button.click()
        _qt.process_events(20)
        dock = window.problems_dock
        self.assertTrue(dock.isVisible())
        self.assertEqual(dock.summary.text(), tr("checks.dock_counts", errors="1", warnings="0", infos="1"))
        self.assertEqual(dock.model.rowCount(), 2)
        self.assertEqual(dock.model.index(0, 2).data(), f"{SIL_REL}:1")
        dock.inherited_check.setChecked(True)
        self.assertEqual(dock.model.rowCount(), 5)
        dock.inherited_check.setChecked(False)
        dock.view.setCurrentIndex(dock.model.index(0, 0))
        window.show_page("project:home")
        dock.why_button.click()
        page = self.page()
        self.assertIs(window.current_page(), page)
        self.assertTrue(page.explainer.isVisible())
        self.assertEqual(page.current_problem().code, "tag_not_registered")
        dock.view.activated.emit(dock.model.index(0, 0))
        self.assertEqual(window.current_page_key(), "project")


class StateTests(ValidationCase):
    def test_a_failed_validation_says_why(self):
        self.open_checks(engines={"validation": {"error": RuntimeError("se rompió la regla")}})
        page = self.page()
        self.window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.window.session.validation_state() == "failed", 5000))
        self.assertIs(page.stack.currentWidget(), page.empty)
        self.assertEqual(page.empty.title.text(), tr("checks.failed_title"))
        self.assertIn("se rompió la regla", page.empty.text.text())
        self.assertEqual(self.window.problems_dock.summary.text(), tr("checks.dock_failed"))

    def test_validation_waits_for_the_index(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.open_checks(engines={"index": {"gate": gate}}, wait_texts=False)
        session = self.window.session
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "busy", 3000))
        page = self.page()
        self.assertTrue(self.window.validate_mod())
        self.assertEqual(session.validation_state(), "waiting")
        self.assertIs(page.stack.currentWidget(), page.running)
        self.assertEqual(page.running_title.text(), tr("checks.waiting_index"))
        gate.set()
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready", 5000))
        self.assertEqual(self.engines["validation"].validations, 1)

    def test_without_a_baseline_nothing_is_marked_inherited(self):
        self.open_checks(engines={"baseline": {"error": RuntimeError("sin juego base")}})
        page = self.validate()
        self.assertEqual(page.model.inherited_count(), 0)
        self.assertEqual(page.model.rowCount(), 5, "sin línea base, los de vanilla cuentan como del mod")
        self.assertIn(tr("checks.no_baseline_reason", error="RuntimeError: sin juego base"), page.summary.text())
        self.assertIn("sin juego base", self.window.session.baseline_error())

    def test_the_baseline_is_computed_once_per_session(self):
        self.open_checks()
        self.validate()
        self.validate()
        self.assertEqual(self.engines["baseline"].computed, 1)
        self.assertEqual(self.engines["validation"].validations, 2)

    def test_cancelling_a_validation(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.open_checks(engines={"validation": {"gate": gate}})
        page = self.page()
        self.window.validate_mod()
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].started.is_set(), 3000))
        self.assertIs(page.stack.currentWidget(), page.running)
        page.cancel_button.click()
        self.assertEqual(self.window.session.validation_state(), "idle")
        self.assertIs(page.stack.currentWidget(), page.empty)
        gate.set()
        _qt.process_events(50)
        self.assertIsNone(self.window.session.report, "lo que llegue de la validación cancelada se descarta")

    def test_without_a_project(self):
        window = self.make_window(session=Session())
        page = window.show_page("project:validation")
        self.assertFalse(page.validate_button.isEnabled())
        self.assertEqual(page.empty.title.text(), tr("checks.empty_no_project_title"))
        self.assertFalse(window.validate_mod())


class RealCoreTests(ValidationCase):
    def test_the_real_validator_runs_on_the_minigame(self):
        self.open_checks(engines={"ready": {}})
        session = self.window.session
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready", 15000))
        page = self.validate()
        self.assertIsNotNone(session.report)
        self.assertTrue(all(p.message("es") for p in session.report.problems))
        self.assertIs(page.stack.currentWidget(), page.results)


class FakeCatalogTests(unittest.TestCase):
    def test_every_fake_code_has_its_severity_and_fixes(self):
        self.assertEqual(set(SEVERITIES), set(FIXES_OF))
        sil = problem("tag_not_registered", SIL_REL, 1, tag="SIL")
        self.assertEqual(sil.fixes, ("register_tag",))
        self.assertEqual(sil.message("en"), "Country SIL has a history but is not in common/countries.txt.")


class ScreenshotToolTests(unittest.TestCase):
    """``tools/screenshot.py`` captura Validación con el explicador, Textos y Ctrl+K (``--demo-index``)."""

    def test_validation_texts_and_palette_with_the_demo_index(self):
        import json
        import os
        import subprocess
        import tempfile

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shots"
            report = out / "report.json"
            result = subprocess.run(
                [sys.executable, str(root / "tools" / "screenshot.py"), "--out", str(out), "--lang", "en",
                 "--size", "1100x700", "--mod", str(root / "tests" / "fixtures" / "shago_mod_min" / "VSM"),
                 "--demo-game", "--no-game-art", "--demo-index", "--explain", "0", "--texts-filter", "studio",
                 "--palette", "AGC", "--page", "localisation:all", "--page", "project:validation",
                 "--report", str(report)],
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in out.glob("*.png")),
                             ["en_1_project_validation_palette.png", "en_7_localisation_all_palette.png"])
            state = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(state["index"], "ready")
        checks = state["checks"]
        self.assertEqual(checks["state"], "ready")
        self.assertGreater(checks["shown"], 0)
        self.assertTrue(checks["explained"].startswith("Why "), checks["explained"])
        self.assertEqual(state["texts"]["filter"], "studio")
        self.assertGreater(state["texts"]["rows"], state["texts"]["visible"])
        self.assertEqual(state["palette"]["text"], "AGC")
        self.assertTrue(any("AGC" in line for line in state["palette"]["results"]))


if __name__ == "__main__":
    unittest.main()
