"""``map/default.map``: ``max_provinces``, ``sea_starts`` y los nombres de los archivos del mapa (H5). Contrato.

Vanilla: 18 claves; ``max_provinces = 3249`` (el mayor id es 3248) y ``sea_starts`` con 546 valores, de los que
545 son distintos: **el 2800 está dos veces seguidas** (posiciones 97 y 98 de la lista). Decisión 4 del contrato de
la iteración 5: el modelo **conserva el orden y los duplicados**. Nada los quita al leer ni al escribir: ni
``sea_starts()``, ni las ediciones (que tocan solo el valor añadido o quitado), ni un guardado sin cambios (I3,
I4). ``GameRules.sea`` y el índice siguen dando el conjunto, que es lo que hace falta para preguntar «¿es de
mar?». El duplicado es un aviso, ``sea_start_duplicate`` (``coherence``), que en vanilla es heredado y entra en la
línea base (criterio 8); arreglarlo es una acción explícita del usuario (``remove_sea_start`` de una aparición).

``DefaultMap`` es una vista sobre el CST del documento (no copia nada); las ediciones van dentro de la transacción
de quien llama, tras ``ws.touch``.
"""

from __future__ import annotations

from collections import Counter

from ..clausewitz.nodes import Block, Scalar
from ..vfs.paths import VPath

DEFAULT_MAP_REL = VPath.of("map/default.map")
SEA_STARTS = "sea_starts"
MAX_PROVINCES = "max_provinces"
FILE_KEYS = ("definitions", "provinces", "positions", "terrain", "rivers", "terrain_definition",
             "tree_definition", "continent", "adjacencies", "region", "region_sea", "province_flag_sprite")


class DefaultMap:
    def __init__(self, document: Block) -> None:
        self.document = document

    def _list(self) -> Block | None:
        value = self.document.get(SEA_STARTS)
        return value if isinstance(value, Block) else None

    def max_provinces(self) -> int | None:
        """El valor de ``max_provinces``; None si falta o no es un entero."""
        value = self.document.get(MAX_PROVINCES)
        if isinstance(value, Scalar):
            try:
                return value.as_int()
            except ValueError:
                return None
        return None

    def set_max_provinces(self, value: int) -> None:
        """Cambia solo ese número (o añade la clave al principio si falta)."""
        entry = self.document.find(MAX_PROVINCES)
        if entry is None:
            self.document.insert(0, MAX_PROVINCES, int(value))
        else:
            entry.value = int(value)

    def sea_starts(self) -> list[int]:
        """Los valores de ``sea_starts`` **en su orden y con sus repetidos** (vanilla: 546 con el 2800 dos
        veces). Los valores que no son enteros se saltan. Lista vacía si falta la clave."""
        block = self._list()
        if block is None:
            return []
        out = []
        for entry in block:
            if entry.key is None and isinstance(entry.value, Scalar):
                try:
                    out.append(entry.value.as_int())
                except ValueError:
                    continue
        return out

    def sea_start_duplicates(self) -> dict[int, int]:
        """``{id: veces}`` de los valores que aparecen más de una vez (vanilla: ``{2800: 2}``)."""
        counts = Counter(self.sea_starts())
        return {pid: n for pid, n in counts.items() if n > 1}

    def is_sea(self, pid: int) -> bool:
        return pid in self.sea_starts()

    def add_sea_start(self, pid: int) -> bool:
        """Añade ``pid`` al final de la lista si no estaba (False si ya estaba: no se repite a propósito). No
        reordena ni toca los demás valores, tampoco los repetidos que ya hubiera."""
        if self.is_sea(pid):
            return False
        block = self._list()
        if block is None:
            block = Block()
            self.document.append(SEA_STARTS, block)
            block = self._list()
        block.append_value(int(pid))
        return True

    def _entries_of(self, pid: int) -> list:
        block = self._list()
        if block is None:
            return []
        found = []
        for entry in block:
            if entry.key is None and isinstance(entry.value, Scalar):
                try:
                    if entry.value.as_int() == pid:
                        found.append(entry)
                except ValueError:
                    continue
        return found

    def remove_sea_start(self, pid: int, *, every: bool = True) -> int:
        """Quita ``pid`` de la lista y devuelve cuántas apariciones quitó. ``every=False`` quita solo la
        última (el arreglo de ``sea_start_duplicate``: deja una). El resto de la lista no cambia."""
        found = self._entries_of(pid)
        if not found:
            return 0
        targets = found if every else found[-1:]
        block = self._list()
        for entry in targets:
            block.remove_entry(entry)
        return len(targets)

    def files(self) -> dict[str, str]:
        """Clave → nombre de archivo tal como está escrito (``"provinces" → "provinces.bmp"``), solo de las
        claves presentes; los valores por defecto y la validación de rutas son de ``GameRules.map_files``."""
        out: dict[str, str] = {}
        for entry in self.document:
            if entry.key is None or not isinstance(entry.value, Scalar):
                continue
            key = entry.key.text
            if key in FILE_KEYS and key not in out:
                out[key] = entry.value.text
        return out
