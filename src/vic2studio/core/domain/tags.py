"""TAG de país: comprobar uno nuevo y sugerir libres a partir del nombre (wizard §14.2, criterio 2 de la iteración 6).

``check_tag`` dice **por qué** un TAG no vale, con un motivo por caso (la interfaz lo explica en vivo en el
asistente «Nuevo país»):

- ``pattern``: no son tres caracteres con una letra mayúscula delante y letras o cifras detrás (``12A``, ``ab1``);
- ``reserved``: ``REB`` es el país de los rebeldes;
- ``script_word``: ``AND``, ``OR``, ``NOT``, ``ALL``, ``ANY``, ``THIS`` y ``FROM`` son palabras del guion (un
  ``AND = { … }`` se leería como condición);
- ``windows_device``: ``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM1``…: su bandera ``CON.tga`` no se puede crear;
- ``dynamic``: ``D01``–``D99`` son los dominios dinámicos que el juego reparte (H11);
- ``taken``: ya está en ``common/countries.txt`` (``PRU`` en vanilla).

``suggest_tags("Somalia")`` → ``SOM``, ``SOL``, ``SMA``: las tres primeras letras; después las dos primeras con
cada consonante posterior; después la primera con la tercera y la cuarta; después cualquier combinación en
orden y, si no queda nada, las dos primeras con una cifra. Solo da TAG válidos y libres.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from itertools import combinations

from ..rules.ids import DYNAMIC_TAG_RE, RESERVED_TAGS, SCRIPT_WORDS, TAG_RE
from ..vfs.paths import WINDOWS_DEVICES

REASON_PATTERN = "pattern"
REASON_RESERVED = "reserved"
REASON_SCRIPT_WORD = "script_word"
REASON_WINDOWS_DEVICE = "windows_device"
REASON_DYNAMIC = "dynamic"
REASON_TAKEN = "taken"
REASONS = (REASON_PATTERN, REASON_RESERVED, REASON_SCRIPT_WORD, REASON_WINDOWS_DEVICE, REASON_DYNAMIC,
           REASON_TAKEN)
VOWELS = frozenset("AEIOU")


@dataclass(frozen=True)
class TagCheck:
    """Resultado de ``check_tag``: ``reason`` es None si el TAG vale."""

    tag: str
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None


def _taken_set(taken) -> Callable[[str], bool]:
    if taken is None:
        return lambda tag: False
    if callable(taken):
        return taken
    upper = {str(t).upper() for t in taken}
    return lambda tag: tag.upper() in upper


def taken_tags(index) -> set[str]:
    """Los TAG registrados en el índice (``common/countries.txt`` efectivo), en mayúsculas."""
    from ..index.model import KIND_TAG

    if index is None:
        return set()
    return {name.upper() for name in index.names(KIND_TAG)}


def check_tag(tag: str, taken: Collection[str] | Callable[[str], bool] | None = None) -> TagCheck:
    """Por qué ``tag`` no puede ser el TAG de un país nuevo (``TagCheck.reason``), o ``ok``.

    ``taken``: los TAG ya registrados (colección o función); None no comprueba si está usado."""
    text = tag if isinstance(tag, str) else ""
    if TAG_RE.fullmatch(text) is None:
        return TagCheck(text, REASON_PATTERN)
    if text in RESERVED_TAGS:
        return TagCheck(text, REASON_RESERVED)
    if text in SCRIPT_WORDS:
        return TagCheck(text, REASON_SCRIPT_WORD)
    if text in WINDOWS_DEVICES:
        return TagCheck(text, REASON_WINDOWS_DEVICE)
    if DYNAMIC_TAG_RE.fullmatch(text) is not None:
        return TagCheck(text, REASON_DYNAMIC)
    if _taken_set(taken)(text):
        return TagCheck(text, REASON_TAKEN)
    return TagCheck(text)


def letters_of(name: str) -> str:
    """Las letras ASCII de ``name`` en mayúsculas, sin acentos (``"Österreich"`` → ``OSTERREICH``)."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    return "".join(c for c in decomposed.upper() if "A" <= c <= "Z")


def _candidates(letters: str) -> Iterable[str]:
    n = len(letters)
    if n >= 3:
        yield letters[:3]
        for k in range(3, n):
            if letters[k] not in VOWELS:
                yield letters[0] + letters[1] + letters[k]
        if n >= 4:
            yield letters[0] + letters[2] + letters[3]
        for j, k in combinations(range(1, n), 2):
            yield letters[0] + letters[j] + letters[k]
    if n >= 2:
        for digit in "0123456789":
            yield letters[:2] + digit
    if n >= 1:
        for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                yield letters[0] + a + b


def suggest_tags(name: str, taken: Collection[str] | Callable[[str], bool] | None = None, *,
                 count: int = 3) -> list[str]:
    """Hasta ``count`` TAG válidos y libres sacados de ``name`` (ver el docstring del módulo)."""
    letters = letters_of(name)
    if not letters:
        letters = "X"
    found: list[str] = []
    seen: set[str] = set()
    for candidate in _candidates(letters):
        if candidate in seen:
            continue
        seen.add(candidate)
        if check_tag(candidate, taken).ok:
            found.append(candidate)
            if len(found) >= count:
                break
    return found
