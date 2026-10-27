"""Localización CSV de Victoria II: lectura, edición, validación y base de claves.

Formato: una entrada por línea, campos separados por ";" (no es CSV estándar: el
juego no interpreta comillas ni escapes). Columna 0 = clave, columnas 1..13 =
idiomas en el orden de ``LANGUAGE_COLUMNS``, columna 14 = marcador de fin "x";
tras la "x" puede haber campos extra. Esta numeración desde 0 es la de todos los
mensajes y argumentos de columna del módulo. Las líneas que empiezan por "#" son
comentarios. Codificación cp1252. El juego vanilla solo muestra English, French,
German y Spanish (``DISPLAYED_LANGUAGES``); las demás columnas se conservan pero
no se ven. El juego lee las columnas por posición; la "x" es la convención de
los archivos vanilla para marcar el final (y que las hojas de cálculo no
recorten las columnas vacías). Por eso el lint solo avisa de las filas a las que
les falta un idioma visible o que tienen columnas desplazadas; la falta de
columnas ocultas o de la "x" es una nota (INFO). El juego carga como localización
los ``.csv`` de la carpeta ``localisation`` (``is_localisation_csv``), no los de
``map/``.

Lo que muestra el corpus (Plantilla Mod/localisation, 22 .csv vanilla):

* Todos en cp1252, sin BOM, con CRLF y salto final; sin líneas vacías intermedias.
  168 comentarios, muchos con ";" (``#;;;;;;;;;;;;;;x;;;;``).
* 21 678 filas de datos: 18 358 con la "x" en la columna 14, 3 278 con la "x" en
  otra columna y 42 sin "x". Las "x" anteriores a la 14 son filas con columnas de
  menos (``darkness_3_01.csv`` usa ``clave;en;fr;de;;es;;;;;;x``); las
  posteriores, textos con un ";" de más. En ``text.csv`` varios caracteres se
  perdieron como "?" junto con su ";" (``Difficult?Schwierigkeit``), lo que
  desplaza columnas. El marcador aparece también como "X", "x ", " x" y "x" con
  tabuladores. Tras la "x" hay de 0 a 11 campos, vacíos salvo un espacio en
  ``event_news.csv`` (``text.csv`` usa ``;x;;;;``).
* 203 filas contienen comillas, pero ninguna encierra un ";" al estilo CSV: el
  juego las muestra tal cual. No hay filas de cabecera.
* Claves repetidas: 100 definiciones repetidas dentro del mismo archivo (79 en
  ``text.csv``), 41 claves repetidas entre archivos (``SPA_2209`` en ``1.2.csv``
  y ``text.csv``) y 9 pares que solo difieren en mayúsculas (``CANCEL``/``cancel``).
  Una fila sin clave (última de ``text.csv``: ``;;;;*;;*;*;;;;;;;x;;;;``).
* ``text.csv.bak`` es una copia anterior de ``text.csv`` con el mismo formato.

En el mod del usuario (VSM), ``00_VSM_countries/decisions/modifiers.csv`` empiezan
con la cabecera ``key;English;French;...`` y sus filas tienen las 13 columnas de
idioma pero ninguna "x". En ``00_VSM_decisions.csv`` (líneas 35 a 45) seis textos
ingleses van entre comillas con un ";" dentro: el juego corta el texto y el
español acaba en la columna del italiano (``semicolon_in_quotes``). El resto de
sus .csv son copias de los vanilla con el mismo nombre, que los sustituyen.

Garantía: ``to_source`` reproduce byte a byte (tras codificar con
``file.encoding``) cualquier archivo sin editar, incluidos saltos CRLF/LF
mezclados, la ausencia de salto final, líneas vacías, comentarios y extras.
Las filas editadas con ``set`` se reescriben como ``clave;13 idiomas;x;extras``.
"""

from __future__ import annotations

from .db import KeyOverride, LocalisationDB
from .diagnostics import CODES, CsvDiagnostic, Severity
from .model import (
    DISPLAYED_LANGUAGES,
    END_MARKER,
    END_MARKER_COLUMN,
    LANGUAGE_CODES,
    LANGUAGE_COLUMNS,
    LANGUAGE_COUNT,
    DuplicateKeyError,
    InvalidFieldError,
    LocalisationFile,
    LocRow,
    RowKind,
    column_index,
    is_localisation_csv,
)
from .serialization import (
    from_json,
    parse_csv,
    read_csv_file,
    render_csv_checked,
    to_json,
    to_source,
    write_csv_file,
)

__all__ = [
    "CODES", "DISPLAYED_LANGUAGES", "END_MARKER", "END_MARKER_COLUMN", "LANGUAGE_CODES",
    "LANGUAGE_COLUMNS", "LANGUAGE_COUNT", "CsvDiagnostic", "DuplicateKeyError", "InvalidFieldError",
    "KeyOverride", "LocalisationDB", "LocalisationFile", "LocRow", "RowKind", "Severity", "column_index",
    "from_json", "is_localisation_csv", "parse_csv", "read_csv_file", "render_csv_checked", "to_json", "to_source",
    "write_csv_file",
]
