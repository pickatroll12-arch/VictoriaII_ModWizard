"""Motor de parseo sin pérdidas del formato Clausewitz (.txt, .mod, .gfx, .gui...).

``parse`` / ``parse_file`` construyen un árbol sintáctico concreto que conserva
espacios, comentarios, saltos de línea y hasta los errores de sintaxis, de modo
que ``to_source`` reproduce el texto exacto; las ediciones hechas con la API de
``Block`` / ``Entry`` solo cambian lo editado. ``to_json`` / ``from_json`` /
``simplify`` / ``walk`` / ``iter_json`` exponen el árbol a la interfaz. Los
errores de la API son ``EditError`` / ``EditTypeError`` (código y mensaje en
español o inglés). Sin dependencias de Qt.
"""

from .diagnostics import Diagnostic, EditError, EditTypeError, Severity
from .json_bridge import from_json, iter_json, simplify, to_json, walk
from .nodes import OPERATORS, Block, ClausewitzDate, Document, Entry, Scalar
from .parser import CLAUSEWITZ_SUFFIXES, ParseResult, parse, parse_file
from .serializer import SourceMismatchError, format_canonical, render_checked, to_source, write_file

__all__ = [
    "CLAUSEWITZ_SUFFIXES",
    "OPERATORS",
    "Block",
    "ClausewitzDate",
    "Diagnostic",
    "Document",
    "EditError",
    "EditTypeError",
    "Entry",
    "ParseResult",
    "Scalar",
    "Severity",
    "SourceMismatchError",
    "format_canonical",
    "from_json",
    "iter_json",
    "parse",
    "parse_file",
    "render_checked",
    "simplify",
    "to_json",
    "to_source",
    "walk",
    "write_file",
]
