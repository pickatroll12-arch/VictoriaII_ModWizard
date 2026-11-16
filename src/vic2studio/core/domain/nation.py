"""Fachada de país: ver y editar un país en la fecha de trabajo (ficha nacional, wizard §14.2). Iteración 6.

Como ``core.domain.province`` para las provincias: junta el registro de su historia (``country_history``, historia
fechada con ``HistoryView``), su archivo de país (``country``), sus partidos (del índice) y sus provincias (las
historias de provincia del índice), sin que la interfaz conozca los archivos.

Reglas (las mismas que la fachada de provincia):

- **Leer no escribe** (I4).
- **Editar va dentro de la transacción de quien llama** (I5): la ficha abre una con ``session.edit`` por gesto.
- **Dónde se escribe** lo decide ``HistoryView`` (§10.6): en la fecha de inicio, la entrada sin fecha; después, el
  último bloque fechado del intervalo (bookmark anterior, fecha]; si no hay, uno nuevo.
- Las claves que el esquema no declara (reformas ``<grupo> = <opción>``, tecnologías ``<tecnología> = 1`` e
  invenciones) se escriben aquí con la misma regla de destino (``set_raw``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.nodes import Block, ClausewitzDate, Entry, Scalar

if TYPE_CHECKING:
    from ..rules.game import GameRules
    from ..schema import Entities
    from ..schema.history import HistoryView

KIND = "country_history"
UNDO_COUNTRY_SET = "undo.country_set"
UNDO_COUNTRY_TECH = "undo.country_tech"
UNDO_COUNTRY_REFORMS = "undo.country_reforms"
UNDO_COUNTRY_UPPER_HOUSE = "undo.country_upper_house"
UNDO_COUNTRY_FILE = "undo.country_file"
UNDO_COUNTRY_FLAGS = "undo.country_flags"
UNDO_COUNTRY_TEXTS = "undo.country_texts"
REFORM_CATEGORIES = ("political_reforms", "social_reforms")
UNCIV_CATEGORIES = ("economic_reforms", "military_reforms")


class NationError(ValueError):
    """``no_history`` (el TAG no tiene historia), ``no_file`` (no tiene archivo de país), ``bad_value`` (un valor
    que no se puede escribir)."""

    def __init__(self, code: str, tag: str, detail: str = "") -> None:
        self.code = code
        self.tag = tag
        self.detail = detail
        super().__init__(f"{code}: {tag}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True)
class PartyInfo:
    name: str
    ideology: str
    start: str | None
    end: str | None
    policies: Mapping[str, str]

    def active_at(self, date: ClausewitzDate) -> bool:
        def key(text, default):
            try:
                parsed = ClausewitzDate.parse(text) if text else None
            except ValueError:
                parsed = None
            return (parsed.year, parsed.month, parsed.day) if parsed else default
        today = (date.year, date.month, date.day)
        return key(self.start, (0, 0, 0)) <= today < key(self.end, (99999, 0, 0))


def _date_tuple(date: ClausewitzDate) -> tuple:
    return (date.year, date.month, date.day)


class Countries:
    def __init__(self, entities: Entities, rules: GameRules | None) -> None:
        self.entities = entities
        self.rules = rules

    @property
    def index(self):
        return self.entities.index

    @property
    def bookmarks(self) -> tuple:
        return tuple(getattr(self.rules, "bookmarks", ()) or ())

    # --- lectura ----------------------------------------------------------------------------------

    def tags(self) -> list[str]:
        from ..index.model import KIND_TAG

        return sorted(self.index.names(KIND_TAG)) if self.index is not None else []

    def record(self, tag: str):
        from ..index.model import KIND_COUNTRY_HISTORY
        from ..schema.record import RecordRef

        index = self.index
        symbol = index.get(KIND_COUNTRY_HISTORY, tag.upper()) if index is not None else None
        rel = symbol.rel if symbol is not None else None
        try:
            return self.entities.open(RecordRef(KIND, tag.upper(), rel))
        except (KeyError, LookupError, FileNotFoundError, ValueError):
            return None

    def view(self, tag: str, date: ClausewitzDate | None) -> HistoryView | None:
        record = self.record(tag)
        if record is None:
            return None
        return record.at(date, self.bookmarks)

    def _writable(self, tag: str, date) -> HistoryView:
        view = self.view(tag, date)
        if view is None:
            raise NationError("no_history", tag)
        return view

    def get(self, tag: str, key: str, date) -> object:
        """Valor vigente de ``key`` en ``date`` (None si no hay)."""
        view = self.view(tag, date)
        if view is None:
            return None
        from ..schema import MISSING

        value = view.get(key).value
        return None if value is MISSING else value

    def values(self, tag: str, date) -> dict[str, object]:
        """Todas las claves escalares vigentes en ``date`` (la última gana), para la ficha y las pruebas."""
        view = self.view(tag, date)
        if view is None:
            return {}
        found: dict[str, object] = {}
        for _when, block in view._layers():
            for entry in block.entries:
                if entry.key is not None and isinstance(entry.value, Scalar):
                    found[entry.key.text] = entry.value.text
        return found

    def technologies(self, tag: str, date) -> set[str]:
        from ..index.model import KIND_INVENTION, KIND_TECHNOLOGY

        index = self.index
        values = self.values(tag, date)
        known = set()
        for key, value in values.items():
            if index is not None and index.exists(KIND_TECHNOLOGY, key) and str(value).strip() not in ("0", "no"):
                known.add(key)
            elif index is not None and index.exists(KIND_INVENTION, key) and str(value).lower() == "yes":
                known.add(key)
        return known

    def reform_groups(self, *, civilized: bool = True) -> dict[str, list[str]]:
        """Grupo → opciones de las categorías de reformas (las económicas y militares solo si no es civilizado)."""
        from ..index.model import KIND_ISSUE_GROUP

        categories = REFORM_CATEGORIES + (() if civilized else UNCIV_CATEGORIES)
        groups = {}
        for symbol in self.index.symbols(KIND_ISSUE_GROUP) if self.index is not None else ():
            if (symbol.attrs or {}).get("category") in categories:
                groups[symbol.name] = list((symbol.attrs or {}).get("options") or ())
        return groups

    def reforms(self, tag: str, date) -> dict[str, str]:
        values = self.values(tag, date)
        groups = self.reform_groups(civilized=False)
        return {group: str(values[group]) for group in groups if group in values}

    def upper_house(self, tag: str, date) -> dict[str, float]:
        view = self.view(tag, date)
        if view is None:
            return {}
        found: dict[str, float] = {}
        for _when, block in view._layers():
            for entry in block.entries:
                if entry.key is not None and entry.key.text.lower() == "upper_house" and isinstance(entry.value, Block):
                    found = {}
                    for child in entry.value.entries:
                        if child.key is not None and isinstance(child.value, Scalar):
                            try:
                                found[child.key.text] = float(child.value.text)
                            except ValueError:
                                continue
        return found

    def parties(self, tag: str) -> list[PartyInfo]:
        from ..index.model import KIND_PARTY
        from ..validate.rules.countries import country_file_of

        index = self.index
        file = country_file_of(index, tag.upper()) if index is not None else None
        if file is None:
            return []
        return [PartyInfo(s.attrs.get("party") or "", s.attrs.get("ideology") or "", s.attrs.get("start"),
                          s.attrs.get("end"), dict(s.attrs.get("policies") or {}))
                for s in index.symbols(KIND_PARTY) if (s.attrs or {}).get("country_file") == file]

    def country_file(self, tag: str) -> str | None:
        from ..validate.rules.countries import country_file_of

        return country_file_of(self.index, tag.upper()) if self.index is not None else None

    def cultures(self, tag: str, date) -> list[str]:
        """Las culturas aceptadas vigentes en ``date`` (``culture = …`` acumulativas)."""
        view = self.view(tag, date)
        if view is None:
            return []
        return [str(item.value) for item in view.get_set("culture")]

    def country_record(self, tag: str):
        """El registro ``country`` del archivo de país que nombra ``countries.txt`` (None si no hay)."""
        from ..index.model import KIND_TAG
        from ..schema.record import RecordRef
        from ..vfs.paths import VPath

        file = self.index.attrs(KIND_TAG, tag.upper(), "file") if self.index is not None else None
        if not isinstance(file, str) or not file.strip('"'):
            return None
        rel = VPath.of("common/" + file.strip('"'))
        try:
            return self.entities.open(RecordRef("country", rel.name.lower(), rel))
        except (KeyError, LookupError, FileNotFoundError, ValueError):
            return None

    def file_value(self, tag: str, key: str) -> object:
        """Un campo del archivo de país (``color``, ``graphical_culture``); None si no hay."""
        from ..schema import MISSING

        record = self.country_record(tag)
        if record is None:
            return None
        value = record.get(key)
        return None if value is MISSING else value

    def provinces(self, tag: str, date) -> list[int]:
        """Las provincias cuyo dueño en ``date`` es ``tag`` (de las historias del índice)."""
        from ..index.model import KIND_PROVINCE_HISTORY
        from ..validate.rules.countries import history_at

        if self.index is None:
            return []
        when = date or (self.bookmarks[0] if self.bookmarks else ClausewitzDate(1836, 1, 1))
        owned = []
        for symbol in self.index.symbols(KIND_PROVINCE_HISTORY):
            if str(history_at(symbol, when).get("owner") or "").upper() == tag.upper() and symbol.name.isdigit():
                owned.append(int(symbol.name))
        return sorted(owned)

    # --- escritura (dentro de la transacción de quien llama) ----------------------------------------------

    def set(self, tag: str, key: str, value: object, date) -> bool:
        """Un campo del esquema (gobierno, prestigio, capital…); None lo quita. False si ya valía eso."""
        view = self._writable(tag, date)
        from ..schema import MISSING

        current = view.get(key).value
        if (current is not MISSING and value is not None and str(current) == str(value)) or \
                (current is MISSING and value is None):
            return False
        try:
            view.set(key, value)
        except (KeyError, ValueError) as exc:
            raise NationError("bad_value", tag, f"{key}: {exc}") from None
        return True

    def set_raw(self, tag: str, key: str, text: str | None, date) -> bool:
        """Una clave escalar que el esquema no declara (reforma, tecnología, invención), como texto; None la quita
        del bloque destino. Misma regla de destino que ``HistoryView.set``."""
        view = self._writable(tag, date)
        current = view.get(key)
        from ..schema import MISSING

        if text is None:
            if current.entry is None:
                return False
            target = view.target_block(create=False)
            if target is None:
                return False
            entries = [e for e in target.entries if e.key is not None and e.key.text.lower() == key.lower()]
            if not entries:
                return False
            view.record._touch()
            target = view.target_block(create=False)
            for entry in [e for e in target.entries if e.key is not None and e.key.text.lower() == key.lower()]:
                target.remove_entry(entry)
            return True
        if current.value is not MISSING and str(current.value) == text:
            return False
        view.record._touch()
        if view.at_start() and current.entry is not None and current.date is not None:
            current = view.get(key)
            current.entry.value = Scalar(text)
            return True
        target = view.target_block(create=True)
        entries = [e for e in target.entries if e.key is not None and e.key.text.lower() == key.lower()
                   and isinstance(e.value, Scalar)]
        if entries:
            entries[-1].value = Scalar(text)
        else:
            _append(view, target, key, Scalar(text))
        return True

    def set_cultures(self, tag: str, wanted: Iterable[str], date) -> list[str]:
        """Deja aceptadas exactamente ``wanted`` en ``date``; devuelve las que cambiaron."""
        view = self._writable(tag, date)
        current = {name.upper(): name for name in self.cultures(tag, date)}
        wanted = [name for name in wanted if name]
        changed = []
        for name in [current[key] for key in current if key not in {w.upper() for w in wanted}]:
            view.remove("culture", name)
            changed.append(name)
        for name in wanted:
            if name.upper() not in current and view.add("culture", name) is not None:
                changed.append(name)
        return changed

    def set_file_value(self, tag: str, key: str, value: object) -> bool:
        """Escribe un campo del archivo de país; False si ya valía eso. ``NationError("no_file")`` si no hay."""
        record = self.country_record(tag)
        if record is None:
            raise NationError("no_file", tag)
        if self.file_value(tag, key) == value:
            return False
        try:
            record.set(key, value)
        except (KeyError, ValueError) as exc:
            raise NationError("bad_value", tag, f"{key}: {exc}") from None
        return True

    def add_party(self, tag: str, name: str, ideology: str, start_date: str = "1800.1.1",
                  end_date: str = "2000.1.1", policies: Mapping[str, str] | None = None) -> None:
        """Añade un ``party = { … }`` al archivo de país, tras el último (H12: el nombre puede repetirse)."""
        record = self.country_record(tag)
        if record is None:
            raise NationError("no_file", tag)
        if not name.strip() or not ideology:
            raise NationError("bad_value", tag, "party")
        block = Block()
        block.append("name", Scalar(name.strip(), True))
        block.append("start_date", Scalar(start_date))
        block.append("end_date", Scalar(end_date))
        block.append("ideology", Scalar(ideology))
        for key, option in (policies or {}).items():
            if option:
                block.append(key, Scalar(option))
        record._touch()
        parties = record.block.find_all("party")
        if parties:
            record.block.insert_after(parties[-1], "party", block)
        else:
            record.block.append("party", block)

    def remove_party(self, tag: str, position: int) -> str:
        """Quita el partido ``position`` (orden del archivo); devuelve su nombre."""
        record = self.country_record(tag)
        if record is None:
            raise NationError("no_file", tag)
        groups = record.groups("party")
        if not 0 <= position < len(groups):
            raise NationError("bad_value", tag, f"party #{position}")
        name = groups[position].block.get_text("name") or ""
        record._touch()
        record.block.remove_entry(record.groups("party")[position]._entry)
        return name

    def set_technologies(self, tag: str, wanted: Iterable[str], date) -> list[str]:
        """Deja conocidas exactamente ``wanted`` (de las tecnologías e invenciones del índice); devuelve las que
        cambiaron. Una tecnología que deja de conocerse se quita del bloque destino si está ahí, o se pone a 0."""
        from ..index.model import KIND_INVENTION

        wanted = set(wanted)
        known = self.technologies(tag, date)
        changed = []
        for name in sorted(wanted - known):
            invention = self.index is not None and self.index.exists(KIND_INVENTION, name)
            if self.set_raw(tag, name, "yes" if invention else "1", date):
                changed.append(name)
        for name in sorted(known - wanted):
            invention = self.index is not None and self.index.exists(KIND_INVENTION, name)
            view = self._writable(tag, date)
            target = view.target_block(create=False)
            here = target is not None and any(e.key is not None and e.key.text == name for e in target.entries)
            if here and self.set_raw(tag, name, None, date) and name not in self.technologies(tag, date):
                changed.append(name)
            elif self.set_raw(tag, name, "no" if invention else "0", date):
                changed.append(name)
        return changed

    def set_reforms(self, tag: str, reforms: Mapping[str, str], date) -> list[str]:
        changed = []
        for group, option in reforms.items():
            if option and self.set_raw(tag, group, option, date):
                changed.append(group)
        return changed

    def set_upper_house(self, tag: str, shares: Mapping[str, float], date) -> bool:
        """Sustituye el bloque ``upper_house`` vigente en el bloque destino (o lo crea ahí)."""
        if self.upper_house(tag, date) == {k: float(v) for k, v in shares.items() if v}:
            return False
        view = self._writable(tag, date)
        view.record._touch()
        target = view.target_block(create=True)
        block = Block()
        for ideology, share in shares.items():
            if share:
                block.append(ideology, Scalar(_number(share)))
        existing: list[Entry] = [e for e in target.entries if e.key is not None
                                 and e.key.text.lower() == "upper_house" and isinstance(e.value, Block)]
        if existing:
            existing[-1].value = block
        else:
            _append(view, target, "upper_house", block)
        return True


def _append(view, target: Block, key: str, value) -> Entry:
    """Al final del bloque destino; en la raíz, delante del primer bloque fechado (nunca detrás, §10.7)."""
    if target is view.record.block:
        from ..schema.placement import first_dated_index

        index = first_dated_index(target)
        if index is not None:
            return target.insert(index, key, value)
    return target.append(key, value)


def _number(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")
