"""Serialización de documentos Clausewitz.

``to_source`` reproduce exactamente las partes no editadas (trivia + texto de
cada token original) y da formato a lo editado o creado por código según su
contexto: sangría de los hermanos, unidad de sangría del archivo y salto de
línea del documento. Las entradas nuevas al final de un bloque van justo antes
de la línea de la llave de cierre; entre dos entradas, antes de los comentarios
que preceden a la siguiente. ``format_canonical`` ignora el formato original.

Ambos recorridos son iterativos, así que la profundidad no está limitada.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..encoding import GAME_ENCODING
from ..fileio import write_text
from .lexer import OP, OPEN_STRING, is_clean_trivia, last_line_indent, newline_split, tokenize
from .nodes import Block, Document, Entry, Scalar, first_token, scalar_source

INLINE_WIDTH = 80  # ancho máximo de una lista de escalares en una línea
_BLANK = " \t\r\x0b\x0c"

# Modos de colocación de las entradas generadas dentro de un bloque.
LINE, INLINE, WRAP = "line", "inline", "wrap"


class SourceMismatchError(ValueError):
    """El texto generado no se vuelve a leer como el árbol en memoria; no se ha escrito nada."""


def _expects_value(trivia: str) -> bool:
    """True si el texto descartado de la trivia acaba en ``clave operador`` (falta el valor)."""
    if is_clean_trivia(trivia):
        return False
    tokens = tokenize(trivia)[:-1]
    index = len(tokens) - 1
    while index >= 0 and tokens[index].kind == OP:
        index -= 1
    return index >= 0 and index < len(tokens) - 1 and tokens[index].kind <= OPEN_STRING


class _Frame:
    __slots__ = (
        "block", "i", "root", "generated", "closer", "inline", "wrap", "open_pos",
        "indent", "base", "run", "override", "override_trivia", "line_len",
    )

    def __init__(self, block, root, generated, closer, inline, wrap, open_pos):
        self.block = block
        self.i = 0
        self.root = root
        self.generated = generated  # sin tokens originales (o en modo canónico)
        self.closer = closer  # "}" original, EOF del documento o None
        self.inline = inline
        self.wrap = wrap
        self.open_pos = open_pos  # posición en la salida justo tras "{"
        self.indent = None  # sangría de las entradas generadas (perezosa)
        self.base = None  # sangría de la línea de "{" (perezosa)
        self.run = None  # modo de la racha actual de entradas generadas
        self.override = None  # token cuya trivia se emite partida...
        self.override_trivia = None  # ...y lo que queda de ella
        self.line_len = 0


class _Writer:
    def __init__(self, newline: str, unit: str, canonical: bool, comments: bool):
        self.out: list[str] = []
        self.newline = newline
        self.unit = unit
        self.canonical = canonical
        self.comments = comments

    def write(self, node) -> str:
        if isinstance(node, Document):
            generated = self.canonical or node._eof is None
            closer = None if generated else node._eof
            self._run(_Frame(node, True, generated, closer, False, False, 0))
        elif isinstance(node, Block):
            self.out.append("{")
            self._run(self._open_frame(node, False))
        elif isinstance(node, Entry):
            child = self._entry(None, node, "")
            if child is not None:
                self._run(child)
        elif isinstance(node, Scalar):
            self.out.append(scalar_source(node))
        else:
            raise TypeError(f"no es un nodo Clausewitz: {type(node).__name__}")
        return "".join(self.out)

    # --- recorrido -------------------------------------------------------------

    def _run(self, frame: _Frame) -> None:
        stack = [frame]
        canonical = self.canonical
        while stack:
            frame = stack[-1]
            entries = frame.block.entries
            child = None
            while frame.i < len(entries):
                entry = entries[frame.i]
                frame.i += 1
                token = None if canonical else first_token(entry)
                if token is not None:
                    frame.run = None
                    lead = frame.override_trivia if token is frame.override else token.trivia
                else:
                    lead = self._generated_lead(frame, entry)
                child = self._entry(frame, entry, lead)
                if child is not None:
                    break
            if child is not None:
                stack.append(child)
            else:
                self._close(frame)
                stack.pop()

    def _entry(self, frame, entry: Entry, lead: str):
        """Emite la entrada; si su valor es un bloque, emite "{" y devuelve su marco."""
        out = self.out
        canonical = self.canonical
        value = entry._value
        vtok = None if canonical else entry._vtok
        key = entry._key
        if key is not None:
            ktok = None if canonical else entry._ktok
            out.append(lead)
            out.append(scalar_source(key) if ktok is None or ktok.raw is None else ktok.raw)
            otok = None if canonical else entry._otok
            if otok is None:
                out.append(" ")
                out.append(entry._op)
            else:
                out.append(otok.trivia)
                out.append(entry._op if otok.raw is None else otok.raw)
            if vtok is not None:
                vlead = vtok.trivia
            elif not canonical and value.__class__ is not Scalar and value._open is not None:
                vlead = value._open.trivia
            else:
                vlead = " "
        else:
            vlead = lead
        out.append(vlead)
        if value.__class__ is Scalar:
            out.append(scalar_source(value) if vtok is None or vtok.raw is None else vtok.raw)
            return None
        out.append("{")
        inline_context = frame is not None and (frame.inline or frame.run == INLINE)
        return self._open_frame(value, inline_context)

    def _open_frame(self, block: Block, inline_context: bool) -> _Frame:
        open_pos = len(self.out)
        if self.canonical or block._open is None:
            inline = inline_context or self._fits_inline(block)
            wrap = not inline and self._is_scalar_list(block)
            return _Frame(block, False, True, None, inline, wrap, open_pos)
        close = block._close
        inline = close is not None and close.line == block._open.line
        return _Frame(block, False, False, close, inline, False, open_pos)

    def _close(self, frame: _Frame) -> None:
        out = self.out
        newline = self.newline
        if frame.root:
            if not frame.generated:
                closer = frame.closer
                out.append(frame.override_trivia if closer is frame.override else closer.trivia)
                return
            for comment in self._trailing(frame.block):
                out.append(comment if self._at_start() else newline + comment)
            if not self._at_start():
                out.append(newline)
            return
        if not frame.generated:
            closer = frame.closer
            if closer is not None:  # un bloque leído sin "}" sigue sin ella
                out.append(frame.override_trivia if closer is frame.override else closer.trivia)
                out.append("}")
            return
        trailing = self._trailing(frame.block)
        if frame.inline and not trailing:
            out.append(" }")
            return
        if trailing:
            indent = self._child_indent(frame)
            for comment in trailing:
                out.append(newline + indent + comment)
        out.append(newline + self._base_indent(frame) + "}")

    # --- entradas generadas ----------------------------------------------------

    def _generated_lead(self, frame: _Frame, entry: Entry) -> str:
        if frame.run is None:
            self._start_run(frame)
        comments = self._comments(entry)
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
        pieces = []
        for comment in comments:
            pieces.append(indent + comment if at_start and not pieces else newline + indent + comment)
        pieces.append(indent if at_start and not pieces else newline + indent)
        return "".join(pieces)

    def _start_run(self, frame: _Frame) -> None:
        """Decide cómo colocar una racha de entradas generadas y parte la trivia vecina."""
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
        target, is_closer = self._next_token(frame)
        if target is None:
            return
        trivia = frame.override_trivia if target is frame.override else target.trivia
        if mode == INLINE:
            # Hace falta un separador si el token siguiente iba pegado; "{}" pasa a "{ x }".
            if not trivia and (not is_closer or frame.i == 1):
                frame.override, frame.override_trivia = target, " "
            return
        # Ante la llave de cierre se inserta tras los comentarios finales del bloque;
        # ante otra entrada, antes de los comentarios que la preceden.
        split = newline_split(trivia, last=is_closer and is_clean_trivia(trivia))
        if split is None:
            head = trivia if trivia.strip(_BLANK) else ""
            if not is_closer:
                rest = self.newline + self._child_indent(frame)
            elif frame.root:
                # Se respeta un archivo sin salto final, salvo si no tenía ninguna entrada.
                has_entries = any(first_token(entry) is not None for entry in frame.block.entries)
                rest = "" if has_entries else self.newline
            else:
                rest = self.newline + self._base_indent(frame)
        else:
            head, rest = split
        if head and _expects_value(head):
            # "clave =" descartada en la misma línea: lo nuevo va delante para no convertirse en su valor.
            head, rest = "", trivia
        self.out.append(head)
        frame.override, frame.override_trivia = target, rest

    def _continues_list(self, frame: _Frame, entry: Entry) -> bool:
        """Un valor suelto tras otro valor suelto sigue en la misma línea si cabe."""
        if frame.root or entry._key is not None or entry._value.__class__ is not Scalar or frame.i < 2:
            return False
        previous = frame.block.entries[frame.i - 2]
        if previous._key is not None or previous._value.__class__ is not Scalar:
            return False
        line = self._current_line()
        # Con "#" en la línea (comentario o cadena) se prefiere una línea nueva.
        if "#" in line or not line.strip(_BLANK):
            return False
        width = len(scalar_source(entry._value))
        return len(line.expandtabs(4)) + 1 + width <= INLINE_WIDTH

    def _current_line(self) -> str:
        return self._line_text_at(len(self.out))

    def _next_token(self, frame: _Frame):
        entries = frame.block.entries
        for index in range(frame.i, len(entries)):
            token = first_token(entries[index])
            if token is not None:
                return token, False
        return frame.closer, True

    def _child_indent(self, frame: _Frame) -> str:
        if frame.indent is None:
            frame.indent = self._infer_indent(frame)
        return frame.indent

    def _infer_indent(self, frame: _Frame) -> str:
        if not frame.generated:
            for entry in frame.block.entries:
                token = first_token(entry)
                if token is not None:
                    indent = last_line_indent(token.trivia)
                    if indent is not None:
                        return indent
            if not frame.root and frame.closer is not None:
                indent = last_line_indent(frame.closer.trivia)
                if indent is not None:
                    return indent + self.unit
        if frame.root:
            return ""
        return self._base_indent(frame) + self.unit

    def _base_indent(self, frame: _Frame) -> str:
        if frame.base is None:
            frame.base = self._line_indent_at(frame.open_pos)
        return frame.base

    def _line_text_at(self, position: int) -> str:
        """Texto de la línea de salida que termina en ``out[position - 1]``."""
        out = self.out
        pieces = []
        index = position - 1
        while index >= 0:
            chunk = out[index]
            cut = chunk.rfind("\n")
            if cut >= 0:
                pieces.append(chunk[cut + 1:])
                break
            pieces.append(chunk)
            index -= 1
        return "".join(reversed(pieces))

    def _line_indent_at(self, position: int) -> str:
        line = self._line_text_at(position)
        return line[: len(line) - len(line.lstrip(" \t"))]

    def _at_start(self) -> bool:
        for chunk in reversed(self.out):
            if chunk:
                return False
        return True

    # --- comentarios y forma de los bloques generados ---------------------------

    def _comments(self, entry: Entry):
        if self.canonical:
            return entry.comments if self.comments else ()
        return entry._comments or ()

    def _trailing(self, block: Block):
        if self.canonical:
            return block.trailing_comments if self.comments else ()
        return block._trailing_comments or ()

    def _fits_inline(self, block: Block) -> bool:
        if self._trailing(block):
            return False
        width = 0
        for entry in block.entries:
            if entry._key is not None or entry._value.__class__ is not Scalar or self._comments(entry):
                return False
            width += len(scalar_source(entry._value)) + 1
            if width > INLINE_WIDTH:
                return False
        return True

    def _is_scalar_list(self, block: Block) -> bool:
        if not block.entries or self._trailing(block):
            return False
        for entry in block.entries:
            if entry._key is not None or entry._value.__class__ is not Scalar or self._comments(entry):
                return False
        return True


def to_source(node, *, newline: str | None = None) -> str:
    """Texto del nodo: idéntico al original salvo en las partes editadas.

    Para un ``Document`` incluye toda la trivia; para otros nodos se omite la
    trivia previa del propio nodo. ``newline`` (por defecto el del documento o
    ``"\\n"``) solo afecta al texto generado.
    """
    if isinstance(node, Document):
        writer = _Writer(newline or node.newline, node._indent_unit, False, True)
    else:
        writer = _Writer(newline or "\n", "\t", False, True)
    return writer.write(node)


def format_canonical(node, *, indent: str = "\t", newline: str = "\n", comments: bool = False) -> str:
    """Impresión normalizada: ``clave = valor``, bloques sangrados y listas cortas en línea.

    Con ``comments`` incluye los comentarios previos a cada entrada y los finales
    de cada bloque.
    """
    return _Writer(newline, indent, True, comments).write(node)


def write_file(path: str | os.PathLike, document_or_result, *, encoding: str | None = None,
               backup: bool = True, verify: bool = True) -> Path | None:
    """Escribe ``to_source`` de forma atómica; devuelve la copia de seguridad o None.

    La codificación por defecto es la detectada al leer (cp1252 para documentos
    nuevos). Con ``verify`` se comprueba antes que el texto se vuelve a leer como
    el árbol en memoria (puede fallar si se editó junto a errores de sintaxis);
    si no, se lanza ``SourceMismatchError`` y el archivo no se toca.
    """
    from .parser import ParseResult, parse

    if isinstance(document_or_result, ParseResult):
        document = document_or_result.document
        detected = document_or_result.encoding
    else:
        document = document_or_result
        detected = getattr(document, "encoding", None)
    if not isinstance(document, Document):
        raise TypeError(f"write_file() espera Document o ParseResult, no {type(document).__name__}")
    text = to_source(document)
    if verify:
        # Sin sangría el texto canónico crece linealmente con la profundidad y la comparación es plana.
        expected = format_canonical(document, indent="")
        if format_canonical(parse(text).document, indent="") != expected:
            raise SourceMismatchError(
                f"{path}: el texto generado no se vuelve a leer igual que el documento editado "
                "(¿ediciones junto a errores de sintaxis?); no se ha escrito el archivo"
            )
    return write_text(path, text, encoding or detected or GAME_ENCODING, backup=backup)
