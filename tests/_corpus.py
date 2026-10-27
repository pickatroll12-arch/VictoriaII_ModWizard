"""Localiza carpetas de mods reales para las pruebas de corpus.

``VIC2_CORPUS`` admite varias rutas separadas por ``os.pathsep``. Si no está
definida se usa ``../Plantilla Mod`` respecto a la raíz del proyecto, cuando
existe, y siempre la muestra mínima del mod del usuario incluida en el
repositorio (``tests/fixtures/shago_mod_min``): así las pruebas del mod del
usuario corren también sin el corpus completo.

Las pruebas que necesitan archivos que la muestra no trae (``text.csv``, una
historia de provincia) usan, si el corpus no los tiene, una plantilla sintética
con la misma forma (``synthetic_template``), y lo indican en su salida.
"""

from __future__ import annotations

import atexit
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Las extensiones Clausewitz son las del parser (map/default.map también): una sola definición.
from vic2studio.core.clausewitz import CLAUSEWITZ_SUFFIXES  # noqa: E402, F401 - la usan las pruebas

FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "shago_mod_min"
USER_MOD_NAME = "VSM"
# Diario de desarrollo en prosa que Paradox dejó en history/units; solo está en el mod completo.
DEV_DIARY = "history/units/v2dd2.txt"
USER_BROKEN_FILES = ("decisions/somaliland_shago.txt", "decisions/zulu_expancionshago.txt")


def corpus_roots() -> list[Path]:
    raw = os.environ.get("VIC2_CORPUS")
    if raw:
        candidates = [Path(p) for p in raw.split(os.pathsep) if p]
    else:
        candidates = [PROJECT_ROOT.parent / "Plantilla Mod", FIXTURE_ROOT]
    return [p for p in candidates if p.is_dir()]


def corpus_files(suffixes: frozenset[str] | set[str]) -> list[Path]:
    files = []
    for root in corpus_roots():
        files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
    return sorted(files)


def vanilla_root() -> Path | None:
    """El juego base real: ``VIC2_GAME`` o la primera raíz de ``VIC2_CORPUS`` con ``map/default.map`` (wizard §19.1).

    None sin corpus: la plantilla del repositorio y la muestra mínima no son el juego.
    """
    explicit = os.environ.get("VIC2_GAME")
    if explicit and Path(explicit, "common").is_dir():
        return Path(explicit)
    if not os.environ.get("VIC2_CORPUS"):
        return None
    return next((root for root in corpus_roots() if (root / "map" / "default.map").is_file()), None)


def user_mod() -> Path | None:
    """Carpeta ``VSM`` del mod del usuario (completo o la muestra mínima), si está en el corpus."""
    return next((r / USER_MOD_NAME for r in corpus_roots() if (r / USER_MOD_NAME / "decisions").is_dir()), None)


def user_mod_error_files(mod: Path) -> list[str]:
    """Archivos del mod del usuario con errores de sintaxis genuinos, en orden de validación."""
    return [*USER_BROKEN_FILES, *([DEV_DIARY] if (mod / DEV_DIARY).is_file() else [])]


# --- plantilla sintética -------------------------------------------------------------------

SYNTHETIC_TEXT_ROWS = 15_300
SYNTHETIC_EXTRA_ROWS = 6_000
# Historia de provincia con la forma de la vanilla «400 - Dunkirk.txt» (solo lo que comprueban las pruebas).
SYNTHETIC_PROVINCE = (
    "owner = FRA\ncontroller = FRA\nadd_core = FRA\ntrade_goods = fish\nlife_rating = 35\nnaval_base = 1\n"
    "1861.1.1 = { railroad = 3 }\n"
)
_WORDS = ("Country Pays Land País Military Score militaire Militär Puntuación Industrial industriel Industrie "
          "Prestige Österreich Großmacht Señorío Città Kraków Zürich Göteborg Nation Reino Imperio").split()
_synthetic: Path | None = None


def _csv_rows(rng: random.Random, prefix: str, count: int) -> list[str]:
    def text() -> str:
        return " ".join(rng.choice(_WORDS) for _ in range(rng.randint(3, 10)))

    lines = []
    for i in range(count):
        if i % 200 == 199:
            lines.append(f"#{prefix} sección {i};;;;;;;;;;;;;;x;;;;")
        elif i % 500 == 0:
            # Como en vanilla, algunas claves comparten prefijo (para las búsquedas).
            lines.append(f"LEDGER_COUNTRY_{prefix}{i};{text()};{text()};{text()};;{text()};;;;;;;;;x;;;;")
        else:
            lines.append(f"{prefix}_KEY_{i:05d};{text()};{text()};{text()};;{text()};;;;;;;;;x;;;;")
    return lines


def synthetic_template() -> Path:
    """Plantilla sintética (creada una vez por proceso y borrada al salir) con la forma del juego base.

    ``localisation/text.csv``: ~15 300 filas y ~3,6 MB en Windows-1252 con CRLF,
    comentarios y los campos vacíos que vanilla deja tras la ``x``;
    ``localisation/newtext.csv`` completa más de 20 000 claves; y
    ``history/provinces/france/400 - Dunkirk.txt``.
    """
    global _synthetic
    if _synthetic is None:
        root = Path(tempfile.mkdtemp(prefix="vic2studio-synthetic-")) / "Plantilla sintética"
        atexit.register(shutil.rmtree, root.parent, True)
        rng = random.Random(1836)
        localisation = root / "localisation"
        localisation.mkdir(parents=True)
        for name, prefix, count in (("text.csv", "TXT", SYNTHETIC_TEXT_ROWS), ("newtext.csv", "NEW", SYNTHETIC_EXTRA_ROWS)):
            (localisation / name).write_bytes(("\r\n".join(_csv_rows(rng, prefix, count)) + "\r\n").encode("cp1252"))
        province = root / "history" / "provinces" / "france" / "400 - Dunkirk.txt"
        province.parent.mkdir(parents=True)
        province.write_bytes(SYNTHETIC_PROVINCE.encode("cp1252"))
        _synthetic = root
    return _synthetic


def is_synthetic(path: Path | None) -> bool:
    return path is not None and _synthetic is not None and _synthetic in path.parents


def copy_user_mod(test, *parts: str) -> Path:
    """Copia temporal de la carpeta VSM del corpus (sin ``.vic2studio``), con su ``VSM.mod`` al lado.

    Las pruebas nunca abren el mod real: abrir un proyecto deja ahí su cerrojo y, si algo se interrumpe con
    cambios sin guardar, una recuperación que otras pruebas encontrarían. ``parts``: solo esas subcarpetas.
    """
    source = user_mod()
    base = Path(tempfile.mkdtemp(prefix="vic2studio-vsm-"))
    test.addCleanup(shutil.rmtree, base, True)   # ``test``: el ``unittest.TestCase`` que la usa
    target = base / source.name
    ignore = shutil.ignore_patterns(".vic2studio")
    if parts:
        target.mkdir()
        for part in parts:
            shutil.copytree(source / part, target / part, ignore=ignore)
    else:
        shutil.copytree(source, target, ignore=ignore)
    descriptor = source.parent / f"{source.name}.mod"
    if descriptor.is_file():
        shutil.copy2(descriptor, base / descriptor.name)
    return target
