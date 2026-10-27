"""Primitivas de escritura del guardado con diario (``core.fileio``, wizard §6.5)."""

import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core import fileio  # noqa: E402
from vic2studio.core.fileio import (  # noqa: E402
    atomic_write_bytes,
    commit_staged,
    copy_file,
    create_exclusive,
    discard_staged,
    fsync_dir,
    make_dirs,
    move_file,
    remove_empty_dirs,
    remove_file,
    stage_bytes,
)


class FileIoPrimitiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def names(self, folder=None):
        return sorted(p.name for p in (folder or self.dir).iterdir())

    def test_stage_writes_a_temp_next_to_the_target_only(self):
        target = self.dir / "sub" / "file.txt"
        temp = stage_bytes(target, b"data")
        self.assertEqual(temp.parent, target.parent)
        self.assertTrue(temp.name.startswith(".file.txt.") and temp.name.endswith(".tmp"))
        self.assertEqual(temp.read_bytes(), b"data")
        self.assertFalse(target.exists())
        commit_staged(temp, target)
        self.assertEqual(target.read_bytes(), b"data")
        self.assertEqual(self.names(target.parent), ["file.txt"])

    def test_stage_with_token_is_predictable_and_exclusive(self):
        target = self.dir / "file.txt"
        temp = stage_bytes(target, b"a", token="20261026T000000-abcdef")
        self.assertEqual(temp.name, ".file.txt.20261026T000000-abcdef.tmp")
        with self.assertRaises(FileExistsError):
            stage_bytes(target, b"b", token="20261026T000000-abcdef")
        self.assertEqual(temp.read_bytes(), b"a")

    def test_discard_staged_tolerates_missing(self):
        temp = stage_bytes(self.dir / "x.txt", b"x")
        discard_staged(temp)
        discard_staged(temp)
        self.assertEqual(self.names(), [])

    def test_commit_retries_permission_errors(self):
        target = self.dir / "file.txt"
        target.write_bytes(b"old")
        temp = stage_bytes(target, b"new")
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) <= 2:
                raise PermissionError(errno.EACCES, "en uso")
            return real(src, dst)

        with mock.patch.object(fileio.os, "replace", flaky), mock.patch.object(fileio.time, "sleep") as sleep:
            commit_staged(temp, target)
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(fileio.REPLACE_RETRY_DELAY)

    def test_commit_gives_up_after_the_retries_and_keeps_the_temp(self):
        target = self.dir / "file.txt"
        target.write_bytes(b"old")
        temp = stage_bytes(target, b"new")
        calls = []

        def locked(src, dst):
            calls.append(dst)
            raise PermissionError(errno.EACCES, "en uso")

        with mock.patch.object(fileio.os, "replace", locked), mock.patch.object(fileio.time, "sleep"):
            with self.assertRaises(PermissionError):
                commit_staged(temp, target, retries=3)
        self.assertEqual(len(calls), 4, "1 intento + 3 reintentos")
        self.assertEqual(target.read_bytes(), b"old")
        self.assertTrue(temp.exists())

    @unittest.skipUnless(os.name == "posix", "permisos POSIX")
    def test_commit_keeps_the_permissions_of_the_target(self):
        target = self.dir / "file.txt"
        target.write_bytes(b"old")
        target.chmod(0o640)
        commit_staged(stage_bytes(target, b"new"), target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_copy_file_is_atomic_and_keeps_metadata(self):
        source = self.dir / "a.txt"
        source.write_bytes(b"contenido")
        os.utime(source, ns=(1_000_000_000, 2_000_000_000))
        target = self.dir / "deep" / "er" / "a.txt.bak"
        copy_file(source, target)
        self.assertEqual(target.read_bytes(), b"contenido")
        self.assertEqual(target.stat().st_mtime_ns, 2_000_000_000)
        self.assertEqual(self.names(target.parent), ["a.txt.bak"], "sin temporales")
        # Si la copia falla, el destino anterior queda intacto y no quedan temporales.
        target.write_bytes(b"anterior")
        with mock.patch.object(fileio.shutil, "copy2", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                copy_file(source, target)
        self.assertEqual(target.read_bytes(), b"anterior")
        self.assertEqual(self.names(target.parent), ["a.txt.bak"])

    def test_move_file_creates_folders_and_falls_back_across_devices(self):
        source = self.dir / "a.txt"
        source.write_bytes(b"x")
        target = self.dir / "trash" / "tx" / "a.txt"
        move_file(source, target)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b"x")
        real = os.replace
        source.write_bytes(b"y")
        other = self.dir / "other" / "a.txt"

        def cross(src, dst):
            if os.fspath(src) == os.fspath(source):
                raise OSError(errno.EXDEV, "otra unidad")
            return real(src, dst)

        with mock.patch.object(fileio.os, "replace", cross):
            move_file(source, other)
        self.assertFalse(source.exists())
        self.assertEqual(other.read_bytes(), b"y")

    def test_remove_and_make_dirs(self):
        make_dirs(self.dir / "a" / "b")
        make_dirs(self.dir / "a" / "b")
        self.assertTrue((self.dir / "a" / "b").is_dir())
        remove_file(self.dir / "nope.txt")
        (self.dir / "f").write_bytes(b"")
        remove_file(self.dir / "f")
        self.assertFalse((self.dir / "f").exists())

    def test_remove_empty_dirs_stops_at_the_first_non_empty_and_at_stop_at(self):
        root = self.dir / "mod"
        (root / ".vic2studio" / "journal").mkdir(parents=True)
        (root / "keep.txt").write_bytes(b"")
        remove_empty_dirs(root / ".vic2studio" / "journal", stop_at=root)
        self.assertEqual(self.names(root), ["keep.txt"])
        # stop_at nunca se borra, aunque quede vacío.
        (root / "keep.txt").unlink()
        (root / "x" / "y").mkdir(parents=True)
        remove_empty_dirs(root / "x" / "y", stop_at=root)
        self.assertTrue(root.is_dir())
        self.assertEqual(self.names(root), [])
        # Una carpeta con contenido no se borra.
        (root / "x").mkdir()
        (root / "x" / "f").write_bytes(b"")
        remove_empty_dirs(root / "x", stop_at=root)
        self.assertTrue((root / "x" / "f").exists())
        # Fuera de stop_at no hace nada.
        outside = self.dir / "outside"
        outside.mkdir()
        remove_empty_dirs(outside, stop_at=root)
        self.assertTrue(outside.is_dir())

    def test_fsync_dir_is_safe(self):
        fsync_dir(self.dir)
        fsync_dir(self.dir / "missing")

    def test_create_exclusive(self):
        lock = self.dir / "locks" / "a.lock"
        self.assertTrue(create_exclusive(lock, b"1"))
        self.assertFalse(create_exclusive(lock, b"2"))
        self.assertEqual(lock.read_bytes(), b"1")

    def test_atomic_write_goes_through_stage_and_commit(self):
        """atomic_write_bytes conserva su comportamiento y usa las primitivas nuevas (misma firma)."""
        target = self.dir / "file.txt"
        with mock.patch.object(fileio, "commit_staged", wraps=fileio.commit_staged) as commit:
            self.assertIsNone(atomic_write_bytes(target, b"one"))
            backup = atomic_write_bytes(target, b"two", backup=True)
        targets = [Path(call.args[1]) for call in commit.call_args_list]
        self.assertEqual(targets, [target, target.with_name("file.txt.bak"), target], "escritura, .bak, escritura")
        self.assertEqual(backup.read_bytes(), b"one")
        self.assertEqual(target.read_bytes(), b"two")
        self.assertEqual(self.names(), ["file.txt", "file.txt.bak"])
        with mock.patch.object(fileio, "commit_staged", side_effect=PermissionError("en uso")):
            with self.assertRaises(PermissionError):
                atomic_write_bytes(target, b"three")
        self.assertEqual(target.read_bytes(), b"two")
        self.assertEqual(self.names(), ["file.txt", "file.txt.bak"], "el temporal se borra si falla")


if __name__ == "__main__":
    unittest.main()
