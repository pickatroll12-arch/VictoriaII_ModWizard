"""Descriptor ``.mod`` de un mod de Victoria II: lectura, generación y revisión.

El descriptor suele vivir en ``<juego>/mod/<Nombre>.mod``, junto a la carpeta del
mod (``path = "mod/<carpeta>"``); algunos mods guardan además una copia dentro de
su propia carpeta. Se lee con el parser Clausewitz, así que sus errores de
sintaxis llegan como diagnósticos; ``modcheck.check_descriptor`` revisa sus
campos. ``render_descriptor`` da los bytes de un descriptor a partir de un
``DescriptorSpec``: uno nuevo en cp1252 con CRLF o, sobre uno existente, solo los
campos que cambian (conserva comentarios y claves desconocidas); un valor que no
se puede escribir lanza ``DescriptorFieldError``. ``descriptor_problems`` revisa el
formulario, ``sanitize_folder`` propone carpetas y ``create_mod_skeleton`` crea un
mod nuevo. Las escrituras las hace ``core.project.journal`` (wizard §4).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .clausewitz import (
    Block,
    Diagnostic,
    ParseResult,
    Scalar,
    Severity,
    parse,
    parse_file,
    render_checked,
    to_source,
)
from .encoding import BOM, GAME_ENCODING, GAME_UNREADABLE, encode_text
from .fileio import FileStamp

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

    def __init__(self, code: str, params: dict[str, str] | None = None, **kw: str):
        self.code = code
        self.params = dict(params or (), **kw)
        super().__init__(self.message("es"))

    def __reduce__(self):
        return (type(self), (self.code, self.params))

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


def _dependencies(doc) -> tuple[str, ...]:
    """Nombres de ``dependencies``: un bloque de cadenas (lo habitual) o escalares sueltos."""
    found: list[str] = []
    for value in doc.get_all("dependencies"):
        if isinstance(value, Block):
            found.extend(_scalar_text(v) for v in value.values() if isinstance(v, Scalar))
        elif isinstance(value, Scalar):
            found.append(value.text)
    return tuple(found)


def descriptor_from_result(file: str | os.PathLike, result: ParseResult, *, location: str = SIBLING) -> ModDescriptor:
    """Descriptor a partir del análisis ya hecho de ``file``."""
    doc = result.document
    return ModDescriptor(
        file=Path(file),
        name=_scalar_text(doc.get("name")).strip(),
        path=_scalar_text(doc.get("path")).strip(),
        user_dir=_scalar_text(doc.get("user_dir")).strip(),
        replace_paths=tuple(_scalar_text(v) for v in doc.get_all("replace_path") if isinstance(v, Scalar)),
        dependencies=_dependencies(doc),
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


def descriptor_files(folder: str | os.PathLike) -> list[Path]:
    """Los ``.mod`` de ``folder`` (``<juego>/mod``), ordenados; ninguno si no se puede leer."""
    return _descriptor_files(Path(folder))


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


def _apply_fields(doc, fields: ModDescriptor, *, archive: bool) -> None:
    """Lleva a ``doc`` los campos de ``fields`` tocando solo los que difieren; con ``archive=False`` no lo toca."""
    for key in (*_TEXT_FIELDS, "archive") if archive else _TEXT_FIELDS:
        value = getattr(fields, key)
        if not value:
            doc.remove(key)
        elif _scalar_text(doc.get(key)).strip() != value:
            doc.set(key, _quoted(key, value))
    _sync_repeated(doc, "replace_path", fields.replace_paths)
    if _dependencies(doc) != fields.dependencies:
        doc.remove("dependencies")
        if fields.dependencies:
            doc.append("dependencies", [_quoted("dependencies", d) for d in fields.dependencies])


# --- generador del .mod (wizard §14.1, iteración 2) ---------------------------------------------
# render_descriptor es la única forma de producir los bytes de un descriptor: la usan «Nuevo mod»
# (create_mod_skeleton) y write_descriptor, que escriben con core.project.journal (tests/test_arch_writes.py no
# admite escrituras directas aquí); el formulario edita el CST vivo con apply_descriptor. Los imports de
# core.project, core.vfs, core.appdirs y core.modcheck van dentro de las funciones: todos importan este módulo.

# Códigos nuevos de descriptor_problems (sus textos, en modcheck.MESSAGES). Los demás son los de
# modcheck.check_descriptor: descriptor_bad_path / descriptor_other_folder (= descriptor_path_mismatch de §14.1),
# descriptor_missing_folder (= descriptor_folder_missing), descriptor_no_name, descriptor_no_path,
# descriptor_bad_user_dir y descriptor_bad_replace_path; y los de DescriptorFieldError (FIELD_QUOTE y
# FIELD_NEWLINE), cuyo texto da el propio error (``Issue.diagnostic``).
DESCRIPTOR_NAME_DUPLICATE = "descriptor_name_duplicate"       # aviso: otro .mod de <juego>/mod con el mismo name
DESCRIPTOR_USER_DIR_EMPTY = "descriptor_user_dir_empty"       # info: sin user_dir, partidas y caché junto a vanilla
DESCRIPTOR_FOLDER_RESERVED = "windows_reserved_name"          # error: CON, NUL, <>:"|?*, punto o espacio final
DESCRIPTOR_FOLDER_TAKEN = "descriptor_folder_taken"           # error (al crear): <juego>/mod/<carpeta> ya existe
REPLACE_PATH_EMPTY = "replace_path_empty"                     # error: el mod deja vacía una carpeta reemplazada
REPLACE_PATH_HIDES_REFERENCED = "replace_path_hides_referenced"   # error; necesita el índice: iteración 3
NEW_CODES = (DESCRIPTOR_NAME_DUPLICATE, DESCRIPTOR_USER_DIR_EMPTY, DESCRIPTOR_FOLDER_RESERVED,
             DESCRIPTOR_FOLDER_TAKEN, REPLACE_PATH_EMPTY, REPLACE_PATH_HIDES_REFERENCED)

# Carpetas que «Nuevo mod» crea vacías (la herencia hace innecesario copiar vanilla, §14.1).
SKELETON_FOLDERS = ("common", "history", "localisation")
# De una plantilla no se copian la carpeta de proyecto, las copias de seguridad ni los temporales.
_TEMPLATE_SKIP_FOLDERS = frozenset({".vic2studio", ".git"})
_SKIP_SUFFIXES = (".bak", ".tmp")


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
        """Lo que se edita de un descriptor leído; ``folder`` es la última parte de su ``path`` (o vacío)."""
        return cls(descriptor.name, descriptor.folder_name, descriptor.user_dir,
                   tuple(descriptor.replace_paths), tuple(descriptor.dependencies))

    def fields(self, file: str | os.PathLike = "") -> ModDescriptor:
        """El ``ModDescriptor`` que describe; sin ``folder`` no hay ``path`` (en vez de un ``mod/`` a medias)."""
        return ModDescriptor(Path(file), name=self.name, path=self.path if self.folder else "",
                             user_dir=self.user_dir, replace_paths=tuple(self.replace_paths),
                             dependencies=tuple(self.dependencies))


class DescriptorProblemsError(ValueError):
    """``create_mod_skeleton`` con errores de ``descriptor_problems``: ``issues`` los lista (el primero, en ``str``)."""

    def __init__(self, issues: list):
        self.issues = list(issues)
        super().__init__(self.issues[0].message("es") if self.issues else "")

    def __reduce__(self):
        return (type(self), (self.issues,))


class DescriptorWriteError(OSError):
    """El diario encontró un problema bloqueante (``problems``: ``core.project.SaveProblem``) y no escribió nada."""

    def __init__(self, problems: list):
        self.problems = list(problems)
        super().__init__(self.problems[0].message("es") if self.problems else "")

    def __reduce__(self):
        return (type(self), (self.problems,))


def _copy_result(existing: ParseResult) -> ParseResult:
    """Copia independiente de ``existing`` (la ida y vuelta es exacta): renderizar no toca el original."""
    copy = parse(to_source(existing.document), filename=existing.path)
    copy.encoding = existing.encoding
    copy.document.extra_boms = existing.document.extra_boms
    return copy


def _render_result(result: ParseResult) -> bytes:
    """Bytes comprobados (``serializer.render_checked``) en la codificación leída, salvo UTF-16, que pasa a cp1252."""
    if result.encoding not in GAME_UNREADABLE:
        return render_checked(result, path=result.path)
    # Un BOM repetido que quedara delante sería U+FEFF, que cp1252 no tiene y el parser toma por espacio: se
    # quita y se vuelve a analizar el texto.
    text = to_source(result.document)
    stripped = text.lstrip(BOM)
    target = result if len(stripped) == len(text) else parse(stripped, filename=result.path)
    return render_checked(target, encoding=GAME_ENCODING, path=result.path)


def _render_fields(fields: ModDescriptor, existing: ParseResult | None, *, archive: bool) -> bytes:
    source = _new_source(fields)  # valida todos los valores antes de nada (DescriptorFieldError)
    if existing is None:
        return encode_text(source, GAME_ENCODING)
    copy = _copy_result(existing)
    _apply_fields(copy.document, fields, archive=archive)
    return _render_result(copy)


def render_descriptor(spec: DescriptorSpec, existing: ParseResult | None = None) -> bytes:
    """Bytes del descriptor. Sin ``existing``: canónico, cp1252 y CRLF (``_new_source``). Con él: solo cambian los
    campos que difieren y se conserva el resto (comentarios, claves desconocidas como ``archive``, formato y
    codificación salvo UTF-16, que pasa a cp1252); ``existing`` no se modifica. Un valor con comillas o saltos
    de línea lanza ``DescriptorFieldError``. Prueba de oro: ``DescriptorSpec("Shago Mod", "VSM", "VSM")`` da los
    bytes de ``tests/fixtures/shago_mod_min/VSM.mod``."""
    return _render_fields(spec.fields(), existing, archive=False)


def apply_descriptor(document, spec: DescriptorSpec) -> bool:
    """Lleva ``spec`` al CST vivo de un descriptor (el ``Document`` que el formulario edita dentro de una
    transacción): solo cambia los campos que difieren y conserva lo demás, ``archive`` incluido. Valida antes
    de tocar nada (``DescriptorFieldError``). Devuelve True si cambió algo."""
    fields = spec.fields()
    _new_source(fields)
    before = to_source(document)
    _apply_fields(document, fields, archive=False)
    return to_source(document) != before


def _entry_names(folder: Path | None) -> set[str]:
    """Nombres (sin mayúsculas, como en Windows) de las carpetas y de los ``.mod`` (sin extensión) de ``folder``."""
    names: set[str] = set()
    if folder is None:
        return names
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.lower().endswith(DESCRIPTOR_SUFFIX):
                    names.add(entry.name[:-len(DESCRIPTOR_SUFFIX)].casefold())
                elif entry.is_dir():
                    names.add(entry.name.casefold())
    except OSError:
        pass
    return names


def taken_folders(game_root: str | os.PathLike | None) -> frozenset[str]:
    """Carpetas y descriptores que ya hay en ``<juego>/mod``, sin mayúsculas (``sanitize_folder(taken=...)``)."""
    return frozenset(_entry_names(None if game_root is None else Path(game_root) / "mod"))


def _windows_rejects(name: str) -> bool:
    """True si Windows no admite ``name`` como carpeta: dispositivo (también ``CON.x`` y ``CON .x``), carácter
    prohibido o punto o espacio final. Delega en ``core.vfs.paths.windows_name_problems``, la regla con la que el
    guardado rechaza un nombre: el formulario no puede aceptar una carpeta que luego no se pueda crear."""
    from .vfs.paths import windows_name_problems

    return bool(windows_name_problems(name))


def _has_files(folder: Path) -> bool:
    """True si bajo ``folder`` hay algún archivo que el juego leería (no cuentan ``.bak`` ni temporales)."""
    for _, _, names in os.walk(folder):
        if any(not name.lower().endswith(_SKIP_SUFFIXES) for name in names):
            return True
    return False


def _find_folder(base: Path, relative: str) -> Path | None:
    """``base/relative`` sin distinguir mayúsculas (como el juego en Windows), o None si no existe."""
    current = base
    for part in relative.replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        candidate = current / part
        if not candidate.is_dir():
            try:
                candidate = next(p for p in current.iterdir() if p.is_dir() and p.name.casefold() == part.casefold())
            except (OSError, StopIteration):
                return None
        current = candidate
    return current if current.is_dir() else None


def descriptor_problems(spec: DescriptorSpec, game_root: Path | None, *, creating: bool = False,
                        descriptor_file: Path | None = None, mod_root: Path | None = None,
                        template: Path | None = None) -> list:
    """``modcheck.Issue`` del formulario (los de ``check_descriptor`` más los códigos nuevos de arriba).

    ``creating``: además comprueba que ``<juego>/mod/<folder>`` y su ``.mod`` no existan, y las carpetas
    reemplazadas se buscan en ``template`` (el mod nuevo nace vacío). ``descriptor_file``: el propio ``.mod``
    (se excluye al buscar nombres duplicados). ``mod_root``: la carpeta real del mod (``path`` debe nombrarla;
    por defecto ``<juego>/mod/<folder>``). Sin ``game_root`` no se mira nada de ``<juego>/mod``. Los valores
    que no se pueden escribir salen como ``FIELD_QUOTE`` o ``FIELD_NEWLINE``. La iteración 3 los convierte en
    ``Problem``.
    """
    from .modcheck import DESCRIPTOR_BAD_REPLACE_PATH, KIND_CLAUSEWITZ, Issue, check_descriptor

    mods = None if game_root is None else Path(game_root) / "mod"
    if descriptor_file is not None:
        file = Path(descriptor_file)
    elif mods is not None and spec.folder:
        file = mods / f"{spec.folder}{DESCRIPTOR_SUFFIX}"
    else:
        file = Path(f"{spec.folder or 'mod'}{DESCRIPTOR_SUFFIX}")
    issues: list = []

    def add(code: str, severity: Severity, diagnostic=None, **args) -> None:
        issues.append(Issue(file, file.name, KIND_CLAUSEWITZ, code, severity, None, None, diagnostic, args))

    fields = spec.fields(file)
    values = [(key, getattr(fields, key)) for key in _TEXT_FIELDS]
    values += [("replace_path", p) for p in fields.replace_paths] + [("dependencies", d) for d in fields.dependencies]
    for key, value in values:
        try:
            _quoted(key, value)
        except DescriptorFieldError as error:
            add(error.code, Severity.ERROR, error, **error.params)
    real_root = mod_root if mod_root is not None else (mods / spec.folder if mods is not None and spec.folder else None)
    for issue in check_descriptor(fields, mod_dir=None if creating else mod_root,
                                  game_dir=None if creating else game_root):
        add(issue.code, issue.severity, issue.diagnostic, **issue.args)
    if spec.folder and _windows_rejects(spec.folder):
        add(DESCRIPTOR_FOLDER_RESERVED, Severity.ERROR, folder=spec.folder)
    if creating and spec.folder and spec.folder.casefold() in _entry_names(mods):
        add(DESCRIPTOR_FOLDER_TAKEN, Severity.ERROR, folder=spec.folder)
    wanted = spec.name.strip().casefold()
    if mods is not None and wanted:
        own = None if descriptor_file is None else os.path.normcase(os.path.realpath(descriptor_file))
        for other in _descriptor_files(mods):
            if own is not None and os.path.normcase(os.path.realpath(other)) == own:
                continue
            found = read_descriptor(other)
            if found is not None and found.name.strip().casefold() == wanted:
                add(DESCRIPTOR_NAME_DUPLICATE, Severity.WARNING, name=spec.name.strip(), file=other.name)
                break
    if not spec.user_dir:
        add(DESCRIPTOR_USER_DIR_EMPTY, Severity.INFO)
    root = (None if template is None else Path(template)) if creating else real_root
    if creating or root is not None:
        bad = {i.args.get("replace_path") for i in issues if i.code == DESCRIPTOR_BAD_REPLACE_PATH}
        for replace_path in spec.replace_paths:
            if replace_path in bad:
                continue
            folder = None if root is None else _find_folder(root, replace_path)
            if folder is None or not _has_files(folder):
                add(REPLACE_PATH_EMPTY, Severity.ERROR, replace_path=replace_path)
    return issues


def sanitize_folder(name: str, *, taken: frozenset[str] = frozenset()) -> list[str]:
    """Propuestas de carpeta para ``name``, la primera la recomendada: siglas (``Dark Age Mod`` → ``DAM``) y
    guiones bajos (``Dark_Age_Mod``), en ASCII, sin nombres que Windows rechace ni los de ``taken``
    (comparados sin mayúsculas). Si una está ocupada se propone con un número (``DAM2``, ``Dark_Age_Mod_2``).
    Sin letras ni cifras, ninguna."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_name)
    if not words:
        return []
    bases = ["".join(word[0] for word in words).upper()] if len(words) > 1 else []
    bases.append("_".join(words))
    blocked = {t.casefold() for t in taken}
    proposals: list[str] = []

    def free(candidate: str) -> bool:
        return (candidate.casefold() not in blocked and not _windows_rejects(candidate)
                and all(candidate.casefold() != p.casefold() for p in proposals))

    for base in bases:
        if free(base):
            proposals.append(base)
            continue
        joiner = "_" if "_" in base else ""
        numbered = next((f"{base}{joiner}{n}" for n in range(2, 100) if free(f"{base}{joiner}{n}")), None)
        if numbered is not None:
            proposals.append(numbered)
    return proposals


def template_files(template: str | os.PathLike) -> list[tuple[str, Path]]:
    """(ruta relativa con ``/``, archivo) de lo que «Nuevo mod» copia de una plantilla, en orden: todo salvo
    ``.vic2studio``/``.git``, las copias ``.bak``, los temporales y los ``.mod`` de su raíz (el mod lleva el suyo)."""
    template = Path(template)
    files: list[tuple[str, Path]] = []
    for folder, dirs, names in os.walk(template):
        top = Path(folder) == template
        dirs[:] = sorted((d for d in dirs if not (top and d.casefold() in _TEMPLATE_SKIP_FOLDERS)), key=str.casefold)
        for name in sorted(names, key=str.casefold):
            if name.lower().endswith(_SKIP_SUFFIXES) or (top and name.lower().endswith(DESCRIPTOR_SUFFIX)):
                continue
            path = Path(folder, name)
            files.append((path.relative_to(template).as_posix(), path))
    return files


def create_mod_skeleton(game_root: Path, spec: DescriptorSpec, *, template: Path | None = None) -> ModDescriptor:
    """«Nuevo mod»: ``<juego>/mod/<folder>/`` con ``SKELETON_FOLDERS`` y ``<juego>/mod/<folder>.mod``, en una sola
    transacción del diario (todo o nada; el diario va en la carpeta de proyecto del mod nuevo, donde lo
    encuentra la recuperación al abrirlo). ``template``: carpeta cuyo contenido se copia dentro (p. ej. una
    «Plantilla Mod», ver ``template_files``). Lanza ``DescriptorProblemsError`` (un ``ValueError``) si
    ``descriptor_problems(..., creating=True)`` tiene errores, y ``DescriptorWriteError`` si el diario encuentra
    un problema bloqueante; en los dos casos sin escribir nada."""
    from .project.journal import JOURNAL_DIR, TRASH_DIR, SaveTransaction, project_dir
    from .project.model import PlannedWrite, WriteAction
    from .vfs.guard import WriteGuard
    from .vfs.paths import DESCRIPTOR_REL, VPath

    game_root = Path(game_root)
    template = None if template is None else Path(template)
    errors = [i for i in descriptor_problems(spec, game_root, creating=True, template=template)
              if i.severity is Severity.ERROR]
    if errors:
        raise DescriptorProblemsError(errors)
    mods = game_root / "mod"
    mod_root = mods / spec.folder
    file = mods / f"{spec.folder}{DESCRIPTOR_SUFFIX}"
    guard = WriteGuard(mod_root, extra_files=(file,))
    folder = project_dir(mod_root)
    transaction = SaveTransaction(guard, folder / JOURNAL_DIR, label="new_mod", backup_bak=False,
                                  trash_dir=folder / TRASH_DIR)
    transaction.add(PlannedWrite(DESCRIPTOR_REL, guard.check(file), WriteAction.CREATE, render_descriptor(spec), None))
    for rel, source in template_files(template) if template is not None else ():
        transaction.add(PlannedWrite(VPath.of(rel), guard.check(mod_root / rel), WriteAction.CREATE,
                                     source.read_bytes(), None))
    for name in SKELETON_FOLDERS:
        # Carpeta vacía dentro de la misma transacción (API pedida al diario: SaveTransaction.add_folder).
        transaction.add_folder(guard.check(mod_root / name))
    blocking = [p for p in transaction.prepare() if p.blocking]
    if blocking:
        raise DescriptorWriteError(blocking)
    transaction.commit()
    return read_descriptor(file) or spec.fields(file)


def write_descriptor(file: str | os.PathLike, descriptor: ModDescriptor, *, backup: bool = True) -> Path | None:
    """Escribe ``descriptor`` en ``file`` (no tiene por qué ser ``descriptor.file``).

    Si ``file`` existe, cambia solo los campos que difieren y conserva el resto
    del archivo (comentarios, claves desconocidas, formato y codificación, salvo
    UTF-16, que el juego no puede leer y pasa a cp1252); si no, crea un
    descriptor canónico (``name = "..."``, cp1252 y CRLF). Un valor con comillas
    o saltos de línea lanza ``DescriptorFieldError`` sin tocar nada. Sin cambios
    no escribe nada. Devuelve la copia de seguridad, si se hizo.

    Los bytes salen del renderizador de ``render_descriptor`` (con ``archive``) y
    los escribe el diario (``core.project.journal``): el guard solo admite ``file`` y
    el diario va en la carpeta de datos de la aplicación
    (``appdirs.detached_project_dir``), nunca junto al juego.
    """
    file = Path(file)
    _new_source(descriptor)  # valida los valores antes de tocar nada
    existing = parse_file(file) if file.exists() else None
    data = _render_fields(descriptor, existing, archive=True)
    if existing is not None and existing.stamp == FileStamp.of(data):
        return None
    return _journal_write(file, data, exists=existing is not None, backup=backup)


def _journal_write(file: Path, data: bytes, *, exists: bool, backup: bool) -> Path | None:
    from .appdirs import detached_project_dir
    from .project.journal import JOURNAL_DIR, SaveTransaction
    from .project.model import PlannedWrite, WriteAction
    from .vfs.guard import WriteGuard
    from .vfs.model import Fingerprint
    from .vfs.paths import DESCRIPTOR_REL

    root = detached_project_dir(file.with_suffix(""))
    guard = WriteGuard(root, extra_files=(file,))
    transaction = SaveTransaction(guard, root / JOURNAL_DIR, label="descriptor", backup_bak=backup)
    action = WriteAction.MODIFY if exists else WriteAction.CREATE
    expected = Fingerprint.of_path(file) if exists else None
    transaction.add(PlannedWrite(DESCRIPTOR_REL, guard.check(file), action, data, expected))
    blocking = [p for p in transaction.prepare() if p.blocking]
    if blocking:
        raise DescriptorWriteError(blocking)
    result = transaction.commit()
    return result.backups[0] if result.backups else None
