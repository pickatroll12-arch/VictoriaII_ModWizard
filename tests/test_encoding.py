import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import corpus_files  # noqa: E402
from vic2studio.core.encoding import (  # noqa: E402
    GAME_ENCODING,
    UnencodableTextError,
    decode_bytes,
    detect_newline,
    encode_text,
    find_unencodable,
)
from vic2studio.core.fileio import atomic_write_bytes, read_text, write_text  # noqa: E402


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


class FileIoTests(unittest.TestCase):
    def test_atomic_write_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "file.txt"
            self.assertIsNone(atomic_write_bytes(target, b"one"))
            backup = write_text(target, "dos ñ", GAME_ENCODING, backup=True)
            self.assertEqual(backup.read_bytes(), b"one")
            self.assertEqual(target.read_bytes(), "dos ñ".encode("cp1252"))
            self.assertEqual(read_text(target).text, "dos ñ")
            self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["file.txt", "file.txt.bak"])


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
