"""``core.lua_defines``: ``defines.lua`` sin pérdidas (I3, wizard §4.1, H20)."""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.lua_defines import LuaDefines, LuaValue  # noqa: E402

SAMPLE = (b"defines = {\r\n\r\nstart_date = '1836.1.1',\r\nend_date = '1935.12.31',\r\n\r\n"
          b"country = {\r\n\tYEARS_OF_NATIONALISM \t= 20,   -- a\xf1os de nacionalismo\r\n"
          b"\tBASE_TAX = 0.2, --[[ bloque\r\nde varias l\xedneas ]] NEGATIVE = -0.5,\r\n"
          b'\tNAME = "dos palabras",\r\n},\r\neconomy = { MAX = 1e3, FLAG = yes }\r\n}\r\n')


class LosslessTests(unittest.TestCase):
    def test_round_trip_and_values(self):
        defines = LuaDefines.from_bytes(SAMPLE)
        self.assertEqual(defines.to_bytes(), SAMPLE)
        values = {(v.table, v.key): v for v in defines.values()}
        self.assertEqual(values[("defines", "start_date")], LuaValue("start_date", "'1836.1.1'", 3, "defines"))
        self.assertEqual(values[("defines", "start_date")].text, "1836.1.1")
        self.assertEqual(values[("country", "YEARS_OF_NATIONALISM")].raw, "20")
        self.assertEqual(values[("country", "NEGATIVE")].raw, "-0.5")
        self.assertEqual(values[("country", "NEGATIVE")].line, 9, "el comentario de bloque cuenta sus líneas")
        self.assertEqual(values[("country", "NAME")].text, "dos palabras")
        self.assertEqual(values[("economy", "MAX")].raw, "1e3")
        self.assertEqual(values[("economy", "FLAG")].raw, "yes")
        self.assertNotIn(("country", "a"), values, "lo comentado no es una asignación")

    def test_set_changes_only_the_value(self):
        defines = LuaDefines.from_bytes(SAMPLE)
        defines.set("END_DATE", "'2300.1.1'")          # sin distinguir mayúsculas
        self.assertEqual(defines.to_bytes(), SAMPLE.replace(b"'1935.12.31'", b"'2300.1.1'"))
        defines.set("YEARS_OF_NATIONALISM", "25", table="country")
        self.assertEqual(defines.get("years_of_nationalism").raw, "25")
        self.assertIn("a\xf1os".encode("latin-1"), defines.to_bytes(), "el comentario cp1252 sigue igual")
        defines.set("NAME", '"el año"')
        self.assertIn('"el a\xf1o"'.encode("cp1252"), defines.to_bytes())

    def test_errors_change_nothing(self):
        defines = LuaDefines.from_bytes(SAMPLE)
        with self.assertRaises(KeyError):
            defines.set("missing", "1")
        with self.assertRaises(KeyError):
            defines.set("BASE_TAX", "1", table="economy")
        with self.assertRaises(ValueError):
            defines.set("BASE_TAX", "1\n2")
        with self.assertRaises(UnencodableTextError):
            defines.set("NAME", '"中"')
        self.assertEqual(defines.to_bytes(), SAMPLE)
        self.assertIsNone(defines.get("BASE_TAX", table="economy"))

    def test_utf8_bom_file_keeps_its_bom(self):
        data = "﻿defines = { start_date = '1836.1.1', name = \"Ñu\" }\n".encode("utf-8")
        defines = LuaDefines.from_bytes(data)
        self.assertEqual(defines.to_bytes(), data)
        self.assertEqual(defines.get("name").text, "Ñu")
        defines.set("name", '"Ola"')
        self.assertTrue(defines.to_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(defines.to_bytes().count(b"\xef\xbb\xbf"), 1)

    def test_any_bytes_round_trip(self):
        rng = random.Random(1836)
        pieces = [b"a = 1,", b"--x\r", b"{", b"}", b"'s", b'"q"', b"\n", b"\r\n", b" ", b"\t", b"=", b"\xff",
                  b"\x00", b"--[[", b"]]", b"b={c=2}", b"\\", b"-", b"1.5e", b";"]
        for _ in range(500):
            data = b"".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            with self.subTest(data=data):
                defines = LuaDefines.from_bytes(data)
                self.assertEqual(defines.to_bytes(), data)
                for value in defines.values():
                    self.assertTrue(value.line >= 1)

    @unittest.skipUnless(vanilla_root(), "requiere el corpus (VIC2_CORPUS)")
    def test_vanilla_defines(self):
        data = (vanilla_root() / "common" / "defines.lua").read_bytes()
        defines = LuaDefines.from_bytes(data)
        self.assertEqual(defines.to_bytes(), data)
        self.assertEqual(defines.get("start_date").text, "1836.1.1")
        self.assertEqual(defines.get("end_date").text, "1935.12.31")
        self.assertEqual(defines.get("start_date").table, "defines")
        self.assertGreater(len(defines.values()), 600)


if __name__ == "__main__":
    unittest.main()
