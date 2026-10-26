"""Carpetas de datos y caché de la aplicación, fuera de cualquier mod (``core.appdirs``, §5.4)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core import appdirs  # noqa: E402


class AppDirsTests(unittest.TestCase):
    def test_environment_overrides(self):
        with mock.patch.dict(os.environ, {appdirs.DATA_ENV: "/x/data", appdirs.CACHE_ENV: "/x/cache"}):
            self.assertEqual(appdirs.data_dir(), Path("/x/data"))
            self.assertEqual(appdirs.cache_dir(), Path("/x/cache"))
            self.assertEqual(appdirs.locks_dir(), Path("/x/data/locks"))

    @unittest.skipIf(os.name == "nt", "rutas de Linux")
    def test_linux_defaults_follow_xdg(self):
        env = {k: v for k, v in os.environ.items() if k not in (appdirs.DATA_ENV, appdirs.CACHE_ENV)}
        env.update({"XDG_DATA_HOME": "/xdg/data", "XDG_CACHE_HOME": "/xdg/cache"})
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(appdirs.data_dir(), Path("/xdg/data/vic2studio"))
            self.assertEqual(appdirs.cache_dir(), Path("/xdg/cache/vic2studio"))
        env.pop("XDG_DATA_HOME")
        env.pop("XDG_CACHE_HOME")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(appdirs.data_dir(), Path.home() / ".local/share/vic2studio")
            self.assertEqual(appdirs.cache_dir(), Path.home() / ".cache/vic2studio")

    def test_windows_defaults(self):
        env = {k: v for k, v in os.environ.items() if k not in (appdirs.DATA_ENV, appdirs.CACHE_ENV)}
        env["LOCALAPPDATA"] = "C:/Users/u/AppData/Local"
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(appdirs, "_is_windows", return_value=True):
            self.assertEqual(appdirs.data_dir(), Path("C:/Users/u/AppData/Local") / "Vic2Studio" / "data")
            self.assertEqual(appdirs.cache_dir(), Path("C:/Users/u/AppData/Local") / "Vic2Studio" / "cache")

    def test_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {appdirs.DATA_ENV: os.path.join(tmp, "d"),
                                             appdirs.CACHE_ENV: os.path.join(tmp, "c")}):
            appdirs.data_dir()
            appdirs.cache_dir()
            appdirs.locks_dir()
            appdirs.detached_project_dir(Path(tmp))
            self.assertEqual(os.listdir(tmp), [])

    def test_mod_key_uses_the_real_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "VSM"
            mod.mkdir()
            key = appdirs.mod_key(mod)
            self.assertEqual(len(key), 40)
            self.assertEqual(appdirs.mod_key(Path(tmp) / "." / "VSM"), key)
            if hasattr(os, "symlink"):
                link = Path(tmp) / "link"
                try:
                    link.symlink_to(mod, target_is_directory=True)
                except OSError:
                    return
                self.assertEqual(appdirs.mod_key(link), key, "un enlace al mismo mod da la misma clave")
            with mock.patch.dict(os.environ, {appdirs.DATA_ENV: "/d"}):
                self.assertEqual(appdirs.detached_project_dir(mod), Path("/d/projects") / key)


if __name__ == "__main__":
    unittest.main()
