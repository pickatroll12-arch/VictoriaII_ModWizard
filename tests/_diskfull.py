"""Simulador de disco lleno: con ``full``, crear archivos o carpetas nuevos da ENOSPC (renombrar y borrar, no).

Parchea ``os.open`` (temporales de ``core.fileio``) y ``fileio.make_dirs`` (en Python 3.10 ``Path.mkdir`` no
pasa por ``os.mkdir`` parcheado: lo enlaza al importar ``pathlib``)."""
import errno
import os
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

STATE = {"full": False}
_real_open = os.open


def _open(path, flags, *a, **k):
    if STATE["full"] and flags & os.O_CREAT and not os.path.exists(path):
        raise OSError(errno.ENOSPC, "No space left on device", path)
    return _real_open(path, flags, *a, **k)


@contextmanager
def patched():
    from vic2studio.core import fileio
    real_make_dirs = fileio.make_dirs

    def make_dirs(folder):
        if STATE["full"] and not Path(folder).is_dir():
            raise OSError(errno.ENOSPC, "No space left on device", str(folder))
        return real_make_dirs(folder)
    with mock.patch.object(os, "open", _open), mock.patch.object(fileio, "make_dirs", make_dirs):
        yield STATE
