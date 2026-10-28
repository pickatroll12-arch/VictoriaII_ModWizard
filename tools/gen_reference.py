"""Escribe la referencia de los esquemas en ``docs/referencia/{es,en}/`` (wizard §10.9, criterio 7).

    python tools/gen_reference.py            # regenera los archivos
    python tools/gen_reference.py --check    # sale con 1 si alguno no está al día (no escribe)

El contenido sale de ``vic2studio.core.schema.docgen`` (que no escribe nada: la regla de ``test_arch_writes``
prohíbe escribir desde ``src/``). Solo documenta los esquemas: ningún dato del juego.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vic2studio.core.schema.docgen import missing_keys, reference  # noqa: E402

OUT = ROOT / "docs" / "referencia"


def expected() -> dict[Path, str]:
    """``{ruta: contenido}`` de toda la referencia."""
    pages: dict[Path, str] = {}
    for lang in ("es", "en"):
        for name, content in reference(lang).items():
            pages[OUT / lang / name] = content
    return pages


def stale(pages: dict[Path, str]) -> list[Path]:
    """Archivos que faltan, sobran o difieren de lo que generaría docgen."""
    found = []
    for path, content in pages.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            found.append(path)
    for lang in ("es", "en"):
        folder = OUT / lang
        if folder.is_dir():
            found.extend(path for path in folder.glob("*.md") if path not in pages)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="no escribe: dice si la referencia está al día")
    args = parser.parse_args(argv)
    for lang in ("es", "en"):
        missing = missing_keys(lang)
        if missing:
            print(f"{lang}: faltan textos: {', '.join(missing)}", file=sys.stderr)
            return 2
    pages = expected()
    outdated = stale(pages)
    if args.check:
        for path in outdated:
            print(f"desfasado: {path.relative_to(ROOT)}")
        return 1 if outdated else 0
    for path in outdated:
        if path in pages:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pages[path], encoding="utf-8", newline="\n")
        else:
            path.unlink()
    print(f"{len(pages)} páginas; {len(outdated)} actualizadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
