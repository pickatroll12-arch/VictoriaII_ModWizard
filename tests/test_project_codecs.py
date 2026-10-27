"""Códecs de documento (wizard §6.1): ida y vuelta exacta, ``render`` comprobado e igual a lo que escriben
``write_file`` y ``write_csv_file`` (``render_checked`` y ``render_csv_checked`` se extrajeron de ellos)."""

import codecs as std_codecs
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import FIXTURE_ROOT  # noqa: E402
from vic2studio.core.clausewitz import parse, parse_file, render_checked, write_file  # noqa: E402,F401
from vic2studio.core.clausewitz.serializer import SourceMismatchError  # noqa: E402
from vic2studio.core.csvloc import read_csv_file, render_csv_checked, write_csv_file  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.project import codecs  # noqa: E402
from vic2studio.core.project.codecs import (  # noqa: E402
    BinaryCodec,
    ClausewitzCodec,
    JsonCodec,
    LocalisationCodec,
    codec_for,
    kind_for,
    parse_bytes,
)
from vic2studio.core.vfs import DESCRIPTOR_REL, DocKind, VPath  # noqa: E402

SAMPLES = [
    "a = 1 # c\rb = 2\r",
    "political_decisions = {\r\n\ta = { }\r\n",            # sin cerrar
    "# León\r\nname = \"España\"\r\n",
]
RAW = [
    std_codecs.BOM_UTF8 + "a = \"ñ\"\n".encode("utf-8"),
    std_codecs.BOM_UTF8 * 2 + b"a = 1\n",
    std_codecs.BOM_UTF16_LE + "a = 1\r\n".encode("utf-16-le"),
    "a = \"café\"\r\n".encode("utf-8"),
    b"a = \x81\x8d\r\n",
]
CSV = [
    b"key;English;French;German;;Spanish;;;;;;;;x\r\nk2;a;b;c;;d;;;;;;;;x\r\n",
    std_codecs.BOM_UTF8 + "k;é;;;;;;;;;;;;x\n".encode("utf-8"),
    b"no;end;marker",
]


class CodecTests(unittest.TestCase):
    def test_clausewitz_round_trip_and_parse_file_equivalence(self):
        codec = ClausewitzCodec()
        with tempfile.TemporaryDirectory() as tmp:
            for data in [s.encode("cp1252") for s in SAMPLES] + RAW:
                with self.subTest(data=data[:20]):
                    model, diagnostics = codec.load(data, VPath.of("common/x.txt"))
                    self.assertIs(diagnostics, model.diagnostics)
                    self.assertEqual(codec.snapshot(model), data)
                    again, _ = codec.load(codec.snapshot(model), VPath.of("common/x.txt"))
                    self.assertEqual(codec.snapshot(again), data)
                    path = Path(tmp) / "x.txt"
                    path.write_bytes(data)
                    from_file = parse_file(path)
                    self.assertEqual(model.encoding, from_file.encoding)
                    self.assertEqual(model.document.extra_boms, from_file.document.extra_boms)
                    self.assertEqual([(d.code, d.line) for d in model.diagnostics],
                                     [(d.code, d.line) for d in from_file.diagnostics])
                    self.assertEqual(parse_bytes(data).stamp, from_file.stamp)

    def test_render_checked_equals_what_write_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for data in [s.encode("cp1252") for s in SAMPLES if "{\r\n\ta" not in s] + RAW:
                with self.subTest(data=data[:20]):
                    path = Path(tmp) / "x.txt"
                    path.write_bytes(data)
                    result = parse_file(path)
                    result.document.append("added", "yes")
                    rendered = render_checked(result)
                    write_file(path, result, backup=False)
                    self.assertEqual(path.read_bytes(), rendered)
                    self.assertEqual(ClausewitzCodec().render(result), rendered)

    def test_render_checks_before_the_disk(self):
        codec = ClausewitzCodec()
        model, _ = codec.load("a = { b = 1 }\r\n".encode(), VPath.of("common/x.txt"))
        model.document.get("a").set("c", "中文")
        with self.assertRaises(UnencodableTextError):
            codec.render(model)
        with self.assertRaises(UnencodableTextError):
            codec.snapshot(model)
        broken, diagnostics = codec.load(b"a = {\r\n\tb = 1\r\n", VPath.of("common/x.txt"))
        self.assertTrue(any(d.code == "unclosed_block" for d in diagnostics))
        self.assertEqual(codec.render(broken), b"a = {\r\n\tb = 1\r\n", "sin cambios se escribe tal cual")
        # Un valor suelto justo antes de un «=» sin clave se releería como «5 = b» (test_clausewitz_edit).
        result = parse("x = {\n\ta = 1\n\t= b\n}\n")
        result.document.get("x").insert(1, None, 5)
        with self.assertRaises(SourceMismatchError):
            codec.render(result)
        self.assertEqual(codec.snapshot(result), b"x = {\n\ta = 1\n\t5\n\t= b\n}\n", "la instantánea no verifica")

    def test_localisation_round_trip_and_write_csv_equivalence(self):
        codec = LocalisationCodec()
        with tempfile.TemporaryDirectory() as tmp:
            for data in CSV:
                with self.subTest(data=data[:20]):
                    model, diagnostics = codec.load(data, VPath.of("localisation/x.csv"))
                    self.assertEqual(codec.snapshot(model), data)
                    self.assertEqual(codec.render(model), data)
                    path = Path(tmp) / "x.csv"
                    path.write_bytes(data)
                    from_file = read_csv_file(path)
                    self.assertEqual(model.encoding, from_file.encoding)
                    self.assertEqual([d.code for d in diagnostics], [d.code for d in from_file.diagnostics])
                    from_file.set("newkey", "en", "Nuevo")
                    rendered = render_csv_checked(from_file)
                    write_csv_file(path, from_file, backup=False)
                    self.assertEqual(path.read_bytes(), rendered)
        file, _ = codec.load(CSV[0], VPath.of("localisation/x.csv"))
        file.set("key", "en", "中文")
        with self.assertRaises(UnencodableTextError):
            codec.render(file)

    def test_new_documents_are_cp1252_with_crlf(self):
        clausewitz = ClausewitzCodec().empty(VPath.of("events/new.txt"))
        clausewitz.document.append("a", "1")
        clausewitz.document.append("b", "España")
        self.assertEqual(ClausewitzCodec().render(clausewitz), "a = 1\r\nb = España\r\n".encode("cp1252"))
        csv = LocalisationCodec().empty(VPath.of("localisation/00_X.csv"))
        csv.set("k", "en", "Ñ")
        self.assertEqual(LocalisationCodec().render(csv), ("k;Ñ" + ";" * 13 + "x\r\n").encode("cp1252"))

    def test_json_and_binary(self):
        json_codec = JsonCodec()
        self.assertTrue(json_codec.writable)
        self.assertEqual(json_codec.render(b'{"a": 1}\n'), b'{"a": 1}\n')
        with self.assertRaises(ValueError):
            json_codec.render(b"{roto")
        binary = BinaryCodec()
        self.assertFalse(binary.writable)
        self.assertEqual(binary.load(b"\0\1", VPath.of("gfx/x.dds")), (b"\0\1", []))
        self.assertEqual(binary.snapshot(b"\0\1"), b"\0\1")

    def test_kinds_and_registry(self):
        self.assertEqual(kind_for(VPath.of("common/cb_types.txt")), DocKind.CLAUSEWITZ)
        self.assertEqual(kind_for(VPath.of("localisation/a.csv")), DocKind.LOCALISATION)
        self.assertEqual(kind_for(VPath.of(".vic2studio/project.json")), DocKind.JSON)
        self.assertEqual(kind_for(DESCRIPTOR_REL), DocKind.CLAUSEWITZ)
        self.assertEqual(kind_for(VPath.of("gfx/flags/AAA.tga")), DocKind.IMAGE)
        self.assertIsInstance(codec_for(DocKind.CLAUSEWITZ), ClausewitzCodec)
        self.assertIsInstance(codec_for(DocKind.IMAGE), BinaryCodec, "sin códec propio todavía: binario")
        self.assertIsInstance(codec_for(DocKind.LUA), BinaryCodec)

        class FakeLua(BinaryCodec):
            kind = DocKind.LUA
            writable = True

        original = codecs._CODECS.copy()
        try:
            codecs.register_codec(FakeLua())
            self.assertIsInstance(codec_for(DocKind.LUA), FakeLua)
        finally:
            codecs._CODECS.clear()
            codecs._CODECS.update(original)

    def test_user_mod_sample_round_trips(self):
        for path in sorted((FIXTURE_ROOT / "VSM").rglob("*")):
            if not path.is_file():
                continue
            rel = VPath.of(path.relative_to(FIXTURE_ROOT / "VSM").as_posix())
            codec = codec_for(kind_for(rel))
            with self.subTest(rel=rel):
                data = path.read_bytes()
                model, _ = codec.load(data, rel)
                self.assertEqual(codec.snapshot(model), data)


if __name__ == "__main__":
    unittest.main()
