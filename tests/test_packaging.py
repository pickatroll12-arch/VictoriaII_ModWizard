"""Empaquetado: el ejecutable de PyInstaller lleva todos los datos que necesita el programa.

El ``.spec`` copia los datos con sus propios patrones (``DATA_PATTERNS``) y ``pyproject.toml`` los declara en
``[tool.setuptools.package-data]``. Desde la iteración 2 había fragmentos ``i18n/<idioma>/*.json`` y textos del
núcleo ``core/**/texts/*.json`` que el ``.spec`` no copiaba: el ejecutable habría enseñado claves crudas. Aquí se
comprueba que los dos dicen lo mismo, que esos patrones cubren todos los archivos del paquete que no son Python y
que la comprobación de humo (``app.SMOKE_KEYS``) mira una clave de cada archivo de textos.
"""

import ast
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "vic2studio"
sys.path.insert(0, str(ROOT / "src"))


def spec_patterns() -> tuple[str, ...]:
    tree = ast.parse((ROOT / "packaging" / "vic2studio.spec").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DATA_PATTERNS" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("el .spec no define DATA_PATTERNS")


def pyproject_patterns() -> tuple[str, ...]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^\[tool\.setuptools\.package-data\]\s*\nvic2studio\s*=\s*\[(.*?)\]", text, re.M | re.S)
    if block is None:
        raise AssertionError("pyproject.toml no tiene [tool.setuptools.package-data]")
    return tuple(re.findall(r'"([^"]+)"', block.group(1)))


def data_files() -> list[Path]:
    """Los archivos del paquete que no son código: los que el ejecutable tiene que llevar."""
    return [p for p in PKG.rglob("*") if p.is_file() and p.suffix not in (".py", ".pyc")
            and "__pycache__" not in p.parts]


class PackagingDataTests(unittest.TestCase):
    def test_the_spec_copies_what_pyproject_declares(self):
        self.assertEqual(sorted(spec_patterns()), sorted(pyproject_patterns()))

    def test_every_data_file_is_covered(self):
        patterns = spec_patterns()
        files = data_files()
        self.assertTrue(any(p.match("*/i18n/es/*.json") for p in files), "hay fragmentos de i18n")
        self.assertTrue(any("texts" in p.parts for p in files), "hay textos del núcleo")
        missing = [str(p.relative_to(PKG)) for p in files
                   if not any(p in PKG.glob(pattern) for pattern in patterns)]
        self.assertEqual(missing, [], "archivos que el ejecutable no llevaría")

    def test_the_smoke_test_checks_one_key_of_each_text_file(self):
        """Cada archivo de textos en español tiene una clave en SMOKE_KEYS: si el ejecutable no lo lleva, falla."""
        import ast as _ast

        source = (PKG / "app.py").read_text(encoding="utf-8")
        keys = None
        for node in _ast.parse(source).body:
            if isinstance(node, _ast.Assign) and any(getattr(t, "id", None) == "SMOKE_KEYS" for t in node.targets):
                keys = set(_ast.literal_eval(node.value))
        self.assertIsNotNone(keys, "app.py define SMOKE_KEYS")
        catalogues = [PKG / "i18n" / "es.json", *sorted((PKG / "i18n" / "es").glob("*.json")),
                      *sorted(PKG.glob("core/**/texts/*.es.json"))]
        for path in catalogues:
            with self.subTest(file=str(path.relative_to(PKG))):
                self.assertTrue(keys & set(json.loads(path.read_text(encoding="utf-8"))),
                                "ninguna clave de SMOKE_KEYS es de este archivo")

    def test_the_smoke_keys_exist_in_both_languages(self):
        import _qt  # noqa: F401  (entorno Qt aislado: i18n importa QtCore)
        from vic2studio.app import smoke_problems

        self.assertEqual(smoke_problems(), [])


class FrozenEntryTests(unittest.TestCase):
    def test_the_entry_point_calls_freeze_support_before_loading_the_app(self):
        """El trabajador del taller de mapas usa «spawn»: congelado, sin freeze_support abriría otra ventana."""
        tree = ast.parse((PKG / "__main__.py").read_text(encoding="utf-8"))
        guard = next(n for n in tree.body if isinstance(n, ast.If))
        calls = [ast.unparse(n) for n in guard.body]
        self.assertEqual(calls[0], "multiprocessing.freeze_support()")
        self.assertTrue(any("vic2studio.app" in c for c in calls[1:]), calls)
        self.assertFalse([n for n in tree.body if isinstance(n, ast.ImportFrom) and "app" in (n.module or "")],
                         "la aplicación no se importa fuera de la guarda")


if __name__ == "__main__":
    unittest.main()
