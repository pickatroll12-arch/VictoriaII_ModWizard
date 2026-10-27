"""Serialización de documentos Clausewitz.

``to_source`` reproduce exactamente las partes no editadas (trivia + texto de
cada token original) y da formato a lo editado, movido o creado por código
según su contexto: sangría de los hermanos, unidad de sangría del archivo y
salto de línea del documento. Los tokens nunca se modifican: lo que cambia al
quitar, reordenar o mover entradas se calcula aquí comparando cada bloque con
su orden leído (``Block._orig``), así que deshacer una edición devuelve el
texto original exacto. Reglas:

- una entrada nueva al final de un bloque va justo antes de la línea de su
  ``}`` (tras los comentarios finales); entre dos entradas, antes de los
  comentarios que preceden a la siguiente;
- al quitar una entrada se quita su línea entera, con su comentario de final de
  línea, sin dejar líneas en blanco sueltas; los comentarios de las líneas de
  encima se quedan, salvo si la entrada se ha movido a otro sitio del
  documento: entonces se van con ella los que tenía pegados encima;
- lo movido se sangra según su nuevo sitio, también su contenido;
- nunca quedan dos palabras pegadas;
- un bloque de una línea al que se añade algo que no cabe en ``INLINE_WIDTH``,
  o que lleva comentarios, pasa a ocupar varias líneas;
- una cadena sin cerrar llega hasta el final del archivo: si algo la sigue tras
  editar, se le añade la comilla de cierre (su texto no cambia).

Límite: en un archivo con errores de sintaxis, lo editado junto a ellos puede
leerse de otra forma, porque el formato no tiene separadores que lo eviten: lo
que se pone detrás de un bloque sin cerrar queda dentro de él, y un valor suelto
seguido de un operador descartado (``= b``) forma con él una asignación. Lo
nuevo nunca se pega al texto descartado, y ``write_file(verify=True)`` rechaza
esos casos (``SourceMismatchError`` con ``near_errors``).

``format_canonical`` ignora el formato original. Los recorridos son iterativos
(la profundidad no está limitada) y un bloque que se contiene a sí mismo da
``EditError("cycle")``.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_left
from collections import Counter
from pathlib import Path

from ..encoding import BOM, BOM_ENCODINGS, GAME_ENCODING, encode_text, normalize_encoding
from ..fileio import BACKUP_SUFFIX, FileStamp, atomic_write_bytes
from .diagnostics import ENCODING_CODES, EditError, EditTypeError, Severity
from .lexer import (
    OP,
    OPEN_STRING,
    WORD_CHAR_RE,
    comment_start,
    first_break,
    is_clean_trivia,
    last_break_end,
    last_line_indent,
    newline_split,
    tail_comment,
    tokenize,
)
from .nodes import Block, Document, Entry, Scalar, first_token, scalar_source, starts_document

INLINE_WIDTH = 80  # ancho máximo de una línea con contenido generado en línea
_TAB_WIDTH = 4
_BLANK = " \t\x0b\x0c"
_BREAKS_RE = re.compile("(\r\n?|\n)")
_LEAD_SPACE = " \t\r\n"

# Modos de colocación de las entradas generadas dentro de un bloque.
LINE, INLINE, WRAP = "line", "inline", "wrap"
# Final de un bloque leído: su "}", una "}" que añade Block.close(), ninguna (sin cerrar) o el final del archivo.
BRACE, ADDED, NO_BRACE, END = range(4)

# Archivos con copia de seguridad (.bak) hecha en esta sesión: los guardados siguientes no la pisan.
_SESSION_BACKUPS: set[str] = set()


class SourceMismatchError(EditError):
    """El texto generado no se vuelve a leer como el árbol en memoria; no se ha escrito nada.

    ``params["entry"]`` es la ruta de la primera entrada distinta y ``params["line"]``
    su línea en el texto generado. ``params["near_errors"]``: lo leído ya tenía errores
    de sintaxis (o bloques sin cerrar), la causa habitual; el mensaje lo dice.
    """

    def __init__(self, path, entry: str, line: int, near_errors: bool = False):
        super().__init__("source_mismatch",
                         {"where": str(path), "entry": entry, "line": line, "near_errors": near_errors})

    def __reduce__(self):
        return (
            type(self),
            (self.params["where"], self.params["entry"], self.params["line"], self.params["near_errors"]),
        )

    def _template(self) -> str:
        return "source_mismatch_near_errors" if self.params.get("near_errors") else self.code


# --- trivia -------------------------------------------------------------------------


def _is_blank(text: str) -> bool:
    return not text.strip(_BLANK)


def _lines(text: str) -> tuple[list[str], list[str]]:
    """Líneas de ``text`` y los saltos que las separan (``len(lines) == len(breaks) + 1``)."""
    parts = _BREAKS_RE.split(text)
    return parts[0::2], parts[1::2]


def _comment_only(line: str) -> bool:
    return line.lstrip(_BLANK).startswith("#")


def _without_final_break(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    return text[:-1] if text.endswith(("\n", "\r")) else text


def _ends_in_comment(text: str) -> bool:
    """True si la última línea completa de ``text`` (acabado en salto) tiene un comentario."""
    lines, _ = _lines(text)
    return len(lines) > 1 and comment_start(lines[-2]) >= 0


def _strip_trailing_blank_lines(prefix: str) -> tuple[str, int]:
    """``prefix`` acaba en salto de línea; quita las líneas completas en blanco del final."""
    lines, breaks = _lines(prefix)
    end = len(lines) - 1  # la última "línea" es lo que hay tras el salto final: ""
    keep = end - 1
    while keep >= 1 and _is_blank(lines[keep]):
        keep -= 1
    removed = end - 1 - keep
    if removed <= 0:
        return prefix, 0
    return "".join(lines[i] + breaks[i] for i in range(keep + 1)), removed


def _strip_leading_blank_lines(suffix: str) -> tuple[str, int]:
    lines, _ = _lines(suffix)
    index = 0
    while index < len(lines) - 1 and _is_blank(lines[index]):
        index += 1
    if not index:
        return suffix, 0
    return "".join(_BREAKS_RE.split(suffix)[2 * index:]), index


def _drop_tail(trail: str) -> str:
    """Quita el comentario de final de la línea anterior (el de antes del primer salto)."""
    cut = first_break(trail)
    head = trail if cut < 0 else trail[:cut]
    start = comment_start(head)
    if start < 0:
        return trail
    return head[:start].rstrip(_BLANK) + ("" if cut < 0 else trail[cut:])


def _join(lead: str, trail: str, *, first: bool, at_start: bool, at_end: bool, root: bool) -> str:
    """Trivia que queda entre lo anterior y el token siguiente al quitar una entrada.

    ``lead`` es la trivia previa de la entrada y ``trail`` la del token siguiente;
    ``first``: no queda nada delante en el bloque; ``at_start``: ``lead`` empieza el
    archivo; ``at_end``: el token siguiente es el cierre (``root``: el final del
    archivo). Se quita la línea de la entrada con su comentario de final de línea,
    sin dejar líneas en blanco sueltas, y se conservan los comentarios de las
    líneas de encima. El texto descartado por errores de sintaxis no se toca.
    """
    split = last_break_end(lead)
    if not split and not at_start:
        # Comparte línea con lo anterior: el token siguiente ocupa su lugar.
        if not is_clean_trivia(lead):
            return lead + trail
        trail = _drop_tail(trail)
        if first and not lead and first_break(trail) < 0 and _is_blank(trail):
            return ""  # iba pegada a la "{": "{b=1 c=2}" -> "{c=2}"
        return trail
    prefix, indent = lead[:split], lead[split:]
    cut = first_break(trail)
    if cut < 0:
        # Lo siguiente estaba en la línea de la entrada.
        if not (is_clean_trivia(trail) and is_clean_trivia(indent)):
            return lead + trail
        if not at_end:
            return lead
        # El cierre sube al final de la línea anterior ("x = {\n\ta = 1 }" -> "x = { }"), salvo si
        # esa línea acaba en un comentario: entonces la "}" sigue en una línea propia.
        stripped, _ = _strip_trailing_blank_lines(prefix) if prefix else (prefix, 0)
        if root or not _ends_in_comment(stripped):
            return _without_final_break(stripped) + trail
        return stripped
    end = cut + (2 if trail.startswith("\r\n", cut) else 1)
    rest_of_line, suffix = trail[:end], trail[end:]
    if not (is_clean_trivia(indent) and is_clean_trivia(rest_of_line)):
        return lead + trail
    stripped_prefix, blank_before = _strip_trailing_blank_lines(prefix) if prefix else (prefix, 0)
    stripped_suffix, blank_after = _strip_leading_blank_lines(suffix)
    if blank_before and blank_after:
        # Había separación en blanco a ambos lados: se conserva solo la de arriba.
        return prefix + stripped_suffix
    if blank_before and at_end and _is_blank(suffix):
        # Detrás solo queda el cierre: sobra la separación de arriba.
        return stripped_prefix + suffix
    if blank_after and first:
        # Delante solo queda la apertura: sobra la separación de abajo.
        return prefix + stripped_suffix
    return prefix + suffix


def _attached(trivia: str, at_start: bool) -> tuple[str, list[str]]:
    """Separa los comentarios pegados encima del token: líneas solo de comentario sin línea en blanco
    entre ellas y él. Devuelve la trivia sin ellos y los comentarios (se van con una entrada movida)."""
    if "#" not in trivia:
        return trivia, []
    lines, breaks = _lines(trivia)
    end = len(lines) - 1
    first = 0 if at_start else 1  # la primera línea de la trivia es la de lo anterior
    start = end
    while start > first and _comment_only(lines[start - 1]):
        start -= 1
    if start == end:
        return trivia, []
    kept = "".join(lines[i] + breaks[i] for i in range(start)) + lines[end]
    return kept, [lines[i].strip(_BLANK) for i in range(start, end)]


def _with_comment_lines(trivia: str, comments, at_start: bool, indent: str, newline: str) -> str:
    """Sustituye las líneas solo de comentario de encima del token por ``comments``."""
    lines, breaks = _lines(trivia)
    end = len(lines) - 1
    if not end and not at_start:
        # El token comparte línea con lo anterior: los comentarios lo bajan a una línea propia.
        if not comments:
            return trivia
        return trivia.rstrip(_BLANK) + "".join(newline + indent + c for c in comments) + newline + indent
    head = "" if at_start else lines[0] + breaks[0]
    nl = breaks[0] if breaks else newline
    kept = "".join(lines[i] + breaks[i] for i in range(0 if at_start else 1, end) if not _comment_only(lines[i]))
    return head + kept + "".join(indent + c + nl for c in comments) + lines[end]


def _with_tail(trivia: str, comment: str | None, newline: str, indent: str | None) -> str:
    """Pone ``comment`` (o ninguno) al final de la línea anterior al token.

    ``indent`` es la sangría del token si hay que bajarlo a otra línea (None al final del archivo).
    """
    cut = first_break(trivia)
    head, rest = (trivia, None) if cut < 0 else (trivia[:cut], trivia[cut:])
    start = comment_start(head)
    base = head if start < 0 else head[:start]
    if comment is None:
        if start < 0:
            return trivia
        head = base.rstrip(_BLANK)
    else:
        head = base.rstrip(_BLANK) + " " + comment
    if rest is None:
        rest = "" if indent is None or comment is None else newline + indent
    return head + rest


def _line_indent(trivia: str) -> str:
    """Espacios y tabs al principio de la última línea de la trivia."""
    line = trivia[last_break_end(trivia):]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _expects_value(trivia: str) -> bool:
    """True si el texto descartado de la trivia acaba en ``clave operador`` (falta el valor)."""
    if is_clean_trivia(trivia):
        return False
    tokens = tokenize(trivia)[:-1]
    index = len(tokens) - 1
    while index >= 0 and tokens[index].kind == OP:
        index -= 1
    return index >= 0 and index < len(tokens) - 1 and tokens[index].kind <= OPEN_STRING


def _shift_pattern(old: str, new: str):
    """(patrón, sangría nueva) que cambia la sangría ``old`` por ``new`` en cada línea no vacía.

    La última línea de una trivia acaba en su token (la "}" de cierre, por ejemplo): también cuenta.
    """
    return re.compile("(\r\n?|\n)" + re.escape(old) + "(?![\r\n])"), new


def _increasing(seq: list[int]) -> list[bool]:
    """Subsecuencia creciente más larga de índices originales (-1: entrada nueva o repetida).

    Esas entradas conservan su sitio y su trivia; las demás se tratan como movidas.
    """
    tails, ends = [], []
    back = [-1] * len(seq)
    for position, value in enumerate(seq):
        if value < 0:
            continue
        length = bisect_left(tails, value)
        if length == len(tails):
            tails.append(value)
            ends.append(position)
        else:
            tails[length] = value
            ends[length] = position
        back[position] = ends[length - 1] if length else -1
    keep = [False] * len(seq)
    position = ends[-1] if ends else -1
    while position >= 0:
        keep[position] = True
        position = back[position]
    return keep


def _is_loose_scalar(entry: Entry) -> bool:
    return entry._key is None and entry._value.__class__ is Scalar


def _eof_closed(value) -> bool:
    """Bloque leído sin su "}": llega hasta el final del archivo (aunque ``close()`` le añada una)."""
    return value.__class__ is not Scalar and value._open is not None and value._close is None


def _moved_entries(node) -> set:
    """Entradas leídas que están en un bloque que no es el suyo original (movidas)."""
    found = set()
    if isinstance(node, Entry):
        node = node._value
        if node.__class__ is Scalar:
            return found
    seen = {id(node)}
    stack = [node]
    while stack:
        block = stack.pop()
        entries = block.entries
        original = block._orig
        if original is None:
            found.update(entry for entry in entries if first_token(entry) is not None)
        elif entries != original:
            own = set(original)
            found.update(entry for entry in entries if entry not in own)
        for entry in entries:
            value = entry._value
            if value.__class__ is not Scalar and id(value) not in seen:
                seen.add(id(value))
                stack.append(value)
    return found


def _one_line(block: Block) -> bool:
    """Bloque generado (se escribe donde quepa) o leído con su "{" y su "}" en la misma línea."""
    return block._open is None or block._close is not None and block._close.line == block._open.line


def _intact(block: Block) -> bool:
    """Bloque leído con su "}", sus entradas en el orden leído y sin comentarios de bloque cambiados."""
    return (block._close is not None and block._open_comment is None and block._trailing_comments is None
            and block.entries == block._orig)


class _Unfold(Exception):
    """Señal interna de _Writer: hay que volver a escribir ``frame``, un bloque de una línea, en varias."""

    def __init__(self, frame):
        super().__init__()
        self.frame = frame


# --- escritor -------------------------------------------------------------------------


class _Frame:
    __slots__ = (
        "block", "items", "i", "root", "generated", "end", "closer_lead", "owns_eof", "inline", "wrap",
        "open_pos", "indent", "base", "run", "line_len", "shift", "prev", "tail_pending", "after",
    )

    def __init__(self, block, root, generated, end, open_pos):
        self.block = block
        self.items = None  # trivia de cada entrada si el bloque cambió de forma (None: se genera)
        self.i = 0
        self.root = root
        self.generated = generated  # sin tokens originales (o en modo canónico)
        self.end = end  # BRACE, ADDED, NO_BRACE o END
        self.closer_lead = None  # trivia antes del cierre (si no es la del final del archivo)
        self.owns_eof = False  # su cierre es el final del archivo: trivia en _Writer.eof_lead
        self.inline = False
        self.wrap = False
        self.open_pos = open_pos  # posición en la salida justo tras "{"
        self.indent = None  # sangría de las entradas generadas (perezosa)
        self.base = None  # sangría de la línea de "{" (perezosa)
        self.run = None  # modo de la racha actual de entradas generadas
        self.line_len = 0
        self.shift = None  # (patrón, sangría nueva) del contenido movido a otra profundidad
        self.prev = None  # última entrada leída emitida: dueña del comentario de final de línea
        # Falta aplicar a la trivia siguiente el comentario de final de línea de prev (o de la "{"): _fix_tail.
        self.tail_pending = not root and block._open_comment is not None
        self.after = None  # comentario de línea de la entrada dueña, tras la "}"


class _Writer:
    def __init__(self, root, newline: str, unit: str, canonical: bool, comments: bool):
        self.out: list[str] = []
        self.newline = newline
        self.unit = unit
        self.canonical = canonical
        self.comments = comments
        self.root = root
        self.active: set[int] = set()  # bloques en el camino actual (para detectar ciclos)
        self.stack: list[_Frame] = []  # marcos abiertos (los de _run)
        self.unfolding: set[int] = set()  # bloques de una línea que se escriben desplegados (ver _unfold)
        self.changed: set[int] = set()  # bloques leídos con algún cambio dentro: no se copian (ver _copy)
        self.moved = None  # entradas movidas a otro bloque (perezoso)
        self.need_break = False  # lo último fue un comentario: lo siguiente va en otra línea
        self.open_string = None  # posición en out de una cadena leída sin cerrar
        eof = root._eof if isinstance(root, Document) and not canonical else None
        self.eof_lead = None if eof is None else eof.trivia

    def write(self, node) -> str:
        if isinstance(node, Document):
            generated = self.canonical or node._eof is None
            frame = _Frame(node, True, generated, END, 0)
            if not generated:
                frame.owns_eof = True
                self._prepare(frame)
            self._run(frame)
        elif isinstance(node, Block):
            self.out.append("{")
            self._run(self._open_frame(node, None, False, None, False))
        elif isinstance(node, Entry):
            child = self._entry(None, node, "", self.canonical)  # en modo canónico todo se genera
            if child is not None:
                self._run(child)
        elif isinstance(node, Scalar):
            self.out.append(scalar_source(node))
        else:
            raise EditTypeError("not_a_node", {"type": type(node).__name__})
        out = self.out
        index = self.open_string
        if index is not None and any(out[index + 1:]):
            out[index] += '"'  # si no, se tragaría lo que la sigue
        return "".join(out)

    # --- recorrido -------------------------------------------------------------

    def _run(self, frame: _Frame) -> None:
        self.active.add(id(frame.block))
        stack = self.stack = [frame]
        while True:
            try:
                self._walk(stack)
                return
            except _Unfold as signal:
                self._restart(stack, signal.frame)

    def _walk(self, stack: list) -> None:
        active = self.active
        while stack:
            frame = stack[-1]
            entries = frame.block.entries
            items = frame.items
            generated = frame.generated
            child = None
            while frame.i < len(entries):
                position = frame.i
                frame.i += 1
                entry = entries[position]
                if generated or items is not None and items[position] is None:
                    child = self._entry(frame, entry, self._generated_lead(frame, entry), True)
                else:
                    # Entrada leída en su sitio: con su trivia (la efectiva si se quitó algo delante).
                    if items is None:
                        lead = first_token(entry).trivia
                        if frame.shift is not None:
                            lead = self._shifted(frame, lead)
                        if entry._comments is not None:
                            if entry._comments and frame.inline:
                                self._unfold()
                            lead = self._with_comments(frame, lead, entry, position)
                    else:
                        lead = items[position]
                    frame.run = None
                    if frame.tail_pending:
                        frame.tail_pending = False
                        lead = self._fix_tail(frame, lead, False)
                    child = self._entry(frame, entry, lead, False)
                    frame.prev = entry
                    frame.tail_pending = entry._line_comment is not None
                if child is not None:
                    break
            if child is not None:
                if id(child.block) in active:
                    raise EditError("cycle")
                active.add(id(child.block))
                stack.append(child)
            else:
                self._close(frame)
                active.discard(id(frame.block))
                stack.pop()

    def _restart(self, stack: list, frame: _Frame) -> None:
        """Vuelve a escribir desde su "{" el bloque de una línea ``frame``, ahora desplegado (ver _unfold)."""
        while stack[-1] is not frame:
            self.active.discard(id(stack.pop().block))
        del self.out[frame.open_pos:]
        if self.open_string is not None and self.open_string >= frame.open_pos:
            self.open_string = None
        self.need_break = False  # tras una "{" nunca está pendiente
        frame.items = frame.indent = frame.run = frame.prev = None
        frame.i = frame.line_len = 0
        frame.tail_pending = frame.block._open_comment is not None
        self._prepare(frame)

    def _entry(self, frame, entry: Entry, lead: str, displaced: bool):
        """Emite la entrada; si su valor es un bloque, emite "{" y devuelve su marco (None si lo ha copiado
        entero porque no ha cambiado: ver _copy).

        ``displaced``: la entrada es nueva o viene de otro sitio (su trivia previa se generó).
        """
        out = self.out
        canonical = self.canonical
        value = entry._value
        key = entry._key
        vtok = None if canonical else entry._vtok
        shift = None if frame is None else frame.shift
        if key is not None:
            ktok = None if canonical else entry._ktok
            raw = scalar_source(key) if ktok is None or ktok.raw is None else ktok.raw
            if self.need_break or not lead or lead[0] not in _LEAD_SPACE:
                lead = self._separated(frame, lead, raw)
            out.append(lead)
            out.append(raw)
            otok = None if canonical else entry._otok
            if otok is None:
                out.append(" ")
                out.append(entry._op)
            else:
                out.append(otok.trivia if shift is None else self._shifted(frame, otok.trivia))
                out.append(entry._op if otok.raw is None else otok.raw)
            if vtok is not None:
                vlead = vtok.trivia
            elif not canonical and value.__class__ is not Scalar and value._open is not None:
                vlead = value._open.trivia
            else:
                vlead = " "
            out.append(vlead if shift is None else self._shifted(frame, vlead))
        else:
            vraw = "{" if value.__class__ is not Scalar else (
                scalar_source(value) if vtok is None or vtok.raw is None else vtok.raw)
            if self.need_break or not lead or lead[0] not in _LEAD_SPACE:
                lead = self._separated(frame, lead, vraw)
            out.append(lead)
        # El de una entrada leída en su sitio ya está en la trivia siguiente (ver _fix_tail).
        comment = entry._line_comment if displaced and self.comments else None
        if value.__class__ is Scalar:
            if vtok is None or vtok.raw is None:
                out.append(scalar_source(value))
            else:
                if vtok.kind == OPEN_STRING:
                    self.open_string = len(out)
                out.append(vtok.raw)
            if comment:
                out.append(" " + comment)
                self.need_break = True
            return None
        out.append("{")
        if not (canonical or displaced) and vtok is None and shift is None and value._open is not None \
                and self._copy(value):
            return None
        inline_context = frame is not None and frame.inline
        moved = not canonical and value._open is not None and (displaced or vtok is not None)
        old_base = None
        if moved and displaced:
            token = first_token(entry)
            if token is not None:
                old_base = last_line_indent(token.trivia)
        child = self._open_frame(value, frame, moved, old_base, inline_context)
        child.after = comment
        return child

    def _open_frame(self, block: Block, parent, moved: bool, old_base, inline_context: bool) -> _Frame:
        """Marco de un bloque cuya "{" acaba de escribirse; ``inline_context``: va en un bloque de una línea."""
        out = self.out
        open_pos = len(out)
        if self.canonical or block._open is None:
            frame = _Frame(block, False, True, BRACE, open_pos)
            if self.canonical and parent is not None and parent.run == LINE:
                frame.base = parent.indent  # la entrada empieza su línea (ver _generated_lead)
            opening = self._opening(block)
            if inline_context:
                # Lo generado dentro de un bloque de una línea va en esa línea si cabe y no lleva comentarios;
                # si no, la línea se despliega (y si no se puede, lo que lleva comentarios ocupa varias líneas).
                width = self._line_width_with(block, open_pos)
                if width is None or width > INLINE_WIDTH:
                    self._unfold()
                    inline_context = width is not None
            width = self._list_width(block)
            frame.inline = not opening and (inline_context or width is not None and width <= INLINE_WIDTH)
            frame.wrap = not frame.inline and width is not None and len(block.entries) > 0
            if opening:
                out.append(" " + opening)
                self.need_break = True
            return frame
        close = block._close
        if close is not None:
            end = BRACE
        else:
            end = NO_BRACE if block._unclosed else ADDED
        frame = _Frame(block, False, False, end, open_pos)
        frame.inline = end == BRACE and close.line == block._open.line
        if moved and inline_context and not frame.inline:
            self._unfold()  # un bloque leído de varias líneas, puesto dentro de uno de una línea
        if parent is not None:
            frame.shift = parent.shift
        if moved and not frame.inline:
            frame.shift = self._shift_for(frame, old_base)
        self._prepare(frame)
        return frame

    def _shift_for(self, frame: _Frame, old_base):
        """Cambio de sangría de un bloque movido: de la de su línea original a la de su nuevo sitio."""
        if old_base is None and frame.end == BRACE:
            old_base = last_line_indent(frame.block._close.trivia)
        if old_base is None:
            return frame.shift
        new_base = self._base_indent(frame)
        return None if new_base == old_base else _shift_pattern(old_base, new_base)

    def _shifted(self, frame: _Frame, text: str) -> str:
        if frame.shift is None or ("\n" not in text and "\r" not in text):
            return text
        pattern, new = frame.shift
        return pattern.sub(lambda match: match.group(1) + new, text)

    # --- bloques leídos sin cambios ----------------------------------------------

    def _copy(self, block: Block) -> bool:
        """Atajo para lo no editado: copia el texto leído de ``block``, de tras su "{" hasta su "}", si ni él ni
        nada de dentro ha cambiado. Es lo que escribiría el recorrido con marcos, sin su coste: los tokens
        leídos con su trivia (en el texto leído no hay palabras pegadas ni texto tras un comentario).

        Si encuentra un cambio deshace la copia, apunta en ``self.changed`` los bloques que lo contienen (no se
        vuelven a intentar: cada bloque se copia a lo sumo dos veces) y devuelve False.
        """
        changed = self.changed
        if id(block) in changed or not _intact(block):
            return False
        out = self.out
        start = len(out)
        levels = []  # (bloque, entradas, posición siguiente) de los bloques que contienen al actual
        current, entries, position = block, block.entries, 0
        pending = None  # comentario de final de línea de la entrada anterior: va en la trivia siguiente
        while True:
            if position == len(entries):
                lead = current._close.trivia
                if pending is not None and tail_comment(lead) != (pending or None):
                    break
                out += (lead, "}")
                if not levels:
                    return True
                current, entries, position = levels.pop()
                pending = entries[position - 1]._line_comment
                continue
            entry = entries[position]
            position += 1
            if entry._comments is not None:
                break
            key = entry._key
            value = entry._value
            vtok = entry._vtok
            if key is not None:
                ktok = entry._ktok
                otok = entry._otok
                if ktok is None or ktok.raw is None or otok is None or otok.raw is None:
                    break
                lead = ktok.trivia
            elif vtok is not None:
                lead = vtok.trivia
            elif value.__class__ is not Scalar and value._open is not None:
                lead = value._open.trivia
            else:
                break
            if pending is not None and tail_comment(lead) != (pending or None):
                break
            if value.__class__ is Scalar:
                if vtok is None or vtok.raw is None or vtok.kind == OPEN_STRING:
                    break
                if key is None:
                    out += (lead, vtok.raw)
                else:
                    out += (lead, ktok.raw, otok.trivia, otok.raw, vtok.trivia, vtok.raw)
                pending = entry._line_comment
            else:
                if vtok is not None or value._open is None or id(value) in changed or not _intact(value):
                    break
                if key is None:
                    out += (lead, "{")
                else:
                    out += (lead, ktok.raw, otok.trivia, otok.raw, value._open.trivia, "{")
                levels.append((current, entries, position))
                current, entries, position, pending = value, value.entries, 0, None
        del out[start:]
        changed.add(id(current))
        changed.update(id(level[0]) for level in levels)
        return False

    # --- forma de un bloque leído -----------------------------------------------

    def _prepare(self, frame: _Frame) -> None:
        """Trivia del cierre y, si el bloque cambió de forma, el plan de sus entradas.

        Un bloque de una línea al que se le pone algo que no cabe en ella se despliega (ver _unfold).
        """
        block = frame.block
        if frame.end == BRACE:
            trivia = block._close.trivia
            frame.closer_lead = trivia if frame.shift is None else self._shifted(frame, trivia)
        elif frame.end != END:
            original = block._orig
            if self.eof_lead is not None and not (original and _eof_closed(original[-1]._value)):
                frame.owns_eof = True  # el bloque sin cerrar más interno: lo sigue el final del archivo
            else:
                frame.closer_lead = ""
        original = block._orig
        if original is not None and block.entries != original:
            self._plan(frame, original)
        if frame.inline:
            # Ya se decidió desplegarlo (_restart) o lo que se le ha puesto no cabe en su línea. Se decide
            # antes de escribir nada dentro: así no hay que volver a escribirlo desde la "{" (R4).
            marked = self.unfolding and id(block) in self.unfolding
            if marked or (block._open_comment or block._trailing_comments
                          or self._must_unfold(frame)) and self._unfold(frame):
                self._unfold_items(frame)

    def _closer_lead(self, frame: _Frame) -> str:
        return self.eof_lead if frame.owns_eof else frame.closer_lead

    def _set_closer_lead(self, frame: _Frame, lead: str) -> None:
        if frame.owns_eof:
            self.eof_lead = lead
        else:
            frame.closer_lead = lead

    def _plan(self, frame: _Frame, original: list) -> None:
        """Trivia efectiva de las entradas que conservan su sitio tras quitar, mover o insertar otras."""
        block = frame.block
        where = {entry: index for index, entry in enumerate(original)}
        seq = [where.pop(entry, -1) for entry in block.entries]  # pop: una entrada repetida cuenta una vez
        anchored = _increasing(seq)
        count = len(original)
        kept = [False] * count
        for position, flag in enumerate(anchored):
            if flag:
                kept[seq[position]] = True
        here = {index for index in seq if index >= 0}
        starts = frame.root and count and starts_document(first_token(original[0]))
        leads = [self._shifted(frame, first_token(entry).trivia) for entry in original]
        for index, entry in enumerate(original):
            if not kept[index]:
                # Movida (dentro del bloque o a otro): sus comentarios pegados se van con ella.
                if index in here or entry in self._moved():
                    leads[index] = _attached(leads[index], starts and not index)[0]
            elif entry._comments is not None:
                leads[index] = self._with_comments(frame, leads[index], entry, index)
        closer = self._closer_lead(frame)
        if frame.items is None and block._trailing_comments is not None:
            closer = self._with_trailing(frame, closer)
        original_closer = closer
        effective = [None] * count
        pending = None  # trivia acumulada de las entradas quitadas seguidas
        pending_start = seen_anchor = False
        for index in range(count + 1):
            lead = leads[index] if index < count else closer
            at_start = starts and not index  # la trivia empieza el archivo
            if pending is not None:
                lead = _join(pending, lead, first=not seen_anchor, at_start=pending_start,
                             at_end=index == count, root=frame.root)
                at_start = pending_start
                pending = None
            if index == count:
                closer = lead
            elif kept[index]:
                effective[index] = lead
                seen_anchor = True
            else:
                pending, pending_start = lead, at_start
        if frame.end == BRACE and closer != original_closer:
            # La "}" acaba en una línea que antes era de una entrada quitada: va con la sangría del bloque.
            cut = last_break_end(closer)
            original_cut = last_break_end(original_closer)
            other_line = original_cut == 0 or closer[cut:] != original_closer[original_cut:]
            if cut and _is_blank(closer[cut:]) and other_line:
                closer = closer[:cut] + self._base_indent(frame)
        self._set_closer_lead(frame, closer)
        frame.items = [effective[seq[position]] if flag else None for position, flag in enumerate(anchored)]

    def _moved(self) -> set:
        if self.moved is None:
            self.moved = _moved_entries(self.root)
        return self.moved

    # --- bloques de una línea que se despliegan ----------------------------------------

    def _must_unfold(self, frame: _Frame) -> bool:
        """True si las entradas añadidas a un bloque de una línea, o los comentarios puestos a las suyas,
        no caben en ella (con lo añadido sería más ancha que ``INLINE_WIDTH``)."""
        entries = frame.block.entries
        if frame.items is None:
            # Las mismas entradas, y leídas en una línea no tenían comentarios (se habrían tragado la "}").
            return any(entry._comments or entry._line_comment for entry in entries)
        added = False
        for entry, lead in zip(entries, frame.items):
            if lead is None:
                if self._comments_of(entry) or entry._line_comment:
                    return True
                added = True
            elif entry._comments or entry._line_comment:
                return True
        if not added:
            return False
        width = len(self._line_text_at(frame.open_pos).expandtabs(_TAB_WIDTH)) + 2
        for entry in entries:
            item = self._inline_width(entry, INLINE_WIDTH)
            if item is None:
                return True
            width += 1 + item
            if width > INLINE_WIDTH:
                return True
        return False

    def _can_unfold(self, frame: _Frame) -> bool:
        """El bloque de una línea no tiene texto descartado entre sus tokens: desplegarlo no pierde nada."""
        block = frame.block
        return _is_blank(block._close.trivia) and all(_is_blank(first_token(entry).trivia) for entry in block._orig)

    def _unfold(self, opening: _Frame | None = None) -> bool:
        """Lo que se escribe ya no cabe en su línea: se despliegan los bloques de una línea que la forman.

        Son los marcos abiertos de la línea y ``opening`` (el bloque que se está abriendo), salvo los que
        tienen texto descartado entre sus tokens. Si ya se ha escrito parte de alguno, se lanza ``_Unfold``
        para volver a escribir desde el más externo (_run). Devuelve si ``opening`` se despliega.
        """
        marked = self.unfolding
        outer = None
        for frame in reversed(self.stack):
            if not frame.inline:
                break
            if not frame.generated and self._can_unfold(frame):
                marked.add(id(frame.block))
                outer = frame
        unfolds = opening is not None and self._can_unfold(opening)
        if unfolds:
            marked.add(id(opening.block))
        if outer is not None:
            raise _Unfold(outer)
        return unfolds

    def _unfold_items(self, frame: _Frame) -> None:
        """Despliega un bloque leído de una línea: cada entrada leída en su línea (salvo los valores sueltos
        seguidos, "{ 1 2 3 }") con la sangría del archivo, y la "}" en la suya con la de la línea de la "{"."""
        block = frame.block
        frame.inline = False
        base = self._base_indent(frame)
        frame.indent = indent = base + self.unit
        newline = self.newline
        items = frame.items
        leads = []
        previous_loose = False
        for position, entry in enumerate(block.entries):
            lead = first_token(entry).trivia if items is None else items[position]
            loose = _is_loose_scalar(entry)
            if lead is not None and not (previous_loose and loose and not entry._comments):
                lead = newline + indent
                if entry._comments is not None:
                    lead = self._with_comments(frame, lead, entry, position)
            leads.append(lead)  # None: nueva o movida, la coloca _generated_lead
            previous_loose = loose
        frame.items = leads
        closer = newline + base
        if block._trailing_comments is not None:
            closer = self._with_trailing(frame, closer)
        frame.closer_lead = closer

    def _line_width_with(self, block: Block, open_pos: int) -> int | None:
        """Ancho de la línea de ``out[open_pos - 1]`` con el bloque generado escrito en ella (deja de contar
        al pasar de ``INLINE_WIDTH``); None si no puede ir en una línea (ver _inline_width)."""
        if self._opening(block) or self._trailing(block):
            return None
        width = len(self._line_text_at(open_pos).expandtabs(_TAB_WIDTH)) + 2
        for entry in block.entries:
            item = self._inline_width(entry, INLINE_WIDTH)
            if item is None:
                return None
            width += 1 + item
            if width > INLINE_WIDTH:
                break
        return width

    def _inline_width(self, entry: Entry, limit: int) -> int | None:
        """Ancho aproximado de la entrada en una sola línea (al pasar de ``limit`` deja de contar); None si
        no puede ir en una: lleva comentarios o un bloque leído de varias líneas."""
        width = 0
        stack = [iter((entry,))]
        while stack:
            for item in stack[-1]:
                if self._comments_of(item) or item._line_comment:
                    return None
                if item._key is not None:
                    width += len(scalar_source(item._key)) + len(item._op) + 2
                value = item._value
                if value.__class__ is Scalar:
                    width += len(scalar_source(value)) + 1
                elif value._open_comment or value._trailing_comments or not _one_line(value):
                    return None
                else:
                    width += 4
                if width > limit:
                    return width
                if value.__class__ is not Scalar:
                    stack.append(iter(value.entries))
                    break
            else:
                stack.pop()
        return width

    # --- comentarios cambiados ----------------------------------------------------

    def _with_comments(self, frame: _Frame, lead: str, entry: Entry, position: int) -> str:
        at_start = frame.root and not position and starts_document(first_token(entry))
        indent = _line_indent(lead) if at_start or first_break(lead) >= 0 else self._child_indent(frame)
        return _with_comment_lines(lead, entry._comments, at_start, indent, self.newline)

    def _with_trailing(self, frame: _Frame, lead: str) -> str:
        at_start = frame.root and not frame.block._orig and starts_document(frame.block._eof)
        return _with_comment_lines(lead, frame.block._trailing_comments, at_start, self._child_indent(frame),
                                   self.newline)

    def _fix_tail(self, frame: _Frame, lead: str, closer: bool) -> str:
        """Aplica a la trivia el comentario de final de línea de la entrada anterior (o de la "{") si ha cambiado.

        Solo se llama con ``frame.tail_pending``: ese comentario no es None ("" si se ha quitado).
        """
        prev = frame.prev
        wanted = (prev._line_comment if prev is not None else frame.block._open_comment) or None
        if tail_comment(lead) == wanted:
            return lead
        if wanted and frame.inline:
            self._unfold()  # el comentario cerraría la línea del bloque
        if not closer:
            indent = self._child_indent(frame)
        else:
            indent = None if frame.owns_eof else self._base_indent(frame)
        return _with_tail(lead, wanted, self.newline, indent)

    # --- entradas generadas ----------------------------------------------------

    def _separated(self, frame, lead: str, raw: str) -> str:
        """Trivia previa del token ``raw`` sin dejar palabras pegadas ni texto tras un comentario.

        _entry solo la llama si hace falta: si no hay salto pendiente y la trivia empieza por espacio o salto,
        va tal cual.
        """
        if self.need_break:
            self.need_break = False
            if first_break(lead) < 0:
                indent = "" if frame is None else self._child_indent(frame)
                lead = self.newline + indent + lead.lstrip(_BLANK)
        if not lead or lead[0] not in _LEAD_SPACE:
            first = lead[:1] or raw[:1]
            if first and WORD_CHAR_RE.match(first) is not None:
                last = self._last_char()
                if last and WORD_CHAR_RE.match(last) is not None:
                    lead = " " + lead
        return lead

    def _unglued(self, lead: str) -> str:
        """Trivia ante un cierre con un espacio delante si empieza por texto descartado que se pegaría a la
        palabra escrita justo antes (lo editado junto a un error: "clave =" tras un valor nuevo)."""
        if lead and WORD_CHAR_RE.match(lead) is not None:
            last = self._last_char()
            if last and WORD_CHAR_RE.match(last) is not None:
                return " " + lead
        return lead

    def _last_char(self) -> str:
        for chunk in reversed(self.out):
            if chunk:
                return chunk[-1]
        return ""

    def _generated_lead(self, frame: _Frame, entry: Entry) -> str:
        if frame.run is None:
            self._start_run(frame)
        comments = self._comments_of(entry)
        mode = frame.run
        if mode == INLINE and not comments:
            return " "
        indent = self._child_indent(frame)
        if mode == WRAP:
            width = len(scalar_source(entry._value))
            if frame.line_len and frame.line_len + 1 + width <= INLINE_WIDTH:
                frame.line_len += 1 + width
                return " "
            frame.line_len = width
            return self.newline + indent
        if not comments and self._continues_list(frame, entry):
            return " "
        newline = self.newline
        at_start = frame.root and self._at_start()
        if not comments:
            return indent if at_start else newline + indent
        pieces = []
        for comment in comments:
            pieces.append(indent + comment if at_start and not pieces else newline + indent + comment)
        pieces.append(indent if at_start and not pieces else newline + indent)
        return "".join(pieces)

    def _start_run(self, frame: _Frame) -> None:
        """Decide cómo colocar una racha de entradas generadas y parte la trivia del token siguiente."""
        if frame.root:
            mode = LINE
        elif frame.inline:
            mode = INLINE
        elif frame.wrap:
            mode = WRAP
        else:
            mode = LINE
        frame.run = mode
        if frame.generated:
            return
        index = self._next_anchor(frame)
        closer = index < 0
        lead = self._closer_lead(frame) if closer else frame.items[index]
        if frame.tail_pending:
            frame.tail_pending = False
            lead = self._fix_tail(frame, lead, closer)
        if mode == INLINE:
            # Hace falta un separador si el token siguiente iba pegado; "{}" pasa a "{ x }".
            if not lead and (not closer or frame.i == 1):
                lead = " "
            self._store(frame, index, lead)
            return
        head, rest = self._split(frame, lead, closer)
        self.out.append(head)
        self._store(frame, index, rest)

    def _split(self, frame: _Frame, lead: str, closer: bool) -> tuple[str, str]:
        """Parte la trivia del token siguiente: lo nuevo va tras ``head`` y antes de ``rest``.

        Ante el cierre, tras los comentarios finales del bloque; ante otra entrada, antes de
        los comentarios que la preceden.
        """
        if closer:
            clean = is_clean_trivia(lead)
            split = newline_split(lead, last=clean)
            if clean and split is not None and comment_start(split[1]) >= 0:
                # El archivo acaba en un comentario sin salto final: lo nuevo va detrás.
                split = (lead, "" if frame.prev is not None or not frame.root else self.newline)
        else:
            split = newline_split(lead)
        if split is None:
            head = lead if lead.strip(_BLANK) else ""
            if not closer:
                rest = self.newline + self._child_indent(frame)
            elif frame.root or frame.owns_eof:
                # Se respeta un archivo sin salto final, salvo si no tenía ninguna entrada.
                rest = "" if frame.prev is not None else self.newline
            else:
                rest = self.newline + self._base_indent(frame)
        else:
            head, rest = split
        if head and _expects_value(head):
            # "clave =" descartada en la misma línea: lo nuevo va delante para no convertirse en su valor.
            head, rest = "", lead
        return head, rest

    def _store(self, frame: _Frame, index: int, lead: str) -> None:
        if index < 0:
            self._set_closer_lead(frame, lead)
        else:
            frame.items[index] = lead

    def _next_anchor(self, frame: _Frame) -> int:
        items = frame.items
        if items is not None:
            for index in range(frame.i, len(items)):
                if items[index] is not None:
                    return index
        return -1

    def _continues_list(self, frame: _Frame, entry: Entry) -> bool:
        """Un valor suelto tras otro valor suelto sigue en la misma línea si cabe."""
        if frame.root or frame.i < 2 or not _is_loose_scalar(entry):
            return False
        if not _is_loose_scalar(frame.block.entries[frame.i - 2]):
            return False
        line = self._line_text_at(len(self.out))
        # Con "#" en la línea (comentario o cadena) se prefiere una línea nueva.
        if "#" in line or not line.strip(_BLANK):
            return False
        width = len(scalar_source(entry._value))
        return len(line.expandtabs(_TAB_WIDTH)) + 1 + width <= INLINE_WIDTH

    def _child_indent(self, frame: _Frame) -> str:
        if frame.indent is None:
            frame.indent = self._infer_indent(frame)
        return frame.indent

    def _infer_indent(self, frame: _Frame) -> str:
        """Sangría más frecuente entre las entradas leídas del bloque que empiezan línea."""
        if not frame.generated:
            counts = Counter()
            for entry in frame.block._orig or ():
                indent = last_line_indent(first_token(entry).trivia)
                if indent is not None:
                    counts[indent] += 1
            indent = counts.most_common(1)[0][0] if counts else None
            if indent is None and frame.end == BRACE and not frame.root:
                indent = last_line_indent(frame.block._close.trivia)
                if indent is not None:
                    indent += self.unit
            if indent is not None:
                if frame.shift is not None:
                    indent = self._shifted(frame, "\n" + indent)[1:]
                return indent
        if frame.root:
            return ""
        return self._base_indent(frame) + self.unit

    def _base_indent(self, frame: _Frame) -> str:
        if frame.base is None:
            line = self._line_text_at(frame.open_pos)
            frame.base = line[: len(line) - len(line.lstrip(" \t"))]
        return frame.base

    def _line_text_at(self, position: int) -> str:
        """Texto de la línea de salida que termina en ``out[position - 1]``."""
        out = self.out
        pieces = []
        index = position - 1
        while index >= 0:
            chunk = out[index]
            if "\n" in chunk or "\r" in chunk:
                pieces.append(chunk[last_break_end(chunk):])
                break
            pieces.append(chunk)
            index -= 1
        return "".join(reversed(pieces))

    def _at_start(self) -> bool:
        for chunk in reversed(self.out):
            if chunk:
                return False
        return True

    # --- cierre ---------------------------------------------------------------------

    def _close(self, frame: _Frame) -> None:
        out = self.out
        if frame.generated:
            self._close_generated(frame)
        else:
            end = frame.end
            lead = self.eof_lead if frame.owns_eof else frame.closer_lead
            if frame.tail_pending:
                frame.tail_pending = False
                lead = self._fix_tail(frame, lead, True)
            if frame.items is None and frame.block._trailing_comments is not None:
                lead = self._with_trailing(frame, lead)
            if end == BRACE:
                if self.need_break:
                    self.need_break = False
                    if first_break(lead) < 0:
                        lead = self.newline + self._base_indent(frame) + lead.lstrip(_BLANK)
                out.append(self._unglued(lead))
                out.append("}")
            elif end == ADDED:
                if frame.owns_eof:
                    split = newline_split(lead, last=is_clean_trivia(lead))
                    if split is None or comment_start(split[1]) >= 0:
                        split = (lead, "")
                    head, rest = split
                else:
                    head, rest = lead, ""
                out.append(self._unglued(head))
                out.append(self.newline + self._base_indent(frame) + "}")
                self.need_break = False
                self._set_closer_lead(frame, rest)
            else:
                self._set_closer_lead(frame, lead)
                if end == END:
                    out.append(self._unglued(self.eof_lead))
        if frame.after:
            out.append(" " + frame.after)
            self.need_break = True

    def _close_generated(self, frame: _Frame) -> None:
        out = self.out
        newline = self.newline
        trailing = self._trailing(frame.block)
        if frame.root:
            for comment in trailing:
                out.append(comment if self._at_start() else newline + comment)
            if not self._at_start():
                out.append(newline)
            self.need_break = False
            return
        if frame.inline and not trailing and not self.need_break:
            out.append(" }")
            return
        if trailing:
            indent = self._child_indent(frame)
            for comment in trailing:
                out.append(newline + indent + comment)
        out.append(newline + self._base_indent(frame) + "}")
        self.need_break = False

    # --- comentarios y forma de los bloques generados ---------------------------

    def _comments_of(self, entry: Entry):
        """Comentarios de encima de una entrada generada o movida."""
        if self.canonical:
            return entry.comments if self.comments else ()
        if entry._comments is not None:
            return entry._comments
        token = first_token(entry)
        if token is None:
            return ()
        return _attached(token.trivia, starts_document(token))[1]

    def _trailing(self, block: Block):
        if self.canonical:
            return block.trailing_comments if self.comments else ()
        return block._trailing_comments or ()

    def _opening(self, block: Block):
        if self.canonical:
            return block.open_comment if self.comments else None
        return block._open_comment or None

    def _list_width(self, block: Block) -> int | None:
        """Ancho en una línea de un bloque generado de valores sueltos sin comentarios (deja de contar al
        pasar de ``INLINE_WIDTH``); None si no es una lista así."""
        if self._trailing(block):
            return None
        width = 0
        for entry in block.entries:
            if not _is_loose_scalar(entry) or self._comments_of(entry) or self.comments and entry._line_comment:
                return None
            if width <= INLINE_WIDTH:
                width += len(scalar_source(entry._value)) + 1
        return width


def to_source(node, *, newline: str | None = None) -> str:
    """Texto del nodo: idéntico al original salvo en las partes editadas.

    Para un ``Document`` incluye toda la trivia; para otros nodos se omite la
    trivia previa del propio nodo. ``newline`` (por defecto el del documento o
    ``"\\n"``) solo afecta al texto generado. Ningún BOM forma parte del texto (las
    posiciones del árbol no los cuentan): el de la codificación y los repetidos
    (``Document.extra_boms``) los pone ``write_file``.
    """
    if isinstance(node, Document):
        writer = _Writer(node, newline or node.newline, node._indent_unit, False, True)
    else:
        writer = _Writer(node, newline or "\n", "\t", False, True)
    return writer.write(node)


def format_canonical(node, *, indent: str = "\t", newline: str = "\n", comments: bool = False) -> str:
    """Impresión normalizada: ``clave = valor``, bloques sangrados y listas cortas en línea.

    Con ``comments`` incluye todos los comentarios: los de encima de cada entrada, el
    de final de su línea, el de la línea de cada ``{`` y los finales de cada bloque.
    """
    return _Writer(node, newline, indent, True, comments).write(node)


def _entry_name(entry: Entry, position: int) -> str:
    return f"[{position}]" if entry._key is None else entry._key._text


def _same_entry(a: Entry, b: Entry) -> bool:
    if a._key != b._key or a._op != b._op:
        return False
    value, other = a._value, b._value
    if value.__class__ is Scalar or other.__class__ is Scalar:
        return value == other
    # Un comentario que se traga una "}" al final del archivo deja el árbol igual, pero sin cerrar.
    return value._unclosed == other._unclosed


def _first_difference(expected: Block, actual: Block) -> tuple[str, int] | None:
    """Ruta (``a > b > c``) de la primera entrada distinta y su línea en el texto releído; None si no hay.

    Compara claves, operadores, valores, la forma de los bloques y si les falta la "}".
    """
    names: list[str] = []
    stack = [(iter(expected.entries), iter(actual.entries), 0)]
    last = None  # última entrada releída: la línea solo se calcula si hay diferencia
    while stack:
        mine, theirs, position = stack[-1]
        a, b = next(mine, None), next(theirs, None)
        if a is None and b is None:
            stack.pop()
            if names:
                names.pop()
            continue
        stack[-1] = (mine, theirs, position + 1)
        if b is not None:
            last = b
        if a is None or b is None or not _same_entry(a, b):
            names.append(_entry_name(a if a is not None else b, position))
            return " > ".join(names), (last.line if last is not None else None) or 1
        if a._value.__class__ is not Scalar:
            names.append(_entry_name(a, position))
            stack.append((iter(a._value.entries), iter(b._value.entries), 0))
    return None


def _new_error(read: list, reread: list):
    """Primer error del texto releído que no estaba en lo leído (comparando cuántos hay de cada código)."""
    left = Counter(d.code for d in read if d.severity is Severity.ERROR)
    for diagnostic in reread:
        if diagnostic.severity is Severity.ERROR:
            if left[diagnostic.code]:
                left[diagnostic.code] -= 1
            else:
                return diagnostic
    return None


def _entry_at(document: Document, line: int) -> str:
    """Ruta (``a > b``) de la última entrada que empieza en la línea ``line`` o antes."""
    found = []
    path = []
    stack = [iter(enumerate(document.entries))]
    while stack:
        for position, entry in stack[-1]:
            if (entry.line or 0) > line:
                return " > ".join(found)
            found = path + [_entry_name(entry, position)]
            if entry._value.__class__ is not Scalar:
                path = found
                stack.append(iter(enumerate(entry._value.entries)))
                break
        else:
            stack.pop()
            path = path[:-1]
    return " > ".join(found)


def _session_key(path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _repeated_boms(document: Document, encoding: str) -> str:
    """Los BOM repetidos del documento si se guarda en la codificación en que se leyeron y esta lleva BOM.

    Con cualquier otra no tienen sentido y se descartan. Una codificación desconocida no da error aquí:
    si es la de destino, lo da ``encode_text``.
    """
    if not document.extra_boms:
        return ""
    try:
        codec = normalize_encoding(encoding)
        same = codec in BOM_ENCODINGS and normalize_encoding(document.encoding or GAME_ENCODING) == codec
    except LookupError:
        return ""
    return BOM * document.extra_boms if same else ""


def render_checked(document_or_result, *, encoding: str | None = None, verify: bool = True,
                   path: str | os.PathLike | None = None) -> bytes:
    """Los bytes que escribiría ``write_file``, sin tocar el disco (wizard §6.1, paso 0 de §6.5).

    Misma verificación por relectura (``SourceMismatchError``, que nombra ``path``),
    misma codificación por defecto (la del documento; cp1252 si es nuevo) con sus
    BOM repetidos, y ``UnencodableTextError`` si algún carácter no cabe.
    ``write_file`` pasa a usarla sin cambiar su comportamiento.
    """
    from .parser import ParseResult, parse

    result = document_or_result if isinstance(document_or_result, ParseResult) else None
    document = document_or_result if result is None else result.document
    if not isinstance(document, Document):
        raise EditTypeError("not_a_document", {"type": type(document).__name__})
    text = to_source(document)
    if verify:
        reread = parse(text)
        difference = _first_difference(document, reread.document)
        read = result.diagnostics if result is not None else [] if document._eof is None else None
        if difference is None and read is not None:
            error = _new_error(read, reread.diagnostics)
            if error is not None:
                difference = _entry_at(reread.document, error.line), error.line
        if difference is not None:
            if result is not None:
                near_errors = any(d.severity is Severity.ERROR and d.code not in ENCODING_CODES for d in read)
            else:
                near_errors = bool(document.unclosed_blocks())
            raise SourceMismatchError(path, *difference, near_errors)
    codec = encoding or document.encoding or GAME_ENCODING
    return encode_text(_repeated_boms(document, codec) + text, codec)


def write_file(path: str | os.PathLike, document_or_result, *, encoding: str | None = None,
               backup: bool = True, verify: bool = True, expected=None) -> Path | None:
    """Escribe ``to_source`` de forma atómica; devuelve la copia de seguridad o None.

    La codificación por defecto es la del documento (``document.encoding``: la
    detectada al leer; cp1252 para documentos nuevos); los BOM repetidos del
    documento (``extra_boms``) se escriben delante solo si se guarda en esa misma
    codificación y lleva BOM (``encoding.BOM_ENCODINGS``). Con ``verify`` se comprueba
    antes que el texto se vuelve a leer como el árbol en memoria (con los mismos
    bloques sin cerrar) y sin errores de sintaxis que no estuvieran en lo leído (el
    ``ParseResult``; ninguno en un documento creado por código); si no, se lanza
    ``SourceMismatchError`` (con la ruta de la primera entrada distinta) y el
    archivo no se toca. Es lo que pasa al editar junto a los errores de sintaxis de
    un archivo (ver el docstring del módulo): el error lo indica (``near_errors``).
    Con ``backup`` se guarda ``archivo.bak`` con lo que tenía
    el archivo antes de su primer guardado de la sesión (del proceso): los
    guardados siguientes no lo pisan, así que sigue siendo el original. Con
    ``expected`` (``ParseResult.stamp``) se lanza ``FileChangedError`` sin escribir
    si el archivo ha cambiado fuera de la aplicación desde que se leyó. Al guardar
    un ``ParseResult`` en su propio archivo, su ``stamp`` pasa a ser el de lo escrito
    (el ``expected`` del guardado siguiente).
    """
    from .parser import ParseResult

    result = document_or_result if isinstance(document_or_result, ParseResult) else None
    data = render_checked(document_or_result, encoding=encoding, verify=verify, path=path)
    target = Path(path)
    session_key = _session_key(target)
    if backup and session_key in _SESSION_BACKUPS:
        atomic_write_bytes(target, data, expected=expected)
        existing = target.with_name(target.name + BACKUP_SUFFIX)
        made = existing if existing.exists() else None
    else:
        made = atomic_write_bytes(target, data, backup=backup, expected=expected)
        if backup:
            _SESSION_BACKUPS.add(session_key)
    if result is not None and result.path is not None and _session_key(result.path) == session_key:
        result.stamp = FileStamp.of(data)
    return made

