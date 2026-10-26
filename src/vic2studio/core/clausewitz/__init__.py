"""Motor de parseo sin pérdidas del formato Clausewitz (.txt, .mod, .gfx, .gui...).

``parse`` / ``parse_file`` construyen un árbol sintáctico concreto que conserva
espacios, comentarios, saltos de línea y hasta los errores de sintaxis, de modo
que ``to_source`` reproduce el texto exacto; las ediciones hechas con la API de
``Block`` / ``Entry`` solo cambian lo editado. ``to_json`` / ``from_json`` /
``simplify`` / ``walk`` exponen el árbol a la interfaz. Sin dependencias de Qt.
"""

from .diagnostics import Diagnostic, Severity
from .json_bridge import from_json, simplify, to_json, walk
from .nodes import OPERATORS, Block, ClausewitzDate, Document, Entry, Scalar
from .parser import ParseResult, parse, parse_file
from .serializer import SourceMismatchError, format_canonical, to_source, write_file

__all__ = [
    "OPERATORS",
    "Block",
    "ClausewitzDate",
    "Diagnostic",
    "Document",
    "Entry",
    "ParseResult",
    "Scalar",
    "Severity",
    "SourceMismatchError",
    "format_canonical",
    "from_json",
    "parse",
    "parse_file",
    "simplify",
    "to_json",
    "to_source",
    "walk",
    "write_file",
]
