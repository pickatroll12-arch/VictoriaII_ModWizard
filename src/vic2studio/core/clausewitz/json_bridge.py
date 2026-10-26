"""Conversión entre el árbol Clausewitz y estructuras JSON.

Esquema de ``to_json`` / ``from_json``::

    bloque:  {"type": "block", "entries": [entrada, ...]}
    entrada: {"key": escalar | null, "op": "=" | "<" | ... | null, "value": escalar | bloque}
    escalar: {"type": "scalar", "text": "GEL", "quoted": false}

Con ``include_comments`` cada entrada puede llevar ``"comments": ["# ..."]`` (los
de sus líneas previas) y cada bloque ``"trailing_comments"`` (los anteriores a su
``}``). El texto descartado por errores de sintaxis no forma parte del JSON.

Invariante: ``to_json(parse(format_canonical(from_json(j))).document) == j`` para
todo ``j = to_json(doc)``. Todos los recorridos son iterativos.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterator

from .nodes import OPERATORS, Block, Document, Entry, Scalar

_INT_RE = re.compile(r"[+-]?[0-9]+")
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def _scalar_json(scalar: Scalar) -> dict:
    return {"type": "scalar", "text": scalar._text, "quoted": scalar._quoted}


def _entry_json(entry: Entry, include_comments: bool, pending: list) -> dict:
    key = entry._key
    item = {"key": None if key is None else _scalar_json(key), "op": entry._op}
    value = entry._value
    if value.__class__ is Scalar:
        item["value"] = _scalar_json(value)
    else:
        child = {"type": "block", "entries": []}
        item["value"] = child
        pending.append((value, child))
    if include_comments:
        comments = entry.comments
        if comments:
            item["comments"] = comments
    return item


def _fill_blocks(pending: list, include_comments: bool) -> None:
    while pending:
        block, target = pending.pop()
        entries = target["entries"]
        for entry in block.entries:
            entries.append(_entry_json(entry, include_comments, pending))
        if include_comments:
            trailing = block.trailing_comments
            if trailing:
                target["trailing_comments"] = trailing


def to_json(node, *, include_comments: bool = False) -> dict:
    """Árbol como dict serializable con ``json`` (ver el esquema del módulo)."""
    if isinstance(node, Scalar):
        return _scalar_json(node)
    pending = []
    if isinstance(node, Entry):
        result = _entry_json(node, include_comments, pending)
    elif isinstance(node, Block):
        result = {"type": "block", "entries": []}
        pending.append((node, result))
    else:
        raise TypeError(f"no es un nodo Clausewitz: {type(node).__name__}")
    _fill_blocks(pending, include_comments)
    return result


def _scalar_from_json(obj, where: str) -> Scalar:
    if not isinstance(obj, dict) or obj.get("type") != "scalar":
        raise ValueError(f"{where}: se esperaba un escalar {{'type': 'scalar', ...}}")
    text = obj.get("text")
    quoted = obj.get("quoted", False)
    if not isinstance(text, str) or not isinstance(quoted, bool):
        raise ValueError(f"{where}: 'text' debe ser str y 'quoted' bool")
    try:
        return Scalar(text, quoted)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from None


def _comments_from_json(obj, where: str) -> list[str]:
    if not isinstance(obj, list) or not all(isinstance(c, str) for c in obj):
        raise ValueError(f"{where}: se esperaba una lista de cadenas")
    comments = []
    for comment in obj:
        for line in comment.replace("\r", "").split("\n"):
            line = line.rstrip()
            comments.append(line if line.startswith("#") else "# " + line if line else "#")
    return comments


def from_json(obj) -> Document:
    """Construye un ``Document`` nuevo (sin formato original) desde el esquema de ``to_json``.

    Lanza ``ValueError`` indicando la ruta del elemento inválido.
    """
    if not isinstance(obj, dict) or obj.get("type") != "block":
        raise ValueError("$: se esperaba un bloque {'type': 'block', 'entries': [...]}")
    document = Document()
    pending = [(obj, document, "$")]
    while pending:
        source, block, where = pending.pop()
        items = source.get("entries")
        if not isinstance(items, list):
            raise ValueError(f"{where}.entries: se esperaba una lista")
        for index, item in enumerate(items):
            here = f"{where}.entries[{index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{here}: se esperaba un objeto")
            raw_key, op, raw_value = item.get("key"), item.get("op"), item.get("value")
            key = None if raw_key is None else _scalar_from_json(raw_key, here + ".key")
            if (key is None) != (op is None):
                raise ValueError(f"{here}: 'key' y 'op' deben ser ambos null o ambos no nulos")
            if op is not None and op not in OPERATORS:
                raise ValueError(f"{here}.op: operador no válido {op!r}")
            if isinstance(raw_value, dict) and raw_value.get("type") == "block":
                value = Block()
                pending.append((raw_value, value, here + ".value"))
            else:
                value = _scalar_from_json(raw_value, here + ".value")
            entry = Entry(key, op, value)
            if "comments" in item:
                entry._comments = _comments_from_json(item["comments"], here + ".comments")
            block.entries.append(entry)
        if "trailing_comments" in source:
            block._trailing_comments = _comments_from_json(source["trailing_comments"], where + ".trailing_comments")
    return document


def _simple_scalar(scalar: Scalar):
    if scalar._quoted:
        return scalar._text
    text = scalar._text
    lowered = text.lower()
    if lowered == "yes":
        return True
    if lowered == "no":
        return False
    if _INT_RE.fullmatch(text):
        return int(text)
    if _NUMBER_RE.fullmatch(text):
        return float(text)
    return text


def _simple_container(block: Block):
    keyed = [entry._key is not None for entry in block.entries]
    return {} if all(keyed) else []


def simplify(node):
    """Vista con pérdidas para lectura rápida.

    Bloque solo con valores sueltos -> list; con asignaciones -> dict (las claves
    repetidas -> list en orden); mixto -> list con las asignaciones como dicts de
    una clave; vacío -> {}. Escalares sin comillas: enteros -> int, decimales ->
    float, yes/no -> bool; el resto (y todo lo entrecomillado) -> str. Se pierden
    los operadores de comparación, comentarios y formato.
    """
    if isinstance(node, Entry):
        node = node._value
    if isinstance(node, Scalar):
        return _simple_scalar(node)
    if not isinstance(node, Block):
        raise TypeError(f"no es un nodo Clausewitz: {type(node).__name__}")
    result = _simple_container(node)
    pending = [(node, result)]
    while pending:
        block, target = pending.pop()
        repeated = None
        if isinstance(target, dict):
            counts = Counter(entry._key._text for entry in block.entries)
            repeated = {key for key, count in counts.items() if count > 1}
        for entry in block.entries:
            value = entry._value
            if value.__class__ is Scalar:
                simple = _simple_scalar(value)
            else:
                simple = _simple_container(value)
                pending.append((value, simple))
            if repeated is None:
                target.append(simple if entry._key is None else {entry._key._text: simple})
            elif entry._key._text in repeated:
                target.setdefault(entry._key._text, []).append(simple)
            else:
                target[entry._key._text] = simple
    return result


def walk(node) -> Iterator[tuple[tuple[str, ...], Entry]]:
    """Recorre en profundidad (preorden) todas las entradas bajo ``node``.

    Devuelve ``(ruta, entrada)``; la ruta acumula las claves desde la raíz e
    incluye la de la propia entrada. Los valores sueltos aparecen como ``"[i]"``
    (su posición en el bloque).
    """
    if isinstance(node, Entry):
        name = "[0]" if node._key is None else node._key._text
        yield (name,), node
        if node._value.__class__ is Scalar:
            return
        prefix, block = (name,), node._value
    elif isinstance(node, Block):
        prefix, block = (), node
    else:
        raise TypeError(f"no es un nodo Clausewitz: {type(node).__name__}")
    stack = [(prefix, iter(enumerate(block.entries)))]
    while stack:
        path, iterator = stack[-1]
        for index, entry in iterator:
            name = f"[{index}]" if entry._key is None else entry._key._text
            here = path + (name,)
            yield here, entry
            if entry._value.__class__ is not Scalar:
                stack.append((here, iter(enumerate(entry._value.entries))))
                break
        else:
            stack.pop()
