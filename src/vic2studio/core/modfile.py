"""Descriptor ``.mod`` de un mod de Victoria II: lectura, escritura y generación.

El descriptor suele vivir en ``<juego>/mod/<Nombre>.mod``, junto a la carpeta del
mod (``path = "mod/<carpeta>"``); algunos mods guardan además una copia dentro de
su propia carpeta. Se lee con el parser Clausewitz, así que sus errores de
sintaxis llegan como diagnósticos; ``modcheck.check_descriptor`` revisa sus
campos. ``write_descriptor`` edita un descriptor existente sin tocar lo demás
(comentarios, claves desconocidas) o genera uno nuevo en cp1252 con CRLF; un
valor que no se puede escribir lanza ``DescriptorFieldError``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .clausewitz import Block, Diagnostic, ParseResult, Scalar, Severity, parse, parse_file, to_source, write_file
from .encoding import BOM, GAME_ENCODING, GAME_UNREADABLE
from .fileio import write_text

DESCRIPTOR_SUFFIX = ".mod"
SIBLING = "sibling"
INSIDE = "inside"
NEWLINE = "\r\n"
# Campos de texto en el orden en que se escriben en un descriptor nuevo.
_TEXT_FIELDS = ("name", "path", "user_dir")

# Códigos de ``DescriptorFieldError``.
FIELD_QUOTE = "descriptor_quote"
FIELD_NEWLINE = "descriptor_newline"
MESSAGES = {
    "es": {
        FIELD_QUOTE: "«{field}» no puede contener comillas (\"): {value}",
        FIELD_NEWLINE: "«{field}» no puede contener saltos de línea.",
    },
    "en": {
        FIELD_QUOTE: "“{field}” cannot contain quotes (\"): {value}",
        FIELD_NEWLINE: "“{field}” cannot contain line breaks.",
    },
}


class DescriptorFieldError(ValueError):
    """Un valor que el descriptor no puede guardar entre comillas.

    ``code`` (``FIELD_QUOTE`` o ``FIELD_NEWLINE``) y ``params`` (``field``, el
    campo, y ``value``) lo identifican; ``message(lang)`` da el texto en español o
    inglés y ``str()``, en español.
    """

    def __init__(self, code: str, **params: str):
        self.code = code
        self.params = params
        super().__init__(self.message("es"))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[self.code].format(**self.params)


def normalize_folder(path: str) -> str:
    """Ruta de carpeta relativa comparable: ``/`` como separador, sin barras sobrantes y en minúsculas."""
    parts = [part for part in path.replace("\\", "/").split("/") if part and part != "."]
    return "/".join(parts).casefold()


@dataclass(frozen=True)
class ModDescriptor:
    """Campos de un descriptor; ``diagnostics`` (de sintaxis) y ``encoding`` no cuentan al comparar ni en el hash."""

    file: Path
    name: str = ""
    path: str = ""
    user_dir: str = ""
    replace_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = field(default=(), compare=False)
    # SIBLING: junto a la carpeta del mod; INSIDE: dentro de ella.
    location: str = SIBLING
    # Archivo comprimido con el mod (``archive = "mod/x.zip"``), si lo usa en vez de ``path``.
    archive: str = ""
    # Codificación del archivo leído (ver ``game_readable``).
    encoding: str = field(default=GAME_ENCODING, compare=False)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def game_readable(self) -> bool:
        """False si el juego no puede leer el archivo por su codificación (UTF-16, ``encoding.GAME_UNREADABLE``)."""
        return self.encoding not in GAME_UNREADABLE

    @property
    def folder_name(self) -> str:
        """Última parte de ``path`` (``mod/VSM`` -> ``VSM``); admite ``\\`` como separador."""
        return PurePosixPath(self.path.replace("\\", "/")).name if self.path else ""

    @property
    def normalized_replace_paths(self) -> tuple[str, ...]:
        """``replace_paths`` comparables (ver ``normalize_folder``): ``common\\\\countries/`` -> ``common/countries``."""
        return tuple(normalize_folder(p) for p in self.replace_paths)

    def replaces(self, folder: str) -> bool:
        """True si el mod sustituye por completo esa carpeta del juego (``replaces("localisation")``)."""
        return normalize_folder(folder) in self.normalized_replace_paths


def _scalar_text(value) -> str:
    return value.text if isinstance(value, Scalar) else ""


def descriptor_from_result(file: str | os.PathLike, result: ParseResult, *, location: str = SIBLING) -> ModDescriptor:
    """Descriptor a partir del análisis ya hecho de ``file``."""
    doc = result.document
    dependencies: list[str] = []
    for value in doc.get_all("dependencies"):
        if isinstance(value, Block):
            dependencies.extend(_scalar_text(v) for v in value.values() if isinstance(v, Scalar))
        elif isinstance(value, Scalar):
            dependencies.append(value.text)
    return ModDescriptor(
        file=Path(file),
        name=_scalar_text(doc.get("name")).strip(),
        path=_scalar_text(doc.get("path")).strip(),
        user_dir=_scalar_text(doc.get("user_dir")).strip(),
        replace_paths=tuple(_scalar_text(v) for v in doc.get_all("replace_path") if isinstance(v, Scalar)),
        dependencies=tuple(dependencies),
        diagnostics=tuple(result.diagnostics),
        location=location,
        archive=_scalar_text(doc.get("archive")).strip(),
        encoding=result.encoding,
    )


def read_descriptor(file: str | os.PathLike, *, location: str = SIBLING) -> ModDescriptor | None:
    """Descriptor de ``file``; ``None`` si no se puede leer (no existe, no es legible...).

    Siempre lee del disco: tras editar el archivo basta con volver a llamarla.
    """
    file = Path(file)
    try:
        result = parse_file(file)
    except (OSError, ValueError):
        return None
    return descriptor_from_result(file, result, location=location)


def _descriptor_files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.suffix.lower() == DESCRIPTOR_SUFFIX and p.is_file())
    except OSError:
        return []


def find_descriptor(folder: str | os.PathLike) -> ModDescriptor | None:
    """Descriptor del mod de ``folder``.

    Primero busca en la carpeta superior un ``.mod`` cuyo ``path`` termine en el
    nombre de la carpeta (o, si ninguno, uno con el mismo nombre que ella); si
    no hay, el primer ``.mod`` que haya dentro de la propia carpeta. El juego
    corre en Windows: los nombres se comparan sin distinguir mayúsculas. Los
    ``.mod`` que no se pueden leer (de este o de otros mods) se pasan por alto, y
    uno que el juego no puede leer (``game_readable``) solo se elige si no hay otro.
    """
    folder = Path(folder)
    name = folder.name.casefold()
    best, best_rank = None, None
    for file in _descriptor_files(folder.parent):
        descriptor = read_descriptor(file)
        if descriptor is None:
            continue
        if descriptor.folder_name.casefold() == name:
            rank = 0
        elif file.stem.casefold() == name:
            rank = 1
        else:
            continue
        if not descriptor.game_readable:
            rank += 2  # después de cualquiera que el juego sí lea
        if best_rank is None or rank < best_rank:
            best, best_rank = descriptor, rank
            if rank == 0:
                break
    if best is not None:
        return best
    inside = [d for d in (read_descriptor(file, location=INSIDE) for file in _descriptor_files(folder)) if d is not None]
    return next((d for d in inside if d.game_readable), inside[0] if inside else None)


def _quoted(field_name: str, value: str) -> Scalar:
    if "\n" in value or "\r" in value:
        raise DescriptorFieldError(FIELD_NEWLINE, field=field_name, value=value)
    if '"' in value:
        raise DescriptorFieldError(FIELD_QUOTE, field=field_name, value=value)
    return Scalar(value, quoted=True)


def _new_source(descriptor: ModDescriptor) -> str:
    """Descriptor canónico: ``name``, ``path``, ``user_dir``, ``replace_path``..., ``dependencies``, ``archive``."""
    lines = [f'{key} = "{_quoted(key, getattr(descriptor, key)).text}"'
             for key in _TEXT_FIELDS if getattr(descriptor, key)]
    lines += [f'replace_path = "{_quoted("replace_path", p).text}"' for p in descriptor.replace_paths]
    if descriptor.dependencies:
        lines.append("dependencies = { "
                     + " ".join(f'"{_quoted("dependencies", d).text}"' for d in descriptor.dependencies) + " }")
    if descriptor.archive:
        lines.append(f'archive = "{_quoted("archive", descriptor.archive).text}"')
    return "".join(line + NEWLINE for line in lines)


def _sync_repeated(doc, key: str, values: tuple[str, ...]) -> None:
    if tuple(_scalar_text(v) for v in doc.get_all(key)) == values:
        return
    doc.remove(key)
    for value in values:
        doc.append(key, _quoted(key, value))


# --- generador del .mod (wizard §14.1, iteración 2) ---------------------------------------------
# Contrato. render_descriptor sustituye a la lógica de write_descriptor (que pasa a usarla y a escribir con
# core.project.journal, como create_mod_skeleton: tests/test_arch_writes.py no admite escrituras directas aquí).
# Los imports de core.project y core.modcheck van dentro de las funciones: los dos importan este módulo.

# Códigos nuevos de descriptor_problems (sus textos, en modcheck.MESSAGES). Los demás son los de
# modcheck.check_descriptor: descriptor_bad_path / descriptor_other_folder (= descriptor_path_mismatch de §14.1),
# descriptor_missing_folder (= descriptor_folder_missing), descriptor_no_name, descriptor_no_path,
# descriptor_bad_user_dir y descriptor_bad_replace_path.
DESCRIPTOR_NAME_DUPLICATE = "descriptor_name_duplicate"       # aviso: otro .mod de <juego>/mod con el mismo name
DESCRIPTOR_USER_DIR_EMPTY = "descriptor_user_dir_empty"       # info: sin user_dir, partidas y caché junto a vanilla
DESCRIPTOR_FOLDER_RESERVED = "windows_reserved_name"          # error: CON, NUL, <>:"|?*, punto o espacio final
DESCRIPTOR_FOLDER_TAKEN = "descriptor_folder_taken"           # error (al crear): <juego>/mod/<carpeta> ya existe
REPLACE_PATH_EMPTY = "replace_path_empty"                     # error: el mod deja vacía una carpeta reemplazada
REPLACE_PATH_HIDES_REFERENCED = "replace_path_hides_referenced"   # error; necesita el índice: iteración 3

# Carpetas que «Nuevo mod» crea vacías (la herencia hace innecesario copiar vanilla, §14.1).
SKELETON_FOLDERS = ("common", "history", "localisation")


@dataclass(frozen=True)
class DescriptorSpec:
    """Lo que el formulario «Descriptor .mod» edita. ``path`` es siempre ``"mod/<folder>"``."""

    name: str
    folder: str
    user_dir: str = ""
    replace_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"mod/{self.folder}"

    @classmethod
    def from_descriptor(cls, descriptor: ModDescriptor) -> DescriptorSpec:
        raise NotImplementedError


def render_descriptor(spec: DescriptorSpec, existing: ParseResult | None = None) -> bytes:
    """Bytes del descriptor. Sin ``existing``: canónico, cp1252 y CRLF (``_new_source``). Con él: solo cambian los
    campos que difieren y se conserva el resto (comentarios, claves desconocidas como ``archive``, formato y
    codificación salvo UTF-16, que pasa a cp1252). Un valor con comillas o saltos de línea lanza
    ``DescriptorFieldError``. Prueba de oro: ``DescriptorSpec("Shago Mod", "VSM", "VSM")`` da los bytes de
    ``tests/fixtures/shago_mod_min/VSM.mod``."""
    raise NotImplementedError


def descriptor_problems(spec: DescriptorSpec, game_root: Path, *, creating: bool = False,
                        descriptor_file: Path | None = None) -> list:
    """``modcheck.Issue`` del formulario (los de ``check_descriptor`` más los códigos nuevos de arriba).

    ``creating``: además comprueba que ``<juego>/mod/<folder>`` y su ``.mod`` no existan. ``descriptor_file``:
    el propio ``.mod`` (se excluye al buscar nombres duplicados). La iteración 3 los convierte en ``Problem``.
    """
    raise NotImplementedError


def create_mod_skeleton(game_root: Path, spec: DescriptorSpec, *, template: Path | None = None) -> ModDescriptor:
    """«Nuevo mod»: ``<juego>/mod/<folder>/`` con ``SKELETON_FOLDERS`` y ``<juego>/mod/<folder>.mod``, en una sola
    transacción del diario (todo o nada). ``template``: carpeta cuyo contenido se copia dentro (p. ej. una
    «Plantilla Mod»). Lanza ``ValueError`` si ``descriptor_problems(..., creating=True)`` tiene errores."""
    raise NotImplementedError


def sanitize_folder(name: str, *, taken: frozenset[str] = frozenset()) -> list[str]:
    """Propuestas de carpeta para ``name``, la primera la recomendada: siglas (``Dark Age Mod`` → ``DAM``) y
    guiones bajos (``Dark_Age_Mod``), en ASCII, sin nombres que Windows rechace ni los de ``taken``
    (comparados sin mayúsculas)."""
    raise NotImplementedError


def write_descriptor(file: str | os.PathLike, descriptor: ModDescriptor, *, backup: bool = True) -> Path | None:
    """Escribe ``descriptor`` en ``file`` (no tiene por qué ser ``descriptor.file``).

    Si ``file`` existe, cambia solo los campos que difieren y conserva el resto
    del archivo (comentarios, claves desconocidas, formato y codificación, salvo
    UTF-16, que el juego no puede leer y pasa a cp1252); si no, crea un
    descriptor canónico (``name = "..."``, cp1252 y CRLF). Un valor con comillas
    o saltos de línea lanza ``DescriptorFieldError`` sin tocar nada. Devuelve la
    copia de seguridad, si se hizo.
    """
    file = Path(file)
    source = _new_source(descriptor)  # también valida los valores antes de tocar nada
    if not file.exists():
        return write_text(file, source, GAME_ENCODING, backup=backup)
    result = parse_file(file)
    doc = result.document
    for key in (*_TEXT_FIELDS, "archive"):
        value = getattr(descriptor, key)
        if not value:
            doc.remove(key)
        elif _scalar_text(doc.get(key)).strip() != value:
            doc.set(key, _quoted(key, value))
    _sync_repeated(doc, "replace_path", descriptor.replace_paths)
    current = descriptor_from_result(file, result).dependencies
    if current != descriptor.dependencies:
        doc.remove("dependencies")
        if descriptor.dependencies:
            doc.append("dependencies", [_quoted("dependencies", d) for d in descriptor.dependencies])
    if result.encoding not in GAME_UNREADABLE:
        return write_file(file, result, backup=backup)
    # UTF-16 pasa a cp1252. Un BOM repetido deja delante U+FEFF, que cp1252 no tiene y el parser
    # toma por espacio: se quita y se vuelve a analizar el texto.
    text = to_source(doc)
    stripped = text.lstrip(BOM)
    target = result if len(stripped) == len(text) else parse(stripped, filename=file).document
    return write_file(file, target, encoding=GAME_ENCODING, backup=backup)
