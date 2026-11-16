"""Ids de evento: el rango del proyecto y sus colisiones (wizard §12.3, D15, decisión 7 del usuario).

Un evento nuevo recibe el primer id libre de ``ProjectSettings.id_ranges["event"]`` (por defecto, 10 000
ids desde 200 000 000). «Libre» se comprueba contra la vista efectiva entera: el juego, las dependencias y
el mod, con lo que está sin guardar.

Hechos de vanilla: 1 064 ids entre 100 y 111 011 928, ninguno repetido y ninguno en 200 000 000 o más. El
juego lee el id como entero de 32 bits con signo (``core.rules.ids.EVENT_ID_RANGE``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..project.model import ProjectSettings
    from ..vfs.model import LayerKind
    from ..vfs.paths import VPath

FAMILY = "event"                              # clave de ``ProjectSettings.id_ranges`` e ``IdRule.INT_RANGE``

# Códigos de ``InvalidIdentError`` para un id de evento (``schema.ident.<código>``).
ID_EMPTY = "empty"
ID_NOT_A_NUMBER = "bad_chars"
ID_OUT_OF_RANGE = "out_of_range"              # fuera del rango del proyecto (o de los 32 bits del juego)
ID_TAKEN = "taken"


class IdRangeExhausted(ValueError):
    """No queda ningún id libre en el rango del proyecto. ``.range`` es ``(primero, último)``."""

    def __init__(self, id_range: tuple[int, int]) -> None:
        self.range = id_range
        super().__init__(f"sin ids libres entre {id_range[0]} y {id_range[1]}")


@dataclass(frozen=True)
class IdCollision:
    """Quién usa ya un id: el archivo, la línea y la capa de su definición efectiva."""

    ident: int
    rel: VPath
    line: int | None
    layer: LayerKind


class EventIdAllocator:
    """Reparte ids de evento del rango del proyecto.

    ``index``: el ``SymbolIndex`` (símbolos ``event``). ``settings``: los ajustes del proyecto. ``pending``:
    ids que ya están en documentos abiertos y el índice aún no conoce (lo recién creado sin reindexar): los
    pasa ``Entities``, que superpone los documentos abiertos al índice.
    """

    def __init__(self, index, settings: ProjectSettings, *, pending: Iterable[int] = ()) -> None:
        self.index = index
        self.settings = settings
        self.pending = {int(ident) for ident in pending}

    @property
    def range(self) -> tuple[int, int]:
        """``(primero, último)`` del rango del proyecto, los dos incluidos."""
        from ..project.model import EVENT_ID_BLOCK, EVENT_ID_START

        ranges = getattr(self.settings, "id_ranges", None) or {}
        low, high = ranges.get(FAMILY, (EVENT_ID_START, EVENT_ID_START + EVENT_ID_BLOCK - 1))
        return int(low), int(high)

    def _used(self) -> set[int]:
        used = set(self.pending)
        if self.index is not None:
            for name in self.index.names("event"):
                try:
                    used.add(int(name))
                except (TypeError, ValueError):
                    continue
        return used

    def next_free(self, *, after: int | None = None) -> int:
        """El menor id libre del rango (mayor que ``after`` si se da). ``IdRangeExhausted`` si no queda
        ninguno."""
        low, high = self.range
        start = low if after is None else max(low, int(after) + 1)
        used = self._used()
        for ident in range(start, high + 1):
            if ident not in used:
                return ident
        raise IdRangeExhausted((low, high))

    def collision(self, ident: int) -> IdCollision | None:
        """La definición que ya usa ``ident`` en la vista efectiva (un id de ``pending`` da una colisión con
        ``rel`` y ``line`` de su documento si se conocen); None si está libre. Vale para cualquier id, no
        solo los del rango."""
        from ..vfs.model import LayerKind
        from ..vfs.paths import VPath

        symbol = self.index.get("event", str(int(ident))) if self.index is not None else None
        if symbol is not None:
            return IdCollision(int(ident), symbol.rel, symbol.line, symbol.layer)
        if int(ident) in self.pending:
            return IdCollision(int(ident), VPath.of("events"), None, LayerKind.MOD)
        return None

    def problem(self, ident: object) -> str | None:
        """Código de por qué ``ident`` no vale para un evento **nuevo** (``ID_EMPTY``, ``ID_NOT_A_NUMBER``,
        ``ID_OUT_OF_RANGE``, ``ID_TAKEN``); None si vale. Acepta el id como texto o como entero.

        ``Entities.create`` y ``duplicate`` lo usan con ``IdRule.INT_RANGE("event")`` y lanzan
        ``InvalidIdentError(código, id, next_free=<siguiente libre>, rel=<archivo>, layer=<capa>)``: el
        mensaje propone el siguiente libre (criterio 6). Los eventos que ya existen fuera del rango (los de
        vanilla) se abren y se editan igual.
        """
        from ..rules.ids import EVENT_ID_RANGE

        if ident is None or (isinstance(ident, str) and not ident.strip()):
            return ID_EMPTY
        if isinstance(ident, bool):
            return ID_NOT_A_NUMBER
        if isinstance(ident, str):
            text = ident.strip()
            if not text.isdigit():
                return ID_NOT_A_NUMBER
            ident = int(text)
        if not isinstance(ident, int):
            return ID_NOT_A_NUMBER
        low, high = self.range
        game_low, game_high = EVENT_ID_RANGE
        if not (low <= ident <= high) or not (game_low <= ident <= game_high):
            return ID_OUT_OF_RANGE
        if self.collision(ident) is not None:
            return ID_TAKEN
        return None


def first_free_block(used: Iterable[int], *, start: int | None = None, size: int | None = None) -> tuple[int, int]:
    """El primer bloque de ``size`` ids consecutivos sin ninguno de ``used``, alineado a ``size`` desde
    ``start`` (por defecto ``EVENT_ID_START`` y ``EVENT_ID_BLOCK`` de ``core.project.model``): el rango que
    se propone a un proyecto nuevo (D15) cuando una dependencia ya ocupa el de por defecto."""
    from ..project.model import EVENT_ID_BLOCK, EVENT_ID_START
    from ..rules.ids import EVENT_ID_RANGE

    start = EVENT_ID_START if start is None else int(start)
    size = EVENT_ID_BLOCK if size is None else int(size)
    if size <= 0:
        raise ValueError("el tamaño del bloque debe ser positivo")
    taken = sorted({int(ident) for ident in used if int(ident) >= start})
    low = start
    for ident in taken:
        if ident < low:
            continue
        if ident <= low + size - 1:
            low = start + ((ident - start) // size + 1) * size
        else:
            break
    if low + size - 1 > EVENT_ID_RANGE[1]:
        raise IdRangeExhausted((start, EVENT_ID_RANGE[1]))
    return low, low + size - 1
