"""Rutas relativas del juego y del mod, y nombres que Windows no admite (wizard §5.1).

El juego corre en Windows: las rutas se comparan sin distinguir mayúsculas
(``VPath.key``), pero se conservan tal cual para escribir (la copia al mod usa la
misma mayúscula que el original). Un mod creado en Linux no puede llevar nombres
que Windows rechaza (``CON.tga``, ``<>:"|?*``, punto o espacio final).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Código de InvalidPathError.
INVALID_PATH = "invalid_path"
MESSAGES = {
    "es": {INVALID_PATH: "«{path}» no es una ruta relativa válida dentro del juego o del mod ({reason})."},
    "en": {INVALID_PATH: "“{path}” is not a valid relative path inside the game or the mod ({reason})."},
}

WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
WINDOWS_FORBIDDEN = frozenset('<>:"|?*') | frozenset(chr(c) for c in range(32))
# MAX_PATH es 260; se avisa antes para dejar sitio a los temporales del guardado.
MAX_PATH_WARNING = 240

# Códigos que devuelve windows_name_problems.
NAME_DEVICE = "windows_device"
NAME_FORBIDDEN = "windows_forbidden_character"
NAME_TRAILING = "windows_trailing_dot_or_space"
NAME_EMPTY = "windows_empty_name"
# Código de long_path_problem.
PATH_TOO_LONG = "path_too_long"


class InvalidPathError(ValueError):
    """Ruta que no se puede usar como relativa: absoluta, con unidad, con ``..`` o vacía."""

    code = INVALID_PATH

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(self.message("es"))

    def __reduce__(self):
        return (type(self), (self.path, self.reason))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[INVALID_PATH].format(path=self.path, reason=self.reason)


class VPath(str):
    """Ruta relativa normalizada: ``/`` como separador, sin ``/`` inicial, sin ``.``, ``..`` ni unidad.

    Conserva las mayúsculas. ``key`` es la forma de comparar y ordenar como Windows
    (igual que ``csvloc.load_order_key``). Se construye con ``VPath.of``.
    """

    __slots__ = ()

    @classmethod
    def of(cls, raw: str | os.PathLike) -> VPath:
        """``\\`` → ``/``, colapsa ``//`` y ``./``; lanza ``InvalidPathError`` con ``..``, unidad, ruta absoluta o
        un primer componente que empiece por ``@`` (reservado: ``DESCRIPTOR_REL``)."""
        if isinstance(raw, VPath) and str.__eq__(raw, DESCRIPTOR_REL):
            return DESCRIPTOR_REL
        text = os.fspath(raw)
        if not isinstance(text, str):
            raise TypeError(f"VPath.of() espera str o PathLike de str, no {type(text).__name__}")
        if "\0" in text:
            raise InvalidPathError(text, "nul")
        slashed = text.replace("\\", "/")
        if slashed.startswith("/"):
            raise InvalidPathError(text, "absolute")
        if _DRIVE_RE.match(slashed):
            raise InvalidPathError(text, "drive")
        parts = [part for part in slashed.split("/") if part and part != "."]
        if not parts:
            raise InvalidPathError(text, "empty")
        if ".." in parts:
            raise InvalidPathError(text, "parent")
        if parts[0].startswith("@"):
            raise InvalidPathError(text, "reserved")
        return str.__new__(cls, "/".join(parts))

    @property
    def key(self) -> str:
        """Clave de comparación sin mayúsculas (``upper()``)."""
        return self.upper()

    @property
    def name(self) -> str:
        return self.rpartition("/")[2]

    @property
    def parent(self) -> VPath:
        """Carpeta que la contiene (``VPath("")`` para un archivo de la raíz)."""
        return str.__new__(VPath, self.rpartition("/")[0])

    @property
    def suffix(self) -> str:
        """Extensión en minúsculas, con el punto (``.txt``)."""
        name = self.name
        dot = name.rfind(".")
        return name[dot:].lower() if dot > 0 else ""

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.split("/")) if self else ()

    def join(self, *parts: str) -> VPath:
        return VPath.of("/".join(p for p in (str(self), *map(os.fspath, parts)) if p))

    def is_under(self, folder: str) -> bool:
        """True si está dentro de ``folder`` (sin distinguir mayúsculas; ``folder`` relativa)."""
        prefix = folder_key(folder)
        return not prefix or self.key.startswith(prefix + "/")

    def __repr__(self) -> str:
        return f"VPath({str.__repr__(self)})"


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def folder_key(folder: str | os.PathLike) -> str:
    """Clave de una carpeta relativa: ``/``, sin barras sobrantes ni ``.``, en mayúsculas (``""`` = la raíz)."""
    text = os.fspath(folder).replace("\\", "/")
    return "/".join(p for p in text.split("/") if p and p != ".").upper()


# Ruta reservada del descriptor ``<juego>/mod/<carpeta>.mod``, que vive fuera de la carpeta del mod: la VFS y el
# Workspace la tratan como un archivo más de la capa MOD (editarlo se deshace y se guarda con el diario).
# Se construye sin VPath.of, que rechaza el «@» inicial en las rutas que vienen de fuera.
DESCRIPTOR_REL = VPath.__new__(VPath, "@descriptor.mod")


def windows_name_problems(name: str) -> list[str]:
    """Códigos ``NAME_*`` por los que Windows rechazaría este nombre (un solo componente).

    Dispositivos también con extensión (``CON.tga``, ``nul.txt``), caracteres de
    ``WINDOWS_FORBIDDEN`` y punto o espacio final. Lista vacía si es válido.
    """
    if not name:
        return [NAME_EMPTY]
    problems = []
    if name.split(".", 1)[0].rstrip(" ").upper() in WINDOWS_DEVICES:
        problems.append(NAME_DEVICE)
    if any(char in WINDOWS_FORBIDDEN for char in name):
        problems.append(NAME_FORBIDDEN)
    if name[-1] in ". ":
        problems.append(NAME_TRAILING)
    return problems


def long_path_problem(path: str | os.PathLike | Path) -> str | None:
    """``PATH_TOO_LONG`` si la ruta absoluta pasa de ``MAX_PATH_WARNING`` caracteres; si no, None."""
    return PATH_TOO_LONG if len(os.path.abspath(path)) > MAX_PATH_WARNING else None
