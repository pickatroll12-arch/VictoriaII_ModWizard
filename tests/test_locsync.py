"""``LocSync`` (wizard §8, D6): dónde se escribe cada texto, con qué formato, en qué idiomas y siempre deshacible.

Contra el ``Project`` real sobre el minijuego (``_minigame``), y el criterio 6 de la iteración 3 también sobre el
corpus (vanilla + VSM, con su propio ``text.csv``) cuando está ``VIC2_CORPUS``.
"""

import dataclasses
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from _fake_index import FakeIndexEngine  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import CRLF, GAME_FILES, build_minigame  # noqa: E402

from vic2studio.core import locsync as locsync_module  # noqa: E402
from vic2studio.core.csvloc import InvalidFieldError  # noqa: E402
from vic2studio.core.csvloc.model import DuplicateKeyError, LocRow, RowKind  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.locsync import (  # noqa: E402
    LocSync,
    is_degraded_copy,
    is_localisation_rel,
    read_localisation,
)
from vic2studio.core.project import Project, WriteAction  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402

LABEL = "pending.undo_revert"
GAME_CSV = "localisation/minigame.csv"
# Cabecera y filas sin «x», como los CSV propios de VSM (H15, csvloc/__init__.py).
VSM_HEADER = "key;English;French;German;Polish;Spanish;Italian;Swedish;Czech;Hugarian;Dutch;Portuguese;Russian;Finish"
VSM_STYLE = CRLF.join([VSM_HEADER, "AAA;Aland;;;;;;;;;;;;", "AAA_ADJ;Alandish;;;;Alandés;;;;;;;;", ""])


# El minijuego puede traer más CSV del juego que minigame.csv (la iteración 3 le añade los nombres de países,
# provincias y eventos para el índice): las pruebas de textos los dejan vacíos, para que lo que cuentan solo
# dependa de minigame.csv y de los archivos que pone cada prueba.
OTHER_GAME_CSVS = tuple(rel for rel in GAME_FILES if is_localisation_rel(rel) and rel != GAME_CSV)


def only_minigame_csv(game_files=None) -> dict:
    """``game_files`` para ``build_minigame`` con los demás CSV del juego vacíos (ver ``OTHER_GAME_CSVS``)."""
    files: dict = dict.fromkeys(OTHER_GAME_CSVS, "")
    files.update(game_files or {})
    return files


class LocSyncCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def open(self, *, mod: bool = True, mod_files=None, game_files=None, mod_copies=(), copy_en_to=(),
             languages=("en", "es")):
        self.game = build_minigame(mod=mod, mod_files=mod_files, game_files=only_minigame_csv(game_files),
                                   mod_copies=mod_copies)
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.loc = LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix,
                           languages=languages, copy_en_to=copy_en_to)
        self.game_hashes = {rel: hashlib.sha256(data).hexdigest() for rel, (_, _, data) in self.game.game_tree().items()}
        return self.loc

    def edit(self, fn):
        with self.project.edit(LABEL, name="x"):
            return fn()

    def writes(self) -> dict[str, tuple[WriteAction, str, bytes | None]]:
        return {str(w.rel): (w.action, w.diff, w.data) for w in self.project.ws.changeset().writes}

    def assert_game_untouched(self) -> None:
        now = {rel: hashlib.sha256(data).hexdigest() for rel, (_, _, data) in self.game.game_tree().items()}
        self.assertEqual(now, self.game_hashes, "los archivos del juego base no cambian nunca")


class PolicyTests(LocSyncCase):
    def test_criterion6_a_game_key_goes_to_the_overrides_file_and_the_game_csv_is_not_copied(self):
        """Criterio 6, minijuego con mod vacío: 00_<P>_overrides.csv con esa fila; el CSV del juego no se copia."""
        loc = self.open(mod=False)
        prefix = self.project.settings.prefix
        rel = self.edit(lambda: loc.set_text("free_people", "es", "Liberar al pueblo"))
        self.assertEqual(rel, VPath.of(f"localisation/00_{prefix}_overrides.csv"))
        writes = self.writes()
        self.assertEqual(list(writes), [str(rel)], "solo el archivo de sobrescrituras; nunca la copia del CSV")
        action, diff, data = writes[str(rel)]
        self.assertIs(action, WriteAction.CREATE)
        # La fila copia los idiomas del juego y solo cambia el español; cp1252 y CRLF, con su «x».
        self.assertEqual(data, "free_people;Free the people;Libérer;Befreien;;Liberar al pueblo;;;;;;;;;x\r\n"
                         .encode("cp1252"))
        self.assertEqual(loc.text("free_people", "es"), "Liberar al pueblo")
        self.assertEqual(loc.text("free_people", "fr"), "Libérer", "las otras traducciones siguen")
        self.assertEqual(loc.where("free_people"), (rel, 1))
        report = self.project.save()
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(sorted(self.game.tree()), [str(rel)], "en el mod solo aparece ese archivo")
        self.assert_game_untouched()

    def test_a_key_whose_winner_is_in_the_mod_is_edited_in_place_with_a_one_line_diff(self):
        loc = self.open()
        rel = self.edit(lambda: loc.set_text("tst_reform", "es", "Reformar"))
        self.assertEqual(rel, VPath.of("localisation/00_TST_decisions.csv"))
        action, diff, data = self.writes()[str(rel)]
        self.assertIs(action, WriteAction.MODIFY)
        self.assertEqual([line for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")],
                         ["-tst_reform;Reform;Réforme;Reform;;Reforma;;;;;;;;x",
                          "+tst_reform;Reform;Réforme;Reform;;Reformar;;;;;;;;x"])
        self.assertEqual(data, "tst_reform;Reform;Réforme;Reform;;Reformar;;;;;;;;x\r\n".encode("cp1252"),
                         "conserva la «x» donde estaba (keep_layout)")

    def test_a_mod_copy_of_a_game_csv_is_edited_in_place(self):
        """Como el text.csv de VSM: el CSV del mod con el nombre del del juego lo sustituye y se edita en su sitio."""
        loc = self.open(mod=False, mod_copies=[GAME_CSV])
        rel = self.edit(lambda: loc.set_text("humble_rival", "es", "Humillar al rival"))
        self.assertEqual(rel, VPath.of(GAME_CSV))
        writes = self.writes()
        self.assertEqual(list(writes), [GAME_CSV])
        action, diff, _ = writes[GAME_CSV]
        self.assertIs(action, WriteAction.MODIFY)
        self.assertEqual(sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")),
                         1)

    def test_a_new_key_goes_to_its_area_file_in_the_vanilla_format_when_the_mod_has_no_csv(self):
        loc = self.open(mod=False)
        prefix = self.project.settings.prefix
        created = self.edit(lambda: loc.ensure({"NEW_KEY": {"en": "New", "es": "Nuevo"}}, area="events"))
        self.assertEqual(created, ["NEW_KEY"])
        rel = f"localisation/00_{prefix}_events.csv"
        self.assertEqual(self.writes()[rel][2], b"NEW_KEY;New;;;;Nuevo;;;;;;;;;x\r\n")
        self.assertEqual(loc.target_file("events"), VPath.of(rel))

    def test_set_text_of_a_new_key_uses_the_area(self):
        loc = self.open(mod=False)
        rel = self.edit(lambda: loc.set_text("BRAND_NEW", "en", "Brand new", area="countries"))
        self.assertEqual(rel.name, f"00_{self.project.settings.prefix}_countries.csv")

    def test_a_new_file_imitates_the_mod_header_and_marker_convention(self):
        prefix = "TESTMOD"
        loc = self.open(mod=False, mod_files={f"localisation/00_{prefix}_countries.csv": VSM_STYLE})
        self.edit(lambda: loc.ensure({"AAA_desc": {"en": "Land of Aland"}}, area="events"))
        data = self.writes()[f"localisation/00_{prefix}_events.csv"][2]
        self.assertEqual(data, (VSM_HEADER + "\r\nAAA_desc;Land of Aland;;;;;;;;;;;;\r\n").encode("cp1252"),
                         "misma cabecera, copiada tal cual, y filas sin «x»")

    def test_a_new_file_imitates_the_users_own_csvs_not_the_copies_of_game_csvs(self):
        """Revisión it3: en VSM sus 22 copias de vanilla (con «x») tapaban a sus 00_VSM_* (sin ella)."""
        prefix = "TESTMOD"
        marked = CRLF.join(f"k{n};Text {n};;;;Texto {n};;;;;;;;;x" for n in range(5)) + CRLF   # 13 idiomas y «x»
        loc = self.open(mod=False, mod_files={f"localisation/00_{prefix}_countries.csv": VSM_STYLE},
                        game_files={"localisation/minigame.csv": marked}, mod_copies=["localisation/minigame.csv"])
        state = loc._state()
        copy = next(f for f in loc._mod_files() if state.info[id(f)].rel.name == "minigame.csv")
        self.assertTrue(all(r.has_end_marker for r in copy.data_rows()), "premisa: la copia del juego lleva «x»")
        self.edit(lambda: loc.ensure({"AAA_desc": {"en": "Land of Aland"}}, area="events"))
        data = self.writes()[f"localisation/00_{prefix}_events.csv"][2]
        self.assertEqual(data, (VSM_HEADER + "\r\nAAA_desc;Land of Aland;;;;;;;;;;;;\r\n").encode("cp1252"))

    def test_a_utf8_mod_csv_also_refuses_characters_the_game_cannot_show(self):
        """Revisión it3: el juego lee en cp1252 cualquier CSV; en uno guardado en UTF-8 se aceptaba «Łódź»."""
        rel = "localisation/00_utf8.csv"
        area = "localisation/00_TESTMOD_events.csv"                 # el archivo del área ya existe, en UTF-8
        loc = self.open(mod=False, mod_files={rel: "KUTF;Café;;;;Café;;;;;;;;x\r\n".encode("utf-8"),
                                              area: "KEV;Événement;;;;Evento;;;;;;;;x\r\n".encode("utf-8")})
        with self.assertRaises(UnencodableTextError):
            self.edit(lambda: loc.set_text("KUTF", "es", "Łódź"))
        with self.assertRaises(UnencodableTextError):
            self.edit(lambda: loc.ensure({"KNEW": {"en": "Łódź"}}, area="events"))
        self.assertEqual(self.project.ws.dirty(), [])
        self.edit(lambda: loc.set_text("KUTF", "es", "Niño"))
        self.assertEqual(loc.text("KUTF", "es"), "Niño")

    def test_a_row_added_to_an_existing_file_follows_that_file_and_edits_keep_its_layout(self):
        prefix = "TESTMOD"
        rel = f"localisation/00_{prefix}_countries.csv"
        loc = self.open(mod=False, mod_files={rel: VSM_STYLE})
        self.assertEqual(loc.target_file("countries"), VPath.of(rel), "reutiliza el archivo que sigue el patrón")
        self.edit(lambda: loc.ensure({"BBB": {"en": "Borland", "es": "Borlandia"}}, area="countries"))
        self.edit(lambda: loc.set_text("AAA", "es", "Alandia"))
        data = self.writes()[rel][2].decode("cp1252")
        self.assertEqual(data.split("\r\n"), [VSM_HEADER, "AAA;Aland;;;;Alandia;;;;;;;;", "AAA_ADJ;Alandish;;;;Alandés;;;;;;;;",
                                              "BBB;Borland;;;;Borlandia;;;;;;;;", ""])

    def test_target_file_reuses_a_mod_file_whatever_its_case(self):
        loc = self.open(mod=False, mod_files={"localisation/00_testmod_Decisions.CSV": "K;Text;;;;;;;;;;;;x\r\n"})
        self.assertEqual(loc.target_file("decisions"), VPath.of("localisation/00_testmod_Decisions.CSV"))
        self.assertEqual(loc.target_file("units"), VPath.of("localisation/00_TESTMOD_units.csv"))

    def test_the_overrides_file_is_renamed_to_load_first_when_a_game_file_would_win(self):
        loc = self.open(mod=False, game_files={"localisation/00_AAA.csv": "free_people;Early;;;;Temprano;;;;;;;;x\r\n"})
        self.assertEqual(loc.text("free_people", "es"), "Temprano")
        rel = self.edit(lambda: loc.set_text("free_people", "es", "Liberar"))
        self.assertEqual(rel.name, "000_TESTMOD_overrides.csv", "carga antes que 00_AAA.csv")
        self.assertEqual(loc.text("free_people", "es"), "Liberar")

    def test_copy_en_to_fills_french_and_german_without_overwriting_real_translations(self):
        loc = self.open(mod=False, copy_en_to=("fr", "de"),
                        mod_files={"localisation/00_TESTMOD_misc.csv": "COPY;Old;Old;Alt;;Viejo;;;;;;;;x\r\n"})
        self.edit(lambda: loc.ensure({"NEW": {"en": "New"}}, area="misc"))
        self.assertEqual((loc.text("NEW", "fr"), loc.text("NEW", "de")), ("New", "New"))
        self.edit(lambda: loc.set_text("COPY", "en", "Fresh"))
        self.assertEqual(loc.text("COPY", "fr"), "Fresh", "el francés era la copia del inglés anterior")
        self.assertEqual(loc.text("COPY", "de"), "Alt", "el alemán es una traducción de verdad: no se pisa")
        self.edit(lambda: loc.set_text("free_people", "en", "Free them"))   # del juego: va a overrides
        self.assertEqual(loc.text("free_people", "fr"), "Libérer", "la traducción del juego se conserva")

    def test_texts_with_a_separator_or_a_newline_are_rejected_before_writing(self):
        loc = self.open()
        for bad in ("uno;dos", "uno\ndos", "uno\rdos"):
            with self.subTest(text=bad), self.assertRaises(InvalidFieldError):
                self.edit(lambda: loc.set_text("free_people", "es", bad))
        with self.assertRaises(InvalidFieldError):
            self.edit(lambda: loc.set_text("free_people", "xx", "hola"))
        with self.assertRaises(InvalidFieldError):
            self.edit(lambda: loc.ensure({" bad_key": {"en": "x"}}, area="misc"))
        self.assertEqual(self.project.ws.dirty(), [])
        self.assertEqual(self.project.ws.history(), [])

    def test_a_character_outside_cp1252_is_rejected_when_the_transaction_closes(self):
        loc = self.open()
        with self.assertRaises(UnencodableTextError):
            self.edit(lambda: loc.set_text("tst_reform", "es", "Łódź"))
        self.assertEqual(self.project.ws.dirty(), [], "la transacción se revierte entera")
        self.assertEqual(loc.text("tst_reform", "es"), "Reforma")

    def test_writing_outside_a_transaction_is_refused(self):
        loc = self.open()
        with self.assertRaises(RuntimeError):
            loc.set_text("tst_reform", "es", "x")
        with self.assertRaises(RuntimeError):
            loc.ensure({"K": {"en": "x"}}, area="misc")

    def test_several_edits_undo_in_one_step(self):
        loc = self.open()
        before = [(e.key, dict(e.texts), e.rel) for e in loc.entries()]

        def both():
            loc.set_text("free_people", "es", "Liberar al pueblo")
            loc.set_text("tst_reform", "es", "Reformar")
            loc.ensure({"NEW": {"en": "New"}}, area="misc")

        self.edit(both)
        self.assertEqual(len(self.project.ws.dirty()), 3)
        self.assertEqual(len(self.project.ws.history()), 1)
        self.project.ws.undo()
        self.assertEqual(self.project.ws.dirty(), [])
        self.assertEqual([(e.key, dict(e.texts), e.rel) for e in loc.entries()], before)
        self.project.ws.redo()
        self.assertEqual(loc.text("free_people", "es"), "Liberar al pueblo")

    def test_ensure_skips_existing_keys_and_validates_everything_first(self):
        loc = self.open()
        created = self.edit(lambda: loc.ensure({"free_people": {"en": "x"}, "K1": {"en": "One"}, "K2": {"es": "Dos"}},
                                               area="misc"))
        self.assertEqual(created, ["K1", "K2"])
        self.assertEqual(loc.text("free_people", "en"), "Free the people", "una clave que ya existe no se toca")
        with self.assertRaises(InvalidFieldError):
            self.edit(lambda: loc.ensure({"K3": {"en": "ok"}, "K4": {"en": "no;vale"}}, area="misc"))
        self.assertIsNone(loc.text("K3"), "todo o nada")

    def test_rename_and_delete_only_touch_mod_rows(self):
        loc = self.open()
        self.edit(lambda: loc.rename("tst_reform", "tst_reform2"))
        self.assertIsNone(loc.text("tst_reform"))
        self.assertEqual(loc.text("tst_reform2", "es"), "Reforma")
        self.edit(lambda: loc.delete("free_people"))   # del juego: no hay filas del mod que quitar
        self.assertEqual(loc.text("free_people", "en"), "Free the people")
        self.assertNotIn(GAME_CSV, self.writes())
        self.edit(lambda: loc.delete("tst_reform2"))
        self.assertIsNone(loc.text("tst_reform2"))
        self.edit(lambda: loc.ensure({"OTHER": {"en": "x"}, "DUP": {"en": "y"}}, area="misc"))
        with self.assertRaises(DuplicateKeyError):
            self.edit(lambda: loc.rename("OTHER", "DUP"))
        self.assertEqual(loc.text("OTHER", "en"), "x", "renombrar es todo o nada")
        self.assert_game_untouched()

    def test_missing_lists_the_languages_without_text(self):
        loc = self.open(mod_files={"localisation/00_TESTMOD_misc.csv": "ONLY_EN;Only;;;;;;;;;;;;x\r\n"})
        self.assertEqual(loc.missing(["ONLY_EN", "free_people", "nope"]), {"ONLY_EN": ["es"], "nope": ["en", "es"]})
        entry = loc.entry("ONLY_EN")
        self.assertEqual(loc.untranslated(entry), ["es"])

    def test_orphans_are_mod_keys_nothing_uses(self):
        loc = self.open(mod_files={"localisation/00_TESTMOD_countries.csv":
                                   "AAA;Aland;;;;;;;;;;;;x\r\nAAA_ADJ;Alandish;;;;;;;;;;;;x\r\nUNUSED;x;;;;;;;;;;;;x\r\n"})
        index = FakeIndexEngine().build(self.project.vfs.snapshot(), {})
        # AAA es un TAG, AAA_ADJ su adjetivo y tst_reform una decisión: solo UNUSED no lo usa nada.
        self.assertEqual(loc.orphans(index), ["UNUSED"])

    def test_reading_never_writes_in_the_mod(self):
        """I4: consultar la vista efectiva no escribe nada ni crea .vic2studio/."""
        loc = self.open(mod_copies=[GAME_CSV])
        before = self.game.tree()
        loc.entries()
        loc.localisation_db()
        loc.text("free_people")
        loc.where("free_people")
        loc.missing(["x"])
        loc.target_file("misc")
        read_localisation(loc.disk_entries(missing_only=False))
        self.assertEqual(self.game.tree(), before)
        self.assertFalse((self.game.mod_root / ".vic2studio").exists())


class EntryFlagTests(LocSyncCase):
    def test_flags_of_the_table_filters(self):
        prefix = "TESTMOD"
        degraded_game = "PRESTIGE;Prestige;Prestige;Prestige;;Prestigio;;;;;;;;x\r\nDIFF;Difficulté facile;x;;;;;;;;;;;x\r\n"
        degraded_mod = "PRESTIGE;Prestige;Prestige;Prestige;;Prestigio;;;;;;;;x\r\nDIFF;Difficult?facile;x;;;;;;;;;;;x\r\n"
        loc = self.open(mod=False, game_files={"localisation/text.csv": degraded_game},
                        mod_files={"localisation/text.csv": degraded_mod,
                                   f"localisation/00_{prefix}_misc.csv": "MINE;Mine;;;;Mío;;;;;;;;x\r\n"})
        entries = {e.key: e for e in loc.entries()}
        self.assertEqual(set(entries), {"MINE", "PRESTIGE", "DIFF", "conquer_land", "free_people", "humble_rival"})
        self.assertTrue(entries["MINE"].created_by_studio)
        self.assertFalse(entries["MINE"].overrides_game)
        self.assertTrue(entries["PRESTIGE"].overrides_game and not entries["PRESTIGE"].degraded)
        self.assertTrue(entries["DIFF"].overrides_game and entries["DIFF"].degraded)
        self.assertIs(entries["conquer_land"].layer, LayerKind.GAME)
        self.assertFalse(entries["conquer_land"].overrides_game)
        self.assertEqual(entries["MINE"].texts["es"], "Mío")
        self.assertEqual(entries["DIFF"].line, 2)

    def test_the_header_row_is_not_a_key(self):
        loc = self.open(mod=False, mod_files={"localisation/00_TESTMOD_countries.csv": VSM_STYLE})
        keys = [e.key for e in loc.entries()]
        self.assertNotIn("key", keys)
        self.assertIn("AAA_ADJ", keys)

    def test_entries_are_reused_until_something_changes(self):
        loc = self.open()
        first = loc.entries()
        self.assertIs(loc.entries(), first)
        self.edit(lambda: loc.set_text("tst_reform", "es", "Reformar"))
        self.assertIsNot(loc.entries(), first)
        self.assertEqual(loc.entry("tst_reform").texts["es"], "Reformar")


class DegradedCopyTests(unittest.TestCase):
    def test_question_marks_where_the_game_has_accented_letters(self):
        self.assertTrue(is_degraded_copy(["Capacit?"], ["Capacité"]))
        self.assertTrue(is_degraded_copy(["Efficacit?fiscale"], ["Efficacité fiscale"]), "también se comió el espacio")
        self.assertTrue(is_degraded_copy(["Difficult?Schwierigkeit"], ["Difficulté;Schwierigkeit"]),
                        "y a veces el «;» de la columna siguiente")
        self.assertTrue(is_degraded_copy(["a?b?c"], ["aébñc"]))

    def test_anything_else_is_not_degraded(self):
        self.assertFalse(is_degraded_copy(["Same"], ["Same"]))
        self.assertFalse(is_degraded_copy(["Other"], ["Otra"]))
        self.assertFalse(is_degraded_copy(["Why?"], ["Why?"]), "un «?» que también está en el juego")
        self.assertFalse(is_degraded_copy(["Capacit?"], ["Capacity"]), "una letra ASCII no se pierde así")
        self.assertFalse(is_degraded_copy(["Capacit? x"], ["Capacité"]))


class BackgroundReadTests(LocSyncCase):
    def test_after_adopting_a_background_read_queries_read_nothing_more(self):
        loc = self.open(mod_copies=[GAME_CSV])
        entries = loc.disk_entries()
        self.assertEqual({(str(e.rel), e.layer.kind) for e in entries if str(e.rel) not in OTHER_GAME_CSVS},
                         {(GAME_CSV, LayerKind.MOD), (GAME_CSV, LayerKind.GAME),
                          ("localisation/00_TST_decisions.csv", LayerKind.MOD)})
        loc.adopt(read_localisation(entries))
        self.assertEqual(loc.disk_entries(), [], "ya están todos leídos")
        with mock.patch.object(locsync_module, "read_localisation", side_effect=AssertionError("lee del disco")):
            self.assertTrue(loc.entries())

    def test_an_unreadable_csv_is_reported_and_skipped(self):
        loc = self.open()
        entry = next(e for e in loc.disk_entries() if e.layer.kind is LayerKind.MOD)
        readout = read_localisation([dataclasses.replace(entry, path=entry.path.with_name("gone.csv"))])
        self.assertEqual(readout.files, [])
        self.assertEqual(len(readout.errors), 1)

    def test_localisation_rels(self):
        self.assertTrue(is_localisation_rel("localisation/text.csv"))
        self.assertTrue(is_localisation_rel("Localisation/00_X.CSV"))
        self.assertFalse(is_localisation_rel("map/definition.csv"))
        self.assertFalse(is_localisation_rel("localisation/sub/a.csv"))
        self.assertFalse(is_localisation_rel("localisation/a.txt"))


class RowLayoutTests(unittest.TestCase):
    def test_keep_layout_changes_only_that_column(self):
        row = LocRow(RowKind.DATA, "K", ["en", "", "", "", "es", "", "", "", "", "", "", "", ""])
        row.set("es", "nuevo", keep_layout=True)
        self.assertEqual(row.to_line(), "K;en;;;;nuevo;;;;;;;;", "sin «x» si no la tenía")
        short = LocRow(RowKind.DATA, "K", ["en"])
        short.set("es", "es", keep_layout=True)
        self.assertEqual(short.to_line(), "K;en;;;;es")
        shifted = LocRow(RowKind.DATA, "K", ["en", "fr", "de", "", "es", "", "x"])
        shifted.set("en", "EN", keep_layout=True)
        self.assertEqual(shifted.to_line(), "K;EN;fr;de;;es;;x", "la «x» desplazada sigue donde estaba")
        shifted.set("pt", "pt", keep_layout=True)   # caería detrás de la «x»: se normaliza
        self.assertEqual(shifted.to_line(), "K;EN;fr;de;;es;;;;;;pt;;;x")
        default = LocRow(RowKind.DATA, "K", ["en"])
        default.set("es", "es")
        self.assertEqual(default.to_line(), "K;en;;;;es;;;;;;;;;x", "sin keep_layout, como siempre")


@unittest.skipUnless(vanilla_root() is not None and user_mod() is not None
                     and (user_mod() / "localisation" / "text.csv").is_file(),
                     "necesita VIC2_CORPUS con vanilla y el VSM completo (su text.csv)")
class CorpusCriterion6Tests(unittest.TestCase):
    """Criterio 6 en VSM, que tiene su propio text.csv: la fila se edita en esa copia con un diff de 1 línea."""

    def setUp(self):
        isolate_appdirs(self)
        self.project = Project.open(vanilla_root(), copy_user_mod(self, "localisation"))
        self.addCleanup(self.project.close, discard=True)
        settings = self.project.settings
        self.loc = LocSync(self.project.ws, self.project.vfs, prefix=settings.prefix, languages=settings.languages)
        self.loc.adopt(read_localisation(self.loc.disk_entries()))

    def test_a_key_of_the_vsm_text_csv_is_edited_in_that_copy_with_a_one_line_diff(self):
        entry = next(e for e in self.loc.entries() if e.rel.name == "text.csv" and not e.degraded)
        self.assertIs(entry.layer, LayerKind.MOD)
        with self.project.edit(LABEL, name="x"):
            rel = self.loc.set_text(entry.key, "es", "Texto del Studio")
        self.assertEqual(rel, VPath.of("localisation/text.csv"))
        (write,) = self.project.ws.changeset().writes
        self.assertEqual((str(write.rel), write.action), ("localisation/text.csv", WriteAction.MODIFY))
        changed = [line for line in write.diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]
        self.assertEqual(len(changed), 2, changed)
        self.assertTrue(changed[0].startswith(f"-{entry.key};") and changed[1].startswith(f"+{entry.key};"))
        self.assertIn(";Texto del Studio;", changed[1])

    def test_vsm_flags_and_its_own_csv_files(self):
        entries = self.loc.entries()
        degraded = sum(e.degraded for e in entries)
        # Medido sobre el corpus: 3 427 claves efectivas degradadas (H15 habla de 3 429 filas que difieren).
        self.assertGreater(degraded, 3400)
        studio = [e for e in entries if e.created_by_studio]
        self.assertTrue(studio and all(e.rel.name.upper().startswith("00_VSM_") for e in studio))
        with self.project.edit(LABEL, name="x"):
            self.loc.set_text("AGC", "es", "Angoche")
        (write,) = self.project.ws.changeset().writes
        self.assertIn("+AGC;Angoche;;;;Angoche;;;;;;;;", write.diff.splitlines(), "sin «x», como el resto del archivo")


@unittest.skipUnless(vanilla_root() is not None, "necesita VIC2_CORPUS con vanilla")
class CorpusEmptyModTests(unittest.TestCase):
    """Criterio 6 sobre vanilla real con un mod vacío: la clave va a 00_<P>_overrides.csv y text.csv no se copia."""

    def test_a_vanilla_key_goes_to_the_overrides_file(self):
        isolate_appdirs(self)
        base = Path(tempfile.mkdtemp(prefix="vic2studio-emptymod-"))
        self.addCleanup(shutil.rmtree, base, True)
        mod = base / "EmptyMod"
        mod.mkdir()
        project = Project.open(vanilla_root(), mod)
        self.addCleanup(project.close, discard=True)
        loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
        entry = next(e for e in loc.entries() if e.rel.name == "text.csv")
        with project.edit(LABEL, name="x"):
            rel = loc.set_text(entry.key, "es", "Nuevo")
        self.assertEqual(rel, VPath.of("localisation/00_EMPTYMOD_overrides.csv"))
        (write,) = project.ws.changeset().writes
        self.assertEqual((str(write.rel), write.action), (str(rel), WriteAction.CREATE))
        self.assertEqual(write.data.count(b"\r\n"), 1, "una sola fila, la de esa clave")
        self.assertTrue(write.data.startswith(f"{entry.key};".encode("cp1252")))
        self.assertEqual(loc.text(entry.key, "es"), "Nuevo")
        self.assertEqual(loc.text(entry.key, "en"), entry.texts["en"], "las demás columnas se conservan")


if __name__ == "__main__":
    unittest.main()
