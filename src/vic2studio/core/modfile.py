"""Lectura del descriptor ``.mod`` de un mod de Victoria II.

El descriptor suele vivir en ``<juego>/mod/<Nombre>.mod``, junto a la carpeta del
mod (``path = "mod/<carpeta>"``); algunos mods guardan además una copia dentro de
su propia carpeta. Se lee con el parser Clausewitz, así que sus errores de
sintaxis llegan como diagnósticos. El generador visual del descriptor queda para
una iteración posterior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .clausewitz import Block, Diagnostic, Scalar, Severity, parse_file

DESCRIPTOR_SUFFIX = ".mod"
SIBLING = "sibling"
INSIDE = "inside"


@dataclass(frozen=True)
class ModDescriptor:
    file: Path
    name: str = ""
    path: str = ""
    user_dir: str = ""
    replace_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    # SIBLING: junto a la carpeta del mod; INSIDE: dentro de ella.
    location: str = SIBLING

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def folder_name(self) -> str:
        """Última parte de ``path`` (``mod/VSM`` -> ``VSM``); admite ``\\`` como separador."""
        return PurePosixPath(self.path.replace("\\", "/")).name if self.path else ""


def _scalar_text(value) -> str:
    return value.text if isinstance(value, Scalar) else ""


def read_descriptor(file: str | os.PathLike, *, location: str = SIBLING) -> ModDescriptor | None:
    """Descriptor de ``file``; ``None`` si no se puede leer."""
    file = Path(file)
    try:
        result = parse_file(file)
    except OSError:
        return None
    doc = result.document
    dependencies: list[str] = []
    for value in doc.get_all("dependencies"):
        if isinstance(value, Block):
            dependencies.extend(_scalar_text(v) for v in value.values() if isinstance(v, Scalar))
        elif isinstance(value, Scalar):
            dependencies.append(value.text)
    return ModDescriptor(
        file=file,
        name=_scalar_text(doc.get("name")).strip(),
        path=_scalar_text(doc.get("path")).strip(),
        user_dir=_scalar_text(doc.get("user_dir")).strip(),
        replace_paths=tuple(_scalar_text(v) for v in doc.get_all("replace_path") if isinstance(v, Scalar)),
        dependencies=tuple(dependencies),
        diagnostics=tuple(result.diagnostics),
        location=location,
    )


def _descriptor_files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.suffix.lower() == DESCRIPTOR_SUFFIX and p.is_file())
    except OSError:
        return []


def find_descriptor(folder: str | os.PathLike) -> ModDescriptor | None:
    """Descriptor del mod de ``folder``.

    Primero busca en la carpeta superior un ``.mod`` cuyo ``path`` termine en el
    nombre de la carpeta (o, si ninguno, uno con el mismo nombre que ella); si
    no hay, el primer ``.mod`` que haya dentro de la propia carpeta. El juego
    corre en Windows: los nombres se comparan sin distinguir mayúsculas.
    """
    folder = Path(folder)
    name = folder.name.casefold()
    fallback = None
    for file in _descriptor_files(folder.parent):
        descriptor = read_descriptor(file)
        if descriptor is None:
            continue
        if descriptor.folder_name.casefold() == name:
            return descriptor
        if fallback is None and file.stem.casefold() == name:
            fallback = descriptor
    if fallback is not None:
        return fallback
    for file in _descriptor_files(folder):
        descriptor = read_descriptor(file, location=INSIDE)
        if descriptor is not None:
            return descriptor
    return None
