"""Avisos de terceros (wizard §18.13, iteración 9a): cada módulo portado de Azgaar's Fantasy Map Generator lleva su
cabecera y ``THIRD_PARTY_NOTICES.md`` el texto MIT íntegro, con la cláusula de obras derivadas."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORGE = ROOT / "src" / "vic2studio" / "core" / "mapforge"
HEADER = "# Port of Azgaar's Fantasy Map Generator "

# Módulos con código o datos portados de FMG.
PORTED = ("graph.py", "relief.py", "data/templates.py", "climate.py", "hydro.py", "biomes.py", "society.py",
          "names.py")


class NoticeTests(unittest.TestCase):
    def test_each_ported_module_has_its_header(self):
        for rel in PORTED:
            with self.subTest(module=rel):
                first, second = (FORGE / rel).read_text(encoding="utf-8").splitlines()[:2]
                self.assertTrue(first.startswith(HEADER), first)
                self.assertIn("(MIT", first)
                self.assertIn("Max Haniyeu", first + second)   # la cabecera larga sigue en la segunda línea

    def test_no_other_module_claims_to_be_a_port(self):
        claimed = {p.relative_to(FORGE).as_posix() for p in FORGE.rglob("*.py")
                   if p.read_text(encoding="utf-8").startswith(HEADER)}
        self.assertEqual(claimed, set(PORTED))

    def test_the_notice_has_the_whole_mit_text(self):
        text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for line in ("MIT License", "Copyright 2017-2024 Max Haniyeu (Azgaar)",
                     "The above copyright notice and this permission notice shall be included in all",
                     "You can produce, without restrictions, any derivative works from the original",
                     'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR'):
            self.assertIn(line, text)
        for rel in PORTED:
            self.assertIn(f"`{rel}`", text)


if __name__ == "__main__":
    unittest.main()
