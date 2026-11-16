"""Frases legibles de un bloque de guion, en ES y EN (wizard §12.3).

«Se dispara si: el país es Aland o Borland, y estamos en 1842 o después, y antes de 1845». La frase sale
de las plantillas ``phrase`` y ``negated`` del catálogo y de los nombres localizados del índice
(``SymbolIndex.display``): ``tag = AAA`` dice «Aland», no «AAA». Se muestra bajo cada constructor y en las
vistas previas, y es de solo lectura: no escribe nada (I4).

Reglas:

- La raíz y ``AND`` unen con «y»; ``OR``, con «o»; ``NOT`` usa ``negated`` de cada hijo y, si un hijo no la
  tiene, antepone «no se cumple que». Un ``OR`` dentro de un ``AND`` va entre comas, sin paréntesis.
- Varios hijos seguidos con la misma clave dentro de un ``OR`` se funden: «el país es Aland o Borland».
- Un ámbito introduce a sus hijos: «en la capital: …», «en alguna provincia propia: …».
- Un valor que es un símbolo se nombra con su texto localizado y, si es un número (provincias, eventos),
  con el id entre paréntesis: «Capital (1)». Sin índice o sin texto se usa el id.
- Un nodo crudo se cita tal cual entre comillas latinas: «foo = bar».
- Los textos fijos («y», «o», «no se cumple que», los encabezados) son ``script.phrase.*`` de
  ``core/script/texts/script.<idioma>.json``.

Criterio 5 de la iteración 7: la frase del evento 31502 de vanilla nombra los dos países, «1842 o después»,
los tres gobiernos y «antes de 1845».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tree import ScriptNode, ScriptTree

# Encabezados de la frase completa: clave de texto ``script.phrase.lead.<encabezado>``.
LEAD_TRIGGER = "trigger"          # «Se dispara si: »
LEAD_POTENTIAL = "potential"      # «Aparece si: »
LEAD_ALLOW = "allow"              # «Se puede tomar si: »
LEAD_EFFECT = "effect"            # «Al tomarla: »
LEAD_IMMEDIATE = "immediate"      # «Nada más dispararse: »
LEAD_OPTION = "option"            # «Al elegirla: »
LEAD_MODIFIER = "modifier"        # «Si: »
LEADS = (LEAD_TRIGGER, LEAD_POTENTIAL, LEAD_ALLOW, LEAD_EFFECT, LEAD_IMMEDIATE, LEAD_OPTION, LEAD_MODIFIER)


@dataclass(frozen=True)
class PhraseLine:
    """Una línea de la frase desplegada: ``depth`` es la sangría, ``path`` el nodo del que sale
    (``ScriptNode.path``) y ``raw`` dice si es un nodo crudo (la interfaz lo pinta distinto)."""

    depth: int
    text: str
    path: tuple[int, ...]
    raw: bool = False


def _t(key: str, lang: str, **fmt) -> str:
    from ..texts import text

    return text(key, lang, **fmt)


def _symbol_text(kind: str | None, name: str, index, loc, lang: str) -> str:
    """Nombre localizado de un símbolo: «Aland»; si es un número, «Capital (1)»; sin texto, el id."""
    if kind is None or index is None or loc is None:
        return name
    try:
        symbol = index.get(kind, name)
        if symbol is None and kind == "province":
            symbol = index.get("sea_province", name)
        if symbol is None:
            return name
        key = index.loc_key_for(symbol)
        label = loc.lookup(key, lang, fallback="en") if key else None
    except Exception:  # noqa: BLE001 - una frase nunca rompe la interfaz
        return name
    if not label:
        return name
    return f"{label} ({name})" if name.isdigit() else label


def _family_kind(definition) -> str | None:
    """Tipo de símbolo de las claves de una familia (``tag`` y ``province`` para las de patrón)."""
    if definition is None or not definition.family:
        return None
    if definition.key_kind:
        return definition.key_kind
    if definition.scope_change is not None and str(definition.scope_change) == "province":
        return "province"
    if definition.scope_change is not None and str(definition.scope_change) == "country":
        return "tag"
    return None


def key_label(definition, lang: str, key: str | None = None, index=None, loc=None) -> str:
    """Etiqueta de una entrada del catálogo en ``lang`` (buscador y filas del constructor). En una familia,
    ``key`` es la clave concreta y ``{key}`` se sustituye por su nombre localizado."""
    template = definition.label.get(lang) or definition.label.get("en") or definition.name
    shown = _symbol_text(_family_kind(definition), key, index, loc, lang) if key else "…"
    try:
        return template.format(key=shown)
    except (KeyError, IndexError, ValueError):
        return template


def _value_text(value_type, node, index, loc, lang: str) -> str:
    """Un valor leído para la frase: los símbolos con su nombre localizado y los números como están."""
    text = getattr(node, "text", None)
    if text is None:
        return "?"
    kind = getattr(value_type, "kind", None)
    if kind is not None:
        return _symbol_text(kind, text, index, loc, lang)
    return text


def _is_no(node) -> bool:
    return getattr(node, "text", "").lower() == "no"


def _leaf(node: ScriptNode, lang: str, index, loc, negated: bool, values: list | None = None) -> str:
    """Frase de un nodo con valor (``VALUE`` o ``STRUCT``). ``values``: textos ya resueltos de varios
    nodos fundidos en un ``OR`` («Aland o Borland»)."""
    from .tree import NodeForm

    definition = node.definition
    form = node.form
    holes: dict[str, str] = {}
    if form is NodeForm.VALUE:
        value_type = definition.value
        if getattr(value_type, "widget", None) == "bool" and _is_no(node.entry.value):
            negated = not negated
        holes["value"] = values[0] if values else _value_text(value_type, node.entry.value, index, loc, lang)
    elif form is NodeForm.STRUCT:
        for item in definition.block:
            if node.entry.value.has(item.key):
                holes[item.key] = _value_text(item.type, node.entry.value.get(item.key), index, loc, lang)
            else:
                holes[item.key] = "?"
        holes.setdefault("value", holes.get("id", "?"))
    if definition.family:
        holes["key"] = _symbol_text(_family_kind(definition), node.key, index, loc, lang)
    template = (definition.negated.get(lang) if negated else None) or definition.phrase.get(lang)
    prefix = ""
    if negated and not definition.negated.get(lang):
        prefix = _t("script.phrase.not", lang) + " "
    if not template:
        template = key_label(definition, lang, node.key if definition.family else None, index, loc) \
            + (" {value}" if "value" in holes and form is NodeForm.VALUE else "")
    try:
        return prefix + template.format(**holes)
    except (KeyError, IndexError, ValueError):
        return prefix + template


def _raw(node: ScriptNode) -> str:
    return "«" + " ".join(node.source().split()) + "»"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _join(parts: list[str], word: str, lang: str, *, grouped: bool) -> str:
    """Une con «y»/«o». Con más de dos partes, o si alguna ya lleva su propio «o», separa con comas."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2 and not grouped:
        return f"{parts[0]} {word} {parts[1]}"
    return f", {word} ".join(parts)


def _children_phrase(node: ScriptNode, lang: str, index, loc, logic: str, negated: bool) -> str:
    """Frase de los hijos de un grupo. ``negated``: estamos dentro de un ``NOT`` (cada hijo, negado)."""
    from .tree import NodeForm

    children = node.children
    if not children:
        return _t(f"script.phrase.empty.{node.inner_kind.value}", lang)
    if logic == "NOT":
        parts = [node_phrase(child, lang, index, loc, negated=not negated) for child in children]
        word = _t("script.phrase.or" if negated else "script.phrase.and", lang)
        return _join(parts, word, lang, grouped=False)
    parts: list[str] = []
    grouped = False
    if logic == "OR":
        position = 0
        while position < len(children):
            child = children[position]
            run = [child]
            if child.form is NodeForm.VALUE and child.definition is not None:
                while position + len(run) < len(children):
                    other = children[position + len(run)]
                    if other.form is NodeForm.VALUE and other.definition is child.definition \
                            and other.key.lower() == child.key.lower() and not _is_no(other.entry.value):
                        run.append(other)
                    else:
                        break
            if len(run) > 1 and "{value}" in (child.definition.phrase.get(lang) or ""):
                word = _t("script.phrase.or", lang)
                values = [_value_text(child.definition.value, n.entry.value, index, loc, lang) for n in run]
                merged = _join(values, word, lang, grouped=False) if len(values) == 2 \
                    else ", ".join(values[:-1]) + f" {word} " + values[-1]
                parts.append(_leaf(child, lang, index, loc, negated, [merged]))
            else:
                parts.extend(node_phrase(n, lang, index, loc, negated=negated) for n in run)
            position += len(run)
        word = _t("script.phrase.and" if negated else "script.phrase.or", lang)
        return _join(parts, word, lang, grouped=False)
    for child in children:
        parts.append(node_phrase(child, lang, index, loc, negated=negated))
        grouped = grouped or child.logic == "OR"
    word = _t("script.phrase.or" if negated else "script.phrase.and", lang)
    return _join(parts, word, lang, grouped=grouped or len(parts) > 2)


def node_phrase(node: ScriptNode, lang: str, index=None, loc=None, *, negated: bool = False) -> str:
    """La frase de un nodo con sus hijos, sin encabezado ni punto final (``ScriptNode.summary``)."""
    from .tree import NodeForm

    form = node.form
    if node.entry is None:
        return _children_phrase(node, lang, index, loc, "AND", negated)
    if form is NodeForm.RAW:
        text = _raw(node)
        return (_t("script.phrase.not", lang) + " " + text) if negated else text
    if form is NodeForm.GROUP:
        if node.logic is None:                   # limit: «solo donde …»
            body = _children_phrase(node, lang, index, loc, "AND", False)
            return f"{_t('script.phrase.limit', lang)} {body}"
        return _children_phrase(node, lang, index, loc, node.logic, negated)
    if form is NodeForm.SCOPE:
        head = _lower_first(key_label(node.definition, lang, node.key if node.definition.family else None,
                                      index, loc))
        body = _children_phrase(node, lang, index, loc, "AND", False)
        text = f"{head}: {body}"
        return (_t("script.phrase.not", lang) + " " + text) if negated else text
    return _leaf(node, lang, index, loc, negated)


def phrase(tree: ScriptTree, lang: str, index=None, loc=None, *, lead: str | None = None) -> str:
    """La frase completa del árbol en una línea. ``lead``: uno de ``LEADS`` (None: sin encabezado). Un
    árbol vacío da el texto ``script.phrase.empty.<tipo de guion>`` («siempre», «no hace nada»)."""
    if not tree.root.children:
        body = _t(f"script.phrase.empty.{tree.kind.value}", lang)
    else:
        body = node_phrase(tree.root, lang, index, loc)
    if lead is None:
        return body
    if lead not in LEADS:
        raise ValueError(f"encabezado desconocido: {lead}")
    return f"{_t(f'script.phrase.lead.{lead}', lang)} {body}"


def phrase_lines(tree: ScriptTree, lang: str, index=None, loc=None) -> list[PhraseLine]:
    """La frase desplegada, una línea por nodo, con la sangría de su nivel: lo que pinta ``PhraseView``."""
    from .tree import NodeForm

    lines = []
    for node in tree.walk():
        depth = len(node.path) - 1
        if node.form is NodeForm.GROUP:
            text = key_label(node.definition, lang, None, index, loc) + ":"
        elif node.form is NodeForm.SCOPE:
            text = key_label(node.definition, lang, node.key if node.definition.family else None, index, loc) + ":"
        elif node.form is NodeForm.RAW:
            text = _raw(node)
        else:
            text = _leaf(node, lang, index, loc, False)
        lines.append(PhraseLine(depth, text, node.path, raw=node.raw))
    return lines
