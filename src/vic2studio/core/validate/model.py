"""Tipos de la validación cruzada: problemas, informe, arreglos y explicador (wizard §11, §11.1).

Dataclasses congeladas sin E/S. Los textos viven en
``core/validate/texts/issues.{es,en}.json``:

- ``issue.<código>``: el mensaje de un ``Problem`` (con ``args`` como formato);
- ``fix.<clave>``: la etiqueta de un arreglo (con ``label_args``);
- ``explain.layer.<capa>``, ``explain.verdict.<veredicto>`` y las claves de
  ``Explanation.title_key``/``outcome_key``.

Así la interfaz los vuelve a traducir al cambiar de idioma sin recalcular nada.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..clausewitz import Severity
from ..vfs.paths import VPath

if TYPE_CHECKING:
    from ..project import Project

SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True)
class Problem:
    """Un problema de la vista efectiva.

    ``entity`` es el símbolo afectado como ``(kind, name)`` del índice (``("tag", "SIL")``): la columna
    «Entidad» y, desde la iteración 4, el editor que se abre. ``field`` es la ruta del campo dentro de la
    entidad (``("ruling_party",)``). ``inherited`` (I11): también ocurre en el juego base solo. ``fixes`` son
    claves de ``fixes.FIXES``; la primera es el SimpleFix.
    """

    code: str
    severity: Severity
    rel: VPath | None
    line: int | None = None
    column: int | None = None
    entity: tuple[str, str] | None = None
    field: tuple[str, ...] = ()
    args: Mapping = dc_field(default_factory=lambda: MappingProxyType({}))
    inherited: bool = False
    fixes: tuple[str, ...] = ()

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"issue.{self.code}", lang, rel=self.rel or "", **dict(self.args))

    def fingerprint(self) -> tuple:
        """Identidad sin la posición: ``(code, rel.key, entity, field, args ordenados)``. La línea base compara
        huellas (un problema de vanilla sigue siendo el mismo aunque cambie de línea)."""
        args = tuple(sorted((str(k), repr(v)) for k, v in self.args.items()))
        return (self.code, None if self.rel is None else self.rel.key, self.entity, self.field, args)

    def __getstate__(self) -> tuple:
        is_proxy = isinstance(self.args, MappingProxyType)
        return (self.code, self.severity, self.rel, self.line, self.column, self.entity, self.field,
                dict(self.args) if is_proxy else self.args, self.inherited, self.fixes, is_proxy)

    def __setstate__(self, state: tuple) -> None:
        (code, severity, rel, line, column, entity, fld, args, inherited, fixes, is_proxy) = state
        for name, value in (("code", code), ("severity", severity), ("rel", rel), ("line", line),
                            ("column", column), ("entity", entity), ("field", fld),
                            ("args", MappingProxyType(args) if is_proxy else args), ("inherited", inherited),
                            ("fixes", fixes)):
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class ValidationReport:
    """Resultado de ``Validator.validate``: todos los problemas (heredados incluidos), ya ordenados por gravedad,
    ruta y línea."""

    problems: tuple[Problem, ...] = ()
    files: int = 0                       # archivos que se revisaron
    elapsed: float = 0.0
    cancelled: bool = False
    baseline_ready: bool = True          # False: aún no hay línea base (los heredados no están marcados)

    def visible(self, *, inherited: bool = False) -> list[Problem]:
        """Lo que muestra el panel: sin los heredados salvo que se pidan (conmutador «Mostrar heredados»)."""
        return [p for p in self.problems if inherited or not p.inherited]

    def count(self, severity: Severity | None = None, *, inherited: bool = False) -> int:
        return sum(1 for p in self.visible(inherited=inherited) if severity is None or p.severity is severity)

    def inherited_count(self) -> int:
        return sum(1 for p in self.problems if p.inherited)


# --- arreglos (SimpleFix, §11.1) ---------------------------------------------------------------------

ACTION_MODIFY = "modify"
ACTION_CREATE = "create"
ACTION_COPY_FROM_GAME = "copy_from_game"
ACTION_TRASH = "trash"


@dataclass(frozen=True)
class PlannedChange:
    rel: VPath
    action: str                          # ACTION_*
    diff: str = ""                       # unified diff (vacío para TRASH)


@dataclass(frozen=True)
class ChangePlan:
    """Vista previa de un arreglo (archivo · acción · diff), antes de confirmarlo."""

    fix: str                             # clave del arreglo
    changes: tuple[PlannedChange, ...] = ()


@dataclass(frozen=True)
class FixSpec:
    """Un arreglo. ``safe=True`` solo añade o restaura; ``safe=False`` borra o sustituye (pide confirmación
    explícita y lo borrado va a la papelera). ``plan`` no cambia nada; ``apply`` es una transacción con nombre
    (``undo.fix_<clave>``), deshacible en un paso. Nunca se aplica nada sin que el usuario lo pida."""

    key: str
    label_key: str                       # «fix.<clave>»
    safe: bool
    plan: Callable[[Problem, Project], ChangePlan]
    apply: Callable[[Problem, Project], None]
    label_args: Callable[[Problem], Mapping] | None = None   # formato de la etiqueta («Registrar {tag}…»)

    def label(self, problem: Problem, lang: str = "en") -> str:
        from ..texts import text

        return text(self.label_key, lang, **dict(self.label_args(problem) if self.label_args else {}))


# --- explicador de conflicto (§11.1) ----------------------------------------------------------------

LAYER_GAME = "game"
LAYER_DEPENDENCY = "dependency"
LAYER_MOD = "mod"
LAYER_REPLACE_PATH = "replace_path"
LAYER_UNSAVED = "unsaved"                # «studio (sin guardar)»

VERDICT_WINS = "wins"
VERDICT_LOSES = "loses"
VERDICT_HIDDEN = "hidden"
VERDICT_NOT_LOADED = "not_loaded"
VERDICT_MISSING = "missing"


@dataclass(frozen=True)
class ExplainStep:
    """Una capa en el orden en que el juego la carga, con su línea real (``excerpt``) y su veredicto."""

    layer: str                           # LAYER_*
    rel: VPath | None
    line: int | None
    excerpt: str
    verdict: str                         # VERDICT_*

    def layer_text(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"explain.layer.{self.layer}", lang)

    def verdict_text(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"explain.verdict.{self.verdict}", lang)


@dataclass(frozen=True)
class Explanation:
    title_key: str
    steps: tuple[ExplainStep, ...]
    outcome_key: str                     # qué verá el jugador, en una frase
    args: Mapping = dc_field(default_factory=lambda: MappingProxyType({}))
    fixes: tuple[str, ...] = ()          # claves de FIXES

    def title(self, lang: str = "en") -> str:
        from ..texts import text

        return text(self.title_key, lang, **dict(self.args))

    def outcome(self, lang: str = "en") -> str:
        from ..texts import text

        return text(self.outcome_key, lang, **dict(self.args))
