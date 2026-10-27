"""Textos del núcleo en JSON (``core.texts``, wizard §4) y los de ``SaveProblem`` (``core/project/texts``)."""

import ast
import json
import string
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core import texts  # noqa: E402
from vic2studio.core.project import model as project_model  # noqa: E402
from vic2studio.core.project import recovery  # noqa: E402
from vic2studio.core.project.model import SaveProblem  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src" / "vic2studio" / "core" / "project"


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def core_undo_labels() -> dict[str, set[str]]:
    """Etiqueta → campos de formato de cada ``transaction(LABEL_..., campo=...)`` de ``core/project``.

    Solo cuentan las etiquetas que son constantes del módulo: las que llegan como argumento (``Project.edit``)
    las pone y las traduce quien llama.
    """
    labels: dict[str, set[str]] = {}
    for path in sorted(PROJECT_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                     for target in node.targets if isinstance(target, ast.Name)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "transaction"
                    and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in constants):
                fields = labels.setdefault(constants[node.args[0].id], set())
                fields.update(keyword.arg for keyword in node.keywords if keyword.arg != "merge_key")
    return labels


class CoreTextsTests(unittest.TestCase):
    def setUp(self):
        texts.clear_cache()
        self.addCleanup(texts.clear_cache)

    def test_es_en_parity_and_same_placeholders(self):
        es, en = texts.load_texts("es"), texts.load_texts("en")
        self.assertTrue(es)
        self.assertEqual(set(es), set(en))
        for key in es:
            with self.subTest(key=key):
                self.assertEqual(_fields(es[key]), _fields(en[key]))
                self.assertNotEqual(es[key].strip(), "")

    def test_every_save_problem_code_and_recovery_note_has_text(self):
        es, en = texts.load_texts("es"), texts.load_texts("en")
        notes = (recovery.NOTE_UNREADABLE, recovery.NOTE_COMPLETED, recovery.NOTE_INCOMPLETE)
        for key in (*(f"project.{code}" for code in project_model.SAVE_CODES), *notes):
            with self.subTest(key=key):
                self.assertIn(key, es)
                self.assertIn(key, en)

    def test_every_undo_label_of_the_core_has_text(self):
        """Los pasos que crea el núcleo salen en el historial y en el botón Deshacer: cada etiqueta necesita texto en
        los dos idiomas, con los mismos huecos que los campos que le pasa."""
        labels = core_undo_labels()
        self.assertEqual(labels, {"undo.revert_file": {"rel"}, "undo.project_settings": set(),
                                  "undo.restore_session": {"session"}})
        es, en = texts.load_texts("es"), texts.load_texts("en")
        for label, fields in labels.items():
            with self.subTest(label=label):
                self.assertEqual(_fields(es[label]), fields)
                self.assertEqual(_fields(en[label]), fields)

    def test_save_problem_message(self):
        problem = SaveProblem(project_model.SAVE_UNENCODABLE, VPath.of("common/a.txt"),
                              {"line": 3, "column": 7, "char": "€", "encoding": "cp1252", "count": 1})
        self.assertIn("common/a.txt", problem.message("es"))
        self.assertIn("línea 3", problem.message("es"))
        self.assertIn("line 3", problem.message("en"))
        self.assertIn("line 3", problem.message("fr"), "idioma desconocido: inglés")

    def test_text_fallbacks(self):
        self.assertEqual(texts.text("no.such.key", "es"), "no.such.key")
        with mock.patch.object(texts, "load_texts", lambda lang: {"es": {}, "en": {"a.b": "B {x}"}}[lang]):
            self.assertEqual(texts.text("a.b", "es", x=1), "B 1", "falta en español: inglés")
            self.assertEqual(texts.text("a.b", "en"), "B {x}", "formato incompleto: la plantilla")

    def test_duplicate_keys_and_bad_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "texts").mkdir(parents=True)
            (root / "b" / "texts").mkdir(parents=True)
            (root / "a" / "texts" / "x.es.json").write_text(json.dumps({"k.one": "1"}), encoding="utf-8")
            (root / "b" / "texts" / "y.es.json").write_text(json.dumps({"k.one": "2"}), encoding="utf-8")
            with mock.patch.object(texts, "CORE_ROOT", root):
                self.assertEqual(len(texts.text_files("es")), 2)
                with self.assertRaises(ValueError):
                    texts.load_texts("es")
                texts.clear_cache()
                (root / "b" / "texts" / "y.es.json").write_text("{", encoding="utf-8")
                with self.assertRaises(ValueError):
                    texts.load_texts("es")
                texts.clear_cache()
                (root / "b" / "texts" / "y.es.json").write_text(json.dumps({"k.two": 2}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    texts.load_texts("es")


if __name__ == "__main__":
    unittest.main()
