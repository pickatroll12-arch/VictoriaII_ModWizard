import codecs
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import corpus_files  # noqa: E402
from vic2studio.core.encoding import (  # noqa: E402
    BOM,
    BOM_ENCODINGS,
    GAME_ENCODING,
    GAME_UNREADABLE,
    STRAY_BOM,
    UTF8,
    UTF8_BOM,
    UTF16,
    UTF16_BE,
    UTF16_BE_BOM,
    UTF16_LE,
    DecodedText,
    UnencodableTextError,
    decode_bytes,
    detect_newline,
    display_name,
    encode_text,
    find_unencodable,
    has_stray_bom,
    match_bom,
    normalize_encoding,
    split_bom,
    split_extra_boms,
)
from vic2studio.core.fileio import (  # noqa: E402
    FileChangedError,
    FileStamp,
    atomic_write_bytes,
    file_stamp,
    read_text,
    write_text,
)

UTF16_TEXT = "political_decisions = {\r\n\tunite = { tag = GEL }\r\n}\r\n# Le\u00f3n\r\n"


class EncodingTests(unittest.TestCase):
    def test_ascii_is_game_encoding(self):
        self.assertEqual(decode_bytes(b"owner = GEL\n").encoding, GAME_ENCODING)

    def test_cp1252_accents(self):
        decoded = decode_bytes("País pequeño".encode("cp1252"))
        self.assertEqual(decoded.encoding, GAME_ENCODING)
        self.assertEqual(decoded.text, "País pequeño")

    def test_undefined_cp1252_bytes_round_trip(self):
        raw = bytes([0x41, 0x81, 0x8D, 0x8F, 0x90, 0x9D, 0xE9])
        decoded = decode_bytes(raw)
        self.assertEqual(encode_text(decoded.text, decoded.encoding), raw)

    def test_utf8_detection(self):
        self.assertEqual(decode_bytes("España".encode("utf-8")).encoding, "utf-8")
        bom = decode_bytes(b"\xef\xbb\xbfkey = 1")
        self.assertEqual((bom.encoding, bom.text), ("utf-8-sig", "key = 1"))
        self.assertEqual(encode_text(bom.text, bom.encoding), b"\xef\xbb\xbfkey = 1")

    def test_unencodable_reports_position(self):
        text = "a = b\nname = 中"
        self.assertEqual(find_unencodable(text), [(13, 2, 8, "中")])
        with self.assertRaises(UnencodableTextError) as ctx:
            encode_text(text)
        self.assertEqual(ctx.exception.problems[0][1:3], (2, 8))

    def test_newline_detection(self):
        self.assertEqual(detect_newline("a\r\nb\r\nc\n"), "\r\n")
        self.assertEqual(detect_newline("a\nb\n"), "\n")
        self.assertEqual(detect_newline(""), "\n")

    def test_display_names(self):
        """Un solo mapa de nombres para el visor, los diagnósticos del parser y el lint del CSV: con el orden de
        bytes y el BOM explícitos, y aceptando alias (antes el parser mostraba «UTF-16-BE-BOM»)."""
        expected = {GAME_ENCODING: "Windows-1252", UTF8: "UTF-8", UTF8_BOM: "UTF-8 BOM", UTF16: "UTF-16 LE BOM",
                    UTF16_BE_BOM: "UTF-16 BE BOM", UTF16_LE: "UTF-16 LE", UTF16_BE: "UTF-16 BE"}
        for encoding, name in expected.items():
            self.assertEqual(display_name(encoding), name, encoding)
        for alias, name in (("windows-1252", "Windows-1252"), ("UTF-16-BE-BOM", "UTF-16 BE BOM"),
                            ("utf_8_sig", "UTF-8 BOM"), ("UTF16", "UTF-16 LE BOM")):
            self.assertEqual(display_name(alias), name, alias)
        self.assertEqual(display_name("latin-1"), "LATIN-1")      # sin nombre propio: en mayúsculas
        self.assertEqual(display_name("no-existe"), "NO-EXISTE")

    def test_cr_only_newlines(self):
        """H2-CR: los archivos vanilla solo con CR (map/region_sea.txt) daban "\\n"."""
        self.assertEqual(detect_newline("a = 1\rb = 2\r"), "\r")
        self.assertEqual(detect_newline("a\rb\rc\r\nd\r"), "\r")
        self.assertEqual(detect_newline("a\r\nb\r\nc\r"), "\r\n")
        # En el CSV del juego un CR suelto es contenido, no un salto.
        self.assertEqual(detect_newline("K;a\rb;c\r\nL;d\r", lone_cr=False), "\r\n")
        self.assertEqual(detect_newline("A;1\rB;2\rC;3\n", lone_cr=False), "\n")

    def test_bom_followed_by_cp1252_never_fails(self):
        """P2: un BOM UTF-8 delante de texto cp1252 lanzaba UnicodeDecodeError (y la app no arrancaba)."""
        raw = b'\xef\xbb\xbfname = "Le\xf3n"\r\nowner = GEL\r\n'
        decoded = decode_bytes(raw)
        self.assertEqual(decoded.encoding, GAME_ENCODING)
        self.assertEqual(decoded.text, STRAY_BOM + 'name = "León"\r\nowner = GEL\r\n')
        self.assertTrue(has_stray_bom(decoded.text, decoded.encoding))
        self.assertEqual(encode_text(decoded.text, decoded.encoding), raw)
        self.assertFalse(has_stray_bom(decode_bytes(b"\xef\xbb\xbfa").text, "utf-8-sig"))
        # Un UTF-8 con BOM cortado a mitad de carácter tampoco falla, y sigue siendo exacto.
        truncated = "\ufeffname = \"León\"".encode("utf-8")[:14]
        decoded = decode_bytes(truncated)
        self.assertEqual(encode_text(decoded.text, decoded.encoding), truncated)

    def test_partial_reads_keep_the_detection(self):
        """P2: una vista previa cortada a mitad de un carácter UTF-8 cambiaba de codificación o fallaba."""
        for raw in ("\ufeffname = \"León\"".encode("utf-8")[:14], "Año = León".encode("utf-8")[:-1]):
            with self.subTest(raw=raw):
                decoded = decode_bytes(raw, partial=True)
                self.assertIn(decoded.encoding, ("utf-8", "utf-8-sig"))
                self.assertEqual(decoded.text, raw.decode("utf-8-sig", "ignore"))
        self.assertEqual(decode_bytes("ab".encode("utf-16")[:-1], partial=True), decode_bytes(b"\xff\xfea\x00"))
        # Si lo único no ASCII es el final cortado, no hay pruebas de UTF-8: puede ser un "é" cp1252.
        for raw in (b"caf\xe9", "name = León".encode("utf-8")[:10]):
            with self.subTest(raw=raw):
                self.assertEqual(decode_bytes(raw, partial=True).encoding, GAME_ENCODING)

    def test_utf16_is_detected(self):
        """P3/LOC-M3: un archivo UTF-16 se leía como cp1252 (claves con NUL) sin ningún aviso."""
        samples = {
            UTF16: UTF16_TEXT.encode("utf-16-le"),
            UTF16_BE_BOM: codecs.BOM_UTF16_BE + UTF16_TEXT.encode("utf-16-be"),
        }
        samples[UTF16] = codecs.BOM_UTF16_LE + samples[UTF16]
        for expected, raw in samples.items():
            with self.subTest(expected=expected):
                decoded = decode_bytes(raw)
                self.assertEqual(decoded.encoding, expected)
                self.assertEqual(decoded.text, UTF16_TEXT)
                self.assertIn(decoded.encoding, GAME_UNREADABLE)
                self.assertEqual(encode_text(decoded.text, decoded.encoding), raw)
        # Sin BOM, por los NUL alternos.
        for name in (UTF16_LE, UTF16_BE):
            with self.subTest(name=name):
                raw = UTF16_TEXT.encode(name)
                self.assertEqual(decode_bytes(raw), decode_bytes(raw, name))
                self.assertEqual(decode_bytes(raw).text, UTF16_TEXT)
        # Unos pocos NUL en un archivo cp1252 no lo convierten en UTF-16.
        self.assertEqual(decode_bytes(b"a = b\x00\r\nc = d\r\n").encoding, GAME_ENCODING)

    def test_no_bom_stays_in_the_text(self):
        """NF-1: con el BOM FE FF el U+FEFF quedaba en el texto: la primera clave de un CSV era
        '\\ufeffKEY' y convertir a cp1252 fallaba. Ahora es como el BOM UTF-8 y el FF FE."""
        text = "KEY;Le\u00f3n\r\n"
        samples = {
            UTF8_BOM: codecs.BOM_UTF8 + text.encode("utf-8"),
            UTF16: codecs.BOM_UTF16_LE + text.encode("utf-16-le"),
            UTF16_BE_BOM: codecs.BOM_UTF16_BE + text.encode("utf-16-be"),
        }
        for name, raw in samples.items():
            with self.subTest(name=name):
                self.assertEqual(decode_bytes(raw), DecodedText(text, name))
                self.assertEqual(encode_text(text, name), raw, "sin cambiar de codificación, los mismos bytes")
                self.assertEqual(encode_text(text, GAME_ENCODING), text.encode("cp1252"))
                # Una vista previa cortada a mitad de carácter tampoco deja el BOM.
                self.assertEqual(decode_bytes(raw[:-1], partial=True), DecodedText(text[:-1], name))
        self.assertEqual(GAME_UNREADABLE, {UTF16, UTF16_LE, UTF16_BE, UTF16_BE_BOM})

    def test_utf16_be_bom_is_a_real_codec(self):
        """NF-1: utf-16-be-bom sirve donde sirve cualquier nombre de codec (str.encode, open, codecs)."""
        text = "KEY;Le\u00f3n\r\n" * 3
        raw = codecs.BOM_UTF16_BE + text.encode("utf-16-be")
        for alias in ("utf-16-be-bom", "UTF-16-BE-BOM", "utf_16_be_bom"):
            self.assertEqual(normalize_encoding(alias), UTF16_BE_BOM)
        self.assertEqual(text.encode(UTF16_BE_BOM), raw)
        self.assertEqual(raw.decode(UTF16_BE_BOM), text)
        self.assertEqual(raw[2:].decode(UTF16_BE_BOM), text, "sin BOM lee big-endian")
        self.assertEqual(decode_bytes(raw, UTF16_BE_BOM), DecodedText(text, UTF16_BE_BOM))
        self.assertEqual(decode_bytes(raw[:-1], UTF16_BE_BOM, partial=True).text, text[:-1])
        decoder = codecs.getincrementaldecoder(UTF16_BE_BOM)()
        pieces = [decoder.decode(raw[i:i + 1]) for i in range(len(raw))]
        self.assertEqual("".join(pieces) + decoder.decode(b"", final=True), text)
        encoder = codecs.getincrementalencoder(UTF16_BE_BOM)()
        self.assertEqual(b"".join(encoder.encode(char) for char in text), raw)
        # getstate/setstate (los usa TextIOWrapper en tell/seek) recuerdan si falta el BOM.
        for cut in (0, 1, 2):
            with self.subTest(cut=cut):
                decoder = codecs.getincrementaldecoder(UTF16_BE_BOM)()
                self.assertEqual(decoder.decode(raw[:cut]), "")
                restored = codecs.getincrementaldecoder(UTF16_BE_BOM)()
                restored.decode(raw, final=True)  # ya sin BOM pendiente: setstate debe devolvérselo
                restored.setstate(decoder.getstate())
                self.assertEqual(restored.decode(raw[cut:], final=True), text)
        encoder = codecs.getincrementalencoder(UTF16_BE_BOM)()
        state = encoder.getstate()
        encoder.encode(text)
        encoder.setstate(state)
        self.assertEqual(encoder.encode(text), raw)
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding=UTF16_BE_BOM, newline="")
        stream.write(text[:5])
        stream.write(text[5:])
        stream.flush()
        self.assertEqual(buffer.getvalue(), raw, "el BOM, una sola vez")
        self.assertEqual(io.TextIOWrapper(io.BytesIO(raw), encoding=UTF16_BE_BOM, newline="").read(), text)
        buffer = io.BytesIO()
        writer = codecs.getwriter(UTF16_BE_BOM)(buffer)
        writer.write(text[:5])
        writer.write(text[5:])
        self.assertEqual(buffer.getvalue(), raw)
        self.assertEqual(codecs.getreader(UTF16_BE_BOM)(io.BytesIO(raw)).read(), text)

    def test_split_bom(self):
        """NF-1: el U+FEFF que deja un codec sin BOM pasa a la codificación sin cambiar los bytes."""
        for name, with_bom in ((UTF8, UTF8_BOM), (UTF16_LE, UTF16), (UTF16_BE, UTF16_BE_BOM)):
            with self.subTest(name=name):
                text = BOM + "K;Le\u00f3n\r\n"
                self.assertEqual(split_bom(text, name.upper()), (text[1:], with_bom))
                self.assertEqual(encode_text(text[1:], with_bom), encode_text(text, name))
                self.assertEqual(split_bom("K", name), ("K", name))
        # Tras un codec que ya quita su BOM, un U+FEFF inicial es un BOM repetido (split_extra_boms).
        for name in (UTF8_BOM, UTF16, UTF16_BE_BOM, GAME_ENCODING):
            with self.subTest(name=name):
                self.assertEqual(split_bom(BOM + "K", name), (BOM + "K", name))

    def test_split_extra_boms(self):
        """R1: los U+FEFF de un BOM repetido se separan del texto y se vuelven a escribir con los mismos bytes."""
        self.assertEqual(BOM_ENCODINGS, {UTF8_BOM, UTF16, UTF16_BE_BOM})
        boms = {UTF8_BOM: codecs.BOM_UTF8, UTF16: codecs.BOM_UTF16_LE, UTF16_BE_BOM: codecs.BOM_UTF16_BE}
        body = "K;Le\u00f3n\r\n"
        for name, bom in boms.items():
            for count in (1, 2, 3):
                with self.subTest(name=name, count=count):
                    raw = bom * count + encode_text(body, name)[len(bom):]
                    decoded = decode_bytes(raw)
                    self.assertEqual(decoded.encoding, name)
                    self.assertEqual(split_extra_boms(decoded.text, name.upper()), (body, count - 1))
                    self.assertEqual(encode_text(BOM * (count - 1) + body, name), raw)
        # Sin BOM propio (o donde ``split_bom`` aún no lo ha pasado a la codificación) es contenido.
        for name in (GAME_ENCODING, UTF8, UTF16_LE, UTF16_BE, "latin-1"):
            with self.subTest(name=name):
                self.assertEqual(split_extra_boms(BOM + body, name), (BOM + body, 0))
        self.assertEqual(split_extra_boms(body + BOM, UTF8_BOM), (body + BOM, 0), "solo al principio")

    def test_match_bom(self):
        """NF-6: un codec explícito que quita el BOM no dice si lo había ni en qué orden de bytes; el
        nombre que devuelve match_bom vuelve a escribir los mismos bytes que se leyeron."""
        body = "K = Le\u00f3n\r\n"
        cases = [
            (codecs.BOM_UTF8 + body.encode("utf-8"), "UTF-8-SIG", UTF8_BOM),
            (body.encode("utf-8"), "utf-8-sig", UTF8),
            (codecs.BOM_UTF16_LE + body.encode("utf-16-le"), "utf-16", UTF16),
            (codecs.BOM_UTF16_BE + body.encode("utf-16-be"), "utf-16", UTF16_BE_BOM),
            (body.encode("utf-16-le" if sys.byteorder == "little" else "utf-16-be"), "UTF16",
             UTF16_LE if sys.byteorder == "little" else UTF16_BE),
            (codecs.BOM_UTF16_BE + body.encode("utf-16-be"), "utf-16-be-bom", UTF16_BE_BOM),
            (body.encode("utf-16-be"), "utf-16-be-bom", UTF16_BE),
        ]
        for raw, explicit, expected in cases:
            with self.subTest(raw=raw[:4], explicit=explicit):
                decoded = decode_bytes(raw, explicit)
                self.assertEqual(decoded.text, body)
                self.assertEqual(match_bom(raw, explicit), expected)
                self.assertEqual(encode_text(decoded.text, expected), raw)
        # Las que dejan el BOM en el texto (las arregla split_bom) y las demás no cambian.
        for name in (UTF8, UTF16_LE, UTF16_BE, GAME_ENCODING):
            with self.subTest(name=name):
                self.assertEqual(match_bom(codecs.BOM_UTF8 + b"K", name.upper()), name)
        self.assertEqual(match_bom(b"K", "latin-1"), "iso8859-1")

    def test_only_text_encodings(self):
        """FC-5: base64 o rot13 pasaban la validación y fallaban después al escribir."""
        self.assertEqual(normalize_encoding("UTF16"), UTF16)
        self.assertEqual(normalize_encoding("latin-1"), "iso8859-1")
        for name in ("base64", "rot13", "no-such-codec"):
            with self.subTest(name=name):
                with self.assertRaises(LookupError):
                    normalize_encoding(name)
                with self.assertRaises(LookupError):
                    encode_text("a", name)


class FileIoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_atomic_write_and_backup(self):
        target = self.dir / "sub" / "file.txt"
        self.assertIsNone(atomic_write_bytes(target, b"one"))
        backup = write_text(target, "dos ñ", GAME_ENCODING, backup=True)
        self.assertEqual(backup.read_bytes(), b"one")
        self.assertEqual(target.read_bytes(), "dos ñ".encode("cp1252"))
        self.assertEqual(read_text(target).text, "dos ñ")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["file.txt", "file.txt.bak"])

    @unittest.skipUnless(os.name == "posix", "permisos POSIX")
    def test_new_files_get_default_permissions(self):
        """FC-4: los archivos nuevos quedaban en 0o600 (los de tempfile.mkstemp)."""
        umask = os.umask(0o022)
        os.umask(umask)
        new = self.dir / "events" / "nuevo.txt"
        write_text(new, "a = b\n", GAME_ENCODING)
        self.assertEqual(new.stat().st_mode & 0o777, 0o666 & ~umask)
        existing = self.dir / "privado.txt"
        existing.write_bytes(b"x")
        existing.chmod(0o640)
        atomic_write_bytes(existing, b"y")
        self.assertEqual(existing.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["events", "privado.txt"])

    def test_external_changes_are_not_overwritten(self):
        """FC-13: guardar pisaba sin aviso lo cambiado fuera de la aplicación desde que se leyó."""
        target = self.dir / "loc.csv"
        target.write_bytes(b"A;uno\r\n")
        read = read_text(target)
        self.assertEqual(read.stamp, FileStamp.of(b"A;uno\r\n"))
        self.assertEqual(file_stamp(target), read.stamp)
        target.write_bytes(b"A;uno\r\nB;de Excel\r\n")
        with self.assertRaises(FileChangedError) as ctx:
            write_text(target, "A;Uno\r\n", GAME_ENCODING, backup=True, expected=read.stamp)
        self.assertEqual(target.read_bytes(), b"A;uno\r\nB;de Excel\r\n")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["loc.csv"], "ni .bak ni temporales")
        self.assertIsInstance(ctx.exception, OSError)
        self.assertIn("loc.csv", ctx.exception.message("es"))
        self.assertIn("changed outside", ctx.exception.message("en"))
        self.assertEqual(str(ctx.exception), ctx.exception.message("es"))
        # Con la huella al día (o sin huella) se escribe; un archivo borrado también cuenta como cambio.
        write_text(target, "A;Uno\r\n", GAME_ENCODING, expected=file_stamp(target))
        self.assertEqual(target.read_bytes(), b"A;Uno\r\n")
        target.unlink()
        self.assertIsNone(file_stamp(target))
        with self.assertRaises(FileChangedError):
            atomic_write_bytes(target, b"x", expected=FileStamp.of(b"A;Uno\r\n"))


class CorpusEncodingTests(unittest.TestCase):
    def test_every_text_file_round_trips(self):
        files = corpus_files({".txt", ".csv", ".mod", ".lua", ".bak"})
        if not files:
            self.skipTest("sin corpus disponible")
        for path in files:
            raw = path.read_bytes()
            decoded = decode_bytes(raw)
            self.assertEqual(encode_text(decoded.text, decoded.encoding), raw, str(path))


if __name__ == "__main__":
    unittest.main()
