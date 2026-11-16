"""Fronteras del mapa (``core.map.borders``): la LUT de grupos de un mapa anterior no rompe el dibujo.

Tras exportar el taller de mapas, el ráster nuevo llega antes que los hechos recalculados; el lienzo pedía la
frontera de estado con la LUT vieja y lanzaba ``IndexError`` (encontrado en las capturas de la iteración 9b)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.map.borders import border_mask  # noqa: E402


class BorderMaskTests(unittest.TestCase):
    def test_groups_merge_borders(self):
        ids = np.array([[1, 1, 2, 2, 3, 3]])
        mask = border_mask(ids, np.array([0, 7, 7, 8]), wrap_x=False)
        self.assertFalse(mask[0, 1], "1 y 2 son del mismo grupo")
        self.assertTrue(mask[0, 3], "2 y 3 no")

    def test_a_short_lut_from_an_older_map_does_not_fail(self):
        ids = np.array([[1, 1, 20, 20], [21, 21, 22, 22]])
        mask = border_mask(ids, np.array([0, 5, 5]), wrap_x=True)
        self.assertEqual(mask.shape, ids.shape)
        self.assertTrue(mask[0, 1], "20 no está en la LUT: es su propio grupo")
        self.assertTrue(mask[0, 3], "con la vuelta, 20 linda con 1")


if __name__ == "__main__":
    unittest.main()
