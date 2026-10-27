"""Extractores del índice (wizard §7) sobre el minijuego: cada tipo, sus atributos y sus referencias."""

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, LAND, MINIGAME_COUNTS, PROVINCE_COLORS, SEA, build_minigame  # noqa: E402
from vic2studio.core.index import build_index, discover_extractors, extract_bytes, extractors_for  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.index import parsing  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402

GAME = LayerKind.GAME


def facts_of(rel: str, data: bytes | str):
    data = data.encode("cp1252") if isinstance(data, str) else data
    return extract_bytes(VPath.of(rel), data, GAME)


def refs_of(rel: str, data, kind: str | None = None) -> list[tuple[str, str, str]]:
    return [(r.kind, r.name, r.role) for f in facts_of(rel, data) for r in f.refs if kind is None or r.kind == kind]


def defs_of(rel: str, data, kind: str | None = None):
    return [s for f in facts_of(rel, data) for s in f.defs if kind is None or s.kind == kind]


class MinigameIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = build_minigame(mod=False)
        cls.index = build_index(cls.game.snapshot(), None)

    @classmethod
    def tearDownClass(cls):
        cls.game.cleanup()

    def test_counts_of_every_kind(self):
        for kind, count in MINIGAME_COUNTS.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.index.count(kind), count)
        self.assertEqual(set(MINIGAME_COUNTS) - set(self.index.kinds()), set())

    def test_every_kind_constant_has_an_extractor_or_is_derived(self):
        discover_extractors()
        kinds = {getattr(m, name) for name in dir(m) if name.startswith("KIND_")}
        produced = set(self.index.kinds()) | {m.KIND_FILE}
        # Tipos que el minijuego no trae todavía, pero cuyo extractor existe: se comprueban abajo con bytes.
        covered_elsewhere = {m.KIND_TRAIT, m.KIND_MODIFIER, m.KIND_PROVINCE_FLAG, m.KIND_GLOBAL_FLAG}
        self.assertEqual(kinds - produced - covered_elsewhere, set())

    def test_tags_and_dynamic_dominions(self):
        self.assertEqual(self.index.names(m.KIND_TAG), ["AAA", "BBB", "CCC", "D01"])
        self.assertFalse(self.index.attrs(m.KIND_TAG, "CCC", "dynamic"))
        self.assertTrue(self.index.attrs(m.KIND_TAG, "D01", "dynamic"))
        self.assertEqual(self.index.attrs(m.KIND_TAG, "AAA", "file"), "countries/Aland.txt")
        self.assertEqual([r.name for r in self.index.refs(m.KIND_COUNTRY_FILE)],
                         ["countries/aland.txt", "countries/borland.txt", "countries/corland.txt",
                          "countries/dominion.txt"])

    def test_parties_are_named_by_country_file(self):
        names = self.index.names(m.KIND_PARTY)
        self.assertIn("countries/borland.txt:shared_party", names)
        self.assertIn("countries/corland.txt:shared_party", names, "H12: el mismo nombre en dos archivos")
        party = self.index.get(m.KIND_PARTY, "countries/aland.txt:AAA_conservative")
        self.assertEqual(party.attrs["ideology"], "conservative")
        self.assertEqual(party.attrs["policies"]["trade_policy"], "protectionism")
        self.assertEqual(self.index.attrs(m.KIND_COUNTRY_FILE, "countries/aland.txt", "color"), [10, 20, 30])
        self.assertEqual(self.index.attrs(m.KIND_COUNTRY_FILE, "countries/aland.txt", "parties"),
                         ["AAA_conservative"])

    def test_country_history_fields_and_refs(self):
        history = self.index.get(m.KIND_COUNTRY_HISTORY, "AAA")
        self.assertEqual(history.attrs["fields"]["government"], "monarchy")
        refs = {(r.kind, r.name, r.role) for r in self.index.refs_from(history.rel)}
        self.assertIn((m.KIND_PROVINCE, "1", "capital"), refs)
        self.assertIn((m.KIND_CULTURE, "alander", "primary_culture"), refs)
        self.assertIn((m.KIND_GOVERNMENT, "monarchy", "government"), refs)

    def test_country_history_classifies_dynamic_keys(self):
        data = ("capital = 1\nnationalvalue = nv_order\nruling_party = AAA_conservative\nmusket_drill = 1\n"
                "field_kitchens = yes\nslavery = no_slavery\nprestige = 10\ncivilized = yes\ncivilized = yes\n"
                "oob = \"/1861/AAA_oob.txt\"\nupper_house = { conservative = 60 liberal = 30 }\n"
                "set_country_flag = mg_flag\n1861.1.1 = { government = republic musket_drill = 1 }\n")
        refs = set(refs_of("history/countries/AAA - Aland.txt", data))
        expected = {(m.KIND_NATIONAL_VALUE, "nv_order", "nationalvalue"),
                    (m.KIND_PARTY, "AAA_conservative", "ruling_party"),
                    (m.KIND_TECHNOLOGY, "musket_drill", "technology"),
                    (m.KIND_INVENTION, "field_kitchens", "invention"),
                    (m.KIND_ISSUE_OPTION, "no_slavery", "slavery"),
                    (m.KIND_FILE, "history/units/1861/aaa_oob.txt", "oob"),
                    (m.KIND_IDEOLOGY, "conservative", "upper_house"), (m.KIND_GOVERNMENT, "republic", "government")}
        self.assertEqual(expected - refs, set())
        self.assertNotIn((m.KIND_TECHNOLOGY, "prestige", "technology"), refs, "los campos fijos no son tecnologías")
        history = defs_of("history/countries/AAA - Aland.txt", data, m.KIND_COUNTRY_HISTORY)[0]
        self.assertEqual(history.name, "AAA")
        self.assertEqual(history.attrs["duplicates"], [["civilized", 9, 8]])
        self.assertEqual(history.attrs["upper_house"], [[11, 90.0]])
        self.assertEqual(history.attrs["dated"], [["1861.1.1", 13, {"government": "republic"}]])
        flags = defs_of("history/countries/AAA - Aland.txt", data, m.KIND_COUNTRY_FLAG)
        self.assertEqual([f.name for f in flags], ["mg_flag"])

    def test_provinces_split_by_sea_starts(self):
        self.assertEqual(self.index.names(m.KIND_PROVINCE), [str(p) for p in LAND])
        self.assertEqual(self.index.names(m.KIND_SEA_PROVINCE), [str(p) for p in SEA])
        land = self.index.get(m.KIND_PROVINCE, "5")
        self.assertEqual(land.attrs["color"], list(PROVINCE_COLORS[5]), "«50.» se lee al estilo atoi (H4)")
        self.assertFalse(land.attrs["is_sea"])
        sea = self.index.get(m.KIND_SEA_PROVINCE, "9")
        self.assertTrue(sea.attrs["is_sea"])
        self.assertEqual(sea.kind, m.KIND_SEA_PROVINCE)
        self.assertIsNone(self.index.get(m.KIND_PROVINCE, "9"))
        self.assertEqual({s.kind for s in self.index.defs_in(VPath.of("map/definition.csv"))},
                         {m.KIND_PROVINCE, m.KIND_SEA_PROVINCE})

    def test_map_groups(self):
        self.assertEqual(self.index.attrs(m.KIND_REGION, "AAA_1", "provinces"), [1, 2, 3])
        self.assertEqual(self.index.attrs(m.KIND_SEA_REGION, "south_sea_region", "provinces"), [11, 12],
                         "region_sea.txt solo con CR")
        self.assertEqual(self.index.attrs(m.KIND_CONTINENT, "west_land", "provinces"), [1, 2, 3, 4])
        self.assertEqual(self.index.attrs(m.KIND_CLIMATE, "harsh_climate", "provinces"), [5, 6, 7, 8],
                         "claves emparejadas: la lista es la 2.ª aparición (H7)")
        self.assertTrue(self.index.attrs(m.KIND_TERRAIN, "ocean", "is_water"))

    def test_province_history(self):
        # Orden de definición: por ruta (east/3 antes que north/1) y línea.
        self.assertEqual(self.index.names(m.KIND_PROVINCE_HISTORY), ["3", "1", "2"])
        self.assertEqual(len(self.index.effective(m.KIND_PROVINCE_HISTORY, "3")), 2, "id repetido en dos carpetas")
        cr_only = self.index.get(m.KIND_PROVINCE_HISTORY, "2")
        self.assertEqual(cr_only.rel, "history/provinces/south/2  Llanura.txt")
        refs = {(r.kind, r.name, r.role, r.line) for r in self.index.refs_from(cr_only.rel)}
        self.assertIn((m.KIND_TAG, "BBB", "add_core", 3), refs, "las líneas cuentan el CR suelto (H2)")
        goods = {r.name for r in self.index.refs(m.KIND_GOODS)}
        self.assertEqual(goods, {"fish", "grain"})

    def test_culture_religion_and_pops(self):
        self.assertEqual(self.index.attrs(m.KIND_CULTURE, "dominer", "group"), "south_folk")
        self.assertEqual(self.index.attrs(m.KIND_CULTURE_GROUP, "north_folk", "cultures"), ["alander", "borlander"])
        self.assertEqual(self.index.attrs(m.KIND_RELIGION, "sunfaith", "color"), [0.8, 0.8, 0])
        blocks = self.index.names(m.KIND_POP_BLOCK)
        self.assertEqual(blocks, ["1836.1.1:1", "1836.1.1:2", "1861.1.1:1"])
        self.assertEqual(len(self.index.effective(m.KIND_POP_BLOCK, "1836.1.1:1")), 2, "H10: bloque repetido")
        pops = VPath.of("history/pops/1836.1.1/North.txt")
        refs = [(r.kind, r.name) for r in self.index.refs_from(pops)]
        self.assertEqual(refs.count((m.KIND_CULTURE, "alander")), 1, "una referencia por nombre y archivo")
        self.assertIn((m.KIND_RELIGION, "moonfaith"), refs)
        self.assertIn((m.KIND_POP_TYPE, "soldiers"), refs)

    def test_politics(self):
        self.assertEqual(self.index.attrs(m.KIND_GOVERNMENT, "republic", "ideologies"),
                         ["liberal", "conservative", "socialist"])
        self.assertEqual(self.index.attrs(m.KIND_GOVERNMENT, "republic", "duration"), "48")
        self.assertTrue(self.index.attrs(m.KIND_GOVERNMENT, "council", "election"))
        self.assertEqual(self.index.attrs(m.KIND_ISSUE_OPTION, "no_slavery", "category"), "political_reforms")
        self.assertEqual(self.index.attrs(m.KIND_ISSUE_GROUP, "slavery", "options"), ["yes_slavery", "no_slavery"])
        self.assertEqual(self.index.attrs(m.KIND_REBEL_TYPE, "loyal_rebels", "government"),
                         {"monarchy": "monarchy", "republic": "monarchy"})
        self.assertEqual(self.index.attrs(m.KIND_IDEOLOGY, "liberal", "group"), "centre_group")

    def test_technology_and_units(self):
        self.assertEqual(self.index.attrs(m.KIND_TECHNOLOGY, "musket_drill", "folder"), "army_tech")
        self.assertEqual(self.index.attrs(m.KIND_TECHNOLOGY, "musket_drill", "year"), 1836)
        self.assertEqual(self.index.attrs(m.KIND_TECHNOLOGY, "musket_drill", "activate_unit"), ["infantry"])
        self.assertEqual(self.index.attrs(m.KIND_INVENTION, "field_kitchens", "activate_unit"), ["frigate"])
        self.assertEqual({(s.name, s.attrs["type"]) for s in self.index.symbols(m.KIND_UNIT_TYPE)},
                         {("infantry", "land"), ("frigate", "naval")})
        self.assertEqual(self.index.attrs(m.KIND_TECH_FOLDER, "army_tech", "areas"), ["army_doctrine", "light_arms"])
        self.assertIn((m.KIND_BUILDING, "fort", "activate_building"),
                      {(r.kind, r.name, r.role) for r in self.index.refs(m.KIND_BUILDING)})

    def test_war_cb_and_bookmarks(self):
        self.assertTrue(self.index.attrs(m.KIND_CB, "conquer_land", "in_peace_order"))
        self.assertEqual(self.index.attrs(m.KIND_CB, "conquer_land", "months"), 12)
        order = [r.name for r in self.index.refs(m.KIND_CB) if r.role == "peace_order"]
        self.assertEqual(order, ["conquer_land", "free_people", "humble_rival", "annex"])
        self.assertNotIn("peace_order", self.index.names(m.KIND_CB))
        self.assertEqual(self.index.attrs(m.KIND_BOOKMARK, "MG_LATE", "date"), "1861.1.1")
        self.assertEqual(self.index.names(m.KIND_WAR), ["Old War"])
        war_refs = {(r.kind, r.name, r.role) for r in self.index.refs_from(VPath.of("history/wars/Old War.txt"))}
        self.assertIn((m.KIND_CB, "conquer_land", "casus_belli"), war_refs)
        self.assertIn((m.KIND_TAG, "BBB", "receiver"), war_refs)
        alliance = {(r.name, r.role) for r in self.index.refs_from(VPath.of("history/diplomacy/Alliances.txt"))}
        self.assertEqual(alliance, {("AAA", "alliance_first"), ("CCC", "alliance_second")})

    def test_events_decisions_and_flags(self):
        self.assertEqual(self.index.names(m.KIND_EVENT), ["1001", "1002", "1003"])
        self.assertEqual(self.index.attrs(m.KIND_EVENT, "1002", "type"), "province_event")
        self.assertTrue(self.index.attrs(m.KIND_EVENT, "1003", "triggered_only"))
        refs = {(r.name, r.role) for r in self.index.refs(m.KIND_EVENT)}
        self.assertEqual(refs, {("1001", "country_event"), ("1999", "country_event")})
        loc = {(r.name, r.role) for r in self.index.refs(m.KIND_LOC_KEY)}
        self.assertTrue({("EVT_1001_NAME", "title"), ("EVT_1001_A", "option"), ("unite_lands_title", "decision_title"),
                         ("unite_lands_desc", "decision_desc")} <= loc)
        self.assertEqual(self.index.names(m.KIND_COUNTRY_FLAG), ["mg_done"])
        self.assertEqual(self.index.names(m.KIND_DECISION), ["unite_lands"])

    def test_interface_and_images(self):
        sprite = self.index.get(m.KIND_SPRITE, "GFX_mg_icon")
        self.assertEqual(sprite.attrs["texture"], "gfx/interface/mg_icon.dds", "«\\\\» se normaliza")
        self.assertEqual(sprite.attrs["frames"], 2)
        self.assertEqual(self.index.attrs(m.KIND_SPRITE, "GFX_mg_button", "texture"), "gfx/interface/mg_button.tga",
                         "textureFile sin distinguir mayúsculas (H23)")
        self.assertEqual(self.index.names(m.KIND_GUI_WINDOW), ["mg_window"])
        self.assertTrue(self.index.exists(m.KIND_IMAGE, "gfx/flags/aaa.tga"))
        self.assertEqual(self.index.get(m.KIND_IMAGE, "gfx/flags/aaa.tga").rel, "gfx/flags/AAA.tga")
        textures = {r.name for r in self.index.refs(m.KIND_IMAGE)}
        self.assertEqual(textures, {"gfx/interface/mg_icon.dds", "gfx/interface/mg_button.tga"})

    def test_localisation_keys(self):
        self.assertIn("PROV1", self.index.names(m.KIND_LOC_KEY))
        self.assertNotIn("PROV12", self.index.names(m.KIND_LOC_KEY))
        self.assertEqual(self.index.get(m.KIND_LOC_KEY, "AAA").rel, "localisation/minigame_names.csv")


class ExtractorEdgeTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_traits_modifiers_and_other_flags(self):
        traits = defs_of("common/traits.txt", "personality = { brave = { attack = 1 } }\n"
                                              "background = { clerk = { defence = 1 } }\n")
        self.assertEqual([(t.name, t.attrs["category"]) for t in traits], [("brave", "personality"),
                                                                           ("clerk", "background")])
        modifiers = defs_of("common/event_modifiers.txt", "plague = { icon = 1 }\nfeast = { icon = 2 }\n")
        self.assertEqual([s.name for s in modifiers], ["plague", "feast"])
        script = defs_of("decisions/x.txt", "political_decisions = { d = { effect = { set_global_flag = g "
                                            "any_owned = { set_province_flag = p } } } }\n")
        self.assertEqual({(s.kind, s.name) for s in script} >= {(m.KIND_GLOBAL_FLAG, "g"), (m.KIND_PROVINCE_FLAG, "p")},
                         True)

    def test_broken_files_never_raise(self):
        for rel, data in (("common/countries.txt", "AAA = { {"), ("common/cultures.txt", "}}} = ="),
                          ("history/countries/AAA - A.txt", "capital = { = }"), ("map/definition.csv", ";;;\x00\xff"),
                          ("events/x.txt", "country_event = { id = { } option = 3 }"),
                          ("interface/x.gfx", "spriteTypes = 3"), ("localisation/x.csv", b"\xff\xfe\x00a")):
            with self.subTest(rel=rel):
                facts = facts_of(rel, data)
                self.assertTrue(facts, "un hecho por extractor aunque el archivo esté roto")

    def test_extractor_that_raises_gives_empty_facts(self):
        from vic2studio.core.index.model import EXTRACTORS, extractor

        @extractor("common/zz_probe.txt", version=1)
        def raising_probe(rel, data, layer):
            raise RuntimeError("probe")

        self.addCleanup(lambda: EXTRACTORS.remove(next(s for s in EXTRACTORS if s.name.endswith("raising_probe"))))
        with self.assertLogs("vic2studio.core.index.builder", "ERROR"):
            facts = facts_of("common/zz_probe.txt", "a = 1")
        self.assertEqual([(f.extractor, f.defs, f.refs) for f in facts if f.extractor.endswith("raising_probe")],
                         [("test_index_extractors.raising_probe", (), ())])

    def test_each_file_is_parsed_once(self):
        discover_extractors()
        with build_minigame(mod=False) as game:
            snap = game.snapshot()
            clausewitz = [e for stack in snap.entries.values() for e in stack
                          if any(s.needs_data for s in extractors_for(e.rel))
                          and e.rel.suffix in (".txt", ".gfx", ".gui", ".map")]
            before = parsing.parse_count()
            build_index(snap, None)
            self.assertEqual(parsing.parse_count() - before, len(clausewitz))

    def test_images_are_not_read(self):
        with build_minigame(mod=False) as game:
            read = []
            real = Path.read_bytes

            def spy(path):
                read.append(path.suffix.lower())
                return real(path)

            with unittest.mock.patch.object(Path, "read_bytes", spy):
                index = build_index(game.snapshot(), None)
        self.assertTrue(index.exists(m.KIND_IMAGE, "gfx/flags/aaa.tga"))
        self.assertIn(".txt", read)
        self.assertFalse({".tga", ".dds"} & set(read), "una imagen no se lee para indexarla: solo cuenta su ruta")

    def test_game_files_are_invented(self):
        """Ningún archivo del minijuego viene del juego: todos se generan aquí (test_no_paradox_data)."""
        self.assertIn("map/provinces.bmp", GAME_FILES)
        self.assertTrue(all(isinstance(v, (str, bytes)) for v in GAME_FILES.values()))


if __name__ == "__main__":
    unittest.main()
