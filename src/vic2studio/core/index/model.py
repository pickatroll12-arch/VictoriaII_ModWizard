"""Tipos del índice de símbolos: definiciones, referencias y hechos por archivo (wizard §7).

Dataclasses congeladas sin E/S: el agente de interfaz las importa desde el commit
de contrato. Un **extractor** lee un archivo (bytes ya leídos, nunca el CST vivo:
I12) y devuelve sus definiciones (``Symbol``) y referencias (``SymbolRef``); el
índice combina los ``FileFacts`` de todas las capas según las reglas de carga
(§5.2). Los extractores se registran con ``@extractor`` en módulos de
``core/index/extractors/`` y se descubren con ``pkgutil`` (sin listas centrales).
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..vfs.model import Fingerprint, LayerKind
from ..vfs.paths import VPath
from ..vfs.rules import _compile

# Formato de la caché de hechos: subirlo invalida todas las cachés (cada extractor tiene además su versión).
INDEX_FORMAT = 1

# --- tipos de símbolo (wizard §7, tabla) ----------------------------------------------------------
# Países y política
KIND_TAG = "tag"                         # common/countries.txt; attrs: file, dynamic, color
KIND_PARTY = "party"                     # common/countries/*.txt; name = "<archivo de país>:<nombre>" (H12)
KIND_GOVERNMENT = "government"           # common/governments.txt; attrs: ideologies, election, duration, flag_type
KIND_IDEOLOGY = "ideology"
KIND_ISSUE_GROUP = "issue_group"         # common/issues.txt; attrs: category (party_issues, political_reforms…)
KIND_ISSUE_OPTION = "issue_option"       # attrs: group, category
KIND_NATIONAL_VALUE = "national_value"
# Mapa
KIND_PROVINCE = "province"               # map/definition.csv (+ default.map: sea_starts); attrs: color, is_sea
KIND_SEA_PROVINCE = "sea_province"
KIND_PROVINCE_HISTORY = "province_history"   # history/provinces/**; name = id
KIND_REGION = "region"                   # map/region.txt; attrs: provinces
KIND_SEA_REGION = "sea_region"
KIND_CONTINENT = "continent"
KIND_CLIMATE = "climate"
KIND_TERRAIN = "terrain"
# Población y cultura
KIND_CULTURE = "culture"                 # common/cultures.txt; attrs: group
KIND_CULTURE_GROUP = "culture_group"
KIND_RELIGION = "religion"               # common/religion.txt; attrs: group
KIND_RELIGION_GROUP = "religion_group"
KIND_POP_TYPE = "pop_type"               # poptypes/*.txt
# Economía, técnica y ejército
KIND_GOODS = "goods"
KIND_BUILDING = "building"
KIND_TECHNOLOGY = "technology"           # technologies/*.txt; attrs: folder, area, year
KIND_INVENTION = "invention"
KIND_TECH_SCHOOL = "tech_school"
KIND_UNIT_TYPE = "unit_type"             # units/*.txt; attrs: type ("land" | "naval")
KIND_GRAPHICAL_CULTURE = "graphical_culture"
KIND_REBEL_TYPE = "rebel_type"
KIND_TRAIT = "trait"
KIND_MODIFIER = "modifier"
# Guerra, historia y guion
KIND_CB = "cb"                           # common/cb_types.txt (sin peace_order); attrs: in_peace_order
KIND_BOOKMARK = "bookmark"               # common/bookmarks.txt; attrs: date
KIND_WAR = "war"                         # history/wars/*.txt
KIND_COUNTRY_HISTORY = "country_history"     # history/countries/<TAG> - <Nombre>.txt; name = TAG
KIND_EVENT = "event"                     # events/*.txt; name = id; attrs: type (country_event | province_event)
KIND_DECISION = "decision"               # decisions/*.txt
# Interfaz e imágenes
KIND_SPRITE = "sprite"                   # interface/*.gfx; attrs: texture, frames
KIND_GUI_WINDOW = "gui_window"
KIND_IMAGE = "image"                     # gfx/** (name = ruta relativa en minúsculas)
# Localización y marcas
KIND_LOC_KEY = "loc_key"                 # localisation/*.csv (el ganador por orden de carga)
KIND_COUNTRY_FLAG = "country_flag"       # definidos por uso (set_country_flag): nunca «inexistentes»
KIND_GLOBAL_FLAG = "global_flag"
KIND_PROVINCE_FLAG = "province_flag"
# Ampliación de la iteración 3 (compatible): archivos que se nombran desde otros.
KIND_COUNTRY_FILE = "country_file"       # common/countries/*.txt; name = "countries/<Archivo>.txt" (como en
                                         # countries.txt); attrs: color, graphical_culture, parties
KIND_FILE = "file"                       # solo en referencias: un archivo por su ruta (``oob``); name = ruta en
                                         # minúsculas con «/»
KIND_TECH_FOLDER = "tech_folder"         # common/technology.txt → folders; attrs: areas
KIND_POP_BLOCK = "pop_block"             # history/pops/<fecha>/*.txt; name = "<fecha>:<provincia>" (H10)

# Rol de las referencias de ``default.map: sea_starts`` (kind ``province``): las provincias de mar.
ROLE_SEA_STARTS = "sea_starts"


@dataclass(frozen=True)
class Symbol:
    """Una definición. ``name`` es el identificador del juego (``PRU``, ``549``, ``north_german``).

    ``line`` empieza en 1 (None si el archivo no tiene líneas, p. ej. una imagen).
    ``attrs`` guarda los datos que necesitan los validadores y los selectores sin
    abrir el archivo (ver los comentarios de ``KIND_*``); debe ser serializable en
    JSON (str, int, float, bool, None, listas y diccionarios de ellos). No cuenta
    en el ``hash`` (un ``Symbol`` se puede meter en un conjunto).
    """

    kind: str
    name: str
    rel: VPath
    line: int | None
    layer: LayerKind
    attrs: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}), hash=False)


@dataclass(frozen=True)
class SymbolRef:
    """Un uso de ``kind``/``name`` en ``rel``. ``role`` dice qué campo lo usa (``owner``, ``add_core``,
    ``nationalvalue``, ``casus_belli``, ``texturefile``…): lo usan «dónde se usa», el renombrado y los mensajes."""

    kind: str
    name: str
    rel: VPath
    line: int | None
    column: int | None
    role: str


@dataclass(frozen=True)
class FileFacts:
    """Lo que un extractor sacó de un archivo concreto de una capa (unidad de la caché y de ``apply``)."""

    rel: VPath
    layer: LayerKind
    fingerprint: Fingerprint
    defs: tuple[Symbol, ...]
    refs: tuple[SymbolRef, ...]
    extractor: str                       # nombre del extractor que los produjo
    version: int                         # su versión: si cambia, la caché de ese extractor no vale


# --- registro de extractores ------------------------------------------------------------------------

# fn(rel, data, layer) -> (defs, refs): recibe los bytes del archivo y la capa de la que vienen.
ExtractorFn = Callable[[VPath, bytes, LayerKind], tuple[tuple[Symbol, ...], tuple[SymbolRef, ...]]]


@dataclass(frozen=True)
class ExtractorSpec:
    name: str                            # «modulo.funcion», estable (va a la caché)
    pattern: str                         # glob relativo sin mayúsculas, como LoadRule.pattern
    version: int
    fn: ExtractorFn
    needs_data: bool = True              # False: solo mira la ruta (imágenes); el constructor no lee el archivo

    def matches(self, rel: VPath) -> bool:
        return _compile(self.pattern).fullmatch(rel if isinstance(rel, VPath) else VPath.of(rel)) is not None


EXTRACTORS: list[ExtractorSpec] = []


def extractor(pattern: str, *, version: int, needs_data: bool = True) -> Callable[[ExtractorFn], ExtractorFn]:
    """Decorador: registra ``fn`` para los archivos que encajan con ``pattern``. Subir ``version`` invalida
    solo la caché de este extractor (criterio 2 de la iteración 3). Un archivo puede tener varios.

    ``needs_data=False``: el extractor solo usa la ruta (recibe ``b""``) y el constructor no lee el archivo.
    """

    def register(fn: ExtractorFn) -> ExtractorFn:
        name = f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__name__}"
        if any(spec.name == name for spec in EXTRACTORS):
            raise ValueError(f"extractor repetido: {name}")
        EXTRACTORS.append(ExtractorSpec(name, pattern, version, fn, needs_data))
        return fn

    return register


def discover_extractors() -> list[ExtractorSpec]:
    """Importa ``core/index/extractors/*`` (registran con ``@extractor``) y devuelve el registro."""
    from . import extractors as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{info.name}")
    return list(EXTRACTORS)


def extractors_for(rel: VPath) -> list[ExtractorSpec]:
    """Los extractores registrados que procesan ``rel`` (tras ``discover_extractors``)."""
    rel = rel if isinstance(rel, VPath) else VPath.of(rel)
    return [spec for spec in EXTRACTORS if _compile(spec.pattern).fullmatch(rel) is not None]


_FOLD_RE = re.compile(r"[̀-ͯ]")


def fold(text: str) -> str:
    """Texto para buscar: sin mayúsculas ni acentos («Berlín» → «berlin»), para ``SymbolIndex.search``."""
    import unicodedata

    return _FOLD_RE.sub("", unicodedata.normalize("NFD", text)).casefold()
