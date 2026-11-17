"""``MapSession``: el mapa de una ``Session`` (wizard §16.1). Contrato de la iteración 5.

Es la única puerta de la interfaz al mapa: ningún widget lee un BMP ni abre ``core.map`` por su cuenta. Se llega
por ``session.map`` (se crea al pedirla) y vive lo que la sesión. Da tres cosas:

1. **El ráster de provincias** (``raster``), cargado en segundo plano (``POOL_MAP``) con
   ``core.map.cache.load_or_build`` sobre los **bytes efectivos** de ``provinces.bmp`` y ``definition.csv``
   (los nombres salen de ``GameRules.map_files``), junto con el terreno mayoritario de ``terrain.bmp``. Nada de
   eso toca el ``Workspace`` en el hilo de la tarea (I12): los bytes se leen de la instantánea de la VFS, como el
   índice. La primera vez con vanilla tarda segundos; desde la caché, ≤ 0,5 s. El hilo de la interfaz nunca
   espera (≤ 100 ms): pide con ``load_raster`` y recibe ``rasterStateChanged``.
2. **Los hechos en la fecha de trabajo** (``facts``: ``core.map.facts.ProvinceFacts``), que los modos de mapa
   convierten en colores. Se construyen en segundo plano con una copia del índice cuando hay índice y ráster, y
   se rehacen al cambiar ``Session.working_date`` o al reconstruirse el índice. Tras una edición propia se
   actualizan en el acto (``ProvinceFacts.update``) y ``factsChanged`` lleva las provincias tocadas; tras un
   deshacer, un rehacer o una edición ajena (``Session.documentsChanged``), se actualizan las provincias de los
   documentos tocados desde sus registros vivos; las tocadas mientras se construían enteros se vuelven a aplicar
   sobre los nuevos al terminar. Si se construyeron con un índice atrasado (el ráster recargado tras «Exportar al
   mod» o deshacerla llega antes que la reindexación, ``REINDEX_DELAY_MS`` después), se rehacen enteros una vez más
   cuando el índice se pone al día (``Session.symbolsChanged``); no en cada ``symbolsChanged``, que llega tras
   cualquier edición.
3. **Las ediciones del mapa**, cada una en una sola transacción de ``Session.edit`` con su etiqueta
   ``core.domain.province.UNDO_*`` (un trazo de brocha = un paso de deshacer): ``set_value``, ``paint``,
   ``set_core``, ``move_to_group``. Lanzan lo que lance el núcleo (``ProvinceError``, ``GroupError``); la página
   lo muestra.

Las reglas (``rules``: ``GameRules``) salen de la vista efectiva, con lo sin guardar, como en la validación: tras
exportar sin guardar, el ``sea_starts`` del ``default.map`` nuevo va con el ráster nuevo. Se calculan una vez y
valen hasta que cambia uno de sus archivos (``core.rules.game.SOURCE_RELS`` o el BMP de provincias; guardarlos
también cuenta), se reconstruye el índice entero («Reindexar») o se abre o cierra un proyecto; con otro mar, los
hechos se rehacen enteros y ``provinces`` (que decide qué es mar para la brocha) se crea de nuevo. Un archivo de
reglas cambiado en el disco fuera del Studio, sin abrir en él, se ve al reindexar o al volver a abrir el proyecto,
como pasa con el índice.

También guarda el estado compartido entre las páginas del mapa: la selección (``selection``) y el centro de la
vista del lienzo en coordenadas del juego (``view_center``), que el editor de fechas de inicio usa para «Usar la
vista actual del mapa».

Señales (todas en el hilo de la interfaz):

- ``rasterStateChanged()``: ``raster_state`` pasó a ``RASTER_IDLE`` (sin proyecto), ``RASTER_LOADING``,
  ``RASTER_READY`` o ``RASTER_FAILED`` (``raster_error`` dice por qué, como clave de ``map.json``).
- ``rasterProgress(hecho, total)``: avance de la carga (los pasos de ``core.map.raster.BUILD_STEPS``).
- ``factsChanged(objeto)``: ``None`` si los hechos son otros (otra fecha, otro índice, o dejaron de existir);
  un ``frozenset[int]`` con las provincias cuyos hechos cambiaron. El lienzo repinta solo eso.
- ``selectionChanged(tupla)``: la selección nueva, en el orden en que se eligió.
- ``viewChanged()``: cambió ``view_center``.

"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.cancel import Cancelled
from ..core.vfs.paths import InvalidPathError, VPath
from .tasks import POOL_MAP, TaskRunner

if TYPE_CHECKING:
    from ..core.domain.province import Provinces
    from ..core.map.adjacency import Adjacency, AdjacencyTable
    from ..core.map.default_map import DefaultMap
    from ..core.map.facts import ProvinceFacts
    from ..core.map.groups import ProvinceGroups
    from ..core.map.positions import Positions
    from ..core.map.raster import ProvinceRaster
    from .session import Session

RASTER_IDLE, RASTER_LOADING, RASTER_READY, RASTER_FAILED = "idle", "loading", "ready", "failed"
# Grupos de provincias que ``groups`` y ``move_to_group`` aceptan (los ``kind`` de sus esquemas).
GROUP_KINDS = ("region", "region_sea", "continent", "climate")
# Motivos de ``RASTER_FAILED`` (claves de ``map.json``).
ERROR_NO_PROVINCES = "map.error.no_provinces"
ERROR_NO_DEFINITION = "map.error.no_definition"
ERROR_BAD_BMP = "map.error.bad_bmp"
ERROR_OTHER = "map.error.other"

log = logging.getLogger(__name__)


def _map_rel(rules, key: str, default: str) -> VPath:
    name = (getattr(rules, "map_files", None) or {}).get(key) or default
    try:
        return VPath.of(f"map/{name}")
    except (InvalidPathError, TypeError):
        return VPath.of(f"map/{default}")


def _read_effective(snapshot, overrides, rel: VPath) -> bytes | None:
    """Bytes efectivos de ``rel``: lo sin guardar si lo hay; si no, el archivo ganador de la instantánea."""
    from ..core.validate.context import ValidationContext

    return ValidationContext(snapshot, None, None, None, overrides).read(rel)


class _Loaded:
    """Lo que entrega la tarea del ráster (inmutable para la interfaz)."""

    def __init__(self, raster=None, terrain=None, terrain_types=None, error: str | None = None, cached=False):
        self.raster = raster
        self.terrain = terrain
        self.terrain_types = terrain_types
        self.error = error
        self.cached = cached


class MapSession(QObject):
    rasterStateChanged = Signal()
    rasterProgress = Signal(int, int)
    factsChanged = Signal(object)                 # None (todo) o frozenset[int]
    selectionChanged = Signal(object)             # tuple[int, ...]
    viewChanged = Signal()

    def __init__(self, session: Session) -> None:
        """Hija de ``session``. No carga nada: el ráster se pide con ``load_raster`` (la sala Mapa lo hace al
        mostrarse por primera vez; abrir un proyecto no paga el mapa si no se mira)."""
        super().__init__(session)
        self.session = session
        self._raster: ProvinceRaster | None = None
        self._raster_state = RASTER_IDLE
        self._raster_error: str | None = None
        self._facts: ProvinceFacts | None = None
        self._selection: tuple[int, ...] = ()
        self._view_center: tuple[int, int] | None = None
        self._terrain = None                 # terreno mayoritario por provincia (o None)
        self._terrain_types = None
        self._raster_rels: set[str] = set()
        self._wanted = False                 # alguien pidió el ráster: se recarga solo si cambian sus archivos
        self._provinces = None
        self._rules_cache: tuple | None = None   # (proyecto, sus GameRules efectivas, claves de sus archivos)
        self._facts_source = None            # el índice que copió la última construcción de los hechos
        self._facts_rules = None             # las reglas con las que se pidieron (su mar)
        self._facts_behind = False           # los hechos pueden no tener algo del índice: rehacer al ponerse al día
        # Provincias y grupos actualizados en el acto mientras se construían los hechos enteros: la construcción copió
        # el índice antes, así que al terminar se vuelven a aplicar sobre los hechos nuevos (si no, se perdían).
        self._replay_pids: set[int] = set()
        self._replay_groups: set[str] = set()
        self._raster_runner = TaskRunner(self, pool=POOL_MAP)
        self._raster_runner.finished.connect(self._on_raster_loaded)
        self._raster_runner.failed.connect(self._on_raster_failed)
        self._raster_runner.progress.connect(self._on_raster_progress)
        self._facts_runner = TaskRunner(self, pool=POOL_MAP)
        self._facts_runner.finished.connect(self._on_facts_built)
        self._facts_runner.failed.connect(self._on_facts_failed)
        session.projectClosed.connect(self._on_project_closed)
        session.projectOpened.connect(self._on_project_opened)
        session.workingDateChanged.connect(self._on_date_changed)
        session.indexStateChanged.connect(self._on_index_state)
        session.symbolsChanged.connect(self._on_symbols_changed)
        session.documentsChanged.connect(self._on_documents_changed)

    # --- ráster -------------------------------------------------------------------------------------

    @property
    def raster(self) -> ProvinceRaster | None:
        """El ráster del proyecto abierto; None hasta ``RASTER_READY`` y al cerrar el proyecto."""
        return self._raster

    @property
    def raster_state(self) -> str:
        return self._raster_state

    @property
    def raster_error(self) -> str | None:
        """Clave de texto del motivo con ``RASTER_FAILED`` (falta el BMP, no es de 24 bits…); None si no falló."""
        return self._raster_error

    def rules(self):
        """Las ``GameRules`` del proyecto abierto, con lo sin guardar (None sin proyecto)."""
        return self._rules()

    def _rules(self):
        """Las reglas de la vista efectiva, calculadas la primera vez que se piden tras abrir el proyecto o cambiar
        uno de sus archivos (``_on_documents_changed``). Se piden a menudo (``groups``, ``_group_rel``,
        ``refresh_facts``): leerlas cada vez eran media docena de archivos del disco."""
        project = self.session.project
        if project is None:
            return None
        fixed = getattr(project, "rules", None)
        if fixed is not None:
            return fixed
        cached = self._rules_cache
        if cached is None or cached[0] is not project:
            rules = self._effective_rules(project)
            cached = self._rules_cache = (project, rules, self._rules_keys(rules))
        return cached[1]

    @staticmethod
    def _effective_rules(project):
        """``GameRules`` de la instantánea de la VFS con los documentos sin guardar de los archivos que leen (como la
        validación). Con solo el disco, tras «Exportar al mod» sin guardar el editor tenía el ráster nuevo con el
        ``sea_starts`` del ``default.map`` viejo: el mar del mundo nuevo era tierra y la brocha le ponía dueño."""
        from ..core.rules.game import SOURCE_RELS, GameRules
        from ..core.validate.context import apply_unsaved_deletions
        from .session import document_overrides

        def effective(rels):
            # Un borrado sin guardar (``None``) deja ganar lo de debajo, como en la validación; sin esto, papelera de
            # la copia idéntica de ``default.map`` dejaba el editor sin mar ni marcadores.
            return GameRules.from_snapshot(*apply_unsaved_deletions(project.vfs.snapshot(),
                                                                    document_overrides(project, rels)))

        try:
            rels = [*SOURCE_RELS, _map_rel(None, "provinces", "provinces.bmp")]
            rules = effective(rels)
            bmp = _map_rel(rules, "provinces", "provinces.bmp")
            if bmp.key not in {rel.key for rel in rels} and document_overrides(project, [bmp]):
                # default.map nombra otro BMP de provincias, sin guardar: su cabecera da ``map_size``.
                rules = effective([*rels, bmp])
            return rules
        except Exception as exc:  # noqa: BLE001 - sin reglas se usan los nombres por defecto
            log.info("no se pudieron leer las reglas del mapa: %s", exc)
            return None

    @staticmethod
    def _rules_keys(rules) -> set[str]:
        """Claves de los archivos de los que salen ``rules``: si cambia uno, ya no valen."""
        from ..core.rules.game import SOURCE_RELS

        return {rel.key for rel in SOURCE_RELS} | {_map_rel(rules, "provinces", "provinces.bmp").key}

    def _forget_rules(self) -> None:
        """Descarta las reglas calculadas y ``Provinces``, que se hizo con ellas (sabe qué provincias son mar)."""
        self._rules_cache = None
        self._provinces = None

    def load_raster(self, *, force: bool = False) -> bool:
        """Pide el ráster en segundo plano. False si no hay proyecto, si ya está listo o si ya se está cargando
        (salvo ``force``, que cancela y vuelve a cargar sin usar la caché). Si ``provinces.bmp`` o
        ``definition.csv`` cambian en el proyecto (``documentsChanged``), se vuelve a cargar solo."""
        project = self.session.project
        if project is None:
            return False
        if not force and self._raster_state in (RASTER_READY, RASTER_LOADING):
            return False
        from ..core.validate.context import apply_unsaved_deletions
        from .session import document_overrides

        self._wanted = True
        rules = self._rules()
        provinces_rel = _map_rel(rules, "provinces", "provinces.bmp")
        definition_rel = _map_rel(rules, "definitions", "definition.csv")
        terrain_rel = _map_rel(rules, "terrain", "terrain.bmp")
        terrain_txt_rel = _map_rel(rules, "terrain_definition", "terrain.txt")
        self._raster_rels = {provinces_rel.key, definition_rel.key, terrain_rel.key, terrain_txt_rel.key}
        # Los borrados sin guardar dejan ganar el archivo del juego (papelera de copias idénticas), no lo quitan.
        snapshot, overrides = apply_unsaved_deletions(
            project.vfs.snapshot(),
            document_overrides(project, (provinces_rel, definition_rel, terrain_rel, terrain_txt_rel)))
        forbidden = [layer.root for layer in getattr(snapshot, "layers", ()) if getattr(layer, "root", None)]
        use_cache = not force

        def task(context) -> _Loaded:
            from ..core.map.bmp import BmpError, read_bmp
            from ..core.map.cache import load_or_build
            from ..core.map.facts import terrain_types

            bmp = _read_effective(snapshot, overrides, provinces_rel)
            if bmp is None:
                return _Loaded(error=ERROR_NO_PROVINCES)
            csv = _read_effective(snapshot, overrides, definition_rel)
            if csv is None:
                return _Loaded(error=ERROR_NO_DEFINITION)
            try:
                raster, cached = load_or_build(bmp, csv, forbidden=forbidden, use_cache=use_cache,
                                               progress=lambda done, total: context.report((done, total)),
                                               cancelled=context.cancelled)
            except Cancelled:
                raise
            except (BmpError, ValueError):
                return _Loaded(error=ERROR_BAD_BMP)
            majority = types = None
            terrain = _read_effective(snapshot, overrides, terrain_rel)
            terrain_txt = _read_effective(snapshot, overrides, terrain_txt_rel)
            if terrain is not None and terrain_txt is not None:
                try:
                    image = read_bmp(terrain)
                    if image.pixels.ndim == 2 and image.pixels.shape == raster.ids.shape:
                        majority = raster.majority(image.pixels)
                        types = terrain_types(terrain_txt)
                except (BmpError, ValueError):
                    majority = types = None
            return _Loaded(raster, majority, types, cached=cached)

        self._raster_state = RASTER_LOADING
        self._raster_error = None
        self._raster_runner.start(task)
        self.rasterStateChanged.emit()
        return True

    def cancel_raster(self) -> None:
        """Cancela la carga en curso (vuelve a ``RASTER_IDLE``); sin carga, nada."""
        if self._raster_state != RASTER_LOADING:
            return
        self._raster_runner.cancel()
        self._raster_state = RASTER_IDLE
        self.rasterStateChanged.emit()

    def _on_raster_progress(self, value) -> None:
        self.rasterProgress.emit(*value)

    def _on_raster_loaded(self, loaded: _Loaded) -> None:
        if loaded.error is not None:
            self._raster_state = RASTER_FAILED
            self._raster_error = loaded.error
            self.rasterStateChanged.emit()
            return
        self._raster = loaded.raster
        self._terrain = loaded.terrain
        self._terrain_types = loaded.terrain_types
        self._raster_state = RASTER_READY
        self.rasterStateChanged.emit()
        self.refresh_facts()

    def _on_raster_failed(self, failure) -> None:
        log.warning("no se pudo cargar el ráster del mapa: %s", failure)
        self._raster_state = RASTER_FAILED
        self._raster_error = ERROR_OTHER
        self.rasterStateChanged.emit()

    def province_at(self, x: int, y: int) -> int:
        """Id de la provincia del píxel ``(x, y)`` en coordenadas del juego (y hacia el norte); 0 si no hay
        ráster, si el punto cae fuera o si el color no es de ninguna provincia."""
        raster = self._raster
        return 0 if raster is None else int(raster.at(int(x), int(y)))

    # --- hechos -------------------------------------------------------------------------------------

    @property
    def facts(self) -> ProvinceFacts | None:
        """Los hechos en ``session.working_date``; None hasta que haya ráster e índice y termine su tarea."""
        return self._facts

    def refresh_facts(self, pids: Iterable[int] | None = None) -> None:
        """Rehace los hechos: enteros en segundo plano (``pids=None``) o solo ``pids`` desde sus registros vivos,
        en el acto. Emite ``factsChanged``."""
        if pids is not None:
            pids = [int(pid) for pid in pids]
            if self._facts_runner.is_busy():
                self._replay_pids.update(pids)
            facts = self._facts
            provinces = self.provinces
            if facts is None or provinces is None:
                return
            changed = set()
            date = self.session.working_date
            for pid in pids:
                pid = int(pid)
                if not 0 < pid < facts.size:
                    continue
                facts.update(pid, provinces.record(pid), date)
                changed.add(pid)
            if changed:
                self.factsChanged.emit(frozenset(changed))
            return
        index = self.session.index
        raster = self._raster
        project = self.session.project
        if index is None or raster is None or project is None:
            return
        rules = self._rules()
        if rules is None:
            return
        copy = index.copy() if hasattr(index, "copy") else index
        date = self.session.working_date
        terrain, types = self._terrain, self._terrain_types
        size = raster.max_id + 1
        # Un índice al que aún le falta algo (una exportación o un deshacer de hace menos de REINDEX_DELAY_MS): se
        # construye igual, para enseñar ya el ráster nuevo, y se rehace cuando se ponga al día (``_catch_up_facts``).
        self._facts_behind = self.session._index_behind()
        self._facts_source = index
        self._facts_rules = rules

        def task(context):
            from ..core.map.facts import ProvinceFacts

            return ProvinceFacts.build(copy, rules, date, size=size, terrain_majority=terrain,
                                       terrain_types=types, cancelled=context.cancelled)

        self._facts_runner.start(task)

    def _on_facts_built(self, facts) -> None:
        if facts is None or facts.date != self.session.working_date:
            return
        self._facts = facts
        self.factsChanged.emit(None)
        # Lo editado mientras se construían (brocha, deshacer, otra sala) se aplicó a los hechos de antes: se aplica
        # ahora a estos, en el acto, en vez de rehacerlos enteros otra vez (eso, con la brocha, no acababa nunca).
        pids, self._replay_pids = self._replay_pids, set()
        kinds, self._replay_groups = self._replay_groups, set()
        if pids:
            self.refresh_facts(pids)
        if kinds:
            self.resync_groups(kinds)
        self._catch_up_facts()

    def _catch_up_facts(self) -> None:
        """Rehace los hechos enteros si se hicieron con un índice atrasado y el índice ya se ha puesto al día (con
        el ráster listo y sin otra construcción en marcha: al terminar, esta vuelve a mirar)."""
        if (self._facts_behind and self._raster is not None and self._raster_state == RASTER_READY
                and not self._facts_runner.is_busy() and not self.session._index_behind()):
            self.refresh_facts()

    def _on_facts_failed(self, failure) -> None:
        log.warning("no se pudieron calcular los hechos del mapa: %s", failure)

    # --- acceso al núcleo (hilo de la interfaz, sobre el Workspace vivo) -----------------------------

    @property
    def provinces(self) -> Provinces | None:
        """``core.domain.province.Provinces`` sobre ``session.entities`` y las reglas del proyecto; None sin
        proyecto."""
        entities = self.session.entities if self.session.project is not None else None
        if entities is None:
            return None
        from ..core.domain.province import Provinces

        if self._provinces is None or self._provinces.entities is not entities:
            self._provinces = Provinces(entities, self._rules())
        return self._provinces

    def groups(self, kind: str) -> ProvinceGroups:
        """``ProvinceGroups`` del archivo de ``kind`` (uno de ``GROUP_KINDS``) con su disposición; ``KeyError``
        si ``kind`` no es un grupo."""
        from ..core.map.groups import GROUP_FILES, ProvinceGroups

        if kind not in GROUP_KINDS:
            raise KeyError(kind)
        project = self.session.project
        if project is None:
            raise KeyError(kind)
        rel, layout = GROUP_FILES[kind]
        if kind != "climate":
            rel = _map_rel(self._rules(), kind, rel.name)
        return ProvinceGroups(project.ws, rel, layout=layout)

    def adjacencies(self) -> AdjacencyTable:
        """La tabla efectiva de ``adjacencies.csv`` (con lo sin guardar); vacía si el archivo no existe."""
        from ..core.map.adjacency import AdjacencyTable, open_adjacencies
        from ..core.tablecsv import Table

        project = self.session.project
        if project is None:
            return AdjacencyTable(Table())
        try:
            return open_adjacencies(project.ws, self.adjacencies_rel())
        except (FileNotFoundError, OSError):
            return AdjacencyTable(Table())

    def adjacencies_rel(self) -> VPath:
        return _map_rel(self._rules(), "adjacencies", "adjacencies.csv")

    def positions(self) -> Positions:
        from ..core.map.positions import Positions

        project = self.session.project
        handle = project.ws.open(_map_rel(self._rules(), "positions", "positions.txt"))
        return Positions(handle.model.document)

    def default_map(self) -> DefaultMap:
        from ..core.map.default_map import DEFAULT_MAP_REL, DefaultMap

        project = self.session.project
        return DefaultMap(project.ws.open(DEFAULT_MAP_REL).model.document)

    def province_name(self, pid: int) -> str:
        """Nombre visible de la provincia en el idioma de la interfaz (``PROV<id>``); ``""`` si no tiene texto."""
        from ..i18n import language

        locsync = self.session.locsync
        if locsync is None:
            return ""
        lang = language()
        try:
            text = locsync.text(f"PROV{int(pid)}", lang) or locsync.text(f"PROV{int(pid)}", "en")
        except Exception:  # noqa: BLE001 - un texto que no se puede leer no rompe el mapa
            return ""
        return text or ""

    # --- ediciones (una transacción cada una) ---------------------------------------------------------

    def _after_edit(self, pids: Iterable[int]) -> None:
        self.refresh_facts(pids)

    def set_value(self, pid: int, key: str, value: object) -> bool:
        """``Provinces.set`` en la fecha de trabajo, dentro de ``session.edit(UNDO_SET, …)``; actualiza los
        hechos y emite ``factsChanged({pid})``. False (sin transacción) si el valor ya era ese."""
        from ..core.domain.province import UNDO_SET

        provinces = self.provinces
        if provinces is None:
            return False
        date = self.session.working_date
        current = provinces.get(pid, key, date).value
        if (current is None and value is None) or (current is not None and value is not None
                                                   and str(current).lower() == str(value).lower()):
            return False
        with self.session.edit(UNDO_SET, province=pid, field=key):
            changed = provinces.set(pid, key, value, date)
        self._after_edit([pid])
        return changed

    def paint(self, pids: Iterable[int], key: str, value: object) -> int:
        """``Provinces.paint`` sobre ``pids`` en una sola transacción (``UNDO_PAINT``): un trazo, un paso de
        deshacer. Devuelve cuántas provincias cambiaron (0: no abre transacción)."""
        from ..core.domain.province import UNDO_PAINT

        provinces = self.provinces
        if provinces is None:
            return 0
        date = self.session.working_date
        pending = []
        for pid in dict.fromkeys(int(p) for p in pids):
            if provinces.is_sea(pid):
                continue
            try:
                current = provinces.get(pid, key, date).value
            except Exception:  # noqa: BLE001 - una provincia desconocida no detiene la brocha
                continue
            if current is None and value is None:
                continue
            if current is not None and value is not None and str(current).lower() == str(value).lower():
                continue
            pending.append(pid)
        if not pending:
            return 0
        with self.session.edit(UNDO_PAINT, field=key, count=len(pending)):
            changed = provinces.paint(pending, key, value, date)
        self._after_edit(changed)
        return len(changed)

    def set_core(self, pid: int, tag: str, on: bool) -> bool:
        """Añade o quita el núcleo de ``tag`` en la fecha de trabajo (``UNDO_CORE``). False si ya estaba así."""
        from ..core.domain.province import UNDO_CORE

        provinces = self.provinces
        if provinces is None:
            return False
        date = self.session.working_date
        has = tag.upper() in (core.upper() for core in provinces.cores(pid, date))
        if has == bool(on):
            return False
        with self.session.edit(UNDO_CORE, province=pid, tag=tag):
            if on:
                provinces.add_core(pid, tag, date)
            else:
                provinces.remove_core(pid, tag, date)
        self._after_edit([pid])
        return True

    def move_to_group(self, kind: str, pids: Iterable[int], group: str | None) -> int:
        """Mueve ``pids`` al grupo ``group`` de ``kind`` (``None``: los saca del suyo) en una transacción
        (``UNDO_GROUP_MOVE``) y actualiza los hechos. Devuelve cuántas se movieron."""
        from ..core.domain.province import UNDO_GROUP_MOVE

        groups = self.groups(kind)
        pending = []
        for pid in dict.fromkeys(int(p) for p in pids):
            current = groups.groups_of(pid)
            if group is None and current:
                pending.append(pid)
            elif group is not None and (current != [group] or groups.members(group).count(pid) != 1):
                pending.append(pid)
        if not pending:
            return 0
        label_province = pending[0] if len(pending) == 1 else len(pending)
        with self.session.edit(UNDO_GROUP_MOVE, province=label_province, group=group or "—"):
            for pid in pending:
                if group is None:
                    groups.remove(pid)
                else:
                    groups.move(pid, group)
        facts = self._facts
        if facts is not None:
            field_name = {"region": "region", "region_sea": "region", "continent": "continent",
                          "climate": "climate"}[kind]
            for pid in pending:
                facts.set_group(field_name, pid, group)
            self.factsChanged.emit(frozenset(pending))
        return len(pending)

    def set_group_members(self, kind: str, gid: str, pids: Iterable[int]) -> tuple[int, int]:
        """Deja el grupo ``gid`` de ``kind`` con exactamente ``pids`` en una transacción (``UNDO_GROUP_MOVE``):
        las nuevas salen de su grupo anterior y las que sobran quedan sin grupo. Devuelve ``(añadidas,
        quitadas)``; (0, 0) sin transacción si ya era así."""
        from ..core.domain.province import UNDO_GROUP_MOVE

        groups = self.groups(kind)
        current = list(dict.fromkeys(groups.members(gid)))
        wanted = list(dict.fromkeys(int(p) for p in pids))
        added = [pid for pid in wanted if pid not in current or groups.groups_of(pid) != [gid]]
        removed = [pid for pid in current if pid not in wanted]
        if not added and not removed:
            return 0, 0
        count = len(added) + len(removed)
        with self.session.edit(UNDO_GROUP_MOVE, province=added[0] if count == 1 and added else count, group=gid):
            for pid in removed:
                groups.remove(pid)
            for pid in added:
                groups.move(pid, gid)
        self.resync_groups([kind])
        return len(added), len(removed)

    def group_edit(self, kind: str, action: str, gid: str, new: str | None = None) -> None:
        """``create``, ``rename`` o ``delete`` del grupo ``gid`` de ``kind`` en su transacción
        (``UNDO_GROUP_*``). ``GroupError`` (sin transacción abierta) si la operación rompería el archivo."""
        from ..core.domain.province import UNDO_GROUP_CREATE, UNDO_GROUP_DELETE, UNDO_GROUP_RENAME
        from ..core.map.groups import GroupError, _NAME

        groups = self.groups(kind)
        existing = set(groups.groups())
        if action == "create":
            if not _NAME.match(gid or ""):
                raise GroupError("bad_name", gid)
            if gid in existing:
                raise GroupError("group_exists", gid)
            with self.session.edit(UNDO_GROUP_CREATE, group=gid):
                groups.create(gid)
        elif action == "rename":
            if not _NAME.match(new or ""):
                raise GroupError("bad_name", new or "")
            if gid not in existing:
                raise GroupError("unknown_group", gid)
            if new in existing:
                raise GroupError("group_exists", new)
            with self.session.edit(UNDO_GROUP_RENAME, group=gid, new=new):
                groups.rename(gid, new)
        elif action == "delete":
            if gid not in existing:
                raise GroupError("unknown_group", gid)
            if groups.members(gid):
                raise GroupError("group_not_empty", gid)
            with self.session.edit(UNDO_GROUP_DELETE, group=gid):
                groups.delete(gid)
        else:
            raise ValueError(action)
        self.resync_groups([kind])

    def add_adjacency(self, start: int, end: int, type: str, *, through: int = 0, data: int = 0,
                      comment: str = "") -> Adjacency:
        """Fila nueva de ``adjacencies.csv`` en su transacción (``UNDO_ADJACENCY_ADD``). ``ValueError`` (sin
        transacción) si el tipo no existe, si las dos provincias son la misma o si ya hay una fila igual."""
        from ..core.domain.province import UNDO_ADJACENCY_ADD
        from ..core.map.adjacency import TYPES, store_adjacencies

        if type not in TYPES:
            raise ValueError("adjacency_type")
        if int(start) == int(end):
            raise ValueError("adjacency_same")
        table = self.adjacencies()
        for row in table.find(int(start), int(end)):
            if row.type == type and (row.through or 0) == int(through):
                raise ValueError("adjacency_exists")
        with self.session.edit(UNDO_ADJACENCY_ADD, start=start, end=end):
            added = table.add(int(start), int(end), type, through=int(through), data=int(data), comment=comment)
            store_adjacencies(self.session.project.ws, table, self.adjacencies_rel())
        return added

    def remove_adjacency(self, row: Adjacency) -> None:
        """Quita la fila (por su línea y su texto) en su transacción (``UNDO_ADJACENCY_REMOVE``). ``KeyError``
        si el archivo cambió y ya no está."""
        from ..core.domain.province import UNDO_ADJACENCY_REMOVE
        from ..core.map.adjacency import store_adjacencies

        table = self.adjacencies()
        table._row(row)                                    # KeyError antes de abrir la transacción
        with self.session.edit(UNDO_ADJACENCY_REMOVE, start=row.start, end=row.end):
            table.remove(row)
            store_adjacencies(self.session.project.ws, table, self.adjacencies_rel())

    # --- estado compartido de las páginas --------------------------------------------------------------

    @property
    def selection(self) -> tuple[int, ...]:
        return self._selection

    def set_selection(self, pids: Iterable[int]) -> None:
        """Cambia la selección (sin repetidos, en el orden dado) y emite ``selectionChanged`` si es otra."""
        selection = tuple(dict.fromkeys(int(pid) for pid in pids))
        if selection != self._selection:
            self._selection = selection
            self.selectionChanged.emit(selection)

    @property
    def view_center(self) -> tuple[int, int] | None:
        """Centro de la vista del lienzo principal en coordenadas del juego (``cameraX``/``cameraY`` de un
        bookmark); None si el lienzo aún no se ha mostrado."""
        return self._view_center

    def set_view_center(self, x: int, y: int) -> None:
        """Lo llama el lienzo al desplazarse o hacer zoom; emite ``viewChanged`` si cambió."""
        center = (int(x), int(y))
        if center != self._view_center:
            self._view_center = center
            self.viewChanged.emit()

    # --- reacciones a la sesión ----------------------------------------------------------------------

    def _on_project_closed(self) -> None:
        self._raster_runner.cancel()
        self._facts_runner.cancel()
        self._raster = None
        self._facts = None
        self._terrain = self._terrain_types = None
        self._forget_rules()
        self._facts_source = None
        self._facts_rules = None
        self._facts_behind = False
        self._replay_pids.clear()
        self._replay_groups.clear()
        self._selection = ()
        self._view_center = None
        self._wanted = False
        changed = self._raster_state != RASTER_IDLE
        self._raster_state = RASTER_IDLE
        self._raster_error = None
        if changed:
            self.rasterStateChanged.emit()
        self.factsChanged.emit(None)

    def _on_project_opened(self, project) -> None:
        self._forget_rules()

    def _on_date_changed(self, date) -> None:
        if self._raster is not None:
            self.refresh_facts()

    def _on_index_state(self) -> None:
        from .session import READY

        # ``index_state`` es un método: compararlo sin llamarlo daba siempre False y, con el ráster listo antes que
        # el índice, los hechos no se hacían nunca.
        if self.session.index_state() != READY or self._raster is None:
            return
        if self._facts is None:
            self.refresh_facts()
        elif self.session.index is not self._facts_source:
            # Un índice nuevo entero («Reindexar»): también las reglas (pueden haber cambiado en el disco, fuera del
            # Studio) y los hechos, que se hicieron con el de antes.
            self._forget_rules()
            self.refresh_facts()

    def _on_symbols_changed(self, kinds) -> None:
        """El índice cambió (una reindexación o uno nuevo). Los hechos se rehacen enteros solo si están marcados
        como atrasados; una construcción en marcha lo mira al terminar (``_on_facts_built``)."""
        self._catch_up_facts()

    def _on_documents_changed(self, rels) -> None:
        keys = {VPath.of(rel).key for rel in rels or ()}
        cached = self._rules_cache
        rules_changed = cached is not None and bool(keys & cached[2])
        if rules_changed:
            # Cambió (o se guardó) un archivo de las reglas: un default.map editado, una exportación del taller
            # hecha o deshecha.
            self._forget_rules()
        if self._wanted and keys & self._raster_rels:
            self._raster_state = RASTER_IDLE
            self.load_raster()                 # al llegar, los hechos se rehacen con las reglas nuevas
            return
        if rules_changed and (self._facts is not None or self._facts_runner.is_busy()) \
                and getattr(self._facts_rules, "sea", None) != getattr(self._rules(), "sea", None):
            # Con otro mar, los hechos de antes pintan de mar la tierra y al revés: se rehacen enteros.
            self.refresh_facts()
        if any(key.startswith("HISTORY/POPS/") for key in keys) \
                and (self._facts is not None or self._facts_runner.is_busy()):
            # La población sale de los bloques de POP del índice: un cambio de POPs (deshacer, rehacer, otra sala o
            # durante una construcción entera, que lee una copia del índice de antes) se ve rehaciendo los hechos
            # cuando el índice se ponga al día. La sala Mundo ya pone al momento la población de lo que edita ella.
            self._facts_behind = True
            QTimer.singleShot(0, self._catch_up_facts)     # después de que la sesión programe la reindexación
        facts = self._facts
        if facts is None:
            return
        touched = set()
        for key in keys:
            if key.startswith("HISTORY/PROVINCES/"):
                from ..core.vfs.rules import leading_int_key

                ident = leading_int_key(VPath.of(key))
                if ident is not None and ident.isdigit():
                    touched.add(int(ident))
        if touched:
            self.refresh_facts(touched)
        group_kinds = [kind for kind in GROUP_KINDS if self._group_rel(kind) in keys]
        if group_kinds:
            self.resync_groups(group_kinds)

    def _group_rel(self, kind: str) -> str | None:
        from ..core.map.groups import GROUP_FILES

        rel, _layout = GROUP_FILES[kind]
        if kind != "climate":
            rel = _map_rel(self._rules(), kind, rel.name)
        return rel.key

    def resync_groups(self, kinds: Iterable[str] = GROUP_KINDS) -> None:
        """Vuelve a leer de los archivos vivos (con lo sin guardar) el grupo de cada provincia para ``kinds`` y
        emite ``factsChanged`` con las que cambiaron. Lo llama ``documentsChanged`` tras un deshacer o una
        edición de los archivos de grupos, sin esperar al índice."""
        from ..core.map.facts import CODED

        kinds = tuple(kinds)
        if self._facts_runner.is_busy():
            self._replay_groups.update(kinds)
        facts = self._facts
        if facts is None or self.session.project is None:
            return
        fields = {"region": "region", "region_sea": "region", "continent": "continent", "climate": "climate"}
        wanted = {fields[kind] for kind in kinds}
        changed: set[int] = set()
        for field_name in sorted(wanted):
            members: dict[int, str] = {}
            sources = [kind for kind in GROUP_KINDS if fields[kind] == field_name]
            for kind in reversed(sources):            # en «region», el estado gana a la región marítima
                try:
                    groups = self.groups(kind)
                    for gid in groups.groups():
                        for pid in groups.members(gid):
                            members[int(pid)] = gid
                except Exception:  # noqa: BLE001 - un archivo que falta deja la provincia sin grupo
                    continue
            table = getattr(facts, field_name)
            for pid in range(1, facts.size):
                name = members.get(pid)
                if (facts.name(CODED[field_name], int(table[pid])) or None) != name:
                    facts.set_group(field_name, pid, name)
                    changed.add(pid)
        if changed:
            self.factsChanged.emit(frozenset(changed))
