"""``SymbolIndex``: combinación por capas y reglas de carga, cambios sin guardar, ``apply``, buscador (§7)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.index import FileFacts, Symbol, SymbolIndex, SymbolRef, build_index, extract_bytes  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.validate.context import effective_localisation  # noqa: E402
from vic2studio.core.vfs import Fingerprint, LayerKind, VPath  # noqa: E402

MOD, GAME = LayerKind.MOD, LayerKind.GAME
COUNTRIES = "common/countries.txt"


def facts(rel: str, layer: LayerKind, *names: str, kind: str = m.KIND_TAG, refs=()) -> FileFacts:
    rel = VPath.of(rel)
    defs = tuple(Symbol(kind, name, rel, line, layer) for line, name in enumerate(names, start=1))
    uses = tuple(SymbolRef(k, n, rel, 1, 1, role) for k, n, role in refs)
    return FileFacts(rel, layer, Fingerprint(1, 1), defs, uses, "probe.x", 1)


class InMemoryTests(unittest.TestCase):
    """Sin instantánea todos los hechos cuentan (el índice falso que usa la interfaz hasta integrar)."""

    def test_without_snapshot_everything_counts(self):
        index = SymbolIndex([facts("a.txt", GAME, "AAA"), facts("a.txt", MOD, "BBB")])
        self.assertEqual(index.names(m.KIND_TAG), ["BBB", "AAA"], "misma ruta y línea: el mod primero")
        self.assertEqual(index.get(m.KIND_TAG, "AAA").layer, GAME)

    def test_lookup_duplicates_and_order(self):
        index = SymbolIndex([facts("events/b.txt", GAME, "1", kind=m.KIND_EVENT),
                             facts("events/a.txt", GAME, "2", "1", kind=m.KIND_EVENT)])
        self.assertEqual(index.names(m.KIND_EVENT), ["2", "1"], "orden por ruta y línea")
        self.assertEqual([s.rel for s in index.lookup(m.KIND_EVENT, "1")], ["events/a.txt", "events/b.txt"])
        self.assertEqual(index.get(m.KIND_EVENT, "1").rel, "events/a.txt")
        self.assertEqual(index.count(m.KIND_EVENT), 2)
        self.assertTrue(index.exists(m.KIND_EVENT, "2"))
        self.assertFalse(index.exists(m.KIND_EVENT, "3"))
        self.assertEqual(index.kinds(), [m.KIND_EVENT])

    def test_exists_ignore_case_and_attrs(self):
        rel = VPath.of(COUNTRIES)
        index = SymbolIndex([FileFacts(rel, GAME, Fingerprint(1, 1), (
            Symbol(m.KIND_CULTURE, "North_German", rel, 3, GAME, {"group": "germanic"}),), (), "probe.x", 1)])
        self.assertTrue(index.exists(m.KIND_CULTURE, "north_german", ignore_case=True))
        self.assertFalse(index.exists(m.KIND_CULTURE, "north_german"))
        self.assertEqual(index.attrs(m.KIND_CULTURE, "North_German", "group"), "germanic")
        self.assertEqual(index.attrs(m.KIND_CULTURE, "North_German", "missing", 7), 7)
        self.assertEqual(index.attrs(m.KIND_CULTURE, "nope", "group", "x"), "x")

    def test_refs(self):
        index = SymbolIndex([facts("history/provinces/1 - A.txt", GAME, refs=[(m.KIND_TAG, "AAA", "owner")]),
                             facts("history/provinces/2 - B.txt", GAME, refs=[(m.KIND_TAG, "AAA", "add_core"),
                                                                               (m.KIND_GOODS, "fish", "trade_goods")])])
        self.assertEqual([r.role for r in index.refs_to(m.KIND_TAG, "AAA")], ["owner", "add_core"])
        self.assertEqual([r.name for r in index.refs_from(VPath.of("history/provinces/2 - B.txt"))], ["AAA", "fish"])
        self.assertEqual(len(index.refs(m.KIND_TAG)), 2)
        self.assertEqual(index.ref_kinds(), [m.KIND_GOODS, m.KIND_TAG])

    def test_symbols_are_hashable(self):
        symbol = Symbol(m.KIND_TAG, "AAA", VPath.of(COUNTRIES), 1, GAME, {"file": "x"})
        self.assertEqual(len({symbol, symbol}), 1)


class LayerTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_mod_file_replaces_the_game_file_whole(self):
        registry = 'AAA = "countries/Aland.txt"\r\nZZZ = "countries/Z.txt"\r\n'
        with build_minigame(mod=False, mod_files={COUNTRIES: registry}) as game:
            index = build_index(game.snapshot(), None)
            self.assertEqual(index.names(m.KIND_TAG), ["AAA", "ZZZ"], "WHOLE_FILE: solo cuenta el ganador")
            self.assertEqual(index.get(m.KIND_TAG, "AAA").layer, MOD)
            losing = index.lookup(m.KIND_TAG, "BBB")
            self.assertEqual([(s.layer, index.is_effective(s)) for s in losing], [(GAME, False)],
                             "lo que pierde queda para el explicador")
            self.assertIsNone(index.get(m.KIND_TAG, "BBB"))

    def test_union_folders_add_and_a_same_path_copy_replaces(self):
        new = "country_event = { id = 5001 title = X }\r\n"
        copy = "country_event = { id = 1001 title = Y }\r\n"
        with build_minigame(mod=False, mod_files={"events/mod_events.txt": new,
                                                  "events/minigame_events.txt": copy}) as game:
            index = build_index(game.snapshot(), None)
            self.assertEqual(set(index.names(m.KIND_EVENT)), {"1001", "1003", "5001"},
                             "1002 desaparece: la copia del mod sustituye el archivo entero")
            self.assertEqual(index.attrs(m.KIND_EVENT, "1001", "title"), "Y")

    def test_localisation_first_key_by_file_order(self):
        early = "AAA;From mod;;;;Del mod;;;;;;;;;x\r\n"
        with build_minigame(mod=False, mod_files={"localisation/00_mod.csv": early}) as game:
            index = build_index(game.snapshot(), None)
            self.assertEqual(index.get(m.KIND_LOC_KEY, "AAA").rel, "localisation/00_mod.csv")
            self.assertEqual(len(index.effective(m.KIND_LOC_KEY, "AAA")), 2, "las dos filas cuentan; gana la primera")

    def test_replace_path_hides_game_files(self):
        with build_minigame(mod=False, mod_files={"history/provinces/x/7 - Vado.txt": "owner = CCC\r\n"}) as game:
            index = build_index(game.snapshot(replace_paths=["history/provinces"]), None)
            self.assertEqual(index.names(m.KIND_PROVINCE_HISTORY), ["7"],
                             "los del juego quedan ocultos; los del mod se siguen cargando (§5.3)")
            self.assertEqual([r.name for r in index.refs(m.KIND_TAG) if r.role == "owner"], ["CCC"])

    def test_overrides_add_replace_and_delete(self):
        with build_minigame() as game:
            snap = game.snapshot()
            overrides = {VPath.of("events/unsaved.txt"): b"country_event = { id = 7777 }\r\n",
                         VPath.of("decisions/tst_decisions.txt"): None}
            counted = []
            index = build_index(snap, None, overrides, on_extract=lambda rel, name: counted.append(rel))
            self.assertIn("7777", index.names(m.KIND_EVENT), "un documento nuevo sin guardar ya cuenta")
            self.assertEqual(index.get(m.KIND_EVENT, "7777").layer, MOD)
            self.assertNotIn("tst_reform", index.names(m.KIND_DECISION), "borrado sin guardar")
            self.assertIn(VPath.of("events/unsaved.txt"), counted)

    def test_apply_is_incremental(self):
        with build_minigame(mod=False) as game:
            snap = game.snapshot()
            index = build_index(snap, None)
            generation = index.generation
            rel = VPath.of(COUNTRIES)
            data = (game.game(COUNTRIES).read_bytes() + b'EEE = "countries/E.txt"\r\n')
            index.apply(extract_bytes(rel, data, MOD))
            self.assertEqual(index.generation, generation + 1)
            self.assertIn("EEE", index.names(m.KIND_TAG), "el mod gana en cuanto tiene hechos")
            self.assertEqual(index.get(m.KIND_TAG, "AAA").layer, MOD)
            index.apply([], removed=[(rel, MOD)])
            self.assertNotIn("EEE", index.names(m.KIND_TAG), "sin la copia del mod vuelve a ganar el juego")
            self.assertEqual(index.get(m.KIND_TAG, "AAA").layer, GAME)
            # Sustituir los hechos de una ruta en una capa reemplaza los de antes (no se suman).
            index.apply(extract_bytes(rel, b'XXX = "countries/X.txt"\r\n', MOD))
            index.apply(extract_bytes(rel, b'YYY = "countries/Y.txt"\r\n', MOD))
            self.assertEqual(index.names(m.KIND_TAG), ["YYY"])

    def test_copy_is_independent_of_later_applies(self):
        with build_minigame(mod=False) as game:
            index = build_index(game.snapshot(), None)
            copy = index.copy()
            index.apply(extract_bytes(VPath.of(COUNTRIES), b'EEE = "countries/E.txt"\r\n', MOD))
            self.assertEqual(index.names(m.KIND_TAG), ["EEE"])
            self.assertEqual(copy.names(m.KIND_TAG), ["AAA", "BBB", "CCC", "D01"], "la copia no cambia")
            self.assertEqual(copy.generation + 1, index.generation)
            copy.apply([], removed=[(VPath.of("map/region.txt"), GAME)])
            self.assertEqual(index.count(m.KIND_REGION), 3, "ni al revés")
            self.assertEqual(copy.count(m.KIND_REGION), 0)

    def test_apply_with_new_snapshot_recomputes_hidden(self):
        with build_minigame(mod=False, mod_files={"history/provinces/x/7 - Vado.txt": "owner = CCC\r\n"}) as game:
            index = build_index(game.snapshot(), None)
            self.assertEqual(len(index.names(m.KIND_PROVINCE_HISTORY)), 4)
            index.apply([], snapshot=game.snapshot(replace_paths=["history/provinces"]))
            self.assertEqual(index.names(m.KIND_PROVINCE_HISTORY), ["7"])

    def test_sea_split_follows_default_map_changes(self):
        with build_minigame(mod=False) as game:
            index = build_index(game.snapshot(), None)
            rel = VPath.of("map/default.map")
            index.apply(extract_bytes(rel, b"max_provinces = 13\nsea_starts = { 8 9 10 11 12 }\n", MOD))
            self.assertIn("8", index.names(m.KIND_SEA_PROVINCE))
            self.assertNotIn("8", index.names(m.KIND_PROVINCE))
            self.assertEqual(index.refs_to(m.KIND_SEA_PROVINCE, "8")[0].role, m.ROLE_SEA_STARTS)


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = build_minigame(mod=False)
        snap = cls.game.snapshot()
        cls.index = build_index(snap, None)
        cls.loc = effective_localisation(snap)

    @classmethod
    def tearDownClass(cls):
        cls.game.cleanup()

    def test_by_id_and_name(self):
        found = self.index.search("1")
        self.assertEqual((found[0].kind, found[0].name), (m.KIND_PROVINCE, "1"), "exacta primero; tierra antes")
        self.assertEqual(self.index.search("AAA")[0].kind, m.KIND_TAG)
        self.assertEqual(self.index.search("alander")[0].kind, m.KIND_CULTURE)
        prefix = [s.name for s in self.index.search("mg_", kinds=[m.KIND_GUI_WINDOW, m.KIND_COUNTRY_FLAG])]
        self.assertEqual(prefix, ["mg_window", "mg_done"])
        self.assertEqual(self.index.search("  "), [])
        self.assertEqual(len(self.index.search("a", limit=3)), 3)

    def test_by_localised_name_without_accents(self):
        found = self.index.search("ALANDÍA", loc=self.loc, lang="es")
        self.assertEqual((found[0].kind, found[0].name), (m.KIND_TAG, "AAA"))
        found = self.index.search("cumbre", loc=self.loc, lang="es")
        self.assertEqual((found[0].kind, found[0].name), (m.KIND_PROVINCE, "8"))
        self.assertEqual(self.index.search("Borlandia", loc=self.loc, lang="en"), [], "en inglés es «Borland»")

    def test_display(self):
        self.assertEqual(self.index.display(m.KIND_TAG, "AAA", self.loc, "es"), "Alandia (AAA)")
        self.assertEqual(self.index.display(m.KIND_PROVINCE, "1", self.loc, "en"), "1 Capital")
        self.assertEqual(self.index.display(m.KIND_DECISION, "unite_lands", self.loc, "es"),
                         "Unir las tierras (unite_lands)")
        self.assertEqual(self.index.display(m.KIND_TAG, "AAA"), "AAA", "sin localización, el nombre")
        self.assertEqual(self.index.display(m.KIND_PROVINCE, "12", self.loc), "12", "PROV12 falta")


if __name__ == "__main__":
    unittest.main()
