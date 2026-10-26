"""Capas de juego, dependencias y mod a partir de diccionarios de bytes (pruebas de la VFS y del proyecto).

Por defecto imita una instalación real (H24): el mod vive dentro del juego, en
``<juego>/mod/<nombre>/``, con su descriptor en ``<juego>/mod/<nombre>.mod``. Todo
se crea en una carpeta temporal que se borra con ``Layers.cleanup`` (o al salir
del ``with``). Solo para pruebas: escribe con ``Path.write_bytes`` porque
``tests/`` queda fuera de la regla de escrituras de ``test_arch_writes``.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

GAME_EXE = "v2game.exe"


def descriptor_bytes(name: str, folder: str, user_dir: str | None = None, *, replace_paths=(), newline="\r\n") -> bytes:
    lines = [f'name = "{name}"', f'path = "mod/{folder}"']
    if user_dir is not None:
        lines.append(f'user_dir = "{user_dir}"')
    lines += [f'replace_path = "{p}"' for p in replace_paths]
    return "".join(line + newline for line in lines).encode("cp1252")


@dataclass
class Layers:
    base: Path
    game_root: Path | None
    mod_root: Path
    descriptor: Path | None
    dependencies: list[Path] = field(default_factory=list)
    _owned: bool = True

    def game(self, rel: str) -> Path:
        assert self.game_root is not None
        return self.game_root / rel

    def mod(self, rel: str) -> Path:
        return self.mod_root / rel

    def tree(self, root: Path | None = None) -> dict[str, tuple[int, int, bytes]]:
        """``{ruta relativa: (tamaño, mtime_ns, bytes)}`` de todo lo que hay bajo ``root`` (el mod por defecto):
        para afirmar que algo no escribió nada (I4)."""
        root = self.mod_root if root is None else root
        result = {}
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    stat = path.stat()
                    result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns, path.read_bytes())
        return result

    def cleanup(self) -> None:
        if self._owned:
            shutil.rmtree(self.base, ignore_errors=True)

    def __enter__(self) -> Layers:
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()


def isolate_appdirs(test) -> Path:
    """Desvía ``VIC2STUDIO_DATA_DIR`` y ``VIC2STUDIO_CACHE_DIR`` a una carpeta temporal mientras dure ``test``
    (un ``unittest.TestCase``): los bloqueos y las cachés de las pruebas no tocan las del usuario."""
    import os
    from unittest import mock

    folder = Path(tempfile.mkdtemp(prefix="vic2studio-appdirs-"))
    test.addCleanup(shutil.rmtree, folder, True)
    patcher = mock.patch.dict(os.environ, {"VIC2STUDIO_DATA_DIR": str(folder / "data"),
                                           "VIC2STUDIO_CACHE_DIR": str(folder / "cache")})
    patcher.start()
    test.addCleanup(patcher.stop)
    return folder


def _write(root: Path, files: Mapping[str, bytes | str]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("cp1252") if isinstance(data, str) else data)


def build_layers(*, game: Mapping[str, bytes | str] | None = None, mod: Mapping[str, bytes | str] | None = None,
                 mod_name: str = "TestMod", descriptor: bytes | None = None, mod_inside_game: bool = True,
                 dependencies: Mapping[str, Mapping[str, bytes | str]] | None = None,
                 base: Path | None = None) -> Layers:
    """Crea las capas. ``game=None``: sin juego base. ``descriptor=None``: uno canónico con ``name = mod_name``.

    ``dependencies``: ``{nombre: archivos}``, cada una como otro mod en ``<juego>/mod/<nombre>/``.
    Con ``mod_inside_game=False`` el mod va en ``<base>/mods/<nombre>`` (y su descriptor al lado).
    """
    owned = base is None
    base = Path(tempfile.mkdtemp(prefix="vic2studio-layers-")) if base is None else base
    game_root = None
    if game is not None:
        game_root = base / "Victoria 2"
        game_root.mkdir(parents=True, exist_ok=True)
        (game_root / GAME_EXE).write_bytes(b"MZ")
        _write(game_root, game)
    mods_dir = game_root / "mod" if (game_root is not None and mod_inside_game) else base / "mods"
    mod_root = mods_dir / mod_name
    mod_root.mkdir(parents=True, exist_ok=True)
    _write(mod_root, mod or {})
    descriptor_path = mods_dir / f"{mod_name}.mod"
    descriptor_path.write_bytes(descriptor if descriptor is not None else descriptor_bytes(mod_name, mod_name, mod_name))
    deps = []
    for name, files in (dependencies or {}).items():
        dep_root = mods_dir / name
        dep_root.mkdir(parents=True, exist_ok=True)
        _write(dep_root, files)
        (mods_dir / f"{name}.mod").write_bytes(descriptor_bytes(name, name, name))
        deps.append(dep_root)
    return Layers(base, game_root, mod_root, descriptor_path, deps, owned)
