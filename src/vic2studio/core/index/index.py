"""``SymbolIndex``: qué existe en la vista efectiva (juego + dependencias + mod + cambios sin guardar), wizard §7.

Se construye con ``builder.build_index`` a partir de ``FileFacts`` y se mantiene
con ``apply`` (incremental: un archivo cambiado sustituye sus hechos). Combina
según las reglas de carga (§5.2):

- ``WHOLE_FILE`` (``common/*.txt``, ``map/*``…): solo cuentan los hechos del
  archivo ganador de esa ruta; los de las capas que pierden se conservan para el
  explicador (``lookup`` los devuelve después del efectivo).
- ``UNION_BY_PATH`` y ``KEYED_UNION`` (eventos, decisiones, historias): cuentan
  todos los ganadores de cada ruta; dos definiciones del mismo nombre en rutas
  distintas son un duplicado (``lookup`` da más de una).
- ``LOCALISATION``: gana la primera clave por orden de carga de los archivos
  (``csvloc.db.load_order_key``), como ``LocalisationDB``.
- Un archivo del juego oculto por ``replace_path`` no aporta nada.

En la práctica las tres primeras son la misma regla por ruta: de cada ruta cuenta
la capa ganadora (mod, si hay hechos del mod, también de un documento sin guardar;
si no, la dependencia; si no, el juego, salvo que ``replace_path`` lo oculte), y
entre rutas distintas la definición efectiva de un nombre es la primera por
``(rel.key, línea)``: el orden de carga del juego en la localización y un orden
estable en el resto.

**Provincias de tierra y de mar.** ``definition.csv`` define todas como
``province``; las que ``default.map`` nombra en ``sea_starts`` (referencias con rol
``sea_starts``) pasan a ``sea_province`` (H5: 3246 es de tierra). Las dos llevan
``attrs["is_sea"]``.

Python puro y de solo lectura para quien consulta; ``apply`` lo llama un solo
hilo (el de la interfaz). Las consultas no leen disco. Las cachés por tipo se
calculan al primer uso y ``apply`` invalida solo las de los tipos que toca.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import replace
from types import MappingProxyType

from ..vfs.model import LayerKind
from ..vfs.paths import VPath
from .model import (
    KIND_BOOKMARK,
    KIND_DECISION,
    KIND_EVENT,
    KIND_PARTY,
    KIND_PROVINCE,
    KIND_SEA_PROVINCE,
    ROLE_SEA_STARTS,
    FileFacts,
    Symbol,
    SymbolRef,
    fold,
    short_name,
)

_PRIORITY = (LayerKind.MOD, LayerKind.DEPENDENCY, LayerKind.GAME)
_ALL = object()            # sin instantánea: todos los hechos cuentan como ganadores
_PROVINCE_KINDS = (KIND_PROVINCE, KIND_SEA_PROVINCE)
# Orden de los resultados del buscador cuando empatan (los tipos que más se buscan primero).
SEARCH_PRIORITY = ("tag", "province", "sea_province", "culture", "religion", "region", "continent", "government",
                   "ideology", "party", "national_value", "technology", "invention", "unit_type", "goods", "building",
                   "pop_type", "cb", "event", "decision", "bookmark", "war", "issue_group", "issue_option",
                   "culture_group", "religion_group", "sea_region", "climate", "terrain", "country_history",
                   "province_history", "sprite", "gui_window", "country_file")
_SEARCH_LAST = ("loc_key", "image", "pop_block", "country_flag", "global_flag", "province_flag")
# Tipos cuyo nombre para mostrar no sale de la localización.
_NOT_LOCALISED = frozenset({"loc_key", "image", "pop_block", "country_flag", "global_flag", "province_flag",
                            "sprite", "gui_window", "country_file", "province_history", "country_history", "file"})


class _Slot:
    """Hechos de una ruta en una capa. ``def_kinds``/``ref_kinds`` se calculan al crearlo; la agrupación por
    tipo (``defs``/``refs``), al primer uso: construir el índice desde la caché no la necesita."""

    __slots__ = ("facts", "def_kinds", "ref_kinds", "_defs", "_refs")

    def __init__(self, facts: list[FileFacts]) -> None:
        self.facts = facts
        if len(facts) == 1:
            item = facts[0]
            self.def_kinds = {s.kind for s in item.defs}
            self.ref_kinds = {r.kind for r in item.refs}
        else:
            self.def_kinds = {s.kind for item in facts for s in item.defs}
            self.ref_kinds = {r.kind for item in facts for r in item.refs}
        self._defs: dict[str, list[Symbol]] | None = None
        self._refs: dict[str, list[SymbolRef]] | None = None

    @property
    def defs(self) -> dict[str, list[Symbol]]:
        if self._defs is None:
            grouped: dict[str, list[Symbol]] = {}
            for item in self.facts:
                for symbol in item.defs:
                    grouped.setdefault(symbol.kind, []).append(symbol)
            self._defs = grouped
        return self._defs

    @property
    def refs(self) -> dict[str, list[SymbolRef]]:
        if self._refs is None:
            grouped: dict[str, list[SymbolRef]] = {}
            for item in self.facts:
                for ref in item.refs:
                    grouped.setdefault(ref.kind, []).append(ref)
            self._refs = grouped
        return self._refs


class _Defs:
    __slots__ = ("names", "effective", "losing", "folded")

    def __init__(self) -> None:
        self.names: list[str] = []
        self.effective: dict[str, list[Symbol]] = {}
        self.losing: dict[str, list[Symbol]] = {}
        self.folded: dict[str, str] | None = None


class _Refs:
    __slots__ = ("all", "by_name")

    def __init__(self) -> None:
        self.all: list[SymbolRef] = []
        self.by_name: dict[str, list[SymbolRef]] = {}


_RANK = {layer: rank for rank, layer in enumerate(_PRIORITY)}


def _order(symbol: Symbol) -> tuple:
    """Por ruta y línea; a igualdad, la capa con más prioridad (mod) primero: un orden estable."""
    return (symbol.rel.key, symbol.line or 0, _RANK.get(symbol.layer, 9))


def _ref_order(ref: SymbolRef) -> tuple:
    return (ref.rel.key, ref.line or 0, ref.column or 0, ref.role, ref.name)


class SymbolIndex:
    """Índice consultable. ``generation`` sube con cada ``apply`` (las vistas lo comparan para refrescar)."""

    generation: int = 0

    def __init__(self, facts: Iterable[FileFacts] = (), *, snapshot=None) -> None:
        """``snapshot`` (``VfsSnapshot``) da el orden de capas y qué está oculto por ``replace_path``; sin él,
        todos los hechos cuentan como ganadores (pruebas con un índice en memoria)."""
        self.generation = 0
        self._snapshot = snapshot
        self._hidden: frozenset[str] = snapshot.hidden if snapshot is not None else frozenset()
        self._slots: dict[tuple[str, LayerKind], _Slot] = {}
        self._layers: dict[str, set[LayerKind]] = {}
        self._effective: dict[str, object] = {}
        self._def_sources: dict[str, set[tuple[str, LayerKind]]] = {}
        self._ref_sources: dict[str, set[tuple[str, LayerKind]]] = {}
        self._defs: dict[str, _Defs] = {}
        self._refs: dict[str, _Refs] = {}
        self._fold: dict[str, str] = {}
        grouped: dict[tuple[str, LayerKind], list[FileFacts]] = {}
        for item in facts:
            grouped.setdefault((item.rel.key, item.layer), []).append(item)
        for (key, layer), items in grouped.items():
            self._put(key, layer, items)
        for key in self._layers:
            self._effective[key] = self._winner(key)

    # --- mantenimiento interno ------------------------------------------------------------------

    def _put(self, key: str, layer: LayerKind, items: list[FileFacts] | None) -> set[str]:
        """Sustituye (o quita, con ``items=None``) los hechos de ``(key, layer)``; devuelve los tipos tocados."""
        touched: set[str] = set()
        old = self._slots.pop((key, layer), None)
        if old is not None:
            for kind in old.def_kinds:
                touched.add(kind)
                sources = self._def_sources.get(kind)
                if sources is not None:
                    sources.discard((key, layer))
            for kind in old.ref_kinds:
                touched.add(kind)
                sources = self._ref_sources.get(kind)
                if sources is not None:
                    sources.discard((key, layer))
            layers = self._layers.get(key)
            if layers is not None:
                layers.discard(layer)
                if not layers:
                    del self._layers[key]
        if items:
            slot = _Slot(list(items))
            self._slots[(key, layer)] = slot
            self._layers.setdefault(key, set()).add(layer)
            for kind in slot.def_kinds:
                touched.add(kind)
                self._def_sources.setdefault(kind, set()).add((key, layer))
            for kind in slot.ref_kinds:
                touched.add(kind)
                self._ref_sources.setdefault(kind, set()).add((key, layer))
        return touched

    def _winner(self, key: str) -> object:
        layers = self._layers.get(key)
        if not layers:
            return None
        if self._snapshot is None:
            return _ALL
        for layer in _PRIORITY:
            if layer in layers:
                if layer is LayerKind.GAME and key in self._hidden:
                    continue
                return layer
        return None

    def _counts(self, key: str, layer: LayerKind) -> bool:
        winner = self._effective.get(key)
        return winner is _ALL or winner is layer

    def _kinds_of(self, key: str) -> set[str]:
        kinds: set[str] = set()
        for layer in self._layers.get(key, ()):
            slot = self._slots.get((key, layer))
            if slot is not None:
                kinds.update(slot.def_kinds)
                kinds.update(slot.ref_kinds)
        return kinds

    def _invalidate(self, kinds: Iterable[str]) -> None:
        for kind in kinds:
            self._defs.pop(kind, None)
            self._refs.pop(kind, None)
            if kind in _PROVINCE_KINDS:
                for other in _PROVINCE_KINDS:
                    self._defs.pop(other, None)

    # --- cachés por tipo -----------------------------------------------------------------------

    def _raw_defs(self, kind: str) -> tuple[list[Symbol], list[Symbol]]:
        effective: list[Symbol] = []
        losing: list[Symbol] = []
        for key, layer in self._def_sources.get(kind, ()):
            slot = self._slots[(key, layer)]
            (effective if self._counts(key, layer) else losing).extend(slot.defs.get(kind, ()))
        effective.sort(key=_order)
        losing.sort(key=_order)
        return effective, losing

    def _sea(self) -> set[str]:
        return {ref.name for ref in self._kind_refs(KIND_PROVINCE).all if ref.role == ROLE_SEA_STARTS}

    def _kind_defs(self, kind: str) -> _Defs:
        cached = self._defs.get(kind)
        if cached is not None:
            return cached
        if kind in _PROVINCE_KINDS:
            effective, losing = self._province_defs(kind)
        else:
            effective, losing = self._raw_defs(kind)
        defs = _Defs()
        for symbol in effective:
            found = defs.effective.get(symbol.name)
            if found is None:
                defs.effective[symbol.name] = [symbol]
                defs.names.append(symbol.name)
            else:
                found.append(symbol)
        for symbol in losing:
            defs.losing.setdefault(symbol.name, []).append(symbol)
        self._defs[kind] = defs
        return defs

    def _province_defs(self, kind: str) -> tuple[list[Symbol], list[Symbol]]:
        sea = self._sea()
        raw_effective, raw_losing = self._raw_defs(KIND_PROVINCE)
        own_effective, own_losing = self._raw_defs(KIND_SEA_PROVINCE) if kind == KIND_SEA_PROVINCE else ([], [])
        want_sea = kind == KIND_SEA_PROVINCE

        def mark(symbol: Symbol, is_sea: bool) -> Symbol:
            attrs = dict(symbol.attrs)
            attrs["is_sea"] = is_sea
            return replace(symbol, kind=KIND_SEA_PROVINCE if is_sea else KIND_PROVINCE,
                           attrs=MappingProxyType(attrs))

        effective = [mark(s, want_sea) for s in raw_effective if (s.name in sea) == want_sea] + own_effective
        losing = [mark(s, want_sea) for s in raw_losing if (s.name in sea) == want_sea] + own_losing
        effective.sort(key=_order)
        losing.sort(key=_order)
        return effective, losing

    def _kind_refs(self, kind: str) -> _Refs:
        cached = self._refs.get(kind)
        if cached is not None:
            return cached
        refs = _Refs()
        for key, layer in self._ref_sources.get(kind, ()):
            if self._counts(key, layer):
                refs.all.extend(self._slots[(key, layer)].refs.get(kind, ()))
        refs.all.sort(key=_ref_order)
        for ref in refs.all:
            refs.by_name.setdefault(ref.name, []).append(ref)
        self._refs[kind] = refs
        return refs

    def _folded(self, text: str) -> str:
        found = self._fold.get(text)
        if found is None:
            if len(self._fold) > 500_000:
                self._fold.clear()
            found = self._fold[text] = fold(text)
        return found

    # --- consultas ---------------------------------------------------------------------------------

    def kinds(self) -> list[str]:
        """Tipos con al menos una definición efectiva, ordenados."""
        candidates = set(self._def_sources)
        if KIND_PROVINCE in candidates:
            candidates.add(KIND_SEA_PROVINCE)
        return sorted(kind for kind in candidates if self._kind_defs(kind).names)

    def names(self, kind: str) -> list[str]:
        """Nombres efectivos de ``kind``, en orden de definición (archivo y línea)."""
        return list(self._kind_defs(kind).names)

    def count(self, kind: str) -> int:
        return len(self._kind_defs(kind).names)

    def get(self, kind: str, name: str) -> Symbol | None:
        """Definición efectiva (la que usa el juego) o None."""
        found = self._kind_defs(kind).effective.get(name)
        return found[0] if found else None

    def lookup(self, kind: str, name: str) -> list[Symbol]:
        """Todas las definiciones, la efectiva primero; más de una = duplicado o capas que pierden."""
        defs = self._kind_defs(kind)
        return [*defs.effective.get(name, ()), *defs.losing.get(name, ())]

    def effective(self, kind: str, name: str) -> list[Symbol]:
        """Solo las definiciones que cuentan (más de una = duplicado en la vista efectiva). Ampliación."""
        return list(self._kind_defs(kind).effective.get(name, ()))

    def is_effective(self, symbol: Symbol) -> bool:
        """True si ``symbol`` viene de la capa ganadora de su ruta. Ampliación."""
        return self._counts(symbol.rel.key, symbol.layer)

    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool:
        defs = self._kind_defs(kind)
        if not ignore_case:
            return name in defs.effective
        if defs.folded is None:
            defs.folded = {n.casefold(): n for n in defs.names}
        return name.casefold() in defs.folded

    def attrs(self, kind: str, name: str, attr: str, default=None) -> object:
        symbol = self.get(kind, name)
        if symbol is None:
            return default
        return symbol.attrs.get(attr, default)

    def symbols(self, kind: str) -> list[Symbol]:
        """Definiciones efectivas de ``kind`` (como ``names``, con todo)."""
        defs = self._kind_defs(kind)
        return [defs.effective[name][0] for name in defs.names]

    def defs_in(self, rel: VPath) -> list[Symbol]:
        """Definiciones que aporta el archivo ganador de ``rel``."""
        key = VPath.of(rel).key
        found: list[Symbol] = []
        for layer in self._layers.get(key, ()):
            if self._counts(key, layer):
                for item in self._slots[(key, layer)].facts:
                    found.extend(item.defs)
        if KIND_PROVINCE in {s.kind for s in found}:
            sea = self._sea()
            found = [replace(s, kind=KIND_SEA_PROVINCE if s.name in sea else KIND_PROVINCE,
                             attrs=MappingProxyType({**s.attrs, "is_sea": s.name in sea}))
                     if s.kind == KIND_PROVINCE else s for s in found]
        return sorted(found, key=_order)

    def refs_to(self, kind: str, name: str) -> list[SymbolRef]:
        """Usos de ``kind``/``name`` en la vista efectiva («dónde se usa»)."""
        if kind == KIND_SEA_PROVINCE:
            kind = KIND_PROVINCE
        return list(self._kind_refs(kind).by_name.get(name, ()))

    def refs_from(self, rel: VPath) -> list[SymbolRef]:
        key = VPath.of(rel).key
        found: list[SymbolRef] = []
        for layer in self._layers.get(key, ()):
            if self._counts(key, layer):
                for item in self._slots[(key, layer)].facts:
                    found.extend(item.refs)
        return sorted(found, key=_ref_order)

    def refs(self, kind: str) -> list[SymbolRef]:
        """Todos los usos de ``kind`` (las reglas ``*_unknown`` los recorren)."""
        if kind == KIND_SEA_PROVINCE:
            kind = KIND_PROVINCE
        return list(self._kind_refs(kind).all)

    def ref_kinds(self) -> list[str]:
        """Tipos con al menos una referencia efectiva. Ampliación."""
        return sorted(kind for kind in self._ref_sources if self._kind_refs(kind).all)

    def rels(self) -> list[VPath]:
        """Rutas con hechos efectivos, ordenadas. Ampliación."""
        found = []
        for key in sorted(self._layers):
            winner = self._effective.get(key)
            for layer in self._layers[key]:
                if winner is _ALL or winner is layer:
                    found.append(self._slots[(key, layer)].facts[0].rel)
                    break
        return found

    # --- buscador y nombres para mostrar ---------------------------------------------------------

    @staticmethod
    def loc_key_for(symbol: Symbol) -> str | None:
        """Clave de localización con el nombre visible de un símbolo (``PROV549``, ``PRU``, ``<decisión>_title``)."""
        kind = symbol.kind
        if kind in _NOT_LOCALISED:
            return None
        if kind in _PROVINCE_KINDS:
            return f"PROV{symbol.name}"
        if kind == KIND_DECISION:
            return f"{symbol.name}_title"
        if kind == KIND_EVENT:
            title = symbol.attrs.get("title")
            return title if isinstance(title, str) else None
        if kind == KIND_PARTY:
            party = symbol.attrs.get("party")
            return party if isinstance(party, str) else None
        return symbol.name

    def _label(self, symbol: Symbol, loc, lang: str) -> str | None:
        if loc is None:
            return None
        key = self.loc_key_for(symbol)
        if not key:
            return None
        try:
            text = loc.lookup(key, lang, fallback="en")
        except (KeyError, ValueError):
            return None
        return text or None

    def search(self, text: str, *, kinds: Collection[str] = (), loc=None, lang: str = "es",
               limit: int = 50) -> list[Symbol]:
        """Buscador universal (Ctrl+K): por id o nombre («549», «PRU», «north_german») y, con ``loc``
        (``LocalisationDB``), por nombre localizado sin mayúsculas ni acentos («Berlín», «berlin»). Primero
        las coincidencias exactas, luego las que empiezan por ``text`` y luego las que lo contienen."""
        query = self._folded(text.strip())
        if not query:
            return []
        if kinds:
            order = list(dict.fromkeys(kinds))
        else:
            available = set(self._def_sources)
            if KIND_PROVINCE in available:
                available.add(KIND_SEA_PROVINCE)
            first = [k for k in SEARCH_PRIORITY if k in available]
            last = [k for k in _SEARCH_LAST if k in available]
            order = first + sorted(available - set(first) - set(last)) + last
        found: list[tuple[int, int, int, int, Symbol]] = []
        for priority, kind in enumerate(order):
            for position, symbol in enumerate(self.symbols(kind)):
                shown = short_name(symbol)
                rank = self._rank(self._folded(shown), query)
                if loc is not None and kind not in _NOT_LOCALISED and rank != 0:
                    label = self._label(symbol, loc, lang)
                    if label is not None:
                        other = self._rank(self._folded(label), query)
                        if other is not None and (rank is None or other < rank):
                            rank = other
                if rank is not None:
                    found.append((rank, priority, len(shown), position, symbol))
        found.sort(key=lambda item: item[:4])
        return [item[4] for item in found[:max(0, limit)]]

    @staticmethod
    def _rank(candidate: str, query: str) -> int | None:
        if candidate == query:
            return 0
        if candidate.startswith(query):
            return 1
        if query in candidate:
            return 2
        return None

    def display(self, kind: str, name: str, loc=None, lang: str = "es") -> str:
        """Nombre para mostrar: «Prusia (PRU)», «549 Berlín»; sin ``loc`` o sin texto, ``name``."""
        symbol = self.get(kind, name)
        if symbol is None:
            symbol = Symbol(kind, name, VPath.of("x"), None, LayerKind.MOD)
        label = self._label(symbol, loc, lang)
        if not label:
            return name
        if kind in _PROVINCE_KINDS:
            return f"{name} {label}"
        if kind == KIND_PARTY:
            party = symbol.attrs.get("party", name)
            return label if label == party else f"{label} ({party})"
        if kind in (KIND_BOOKMARK,) or label == name:
            return label
        return f"{label} ({name})"

    # --- mantenimiento ------------------------------------------------------------------------------

    def apply(self, facts: Iterable[FileFacts], removed: Iterable[tuple[VPath, object]] = (), *,
              snapshot=None) -> None:
        """Sustituye los hechos de cada ``(rel, capa)`` de ``facts`` y quita los de ``removed`` (pares
        ``(rel, LayerKind)``). ``snapshot`` actualiza el orden de capas (un archivo nuevo del mod puede ganar
        ahora). Sube ``generation``."""
        touched_keys: set[str] = set()
        kinds: set[str] = set()
        if snapshot is not None:
            had_snapshot = self._snapshot is not None
            old_hidden = self._hidden
            self._snapshot = snapshot
            self._hidden = snapshot.hidden
            if had_snapshot:
                touched_keys.update(old_hidden ^ self._hidden)
            else:
                touched_keys.update(self._layers)       # de «todos ganan» a capas: se recalcula todo
        for rel, layer in removed:
            key = VPath.of(rel).key
            kinds |= self._kinds_of(key)
            kinds |= self._put(key, layer, None)
            touched_keys.add(key)
        grouped: dict[tuple[str, LayerKind], list[FileFacts]] = {}
        for item in facts:
            grouped.setdefault((item.rel.key, item.layer), []).append(item)
        for (key, layer), items in grouped.items():
            kinds |= self._kinds_of(key)
            kinds |= self._put(key, layer, items)
            touched_keys.add(key)
        for key in touched_keys:
            before = self._effective.get(key)
            after = self._winner(key)
            if after is None:
                self._effective.pop(key, None)
            else:
                self._effective[key] = after
            if before is not after:
                kinds |= self._kinds_of(key)
        self._invalidate(kinds)
        self.generation += 1

    def copy(self) -> SymbolIndex:
        """Copia independiente para otro hilo (ampliación): comparte los ``FileFacts`` (inmutables) pero no las
        tablas ni las cachés, así que la tarea de validación la consulta mientras el hilo de la interfaz sigue
        haciendo ``apply`` sobre el original. Cuesta copiar unos diccionarios (milisegundos)."""
        other = SymbolIndex.__new__(SymbolIndex)
        other.generation = self.generation
        other._snapshot = self._snapshot
        other._hidden = self._hidden
        other._slots = dict(self._slots)
        other._layers = {key: set(layers) for key, layers in self._layers.items()}
        other._effective = dict(self._effective)
        other._def_sources = {kind: set(sources) for kind, sources in self._def_sources.items()}
        other._ref_sources = {kind: set(sources) for kind, sources in self._ref_sources.items()}
        other._defs = {}
        other._refs = {}
        other._fold = {}
        return other

    def facts(self) -> list[FileFacts]:
        """Todos los hechos que contiene (para la caché y las pruebas)."""
        return [item for key in sorted(self._slots, key=lambda k: (k[0], k[1].value))
                for item in self._slots[key].facts]

    def facts_of(self, rel: VPath) -> list[FileFacts]:
        """Hechos de ``rel`` en todas las capas (ganador primero). Ampliación."""
        key = VPath.of(rel).key
        layers = sorted(self._layers.get(key, ()), key=_PRIORITY.index)
        return [item for layer in layers for item in self._slots[(key, layer)].facts]
