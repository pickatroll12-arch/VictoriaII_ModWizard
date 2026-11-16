"""Auditoría de dependencias del taller (wizard §18.9), versión de la iteración 9a.

Qué queda huérfano al exportar un mapa nuevo «Solo mapa» sobre la instalación efectiva. La auditoría completa del
diseño recorre el índice de símbolos por rol; esta versión lee el texto de las carpetas que importan con
expresiones regulares (sin escribir nada) y agrupa por carpeta y rol:

- ``mod_files``: archivos del propio mod bajo carpetas reemplazadas (acción: papelera).
- ``oob``: archivos ``history/units`` citados por las historias de país; con la carpeta reemplazada quedan sin
  leer y las citas ``oob`` se quitan al exportar (acción: vaciar, que es lo que hace la exportación).
- ``province_id``: ids de provincia en ``events`` y ``decisions`` (``province_id``, ``owns``, ``controls``,
  ``capital`` y ámbitos ``<id> = {``) que pasan a ser otra provincia o ninguna (acción: ver usos).
- ``continent``: continentes que ya no existen citados en ``events``, ``decisions``, ``common`` y ``poptypes``.

Las citas de TAG no se auditan: con «Conservar los TAG existentes» siguen siendo válidas (§18.9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PROVINCE_KEYS = ("province_id", "owns", "controls", "capital")
_KEY_RE = re.compile(r"(?m)\b(" + "|".join(PROVINCE_KEYS) + r")\s*=\s*(\d+)\b")
_SCOPE_RE = re.compile(r"(?m)^\s*(\d{1,5})\s*=\s*\{")
_COMMENT_RE = re.compile(r"#[^\r\n]*")
SCRIPT_FOLDERS = ("events", "decisions")
CONTINENT_FOLDERS = ("events", "decisions", "poptypes", "common")
ACTIONS = {"mod_files": ("trash", "ignore"), "oob": ("empty", "ignore"), "province_id": ("view", "ignore"),
           "continent": ("view", "ignore")}


@dataclass
class OrphanGroup:
    folder: str
    role: str
    files: dict = field(default_factory=dict)      # rel → número de citas
    examples: list = field(default_factory=list)   # valores citados (los primeros)

    @property
    def count(self) -> int:
        return sum(self.files.values())

    @property
    def actions(self) -> tuple[str, ...]:
        return ACTIONS.get(self.role, ("view", "ignore"))


class DependencyAudit:
    """``DependencyAudit(vfs, world, inputs).run()`` → grupos de huérfanos ordenados por carpeta y rol."""

    def __init__(self, vfs, world, inputs, *, old_province_count: int | None = None,
                 old_continents: list[str] | None = None) -> None:
        self.vfs = vfs
        self.world = world
        self.inputs = inputs
        self.old_count = old_province_count
        self.old_continents = old_continents

    def _text(self, entry) -> str:
        try:
            return _COMMENT_RE.sub("", self.vfs.read_bytes(entry).decode("cp1252", errors="replace"))
        except OSError:
            return ""

    def run(self, cancelled=None) -> list[OrphanGroup]:
        from ..cancel import raise_if_cancelled

        out: list[OrphanGroup] = []
        groups: dict[tuple[str, str], OrphanGroup] = {}

        def add(folder: str, role: str, rel: str, n: int, example=None) -> None:
            g = groups.setdefault((folder, role), OrphanGroup(folder, role))
            g.files[rel] = g.files.get(rel, 0) + n
            if example is not None and len(g.examples) < 8 and example not in g.examples:
                g.examples.append(example)

        for rel in self.inputs.mod_trash:
            add("/".join(rel.split("/")[:2]), "mod_files", rel, 1)
        for rel in self.inputs.oob_paths:
            add("history/units", "oob", rel, 1)
        r = self.world.raster
        new_count = r.count if r is not None else 0
        changed = self._changed_ids(new_count)
        for folder in SCRIPT_FOLDERS:
            for entry in self.vfs.list(folder, "*.txt", recursive=True):
                raise_if_cancelled(cancelled)
                text = self._text(entry)
                hits = [int(m.group(2)) for m in _KEY_RE.finditer(text)]
                hits += [int(m.group(1)) for m in _SCOPE_RE.finditer(text)]
                bad = [v for v in hits if v in changed or v > new_count]
                if bad:
                    add(folder, "province_id", str(entry.rel), len(bad), bad[0])
        old_conts = self.old_continents
        if old_conts is None and self.world.install is not None:
            old_conts = list(self.world.install.continents)
        new_conts = set(self.world.entities.get("continent_names") or [])
        gone = [c for c in (old_conts or []) if c not in new_conts]
        if gone:
            pat = re.compile(r"\b(" + "|".join(re.escape(c) for c in gone) + r")\b")
            for folder in CONTINENT_FOLDERS:
                for entry in self.vfs.list(folder, "*.txt", recursive=True):
                    raise_if_cancelled(cancelled)
                    found = pat.findall(self._text(entry))
                    if found:
                        add(folder, "continent", str(entry.rel), len(found), found[0])
        out = sorted(groups.values(), key=lambda g: (g.folder, g.role))
        return out

    def _changed_ids(self, new_count: int) -> set[int]:
        """Ids que cambian de sentido: en «Solo mapa» todos los ids antiguos pasan a ser otra provincia (o
        ninguna). Se marcan los que existían antes (``old_province_count`` o ``max_provinces`` de la instalación)."""
        old = self.old_count
        if old is None and self.world.install is not None:
            m = re.search(r"max_provinces\s*=\s*(\d+)", self.world.install.default_map or "")
            old = int(m.group(1)) - 1 if m else 0
        return set(range(1, (old or 0) + 1))


__all__ = ["DependencyAudit", "OrphanGroup", "ACTIONS"]
