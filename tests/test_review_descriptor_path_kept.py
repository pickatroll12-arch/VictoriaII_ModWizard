"""Regresión (ronda 2): cambiar otro campo del formulario no reescribe un ``path`` con ``\\`` que ya nombra la
misma carpeta (I3: lo que no se edita se conserva)."""
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

from vic2studio.core.clausewitz import parse, to_source  # noqa: E402
from vic2studio.core.modfile import DescriptorSpec, apply_descriptor, descriptor_from_result  # noqa: E402
from vic2studio.core.modfile import render_descriptor  # noqa: E402

SRC = 'name = "Old"\r\npath = "mod\\OLD" # con barra invertida\r\nuser_dir = "OLD"\r\n'


class BackslashPathTests(unittest.TestCase):
    def spec(self):
        result = parse(SRC)
        return result, DescriptorSpec.from_descriptor(descriptor_from_result("OLD.mod", result))

    def test_renaming_keeps_the_path_line(self):
        result, spec = self.spec()
        renamed = DescriptorSpec("New", spec.folder, spec.user_dir, spec.replace_paths, spec.dependencies)
        self.assertTrue(apply_descriptor(result.document, renamed))
        self.assertEqual(to_source(result.document), SRC.replace('"Old"', '"New"'))

    def test_render_keeps_it_too(self):
        result, spec = self.spec()
        renamed = DescriptorSpec("New", spec.folder, spec.user_dir, spec.replace_paths, spec.dependencies)
        self.assertEqual(render_descriptor(renamed, result), SRC.replace('"Old"', '"New"').encode("cp1252"))

    def test_another_folder_still_changes_it(self):
        result, spec = self.spec()
        moved = DescriptorSpec(spec.name, "NEW", spec.user_dir, spec.replace_paths, spec.dependencies)
        self.assertTrue(apply_descriptor(result.document, moved))
        self.assertIn('path = "mod/NEW"', to_source(result.document))


if __name__ == "__main__":
    unittest.main()
