"""Comprueba que el repositorio no contenga archivos ni líneas de datos de Paradox (wizard §19.5)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import PROJECT_ROOT, vanilla_root  # noqa: E402
from vic2studio.core.encoding import decode_bytes  # noqa: E402

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
ALLOWED_FIXTURES = frozenset({
    "shago_mod_min/VSM.mod",
    "shago_mod_min/VSM/common/countries/Angoche.txt",
    "shago_mod_min/VSM/common/countries/Geledi.txt",
    "shago_mod_min/VSM/common/countries/Imperio Zulu.txt",
    "shago_mod_min/VSM/common/countries/Majeerteen.txt",
    "shago_mod_min/VSM/common/countries/Somalia.txt",
    "shago_mod_min/VSM/common/countries/Warsangali.txt",
    "shago_mod_min/VSM/decisions/angoche_shago.txt",
    "shago_mod_min/VSM/decisions/expansion_shagomod_varios.txt",
    "shago_mod_min/VSM/decisions/somaliland_shago.txt",
    "shago_mod_min/VSM/decisions/zulu_expancionshago.txt",
    "shago_mod_min/VSM/history/countries/AGC - Angoche.txt",
    "shago_mod_min/VSM/history/countries/GEL - Geledi.txt",
    "shago_mod_min/VSM/history/countries/IZU - Imperio Zulu.txt",
    "shago_mod_min/VSM/history/countries/MAJ - Majeerteen.txt",
    "shago_mod_min/VSM/history/countries/SOM - Somalia.txt",
    "shago_mod_min/VSM/history/countries/WRL - Warsangali.txt",
    "shago_mod_min/VSM/localisation/00_VSM_countries.csv",
    "shago_mod_min/VSM/localisation/00_VSM_decisions.csv",
    "shago_mod_min/VSM/localisation/00_VSM_modifiers.csv",
})
VANILLA_TEXT_SUFFIXES = frozenset({
    ".txt", ".csv", ".gui", ".gfx", ".lua", ".asset", ".sfx", ".map", ".fx", ".fnt",
})
REPO_SCAN_FOLDERS = ("src", "tests", "docs")
GAME_ART_SUFFIXES = frozenset({".dds", ".tga", ".fnt"})
BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".dds", ".ico",
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".zip", ".gz",
})
MIN_LINE_LENGTH = 40
# Asignación simple «clave = palabra» del vocabulario del juego (p. ej. citizenship_policy = limited_citizenship).
SIMPLE_ASSIGNMENT_RE = re.compile(r"^[A-Za-z0-9_.]+ = [A-Za-z0-9_.]+$")


def normalize_line(line: str) -> str:
    """Quita espacios a los lados y colapsa los espacios internos en uno solo."""
    return " ".join(line.split())


def collect_vanilla_lines(vanilla: Path) -> dict[str, str]:
    """Líneas normalizadas de 40+ caracteres de los archivos de texto de vanilla → archivo de origen."""
    lines: dict[str, str] = {}
    for path in sorted(vanilla.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in VANILLA_TEXT_SUFFIXES:
            continue
        rel = path.relative_to(vanilla).as_posix()
        text = decode_bytes(path.read_bytes()).text
        for raw in text.splitlines():
            norm = normalize_line(raw)
            if len(norm) >= MIN_LINE_LENGTH and not SIMPLE_ASSIGNMENT_RE.match(norm):
                lines.setdefault(norm, rel)
    return lines


def find_repo_matches(repo_root: Path, vanilla_lines: dict[str, str]) -> list[tuple[str, int, str, str]]:
    """Coincidencias (archivo_repo, línea, texto_normalizado, archivo_vanilla) en src/, tests/ y docs/."""
    matches: list[tuple[str, int, str, str]] = []
    for folder_name in REPO_SCAN_FOLDERS:
        folder = repo_root / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix.lower() in BINARY_SUFFIXES:
                continue
            data = path.read_bytes()
            if b"\x00" in data:
                continue
            rel = path.relative_to(repo_root).as_posix()
            text = decode_bytes(data).text
            for lineno, raw in enumerate(text.splitlines(), 1):
                norm = normalize_line(raw)
                if len(norm) >= MIN_LINE_LENGTH and norm in vanilla_lines:
                    matches.append((rel, lineno, norm, vanilla_lines[norm]))
    return matches


class NoParadoxDataTests(unittest.TestCase):
    def test_fixtures_only_contain_allowed_paths(self):
        found = {p.relative_to(FIXTURES_DIR).as_posix() for p in FIXTURES_DIR.rglob("*") if p.is_file()}
        unexpected = sorted(found - ALLOWED_FIXTURES)
        self.assertEqual(
            unexpected,
            [],
            f"Archivos no permitidos en tests/fixtures/: {', '.join(unexpected)}",
        )
        missing = sorted(ALLOWED_FIXTURES - found)
        self.assertEqual(
            missing,
            [],
            f"Faltan archivos esperados en tests/fixtures/: {', '.join(missing)}",
        )

    def test_no_game_textures_or_fonts_in_the_repository(self):
        """Iteración 8, criterio 4: la suite de interfaces lee el arte del juego en tiempo de ejecución; el
        repositorio no trae texturas ni fuentes del juego (ni ningún archivo .dds, .tga o .fnt)."""
        found = sorted(p.relative_to(PROJECT_ROOT).as_posix() for folder in REPO_SCAN_FOLDERS
                       for p in (PROJECT_ROOT / folder).rglob("*")
                       if p.is_file() and p.suffix.lower() in GAME_ART_SUFFIXES)
        self.assertEqual(found, [])

    def test_no_repository_file_is_a_copy_of_a_game_image(self):
        vanilla = vanilla_root()
        if vanilla is None:
            self.skipTest("Requiere el juego base (VIC2_GAME o VIC2_CORPUS)")
        import hashlib

        def digest(path: Path) -> str:
            return hashlib.sha1(path.read_bytes()).hexdigest()

        game = {}
        for folder in ("gfx", "interface"):
            for path in (vanilla / folder).rglob("*"):
                if path.is_file() and path.suffix.lower() in GAME_ART_SUFFIXES | {".png", ".bmp", ".jpg"}:
                    game.setdefault((path.stat().st_size), []).append(path)
        copies = []
        for folder in REPO_SCAN_FOLDERS:
            for path in (PROJECT_ROOT / folder).rglob("*"):
                if not path.is_file() or path.stat().st_size not in game:
                    continue
                mine = digest(path)
                copies.extend((path.relative_to(PROJECT_ROOT).as_posix(), other.name)
                              for other in game[path.stat().st_size] if digest(other) == mine)
        self.assertEqual(copies, [])

    def test_no_vanilla_lines_in_repository_text_files(self):
        vanilla = vanilla_root()
        if vanilla is None:
            self.skipTest("Requiere el juego base (VIC2_GAME o VIC2_CORPUS)")
        vanilla_lines = collect_vanilla_lines(vanilla)
        self.assertGreater(
            len(vanilla_lines),
            1000,
            f"Vanilla ({vanilla}) aportó muy pocas líneas ({len(vanilla_lines)}): ¿ruta incorrecta?",
        )
        matches = find_repo_matches(PROJECT_ROOT, vanilla_lines)
        details = "\n".join(
            f"  {rel}:{lineno}: {norm!r} (de vanilla {origin})"
            for rel, lineno, norm, origin in matches[:20]
        )
        self.assertEqual(
            matches,
            [],
            f"Se encontraron {len(matches)} línea(s) de vanilla en el repositorio:\n{details}",
        )


if __name__ == "__main__":
    unittest.main()
