"""Conversión entre el árbol Clausewitz y estructuras JSON.

Esquema de ``to_json`` / ``from_json``::

    bloque:  {"type": "block", "entries": [entrada, ...]}
    entrada: {"key": escalar | null, "op": "=" | "<" | ... | null, "value": escalar | bloque}
    escalar: {"type": "scalar", "text": "GEL", "quoted": false}

Con ``include_comments`` se añaden estas claves opcionales, solo si hay comentario:

- en una entrada, ``"comments": ["# ..."]`` (los de las líneas propias de encima;
  los de la cabecera del archivo son de su primera entrada) y ``"line_comment":
  "# ..."`` (el del final de su línea, también tras la ``}`` de su bloque);
- en un bloque, ``"open_comment": "# ..."`` (en la línea de su ``{``) y
  ``"trailing_comments": ["# ..."]`` (los de las líneas de encima de su ``}`` o, en
  el documento, del final del archivo).

El texto descartado por errores de sintaxis no forma parte del JSON. Invariante,
para todo ``j = to_json(doc, include_comments=c)``::

    to_json(parse(format_canonical(from_json(j), comments=c)).document, include_comments=c) == j

Los recorridos son iterativos (sin límite de profundidad) y un bloque que se
contiene a sí mismo da ``EditError("cycle")``. ``iter_json`` escribe el JSON por
trozos sin recursión: ``json.dump`` es recursivo y falla con anidamientos profundos.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Iterator

from .diagnostics import EditError, EditTypeError
from .nodes import OPERATORS, Block, Document, Entry, Scalar, normalize_comments, normalize_line_comment

_INT_RE = re.compile(r"[+-]?[0-9]+")
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_NODE_TYPES = ("block", "scalar")
_ENCODER = json.JSONEncoder(ensure_ascii=False)
_END = object()


def _preorder(block: Block) -> Iterator[tuple[int, int, Entry]]:
    """``(profundidad, índice, entrada)`` de todo lo que hay bajo ``block``, en preorden y sin recursión.

    La profundidad de las entradas de ``block`` es 0. Un ciclo da ``EditError("cycle")``.
    """
    active = {id(block)}
    blocks = [block]
    stack = [enumerate(block.entries)]
    while stack:
        for index, entry in stack[-1]:
            yield len(stack) - 1, index, entry
            value = entry._value
            if value.__class__ is not Scalar:
                if id(value) in active:
                    raise EditError("cycle")
                active.add(id(value))
                blocks.append(value)
                stack.append(enumerate(value.entries))
                break
        else:
            stack.pop()
            active.discard(id(blocks.pop()))


# --- to_json ------------------------------------------------------------------------


def _scalar_json(scalar: Scalar) -> dict:
    return {"type": "scalar", "text": scalar._text, "quoted": scalar._quoted}


def _block_json(block: Block, include_comments: bool) -> dict:
    """Bloque del esquema con sus comentarios propios; las entradas se añaden después."""
    result = {"type": "block"}
    if include_comments:
        opening = block.open_comment
        if opening:
            result["open_comment"] = opening
    result["entries"] = []
    if include_comments:
        trailing = block.trailing_comments
        if trailing:
            result["trailing_comments"] = trailing
    return result


def _entry_json(entry: Entry, include_comments: bool) -> dict:
    """Entrada del esquema; si su valor es un bloque, sin sus entradas."""
    key = entry._key
    value = entry._value
    item = {
        "key": None if key is None else _scalar_json(key),
        "op": entry._op,
        "value": _scalar_json(value) if value.__class__ is Scalar else _block_json(value, include_comments),
    }
    if include_comments:
        comments = entry.comments
        if comments:
            item["comments"] = comments
        line_comment = entry.line_comment
        if line_comment:
            item["line_comment"] = line_comment
    return item


def to_json(node, *, include_comments: bool = False) -> dict:
    """Árbol como dict serializable con ``json`` (ver el esquema del módulo)."""
    if isinstance(node, Scalar):
        return _scalar_json(node)
    if isinstance(node, Entry):
        result = _entry_json(node, include_comments)
        block = node._value
        if block.__class__ is Scalar:
            return result
        root = result["value"]
    elif isinstance(node, Block):
        result = root = _block_json(node, include_comments)
        block = node
    else:
        raise EditTypeError("not_a_node", {"type": type(node).__name__})
    targets = [root["entries"]]
    for depth, _, entry in _preorder(block):
        del targets[depth + 1:]
        item = _entry_json(entry, include_comments)
        targets[depth].append(item)
        if entry._value.__class__ is not Scalar:
            targets.append(item["value"]["entries"])
    return result


# --- from_json ----------------------------------------------------------------------
# La ruta de un elemento (``$.entries[0].value.entries[2].key``) solo se compone al
# fallar: cada bloque guarda ``(ruta del padre, índice de su entrada)``.


def _path(where, index: int | None = None, field: str = "") -> str:
    indexes = []
    while where is not None:
        where, position = where
        indexes.append(position)
    path = "$" + "".join(f".entries[{position}].value" for position in reversed(indexes))
    if index is not None:
        path += f".entries[{index}]"
    return path + field


def _fail(code: str, where, index: int | None = None, field: str = "", **params) -> EditError:
    params["where"] = _path(where, index, field)
    return EditError(code, params)


def _located(error: EditError, where, index: int | None, field: str) -> EditError:
    """El mismo error con la ruta del elemento JSON que lo causó."""
    return error.__class__(error.code, {**error.params, "where": _path(where, index, field)})


def _node_type(obj, where, index: int | None = None, field: str = "") -> str:
    if not isinstance(obj, dict):
        raise _fail("json_expected_object", where, index, field)
    kind = obj.get("type")
    if kind is None:
        raise _fail("json_missing_type", where, index, field)
    if kind not in _NODE_TYPES:
        raise _fail("json_unknown_type", where, index, field, type=repr(kind))
    return kind


def _scalar_fields(obj: dict, where, index: int, field: str) -> Scalar:
    text = obj.get("text")
    quoted = obj.get("quoted", False)
    if not isinstance(text, str) or not isinstance(quoted, bool):
        raise _fail("json_scalar_fields", where, index, field)
    try:
        return Scalar._lenient(text, quoted)
    except EditError as error:
        raise _located(error, where, index, field) from None


def _comments_field(value, where, index: int | None, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(comment, str) for comment in value):
        raise _fail("json_expected_strings", where, index, field)
    try:
        return normalize_comments(value)
    except EditError as error:
        raise _located(error, where, index, field) from None


def _line_comment_field(value, where, index: int | None, field: str) -> str:
    if value is not None and not isinstance(value, str):
        raise _fail("json_expected_string", where, index, field)
    try:
        return normalize_line_comment(value)
    except EditError as error:
        raise _located(error, where, index, field) from None


def _new_block(source: dict, block: Block, where):
    """Pone en ``block`` los comentarios propios de ``source`` y devuelve sus entradas JSON."""
    if where is not None and "open_comment" in source:  # el documento no tiene "{"
        block._open_comment = _line_comment_field(source["open_comment"], where, None, ".open_comment")
    if "trailing_comments" in source:
        block._trailing_comments = _comments_field(source["trailing_comments"], where, None, ".trailing_comments")
    items = source.get("entries")
    if not isinstance(items, list):
        raise _fail("json_expected_list", where, None, ".entries")
    return enumerate(items)


def from_json(obj) -> Document:
    """Construye un ``Document`` nuevo (sin formato original) desde el esquema de ``to_json``.

    Admite todo lo que puede leerse de un archivo (cadenas de varias líneas,
    claves con caracteres invisibles...). Lanza ``EditError`` con la ruta del
    elemento inválido en ``params["where"]`` (``$.entries[0].value.entries[2].key``).
    """
    if not isinstance(obj, dict) or _node_type(obj, None) != "block":
        raise _fail("json_expected_block", None)
    document = Document()
    active = {id(obj)}  # objetos JSON en el camino actual: uno que se contiene a sí mismo es un ciclo
    stack = [(obj, document, None, _new_block(obj, document, None))]
    while stack:
        source, block, where, items = stack[-1]
        for index, item in items:
            if not isinstance(item, dict):
                raise _fail("json_expected_object", where, index)
            raw_key, op, raw_value = item.get("key"), item.get("op"), item.get("value")
            key = None
            if raw_key is not None:
                if _node_type(raw_key, where, index, ".key") != "scalar":
                    raise _fail("json_expected_scalar", where, index, ".key")
                key = _scalar_fields(raw_key, where, index, ".key")
            if (key is None) != (op is None):
                raise _fail("json_key_op", where, index)
            if op is not None and op not in OPERATORS:
                raise _fail("invalid_operator", where, index, ".op", op=op, allowed=", ".join(OPERATORS))
            child = None
            if _node_type(raw_value, where, index, ".value") == "block":
                if id(raw_value) in active:
                    raise _fail("cycle", where, index, ".value")
                value = child = Block()
                child_where = (where, index)
                child_items = _new_block(raw_value, child, child_where)
            else:
                value = _scalar_fields(raw_value, where, index, ".value")
            entry = Entry._made(key, value, op)
            if "comments" in item:
                entry._comments = _comments_field(item["comments"], where, index, ".comments")
            if "line_comment" in item:
                entry._line_comment = _line_comment_field(item["line_comment"], where, index, ".line_comment")
            block.entries.append(entry)
            if child is not None:
                active.add(id(raw_value))
                stack.append((raw_value, child, child_where, child_items))
                break
        else:
            active.discard(id(source))
            stack.pop()
    return document


# --- vistas de lectura ------------------------------------------------------------------


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
    """``(contenedor vacío, claves repetidas)``: dict si todas las entradas tienen clave; si no, list."""
    if all(entry._key is not None for entry in block.entries):
        counts = Counter(entry._key._text for entry in block.entries)
        return {}, {key for key, count in counts.items() if count > 1}
    return [], None


def simplify(node):
    """Vista con pérdidas para lectura rápida.

    Bloque solo con valores sueltos -> list; con asignaciones -> dict (las claves
    repetidas -> list en orden); mixto -> list con las asignaciones como dicts de
    una clave; vacío -> {}. Escalares sin comillas: enteros -> int, decimales ->
    float, yes/no -> bool; el resto (y todo lo entrecomillado) -> str. Se pierden
    los operadores de comparación, comentarios y formato.

    No sirve para escribir de vuelta: ``set(clave, simplify(...))`` convierte
    ``tag = GEL tag = MAJ`` en ``tag = { GEL MAJ }``. Para editar se usan las
    entradas (``find_all``, ``remove``...) y, para construir claves repetidas o con
    operadores, ``Block.from_pairs``.
    """
    if isinstance(node, Entry):
        node = node._value
    if isinstance(node, Scalar):
        return _simple_scalar(node)
    if not isinstance(node, Block):
        raise EditTypeError("not_a_node", {"type": type(node).__name__})
    root = _simple_container(node)
    targets = [root]
    for depth, _, entry in _preorder(node):
        del targets[depth + 1:]
        target, repeated = targets[depth]
        value = entry._value
        if value.__class__ is Scalar:
            simple = _simple_scalar(value)
        else:
            container = _simple_container(value)
            targets.append(container)
            simple = container[0]
        key = entry._key
        if repeated is None:
            target.append(simple if key is None else {key._text: simple})
        elif key._text in repeated:
            target.setdefault(key._text, []).append(simple)
        else:
            target[key._text] = simple
    return root[0]


def walk(node) -> Iterator[tuple[tuple[str, ...], Entry]]:
    """Recorre en profundidad (preorden) todas las entradas bajo ``node``.

    Devuelve ``(ruta, entrada)``; la ruta acumula las claves desde la raíz e
    incluye la de la propia entrada. Los valores sueltos aparecen como ``"[i]"``
    (su posición en el bloque). Cada ruta es una tupla nueva: la memoria es
    proporcional a la profundidad, no a su cuadrado.
    """
    if isinstance(node, Entry):
        name = "[0]" if node._key is None else node._key._text
        yield (name,), node
        if node._value.__class__ is Scalar:
            return
        names, block = [name], node._value
    elif isinstance(node, Block):
        names, block = [], node
    else:
        raise EditTypeError("not_a_node", {"type": type(node).__name__})
    base = len(names)
    for depth, index, entry in _preorder(block):
        del names[base + depth:]
        names.append(f"[{index}]" if entry._key is None else entry._key._text)
        yield tuple(names), entry


def iter_json(value, *, indent: int = 2) -> Iterator[str]:
    """Trozos de ``json.dumps(value, ensure_ascii=False, indent=indent)``, sin recursión.

    Sirve para el JSON de ``to_json`` o ``simplify`` a cualquier profundidad. Admite
    dict (con claves str), list, tuple, str, int, float, bool y None. Un contenedor
    que se contiene a sí mismo da ``EditError("cycle")`` (un ``ValueError``, como en
    ``json.dumps``).
    """
    unit = " " * indent
    encode = _ENCODER.encode
    stack = []  # [elementos pendientes, cierre, ¿ya se escribió alguno?, id] de cada contenedor abierto
    active = set()  # ids de los contenedores abiertos
    item = value
    while True:
        if isinstance(item, (dict, list, tuple)):
            if not item:
                yield "{}" if isinstance(item, dict) else "[]"
            elif id(item) in active:
                raise EditError("cycle")
            else:
                active.add(id(item))
                if isinstance(item, dict):
                    stack.append([iter(item.items()), "}", False, id(item)])
                    yield "{"
                else:
                    stack.append([iter(item), "]", False, id(item)])
                    yield "["
        elif item is None:
            yield "null"
        elif item is True:
            yield "true"
        elif item is False:
            yield "false"
        else:
            yield encode(item)
        while stack:
            frame = stack[-1]
            following = next(frame[0], _END)
            if following is _END:
                stack.pop()
                active.discard(frame[3])
                yield "\n" + unit * len(stack) + frame[1]
                continue
            prefix = (",\n" if frame[2] else "\n") + unit * len(stack)
            frame[2] = True
            if frame[1] == "}":
                key, item = following
                yield prefix + encode(key) + ": "
            else:
                item = following
                yield prefix
            break
        else:
            return
