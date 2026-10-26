"""Pruebas del parser Clausewitz sobre mods reales (ver ``_corpus.py``)."""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import CLAUSEWITZ_SUFFIXES, corpus_files  # noqa: E402
from vic2studio.core.clausewitz import format_canonical, from_json, parse, parse_file, to_json, to_source  # noqa: E402
from vic2studio.core.encoding import BOM, encode_text  # noqa: E402

# Errores genuinos de los archivos (revisados a mano), por sufijo de ruta: [(código, línea)].
EXPECTED_ERRORS = {
    # Diario de desarrollo en prosa ("AHD DD2 - Railroads and Tradegoods") que Paradox dejó en
    # history/units del juego base: no es un archivo Clausewitz. "goods.\n<img>" se lee como
    # "goods. < img" y el ">" de la línea 4 queda sin clave.
    "history/units/v2dd2.txt": [("missing_key", 4)],
    # Juego base completo: textos en prosa que no son scripts (créditos y el marcador de la carpeta mod).
    # Un "!" suelto al final de una frase no es un token válido; "=^.^=" deja un "=" sin clave ni valor.
    "interface/credits.txt": [("invalid_character", 294), ("missing_key", 297), ("missing_value", 297)],
    "mod/dummy.txt": [("invalid_character", 4)],
    # Shago Mod: falta la "}" del bloque political_decisions abierto en la línea 1.
    "decisions/somaliland_shago.txt": [("unclosed_block", 1)],
    "decisions/zulu_expancionshago.txt": [("unclosed_block", 1)],
}
USER_BROKEN_FILES = ("decisions/somaliland_shago.txt", "decisions/zulu_expancionshago.txt")
CORPUS_TIME_LIMIT = 60.0
MEGABYTE_TIME_LIMIT = 2.0


def _expected_for(path):
    posix = path.as_posix()
    for suffix, errors in EXPECTED_ERRORS.items():
        if posix.endswith("/" + suffix):
            return errors
    return None


def _log(message):
    print(f"\n[clausewitz] {message}", file=sys.stderr, flush=True)


class CorpusClausewitzTests(unittest.TestCase):
    """Una sola pasada por el corpus; cada prueba comprueba un aspecto de los resultados."""

    @classmethod
    def setUpClass(cls):
        cls.files = corpus_files(CLAUSEWITZ_SUFFIXES)
        cls.crashes, cls.roundtrip_failures, cls.invariant_failures = [], [], []
        cls.errors, cls.results = {}, {}
        cls.total_bytes = 0
        if not cls.files:
            return
        parse_time = invariant_time = 0.0
        started = time.perf_counter()
        for path in cls.files:
            raw = path.read_bytes()
            cls.total_bytes += len(raw)
            t0 = time.perf_counter()
            try:
                result = parse_file(path)
            except Exception as exc:  # noqa: BLE001 - la prueba registra cualquier fallo
                cls.crashes.append((path, repr(exc)))
                continue
            parse_time += time.perf_counter() - t0
            # Los BOM repetidos no son del texto: write_file los vuelve a poner en su codificación.
            if encode_text(BOM * result.document.extra_boms + to_source(result.document), result.encoding) != raw:
                cls.roundtrip_failures.append(path)
            if result.errors:
                cls.errors[path] = result.errors
            if _expected_for(path) is not None:
                cls.results[path] = result
            t0 = time.perf_counter()
            exported = to_json(result.document)
            if to_json(parse(format_canonical(from_json(exported))).document) != exported:
                cls.invariant_failures.append(path)
            invariant_time += time.perf_counter() - t0
        cls.elapsed = time.perf_counter() - started
        _log(
            f"corpus: {len(cls.files)} archivos, {cls.total_bytes / 1e6:.1f} MB en {cls.elapsed:.2f} s "
            f"(parse_file {parse_time:.2f} s; invariante JSON {invariant_time:.2f} s; "
            f"{cls.total_bytes / 1e6 / max(parse_time, 1e-9):.1f} MB/s)"
        )

    def setUp(self):
        if not self.files:
            self.skipTest("sin corpus disponible (VIC2_CORPUS)")

    def test_a_parse_file_never_raises(self):
        self.assertEqual(self.crashes, [])

    def test_b_to_source_reproduces_original_bytes(self):
        self.assertEqual(self.roundtrip_failures, [])

    def test_c_only_known_errors(self):
        unexpected = {
            str(path): [(d.code, d.line) for d in errors]
            for path, errors in self.errors.items()
            if _expected_for(path) is None
        }
        self.assertEqual(unexpected, {})
        for path in self.files:
            expected = _expected_for(path)
            if expected is not None:
                found = [(d.code, d.line) for d in self.errors.get(path, [])]
                self.assertEqual(found, expected, str(path))

    def test_c_user_broken_files_point_to_line_1(self):
        broken = [p for p in self.results if p.as_posix().endswith(USER_BROKEN_FILES)]
        if not broken:
            self.skipTest("el corpus del usuario no está disponible")
        self.assertEqual(len(broken), 2)
        for path in broken:
            (error,) = self.results[path].errors
            self.assertEqual((error.code, error.line, error.column), ("unclosed_block", 1, 23), str(path))
            self.assertEqual(error.args, {"key": "political_decisions", "open_line": 1})
            self.assertEqual(error.message("es"),
                             "El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}')")
            self.assertEqual(error.message("en"),
                             "Block 'political_decisions' opened on line 1 is never closed (missing '}')")

    def test_d_json_invariant(self):
        self.assertEqual(self.invariant_failures, [])

    def test_e_corpus_time(self):
        self.assertLess(self.elapsed, CORPUS_TIME_LIMIT)


class MegabyteTimingTest(unittest.TestCase):
    def test_e_one_megabyte_file(self):
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        pieces, size = [], 0
        for path in sorted(files, key=lambda p: -p.stat().st_size):
            result = parse_file(path)
            if not result.ok:
                continue
            text = to_source(result.document)
            pieces.append(text)
            size += len(text)
            if size >= 1_000_000:
                break
        if size < 1_000_000:
            block = "".join(f"p{i} = {{\n\towner = GEL\n\tadd_core = RUS # núcleo\n\tcolor = {{ 1 2 3 }}\n}}\n"
                            for i in range(4000))
            pieces = [block] * (1_000_000 // len(block) + 1)
        text = "\n".join(pieces)
        started = time.perf_counter()
        result = parse(text)
        same = to_source(result.document) == text
        elapsed = time.perf_counter() - started
        _log(f"archivo de {len(text) / 1e6:.2f} MB: parse + to_source en {elapsed:.3f} s")
        self.assertTrue(same)
        self.assertTrue(result.ok)
        self.assertLess(elapsed, MEGABYTE_TIME_LIMIT)


if __name__ == "__main__":
    unittest.main()
