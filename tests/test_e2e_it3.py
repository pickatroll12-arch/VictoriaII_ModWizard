"""Iteración 3 de extremo a extremo: la ventana, la ``Session`` y el ``Project`` reales, con el núcleo real.

Sin falsos: el índice (``core.index``), la validación con su línea base (``core.validate``) y la localización
(``core.locsync``) de verdad, sobre el minijuego y, con ``VIC2_CORPUS``, sobre una copia de VSM (nunca el real).
Comprueba que encajan las piezas de los dos agentes:

- un arreglo se aplica desde la interfaz (plan, confirmación), se revalida solo y Ctrl+Z lo deshace;
- los cambios sin guardar de Textos llegan al índice y a la validación (no hace falta guardar);
- el arreglo que borra pide confirmación explícita, guarda en la papelera y se deshace también después;
- Ctrl+K abre un símbolo real en su línea;
- con el corpus, los criterios 3, 5 y 6 recorridos con la ventana.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from _minigame import GAME_FILES  # noqa: E402
from test_ui_validation import MOD, ValidationCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.project import WriteAction  # noqa: E402
from vic2studio.core.project.diffing import changed_lines  # noqa: E402
from vic2studio.ui.dialogs.add_key import AddKeyDialog  # noqa: E402
from vic2studio.ui.dialogs.fix_plan import FixPlanDialog  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402

REAL = {"ready": {}}          # Session(): los motores reales del núcleo
# La historia de SIL y su archivo de país, como en VSM: sin él, «Registrar SIL» se niega (no_country_file).
SIL_MOD = {**MOD, "common/countries/Silesia.txt": GAME_FILES["common/countries/Aland.txt"]}
INDEX_MS = 20000
VSM_MS = 120000


def added_lines(diff: str) -> list[str]:
    return [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]


class RealCoreWindowCase(ValidationCase):
    def open_real(self, **options):
        options.setdefault("mod_files", SIL_MOD)
        window = self.open_checks(engines=REAL, **options)
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready" and not window.is_busy(),
                                       INDEX_MS), f"el índice no llegó: {session.index_error()}")
        return window

    def codes(self, page) -> list[str]:
        return [p.code for p in page.model.problems()]

    def wait_validated(self, timeout: int = INDEX_MS) -> None:
        session = self.window.session
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready" and not self.window.is_busy(),
                                       timeout), f"la validación no terminó: {session.validation_error()}")

    def select_where(self, page, code: str, **args):
        """Como ``select``, pero el primer problema de ``code`` con esos argumentos."""
        for row, item in enumerate(page.model.problems()):
            if item.code == code and all(item.args.get(k) == v for k, v in args.items()):
                page.view.setCurrentIndex(page.model.index(row, 0))
                return item
        self.fail(f"no está el problema {code} {args}")

    def apply_from_dialog(self, page, code: str, *, confirm: bool = False, **args) -> str:
        """[Arreglar] del problema ``code`` (y ``args``) como el usuario: revisa el plan y acepta. Devuelve el diff
        del plan."""
        self.select_where(page, code, **args)
        seen = []

        def review(dialog: FixPlanDialog):
            seen.append(dialog.diff.toPlainText())
            self.assertEqual(self.window.session.history(), [], "el plan no cambia nada")
            if confirm:
                self.assertFalse(dialog.apply_button.isEnabled(), "hasta confirmar, no se puede aplicar")
                dialog.confirm.setChecked(True)
            dialog.apply_button.click()

        self.dialogs.handlers[FixPlanDialog] = review
        page.fix_button.click()
        self.assertEqual(len(seen), 1, "el arreglo no enseñó su plan")
        return seen[0]


class MinigameEndToEndTests(RealCoreWindowCase):
    def test_register_tag_from_the_window_revalidates_and_ctrl_z_undoes_it(self):
        window = self.open_real()
        session = window.session
        page = self.validate()
        self.assertIn("tag_not_registered", self.codes(page))
        self.assertTrue(all(not p.inherited for p in page.model.problems()), "los heredados, ocultos")
        self.assertGreater(len(session.problems(inherited=True)), len(session.problems()), "hay heredados")
        diff = self.apply_from_dialog(page, "tag_not_registered")
        self.assertEqual(added_lines(diff), ['+SIL = "countries/Silesia.txt"'], "el nombre, del archivo de historia")
        self.wait_validated()
        self.assertNotIn("tag_not_registered", self.codes(page), "revalidar quita el error, sin guardar")
        (write,) = session.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("common/countries.txt", WriteAction.COPY_FROM_GAME))
        game = self.game.game("common/countries.txt").read_bytes()
        self.assertEqual(changed_lines(game, write.data), (1, 0), "una línea más que la del juego")
        self.assertEqual(len(session.history()), 1)
        window.undo()
        self.assertEqual(session.dirty_count(), 0, "Ctrl+Z deshace el arreglo en un paso")
        page = self.validate()
        self.assertIn("tag_not_registered", self.codes(page))
        self.assertFalse(self.game.mod("common/countries.txt").exists(), "nada se guardó")

    def test_a_plan_that_went_stale_is_not_applied_and_says_why_in_the_ui_language(self):
        """Revisión it3: si el archivo cambia entre enseñar el plan y aceptarlo, no se aplica otra cosa."""
        from vic2studio.core.project.codecs import codec_for
        from vic2studio.i18n import set_language

        window = self.open_real()
        session = window.session
        page = self.validate()
        self.addCleanup(set_language, "es")
        set_language("en")
        self.select(page, "tag_not_registered")

        def edit_then_accept(dialog: FixPlanDialog):
            with session.edit("pending.undo_revert", name="common/countries.txt"):
                handle = session.project.ws.open("common/countries.txt")
                data = codec_for(handle.kind).snapshot(handle.model)
                session.project.ws.replace_text(handle, data.replace(b"countries/Corland.txt",
                                                                     b"countries/Corland2.txt"))
            dialog.apply_button.click()

        self.dialogs.handlers[FixPlanDialog] = edit_then_accept
        page.fix_button.click()
        self.assertEqual([label for label, _ in session.history()], ["pending.undo_revert"], "no se aplicó")
        self.assertIn("The file changed since the plan was prepared", window.status_label.text())

    def test_unsaved_texts_reach_the_index_and_the_validator(self):
        window = self.open_real()
        page = self.validate()
        self.assertIn("loc_key_missing", self.codes(page))
        missing = {p.args["key"] for p in page.model.problems() if p.code == "loc_key_missing"}
        self.assertIn("tst_reform_title", missing)
        texts = self.texts()

        def fill(dialog: AddKeyDialog):
            dialog.key_edit.setText("tst_reform_title")
            dialog.text_edits["en"].setText("Reform")
            dialog.text_edits["es"].setText("Reforma")
            dialog.ok_button.click()

        self.dialogs.handlers[AddKeyDialog] = fill
        texts.add_button.click()
        self.assertTrue(_qt.wait_until(lambda: not window.is_busy(), INDEX_MS))
        page = self.validate()
        missing = {p.args["key"] for p in page.model.problems() if p.code == "loc_key_missing"}
        self.assertNotIn("tst_reform_title", missing, "la clave sin guardar ya cuenta")
        self.assertIn("tst_reform_desc", missing)
        found = window.session.search("tst_reform_title")
        self.assertIn(("loc_key", "tst_reform_title"), [(s.kind, s.name) for s in found], "y el índice la ve")
        window.undo()
        page = self.validate()
        missing = {p.args["key"] for p in page.model.problems() if p.code == "loc_key_missing"}
        self.assertIn("tst_reform_title", missing, "Ctrl+Z la quita también para la validación")

    def test_trashing_an_identical_copy_needs_confirmation_and_undoes_after_saving(self):
        window = self.open_real()
        session = window.session
        page = self.validate()
        copy = self.game.mod("common/cb_types.txt")
        original = copy.read_bytes()
        self.apply_from_dialog(page, "mod_shadow_identical", confirm=True)
        (write,) = session.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("common/cb_types.txt", WriteAction.TRASH))
        self.wait_validated()
        self.assertNotIn("mod_shadow_identical", self.codes(page))
        report = session.save()
        self.assertTrue(report.ok, report)
        self.assertFalse(copy.exists(), "a la papelera")
        self.assertEqual(self.game.mod(f".vic2studio/trash/{report.result.txid}/common/cb_types.txt").read_bytes(),
                         original)
        window.undo()
        (write,) = session.changeset().writes
        self.assertEqual(write.action, WriteAction.CREATE, "deshacer tras guardar la devuelve al mod al guardar")
        self.assertTrue(session.save().ok)
        self.assertEqual(copy.read_bytes(), original)

    def test_ctrl_k_opens_a_real_symbol_at_its_line(self):
        window = self.open_real()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        QTest.keyClick(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(20)
        palette = window.palette
        self.assertTrue(palette.isVisible())
        QTest.keyClicks(palette.edit, "tst_reform")
        palette.search()
        row = next(i for i, r in enumerate(palette.results())
                   if (r.symbol.kind, r.symbol.name) == ("decision", "tst_reform"))
        self.assertEqual(palette.results()[row].symbol.line, 2)
        palette.list.setCurrentRow(row)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return)
        viewer = window.page("project").clausewitz_viewer
        target = self.game.mod("decisions/tst_decisions.txt")
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                       and viewer.current_load().path == target, 5000))
        self.assertTrue(_qt.wait_until(lambda: viewer.code.current_line() == 2, 3000), "en su línea")

    def test_ctrl_k_shows_a_party_by_its_name_not_by_its_index_id(self):
        """Un partido es «archivo:partido» en el índice: la paleta enseña y busca por el partido."""
        window = self.open_real()
        palette = window.palette
        palette.open("AAA_cons")
        palette.search()
        rows = [(r.symbol.kind, r.symbol.name) for r in palette.results()]
        self.assertIn(("party", "countries/aland.txt:AAA_conservative"), rows)
        row = rows.index(("party", "countries/aland.txt:AAA_conservative"))
        self.assertNotIn("countries/aland.txt", palette.result_texts()[row].split("  ·  ")[1])
        palette.open("countries/aland")
        palette.search()
        self.assertNotIn("party", [r.symbol.kind for r in palette.results()], "la ruta no encuentra partidos")


def full_vsm() -> Path | None:
    mod = user_mod()
    return mod if mod is not None and (mod / "localisation" / "text.csv").is_file() else None


@unittest.skipUnless(vanilla_root() and full_vsm(), "requiere el corpus completo (VIC2_CORPUS)")
class VsmEndToEndTests(RealCoreWindowCase):
    """Criterios 3, 5 y 6 con la ventana sobre una copia de VSM (el real no se abre nunca)."""

    def open_vsm(self):
        window = self.make_window(session=Session())
        window.exec_dialog = self.dialogs
        self.window = window
        files = window.page("project")
        files.set_game_path(vanilla_root())
        self.mod = copy_user_mod(self)
        files.set_mod_path(self.mod)
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready" and session.texts_ready()
                                       and not window.is_busy(), VSM_MS), f"VSM no abrió: {session.index_error()}")
        return window

    def test_criteria_3_and_5_through_the_window(self):
        window = self.open_vsm()
        session = window.session
        self.assertTrue(window.validate_mod())
        self.wait_validated(VSM_MS)
        page = self.page()
        errors = sorted((p.code, str(p.rel)) for p in page.model.problems() if p.severity is Severity.ERROR)
        self.assertEqual(errors, [
            ("nationalvalue_unknown", "history/countries/GEL - Geledi.txt"),
            ("nationalvalue_unknown", "history/countries/MAJ - Majeerteen.txt"),
            ("nationalvalue_unknown", "history/countries/SOM - Somalia.txt"),
            ("nationalvalue_unknown", "history/countries/WRL - Warsangali.txt"),
            ("tag_not_registered", "history/countries/SIL - Silesia.txt"),
            ("unclosed_block", "decisions/somaliland_shago.txt"),
            ("unclosed_block", "decisions/zulu_expancionshago.txt"),
        ], "criterio 3: los errores propios, sin heredados")
        diff = self.apply_from_dialog(page, "tag_not_registered", tag="SIL")
        self.assertEqual(added_lines(diff), ['+SIL = "countries/Silesia.txt"'])
        self.wait_validated(VSM_MS)
        codes = self.codes(page)
        self.assertNotIn("tag_not_registered", codes, "criterio 5: revalidar quita el error de SIL")
        self.assertIn("graphical_culture_unknown", codes, "y destapa los de los archivos de SIL")
        (write,) = session.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("common/countries.txt", WriteAction.MODIFY))
        self.assertEqual(changed_lines((self.mod / "common" / "countries.txt").read_bytes(), write.data), (1, 0))
        window.undo()
        self.assertEqual(session.dirty_count(), 0, "Ctrl+Z")

    def test_criterion_6_a_text_csv_key_is_edited_in_place(self):
        window = self.open_vsm()
        page = self.texts()
        self.edit_cell(page, "LEDGER_COUNTRY_NAME", "es", "Nación")   # hoy dice «País»
        (write,) = window.session.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("localisation/text.csv", WriteAction.MODIFY))
        before = (self.mod / "localisation" / "text.csv").read_bytes()
        self.assertEqual(changed_lines(before, write.data), (1, 1), "un diff de 1 línea")
        window.undo()
        self.assertEqual(window.session.dirty_count(), 0)


if __name__ == "__main__":
    unittest.main()
