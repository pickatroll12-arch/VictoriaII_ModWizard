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
   documentos tocados desde sus registros vivos.
3. **Las ediciones del mapa**, cada una en una sola transacción de ``Session.edit`` con su etiqueta
   ``core.domain.province.UNDO_*`` (un trazo de brocha = un paso de deshacer): ``set_value``, ``paint``,
   ``set_core``, ``move_to_group``. Lanzan lo que lance el núcleo (``ProvinceError``, ``GroupError``); la página
   lo muestra.

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

En el commit de contrato solo existe el constructor; lo demás lanza ``NotImplementedError`` hasta que lo
implemente la cadena B.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from ..core.domain.province import Provinces
    from ..core.map.adjacency import AdjacencyTable
    from ..core.map.default_map import DefaultMap
    from ..core.map.facts import ProvinceFacts
    from ..core.map.groups import ProvinceGroups
    from ..core.map.positions import Positions
    from ..core.map.raster import ProvinceRaster
    from .session import Session

RASTER_IDLE, RASTER_LOADING, RASTER_READY, RASTER_FAILED = "idle", "loading", "ready", "failed"
# Grupos de provincias que ``groups`` y ``move_to_group`` aceptan (los ``kind`` de sus esquemas).
GROUP_KINDS = ("region", "region_sea", "continent", "climate")


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

    # --- ráster -------------------------------------------------------------------------------------

    @property
    def raster(self) -> ProvinceRaster | None:
        """El ráster del proyecto abierto; None hasta ``RASTER_READY`` y al cerrar el proyecto."""
        raise NotImplementedError

    @property
    def raster_state(self) -> str:
        raise NotImplementedError

    @property
    def raster_error(self) -> str | None:
        """Clave de texto del motivo con ``RASTER_FAILED`` (falta el BMP, no es de 24 bits…); None si no falló."""
        raise NotImplementedError

    def load_raster(self, *, force: bool = False) -> bool:
        """Pide el ráster en segundo plano. False si no hay proyecto, si ya está listo o si ya se está cargando
        (salvo ``force``, que cancela y vuelve a cargar sin usar la caché). Si ``provinces.bmp`` o
        ``definition.csv`` cambian en el proyecto (``documentsChanged``), se vuelve a cargar solo."""
        raise NotImplementedError

    def cancel_raster(self) -> None:
        """Cancela la carga en curso (vuelve a ``RASTER_IDLE``); sin carga, nada."""
        raise NotImplementedError

    def province_at(self, x: int, y: int) -> int:
        """Id de la provincia del píxel ``(x, y)`` en coordenadas del juego (y hacia el norte); 0 si no hay
        ráster, si el punto cae fuera o si el color no es de ninguna provincia."""
        raise NotImplementedError

    # --- hechos -------------------------------------------------------------------------------------

    @property
    def facts(self) -> ProvinceFacts | None:
        """Los hechos en ``session.working_date``; None hasta que haya ráster e índice y termine su tarea."""
        raise NotImplementedError

    def refresh_facts(self, pids: Iterable[int] | None = None) -> None:
        """Rehace los hechos: enteros en segundo plano (``pids=None``) o solo ``pids`` desde sus registros vivos,
        en el acto. Emite ``factsChanged``."""
        raise NotImplementedError

    # --- acceso al núcleo (hilo de la interfaz, sobre el Workspace vivo) -----------------------------

    @property
    def provinces(self) -> Provinces | None:
        """``core.domain.province.Provinces`` sobre ``session.entities`` y las reglas del proyecto; None sin
        proyecto."""
        raise NotImplementedError

    def groups(self, kind: str) -> ProvinceGroups:
        """``ProvinceGroups`` del archivo de ``kind`` (uno de ``GROUP_KINDS``) con su disposición; ``KeyError``
        si ``kind`` no es un grupo."""
        raise NotImplementedError

    def adjacencies(self) -> AdjacencyTable:
        """La tabla efectiva de ``adjacencies.csv`` (con lo sin guardar); vacía si el archivo no existe."""
        raise NotImplementedError

    def positions(self) -> Positions:
        raise NotImplementedError

    def default_map(self) -> DefaultMap:
        raise NotImplementedError

    def province_name(self, pid: int) -> str:
        """Nombre visible de la provincia en el idioma de la interfaz (``PROV<id>``); ``""`` si no tiene texto."""
        raise NotImplementedError

    # --- ediciones (una transacción cada una) ---------------------------------------------------------

    def set_value(self, pid: int, key: str, value: object) -> bool:
        """``Provinces.set`` en la fecha de trabajo, dentro de ``session.edit(UNDO_SET, …)``; actualiza los
        hechos y emite ``factsChanged({pid})``. False (sin transacción) si el valor ya era ese."""
        raise NotImplementedError

    def paint(self, pids: Iterable[int], key: str, value: object) -> int:
        """``Provinces.paint`` sobre ``pids`` en una sola transacción (``UNDO_PAINT``): un trazo, un paso de
        deshacer. Devuelve cuántas provincias cambiaron (0: no abre transacción)."""
        raise NotImplementedError

    def set_core(self, pid: int, tag: str, on: bool) -> bool:
        """Añade o quita el núcleo de ``tag`` en la fecha de trabajo (``UNDO_CORE``). False si ya estaba así."""
        raise NotImplementedError

    def move_to_group(self, kind: str, pids: Iterable[int], group: str | None) -> int:
        """Mueve ``pids`` al grupo ``group`` de ``kind`` (``None``: los saca del suyo) en una transacción
        (``UNDO_GROUP_MOVE``) y actualiza los hechos. Devuelve cuántas se movieron."""
        raise NotImplementedError

    # --- estado compartido de las páginas --------------------------------------------------------------

    @property
    def selection(self) -> tuple[int, ...]:
        raise NotImplementedError

    def set_selection(self, pids: Iterable[int]) -> None:
        """Cambia la selección (sin repetidos, en el orden dado) y emite ``selectionChanged`` si es otra."""
        raise NotImplementedError

    @property
    def view_center(self) -> tuple[int, int] | None:
        """Centro de la vista del lienzo principal en coordenadas del juego (``cameraX``/``cameraY`` de un
        bookmark); None si el lienzo aún no se ha mostrado."""
        raise NotImplementedError

    def set_view_center(self, x: int, y: int) -> None:
        """Lo llama el lienzo al desplazarse o hacer zoom; emite ``viewChanged`` si cambió."""
        raise NotImplementedError
