"""Plantillas de relieve con la sintaxis de FMG (wizard §18.6): validación por línea y conversión de la y.

FMG da la y en % desde arriba; el taller trabaja con la y del juego (fila 0 = sur, H1): y_juego = 100 − y. La
conversión cambia solo la columna y de Hill, Pit, Range y Trough («40-60» → «40-60», «0-10» → «90-100»).
"""

from __future__ import annotations

from dataclasses import dataclass

OPS_POSITIONED = {"Hill", "Pit", "Range", "Trough"}
OPS = OPS_POSITIONED | {"Strait", "Mask", "Add", "Multiply", "Smooth", "Invert"}


@dataclass(frozen=True)
class TemplateError:
    line: int          # 1-based
    column: int        # 1-based, la palabra con el problema
    code: str          # unknown_op | bad_number | bad_range | bad_axis | missing


def _flip_range(token: str) -> str:
    parts = token.split("-")
    if len(parts) == 1:
        return f"{100 - float(parts[0]):g}"
    a, b = float(parts[0]), float(parts[1])
    return f"{100 - b:g}-{100 - a:g}"


def to_game(text: str) -> str:
    """La plantilla de FMG con la y convertida a la del juego (las líneas no reconocidas quedan igual)."""
    out = []
    for line in text.strip().splitlines():
        words = line.split()
        if len(words) >= 5 and words[0] in OPS_POSITIONED:
            try:
                words[4] = _flip_range(words[4])
            except ValueError:
                pass
        out.append(" ".join(words))
    return "\n".join(out)


def _is_number(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def _is_range(token: str) -> bool:
    body = token[1:] if token.startswith("-") else token
    parts = body.split("-")
    return 1 <= len(parts) <= 2 and all(_is_number(p) for p in parts)


def validate(text: str) -> list[TemplateError]:
    """Problemas por línea (vacío = la plantilla se puede ejecutar)."""
    errors: list[TemplateError] = []
    for n, line in enumerate(text.splitlines(), start=1):
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        op = words[0]
        if op not in OPS:
            errors.append(TemplateError(n, 1, "unknown_op"))
            continue
        need = 5 if op in OPS_POSITIONED else 3 if op in {"Add", "Multiply", "Strait", "Invert"} else 2
        if len(words) < need:
            errors.append(TemplateError(n, len(words) + 1, "missing"))
            continue
        if op in OPS_POSITIONED:
            for col in (1, 2, 3, 4):
                if not _is_range(words[col]):
                    errors.append(TemplateError(n, col + 1, "bad_range"))
                    break
        elif op in {"Mask", "Smooth"}:
            if not _is_number(words[1]):
                errors.append(TemplateError(n, 2, "bad_number"))
        elif op in {"Add", "Multiply"}:
            if not _is_number(words[1]):
                errors.append(TemplateError(n, 2, "bad_number"))
            elif words[2] not in ("land", "all") and not _is_range(words[2]):
                errors.append(TemplateError(n, 3, "bad_range"))
        elif op == "Strait":
            if not _is_range(words[1]):
                errors.append(TemplateError(n, 2, "bad_range"))
            elif words[2] not in ("vertical", "horizontal"):
                errors.append(TemplateError(n, 3, "bad_axis"))
        elif op == "Invert":
            if not _is_number(words[1]):
                errors.append(TemplateError(n, 2, "bad_number"))
            elif words[2] not in ("x", "y", "both"):
                errors.append(TemplateError(n, 3, "bad_axis"))
    return errors
