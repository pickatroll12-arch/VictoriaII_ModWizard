"""``VirtualFS.list`` guarda cada listado hasta el siguiente cambio de los archivos (iteración 10).

Con vanilla, el nombre de cada provincia buscaba los CSV de ``localisation/`` recorriendo las 9 000 claves: abrir un
mod bloqueaba la interfaz unos 10 s rellenando listas de provincias que ni se veían."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.vfs import VirtualFS, VPath  # noqa: E402
from vic2studio.core.vfs import vfs as vfs_module  # noqa: E402


def _write(path: Path, data: bytes = b"x;y;\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class ListingCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.game, self.mod = base / "game", base / "mod"
        _write(self.game / "localisation" / "text.csv")
        _write(self.game / "localisation" / "zz.csv")
        _write(self.game / "common" / "defines.txt", b"a = 1\n")
        self.mod.mkdir()
        self.vfs = VirtualFS(self.game, self.mod)
        self.vfs.scan()

    def names(self):
        return [e.rel.name for e in self.vfs.list("localisation", "*.csv", recursive=False)]

    def test_repeated_listings_walk_the_keys_once(self):
        with mock.patch.object(vfs_module, "matching_keys", wraps=vfs_module.matching_keys) as walked:
            first = self.names()
            for _ in range(50):
                self.assertEqual(self.names(), first)
        self.assertEqual(walked.call_count, 1)
        self.assertEqual(first, ["text.csv", "zz.csv"])

    def test_the_listing_is_a_copy(self):
        listing = self.vfs.list("localisation", "*.csv", recursive=False)
        listing.clear()
        self.assertEqual(self.names(), ["text.csv", "zz.csv"])

    def test_refresh_and_scan_forget_the_listing(self):
        self.assertEqual(self.names(), ["text.csv", "zz.csv"])
        _write(self.mod / "localisation" / "00_mio.csv")
        self.vfs.refresh([VPath.of("localisation/00_mio.csv")])
        self.assertEqual(self.names(), ["00_mio.csv", "text.csv", "zz.csv"])
        (self.game / "localisation" / "zz.csv").unlink()
        self.vfs.scan()
        self.assertEqual(self.names(), ["00_mio.csv", "text.csv"])

    def test_the_mod_copy_wins_in_the_listing_after_refresh(self):
        before = {e.rel.name: e.layer.kind for e in self.vfs.list("localisation", "*.csv", recursive=False)}
        _write(self.mod / "localisation" / "text.csv", b"mio;mio;\n")
        self.vfs.refresh([VPath.of("localisation/text.csv")])
        after = {e.rel.name: e.layer.kind for e in self.vfs.list("localisation", "*.csv", recursive=False)}
        self.assertNotEqual(before["text.csv"], after["text.csv"])


if __name__ == "__main__":
    unittest.main()
