"""Rutas relativas (``VPath``), nombres de Windows y reglas de carga (``core.vfs``, wizard §5.1–5.2)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.vfs import (  # noqa: E402
    DESCRIPTOR_REL,
    LOAD_RULES,
    MAX_PATH_WARNING,
    DocKind,
    InvalidPathError,
    LoadMode,
    VPath,
    long_path_problem,
    rule_for,
    windows_name_problems,
)
from vic2studio.core.vfs import paths, rules  # noqa: E402


class VPathTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(VPath.of("common\\cb_types.txt"), "common/cb_types.txt")
        self.assertEqual(VPath.of("./history//provinces/./south/2  Llanura.txt"),
                         "history/provinces/south/2  Llanura.txt")
        self.assertEqual(VPath.of("events/"), "events")
        self.assertEqual(VPath.of(Path("common") / "a.txt"), "common/a.txt")
        self.assertIsInstance(VPath.of("a"), VPath)

    def test_rejected(self):
        for raw, reason in (("", "empty"), ("./", "empty"), ("/etc/passwd", "absolute"), ("\\x", "absolute"),
                            ("C:/game/x.txt", "drive"), ("c:x.txt", "drive"), ("common/../../x", "parent"),
                            ("..", "parent"), ("@descriptor.mod", "reserved"), ("@x/y", "reserved"),
                            ("a\0b", "nul")):
            with self.subTest(raw=raw):
                with self.assertRaises(InvalidPathError) as ctx:
                    VPath.of(raw)
                self.assertEqual(ctx.exception.reason, reason)
                self.assertIn(raw, ctx.exception.message("es"))
                self.assertIsInstance(ctx.exception, ValueError)
        self.assertEqual(VPath.of("a/@b"), "a/@b", "solo el primer componente está reservado")

    def test_descriptor_rel_is_accepted_only_as_the_constant(self):
        self.assertIs(VPath.of(DESCRIPTOR_REL), DESCRIPTOR_REL)
        with self.assertRaises(InvalidPathError):
            VPath.of(str(DESCRIPTOR_REL))

    def test_properties(self):
        rel = VPath.of("History/Provinces/south/2  Llanura.TXT")
        self.assertEqual(rel.key, "HISTORY/PROVINCES/SOUTH/2  LLANURA.TXT")
        self.assertEqual(rel.name, "2  Llanura.TXT")
        self.assertEqual(rel.parent, "History/Provinces/south")
        self.assertEqual(rel.suffix, ".txt")
        self.assertEqual(VPath.of("a.txt").parent, "")
        self.assertEqual(VPath.of(".hidden").suffix, "")
        self.assertEqual(rel.parts, ("History", "Provinces", "south", "2  Llanura.TXT"))
        self.assertEqual(VPath.of("common").join("countries", "A.txt"), "common/countries/A.txt")
        self.assertTrue(rel.is_under("history"))
        self.assertTrue(rel.is_under("HISTORY\\provinces/"))
        self.assertFalse(rel.is_under("history/prov"))
        self.assertFalse(VPath.of("common").is_under("common"))
        self.assertTrue(rel.is_under(""))


class WindowsNameTests(unittest.TestCase):
    def test_devices_also_with_extension(self):
        for name in ("CON", "con.tga", "Nul.txt", "COM1", "lpt9.csv", "AUX.tar.gz", "PRN "):
            with self.subTest(name=name):
                self.assertIn(paths.NAME_DEVICE, windows_name_problems(name))
        for name in ("CONSOLE.txt", "COM10", "icon.tga", "AAA - Aland.txt", "2  Llanura.txt"):
            with self.subTest(name=name):
                self.assertEqual(windows_name_problems(name), [])

    def test_forbidden_and_trailing(self):
        self.assertEqual(windows_name_problems('a<b'), [paths.NAME_FORBIDDEN])
        self.assertEqual(windows_name_problems("a?"), [paths.NAME_FORBIDDEN])
        self.assertEqual(windows_name_problems("tab\tname"), [paths.NAME_FORBIDDEN])
        self.assertEqual(windows_name_problems("name."), [paths.NAME_TRAILING])
        self.assertEqual(windows_name_problems("name "), [paths.NAME_TRAILING])
        self.assertEqual(windows_name_problems(""), [paths.NAME_EMPTY])
        self.assertEqual(windows_name_problems("CON."), [paths.NAME_DEVICE, paths.NAME_TRAILING])

    def test_long_path(self):
        self.assertIsNone(long_path_problem("/" + "a" * (MAX_PATH_WARNING - 1)))
        self.assertEqual(long_path_problem("/" + "a" * MAX_PATH_WARNING), paths.PATH_TOO_LONG)


class LoadRuleTests(unittest.TestCase):
    def check(self, rel, pattern, mode, kind, recursive=False):
        rule = rule_for(rel)
        self.assertEqual((rule.pattern, rule.mode, rule.doc_kind, rule.recursive), (pattern, mode, kind, recursive),
                         rel)
        return rule

    def test_table_of_section_5_2(self):
        C, L = DocKind.CLAUSEWITZ, DocKind.LOCALISATION
        self.check("common/cb_types.txt", "common/*.txt", LoadMode.WHOLE_FILE, C)
        self.check("common/defines.lua", "common/defines.lua", LoadMode.WHOLE_FILE, DocKind.LUA)
        self.check("common/countries/Aland.txt", "common/countries/*.txt", LoadMode.REFERENCED, C)
        self.check("history/units/1861/AAA_oob.txt", "history/units/**/*.txt", LoadMode.REFERENCED, C, True)
        self.check("history/pops/1836.1.1/North.txt", "history/pops/**/*.txt", LoadMode.UNION_BY_PATH, C, True)
        self.check("history/wars/Guerra.txt", "history/wars/*.txt", LoadMode.UNION_BY_PATH, C)
        self.check("history/diplomacy/Alliances.txt", "history/diplomacy/*.txt", LoadMode.UNION_BY_PATH, C)
        for folder in ("events", "decisions", "units", "news", "poptypes"):
            self.check(f"{folder}/x.txt", f"{folder}/*.txt", LoadMode.UNION_BY_PATH, C)
        tech = self.check("technologies/army_tech.txt", "technologies/*.txt", LoadMode.REFERENCED, C)
        self.assertFalse(tech.verified, "[verificar en juego]")
        self.assertFalse(self.check("interface/a.gfx", "interface/*.gfx", LoadMode.UNION_BY_PATH, C).verified)
        self.check("interface/a.gui", "interface/*.gui", LoadMode.WHOLE_FILE, C)
        self.check("localisation/00_TST.csv", "localisation/*.csv", LoadMode.LOCALISATION, L)
        self.check("map/default.map", "map/default.map", LoadMode.MAP_BUNDLE, C)
        self.check("map/climate.txt", "map/*.txt", LoadMode.MAP_BUNDLE, C)
        self.check("map/definition.csv", "map/*.csv", LoadMode.MAP_BUNDLE, DocKind.TABLE)
        self.check("map/provinces.bmp", "map/*.bmp", LoadMode.MAP_BUNDLE, DocKind.BMP)
        self.check("gfx/flags/AAA.tga", "gfx/**/*.tga", LoadMode.ASSET, DocKind.IMAGE, True)
        self.check(DESCRIPTOR_REL, "@descriptor.mod", LoadMode.WHOLE_FILE, C)

    def test_keyed_rules(self):
        countries = self.check("history/countries/AAA - Aland.txt", "history/countries/*.txt",
                               LoadMode.KEYED_UNION, DocKind.CLAUSEWITZ)
        self.assertEqual(countries.key_of(VPath.of("history/countries/aaa - Aland.txt")), "AAA")
        self.assertIsNone(countries.key_of(VPath.of("history/countries/a.txt")))
        provinces = self.check("history/provinces/south/2  Llanura.txt", "history/provinces/**/*.txt",
                               LoadMode.KEYED_UNION, DocKind.CLAUSEWITZ, True)
        self.assertEqual(provinces.key_of(VPath.of("history/provinces/south/2  Llanura.txt")), "2")
        self.assertEqual(provinces.key_of(VPath.of("history/provinces/3246  JanMayen.txt")), "3246")
        self.assertEqual(provinces.key_of(VPath.of("history/provinces/a/007 - x.txt")), "7")
        self.assertIsNone(provinces.key_of(VPath.of("history/provinces/a/readme.txt")))

    def test_case_insensitive_and_fallbacks(self):
        self.check("COMMON/CB_TYPES.TXT", "common/*.txt", LoadMode.WHOLE_FILE, DocKind.CLAUSEWITZ)
        self.assertEqual(rule_for("common/sub/x.txt").pattern, "**/*.txt", "common/*.txt no baja de carpeta")
        self.assertEqual(rule_for("music/theme.ogg").doc_kind, DocKind.BINARY)
        self.assertIs(rule_for("music/theme.ogg"), LOAD_RULES[-1])
        self.assertEqual(rule_for("readme.txt").doc_kind, DocKind.CLAUSEWITZ)

    def test_glob_compiler(self):
        regex = rules._compile("history/provinces/**/*.txt")
        self.assertTrue(regex.fullmatch("history/provinces/a.txt"))
        self.assertTrue(regex.fullmatch("history/provinces/a/b/c.TXT"))
        self.assertFalse(regex.fullmatch("history/provinces.txt"))
        self.assertFalse(rules._compile("common/*.txt").fullmatch("common/a/b.txt"))
        self.assertTrue(rules._compile("a?c").fullmatch("abc"))
        self.assertFalse(rules._compile("a?c").fullmatch("a/c"))


if __name__ == "__main__":
    unittest.main()
