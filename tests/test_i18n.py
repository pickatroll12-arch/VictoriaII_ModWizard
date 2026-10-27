import ast
import json
import re
import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402,F401  (entorno offscreen y preferencias aisladas)
from vic2studio import i18n  # noqa: E402
from vic2studio.i18n import (  # noqa: E402
    LANGUAGES,
    SETTINGS_KEY,
    Translator,
    available_languages,
    catalog_path,
    language,
    load_catalog,
    set_language,
    system_language,
    tr,
    translator,
)
from vic2studio.settings import app_settings  # noqa: E402

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "vic2studio"
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
# Funciones cuyo primer argumento es una clave de catálogo.
KEY_FUNCTIONS = {"tr", "N_", "request_status", "show_status"}


def _key_candidates(node: ast.AST) -> list[str]:
    """Cadenas literales que pueden acabar como clave: literales, ramas de ``a if c else b``
    y valores por defecto literales de llamadas como ``dict.get(x, "clave")``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _key_candidates(node.body) + _key_candidates(node.orelse)
    if isinstance(node, ast.Call):
        return [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return []


def used_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in KEY_FUNCTIONS:
                for key in _key_candidates(node.args[0]):
                    keys.setdefault(key, f"{path.relative_to(PACKAGE)}:{node.lineno}")
    return keys


def placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {code: load_catalog(code) for code, _ in LANGUAGES}

    def test_files_are_utf8_json_without_bom(self):
        for code, _ in LANGUAGES:
            raw = catalog_path(code).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), code)
            self.assertIsInstance(json.loads(raw.decode("utf-8")), dict)

    def test_same_keys_in_every_language(self):
        es, en = self.catalogs["es"], self.catalogs["en"]
        self.assertEqual(sorted(set(es) - set(en)), [], "claves solo en es.json")
        self.assertEqual(sorted(set(en) - set(es)), [], "claves solo en en.json")

    def test_no_empty_values_and_valid_keys(self):
        for code, catalog in self.catalogs.items():
            for key, value in catalog.items():
                self.assertRegex(key, KEY_PATTERN)
                self.assertTrue(value.strip(), f"{code}:{key} vacío")
                self.assertEqual(value, value.strip(), f"{code}:{key} con espacios sobrantes")

    def test_placeholders_match_and_format(self):
        es, en = self.catalogs["es"], self.catalogs["en"]
        for key in es:
            self.assertEqual(placeholders(es[key]), placeholders(en[key]), key)
            dummy = {name: "x" for name in placeholders(es[key])}
            es[key].format(**dummy)
            en[key].format(**dummy)

    def test_most_texts_are_really_translated(self):
        es, en = self.catalogs["es"], self.catalogs["en"]
        identical = [k for k in es if es[k] == en[k]]
        self.assertLess(len(identical), len(es) * 0.1, identical)

    def test_every_key_used_in_code_exists(self):
        catalog = self.catalogs["es"]
        missing = {k: where for k, where in used_keys().items() if k not in catalog}
        self.assertEqual(missing, {}, "claves usadas en el código sin traducción")

    def test_every_catalog_key_is_used(self):
        used = used_keys()
        self.assertGreater(len(used), 100)
        # Los textos del núcleo (core/**/texts) se buscan por código de mensaje o de esquema, no con tr()/N_()
        # literales: se comprueban en las pruebas del núcleo, no aquí.
        core = set(i18n.core_catalog("es"))
        unused = sorted(k for k in self.catalogs["es"] if k not in used and k not in core)
        self.assertEqual(unused, [], "claves del catálogo que ningún tr()/N_() usa")


class TranslatorTests(unittest.TestCase):
    def setUp(self):
        self.original = language()

    def tearDown(self):
        set_language(self.original)
        self.assertEqual(_qt.take_qt_messages(), [])

    def test_available_languages(self):
        self.assertEqual(available_languages(), [("es", "Español"), ("en", "English")])

    def test_tr_translates_and_formats(self):
        set_language("es")
        self.assertEqual(tr("nav.map"), "Editor de Mapa")
        self.assertEqual(tr("status.page", name="X"), "Módulo activo: X")
        set_language("en")
        self.assertEqual(tr("nav.map"), "Map Editor")
        self.assertEqual(tr("status.version", version="9"), "Version 9")

    def test_unknown_key_returns_key_and_warns_once(self):
        with self.assertLogs("vic2studio.i18n", "WARNING") as logs:
            self.assertEqual(tr("no.such.key"), "no.such.key")
            self.assertEqual(tr("no.such.key"), "no.such.key")
            tr("another.missing.key")
        self.assertEqual(len(logs.records), 2)
        self.assertIn("no.such.key", translator().missing_keys())

    def test_bad_format_arguments_do_not_raise(self):
        with self.assertLogs("vic2studio.i18n", "WARNING"):
            self.assertEqual(tr("status.page", wrong="x"), translator().catalog()["status.page"])

    def test_set_language_emits_signal_and_persists(self):
        received = []
        translator().languageChanged.connect(received.append)
        try:
            set_language("es")
            received.clear()
            set_language("en")
            set_language("en")  # mismo idioma: sin señal
            self.assertEqual(received, ["en"])
            self.assertEqual(language(), "en")
            self.assertEqual(app_settings().value(SETTINGS_KEY), "en")
            set_language("es")
            self.assertEqual(received, ["en", "es"])
            self.assertEqual(app_settings().value(SETTINGS_KEY), "es")
        finally:
            translator().languageChanged.disconnect(received.append)

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(ValueError):
            set_language("fr")

    def test_registered_catalog_is_not_persisted(self):
        set_language("es")
        translator().register_catalog("zz", {"nav.map": "ZZ"})
        set_language("zz")
        self.assertEqual(tr("nav.map"), "ZZ")
        self.assertEqual(app_settings().value(SETTINGS_KEY), "es")

    def test_system_language_mapping(self):
        self.assertEqual(system_language("es_ES"), "es")
        self.assertEqual(system_language("es_CL"), "es")
        self.assertEqual(system_language("es"), "es")
        self.assertEqual(system_language("en_US"), "en")
        self.assertEqual(system_language("fr_FR"), "en")
        self.assertEqual(system_language("C"), "en")

    def test_initial_language_comes_from_settings_or_system(self):
        settings = app_settings()
        saved = settings.value(SETTINGS_KEY)
        try:
            settings.setValue(SETTINGS_KEY, "en")
            self.assertEqual(Translator().language(), "en")
            settings.setValue(SETTINGS_KEY, "es")
            self.assertEqual(Translator().language(), "es")
            settings.remove(SETTINGS_KEY)
            self.assertEqual(Translator().language(), system_language())
            settings.setValue(SETTINGS_KEY, "xx")
            self.assertEqual(Translator().language(), system_language())
        finally:
            if saved is None:
                settings.remove(SETTINGS_KEY)
            else:
                settings.setValue(SETTINGS_KEY, saved)

    def test_module_singleton(self):
        self.assertIs(translator(), i18n.translator())


if __name__ == "__main__":
    unittest.main()
