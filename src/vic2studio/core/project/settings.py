"""``<mod>/.vic2studio/project.json`` ⇄ ``ProjectSettings`` (wizard §5.4, §6.4).

Leer no crea nada (I4): sin archivo se usan los valores por defecto. El JSON se
escribe con el siguiente guardado que lo cambie, a través del diario. Las claves
desconocidas se conservan al reescribirlo. Un campo con un valor no válido toma
su valor por defecto (los demás se respetan).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import MappingProxyType

from ..clausewitz.diagnostics import EditError
from ..clausewitz.nodes import ClausewitzDate
from ..modfile import ModDescriptor
from .model import PROJECT_FORMAT, ProjectSettings

MODES = ("simple", "advanced")


def default_prefix(mod_root: Path, descriptor: ModDescriptor | None = None) -> str:
    """Nombre de la carpeta del mod en mayúsculas, solo letras y cifras (``VSM``, ``DAM``)."""
    name = descriptor.folder_name if descriptor is not None and descriptor.folder_name else Path(mod_root).name
    prefix = re.sub(r"[^A-Z0-9]", "", name.upper())
    return prefix or "MOD"


def default_settings(mod_root: Path, descriptor: ModDescriptor | None = None) -> ProjectSettings:
    return ProjectSettings(prefix=default_prefix(mod_root, descriptor))


def _strings(value, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    return default


def _ranges(value, default):
    if not isinstance(value, dict):
        return default
    ranges = {}
    for key, pair in value.items():
        if (isinstance(key, str) and isinstance(pair, list) and len(pair) == 2
                and all(type(n) is int for n in pair) and pair[0] <= pair[1]):
            ranges[key] = (pair[0], pair[1])
    merged = dict(default)
    merged.update(ranges)
    return MappingProxyType(merged)


def settings_from_json(data: bytes | str | None, *, mod_root: Path,
                       descriptor: ModDescriptor | None = None) -> ProjectSettings:
    """``ProjectSettings`` de un JSON (``None`` o ilegible: valores por defecto)."""
    defaults = default_settings(mod_root, descriptor)
    if data is None:
        return defaults
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return defaults
    if not isinstance(obj, dict):
        return defaults
    prefix = obj.get("prefix")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_]+", prefix):
        prefix = defaults.prefix
    date = defaults.working_date
    if isinstance(obj.get("working_date"), str):
        try:
            date = ClausewitzDate.parse(obj["working_date"])
        except EditError:
            pass
    mode = obj.get("mode") if obj.get("mode") in MODES else defaults.mode
    backup = obj.get("backup_bak") if isinstance(obj.get("backup_bak"), bool) else defaults.backup_bak
    return ProjectSettings(
        prefix=prefix,
        languages=_strings(obj.get("languages"), defaults.languages),
        copy_en_to=_strings(obj.get("copy_en_to"), defaults.copy_en_to),
        id_ranges=_ranges(obj.get("id_ranges"), defaults.id_ranges),
        working_date=date,
        mode=mode,
        backup_bak=backup,
    )


def load_settings(path: Path, *, mod_root: Path, descriptor: ModDescriptor | None = None) -> ProjectSettings:
    """``path`` es el project.json; si no existe o es ilegible, valores por defecto (sin escribir nada)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        data = None
    return settings_from_json(data, mod_root=mod_root, descriptor=descriptor)


def render_settings(settings: ProjectSettings, existing: bytes | None = None) -> bytes:
    """JSON UTF-8 con sangría 2 y salto final; conserva las claves de ``existing`` que no conoce."""
    obj: dict = {}
    if existing:
        try:
            parsed = json.loads(existing)
        except (ValueError, UnicodeDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            obj = parsed
    obj["format"] = PROJECT_FORMAT
    obj["prefix"] = settings.prefix
    obj["languages"] = list(settings.languages)
    obj["copy_en_to"] = list(settings.copy_en_to)
    obj["id_ranges"] = {key: [low, high] for key, (low, high) in settings.id_ranges.items()}
    obj["working_date"] = str(settings.working_date)
    obj["mode"] = settings.mode
    obj["backup_bak"] = settings.backup_bak
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
