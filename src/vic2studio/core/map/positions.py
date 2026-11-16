"""``map/positions.txt``: lectura y edición de los puntos de cada provincia (wizard §14.3, §16). Contrato.

Un bloque ``<id> = { … }`` por provincia (3 248 en vanilla, 1,4 MB, CRLF; uno vacío). Dentro hay puntos ``{ x y }``
(``unit``, ``text_position``, ``factory``, ``building_construction``, ``military_construction``, ``city``,
``town``), ``building_position = { fort|naval_base|railroad = { x y } }``, giros (``building_rotation = {
naval_base = r }``, ``text_rotation``) y escalas (``text_scale``). Las coordenadas son las del juego, las mismas
del ráster (criterio 2: el punto ``unit`` cae en su provincia o junto a ella en ≥ 95 % de los casos).

``Positions`` es una vista sobre el CST del documento: no copia nada y editar un punto cambia solo sus dos
números, con los decimales que ya tenía (3 en vanilla), I3. Las ediciones van dentro de la transacción de quien
llama, tras ``ws.touch``. Los puntos de un mapa nuevo los genera ``generate`` (taller de mapas, §18.5).

Ojo con el tamaño: reanalizar este archivo cuesta 0,6–1 s (CONTINUAR §6), así que la interfaz no lo abre para
pintar; para leer en segundo plano está ``unit_points``, que recibe bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..clausewitz.nodes import Block, Entry, Scalar
from ..project.codecs import parse_bytes
from ..vfs.paths import VPath

POSITIONS_REL = VPath.of("map/positions.txt")
POINT_KEYS = ("unit", "text_position", "factory", "building_construction", "military_construction", "city",
              "town")
BUILDING_KEYS = ("fort", "naval_base", "railroad")
SCALAR_KEYS = ("text_scale", "text_rotation")
DECIMALS = 3                         # los de un número nuevo (los existentes conservan los suyos)


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _number(value: float, like: str | None = None) -> Scalar:
    """Número con los decimales de ``like`` (el texto que sustituye) o con ``DECIMALS`` si es nuevo."""
    places = DECIMALS if like is None else _decimals(like)
    return Scalar(f"{float(value):.{places}f}" if places else str(int(round(float(value)))))


def _float(value) -> float | None:
    if isinstance(value, Scalar):
        try:
            return value.as_float()
        except ValueError:
            return None
    return None


def _point_of(value) -> Point | None:
    if not isinstance(value, Block):
        return None
    x, y = _float(value.get("x")), _float(value.get("y"))
    if x is None or y is None:
        return None
    return Point(x, y)


def _set_number(block: Block, key: str, value: float) -> None:
    entry = block.find(key)
    if entry is None:
        block.append(key, _number(value))
    elif not (isinstance(entry.value, Scalar) and _float(entry.value) == float(value)):
        old = entry.value.text if isinstance(entry.value, Scalar) else None
        entry.value = _number(value, old)


def _set_xy(parent: Block, key: str, point: Point | None) -> None:
    entry = parent.find(key)
    if point is None:
        if entry is not None:
            parent.remove_entry(entry)
        return
    if entry is None or not isinstance(entry.value, Block):
        block = Block()
        block.append("x", _number(point.x))
        block.append("y", _number(point.y))
        if entry is None:
            parent.append(key, block)
        else:
            entry.value = block
        return
    _set_number(entry.value, "x", point.x)
    _set_number(entry.value, "y", point.y)


def _pid(entry: Entry) -> int | None:
    if entry.key is None or not isinstance(entry.value, Block):
        return None
    try:
        return entry.key.as_int()
    except ValueError:
        return None


class Positions:
    """Puntos de ``positions.txt`` sobre su documento (``DocHandle.model.document``)."""

    def __init__(self, document: Block) -> None:
        self.document = document

    def _blocks(self) -> dict[int, Block]:
        out: dict[int, Block] = {}
        for entry in self.document:
            pid = _pid(entry)
            if pid is not None and pid not in out:
                out[pid] = entry.value
        return out

    def _block(self, pid: int, *, create: bool = False) -> Block | None:
        block = self._blocks().get(pid)
        if block is None and create:
            self.document.append(str(int(pid)), Block())
            block = self._blocks().get(pid)
        return block

    def ids(self) -> list[int]:
        """Ids con bloque, en orden de archivo (un id repetido sale una vez; cuenta su primer bloque)."""
        return list(self._blocks())

    def has(self, pid: int) -> bool:
        return pid in self._blocks()

    def point(self, pid: int, key: str) -> Point | None:
        """Punto ``key`` (uno de ``POINT_KEYS``) de ``pid``; None si falta o no son dos números."""
        block = self._block(pid)
        return None if block is None else _point_of(block.get(key))

    def building_point(self, pid: int, building: str) -> Point | None:
        """``building_position = { <building> = { x y } }``."""
        block = self._block(pid)
        inner = None if block is None else block.get("building_position")
        return _point_of(inner.get(building)) if isinstance(inner, Block) else None

    def rotation(self, pid: int, building: str) -> float | None:
        """``building_rotation = { <building> = r }``."""
        block = self._block(pid)
        inner = None if block is None else block.get("building_rotation")
        return _float(inner.get(building)) if isinstance(inner, Block) else None

    def scalar(self, pid: int, key: str) -> float | None:
        """``text_scale`` o ``text_rotation``."""
        block = self._block(pid)
        return None if block is None else _float(block.get(key))

    def set_point(self, pid: int, key: str, point: Point | None) -> None:
        """Pone o quita (None) el punto. Si el bloque de ``pid`` no existe, lo crea al final del archivo; si el
        punto existe, cambia solo ``x`` e ``y``. ``ValueError`` si ``key`` no es de ``POINT_KEYS``."""
        if key not in POINT_KEYS:
            raise ValueError(f"no es un punto de positions.txt: {key}")
        block = self._block(pid, create=point is not None)
        if block is not None:
            _set_xy(block, key, point)

    def _inner(self, pid: int, key: str, create: bool) -> Block | None:
        block = self._block(pid, create=create)
        if block is None:
            return None
        inner = block.get(key)
        if not isinstance(inner, Block) and create:
            block.append(key, Block())
            inner = block.get(key)
        return inner if isinstance(inner, Block) else None

    def set_building_point(self, pid: int, building: str, point: Point | None) -> None:
        if building not in BUILDING_KEYS:
            raise ValueError(f"no es un edificio de positions.txt: {building}")
        inner = self._inner(pid, "building_position", point is not None)
        if inner is not None:
            _set_xy(inner, building, point)

    def set_rotation(self, pid: int, building: str, value: float | None) -> None:
        if building not in BUILDING_KEYS:
            raise ValueError(f"no es un edificio de positions.txt: {building}")
        inner = self._inner(pid, "building_rotation", value is not None)
        if inner is None:
            return
        if value is None:
            inner.remove(building)
        else:
            _set_number(inner, building, value)

    def set_scalar(self, pid: int, key: str, value: float | None) -> None:
        if key not in SCALAR_KEYS:
            raise ValueError(f"no es un valor de positions.txt: {key}")
        block = self._block(pid, create=value is not None)
        if block is None:
            return
        if value is None:
            block.remove(key)
        else:
            _set_number(block, key, value)


def unit_points(data: bytes) -> dict[int, Point]:
    """El punto ``unit`` de cada provincia que lo tiene, leído de los bytes del archivo (hilo de tarea, I12)."""
    positions = Positions(parse_bytes(data).document)
    out: dict[int, Point] = {}
    for pid, block in positions._blocks().items():
        point = _point_of(block.get("unit"))
        if point is not None:
            out[pid] = point
    return out


# --- generación (taller de mapas, wizard §18.5) ------------------------------------------------------------

SECONDARY_DEFAULT = {"building_construction": 6, "military_construction": 7, "factory": 8, "fort": 10, "railroad": 5}
_SECONDARY_START = {"building_construction": 0, "military_construction": 2, "factory": 4, "fort": 6, "railroad": 1}
_DIRS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


def generate(ids, is_sea, *, cap: int = 24, band: int = 256, secondary: dict | None = None) -> dict:
    """Puntos de cada provincia de un ráster de ids compactados (``ids`` (H, W), ``is_sea`` (N+1,)).

    - Centroide por bandas con ``bincount``, sin trigonometría; solo las provincias que tocan x = 0 y x = W−1
      suman W a sus x < W/2.
    - ``unit`` (y ``text_position``): el píxel más alejado del borde (hasta ``cap`` erosiones 4-conexas) y, entre
      empates, el más cercano al centroide.
    - Puntos secundarios: dirección unitaria × min(d, r) con r = distancia al borde de ``unit`` − 1; 8 direcciones
      en un orden distinto por clave hasta caer dentro con distancia al borde ≥ 2; si ninguna sirve, ``unit``.
    - ``naval_base``: el píxel de mar contiguo más cercano a ``unit`` (``-1`` si la provincia no es costera).
    - ``text_scale`` = 0,749·área^0,214 con ``math.pow`` (misma salida en cualquier CPU).

    Devuelve arrays por id (índice 0 sin uso): ``area``, ``cx``, ``cy``, ``ux``, ``uy``, ``extra[clave] = (x, y)``,
    ``nbx``, ``nby`` y la lista ``text_scale``."""
    import math

    import numpy as np

    secondary = dict(SECONDARY_DEFAULT if secondary is None else secondary)
    ids = np.asarray(ids)
    is_sea = np.asarray(is_sea, bool)
    H, W = ids.shape
    NP = int(is_sea.size - 1)
    flat = ids.ravel().astype(np.int64)
    area = np.bincount(flat, minlength=NP + 1)
    touch = np.zeros(NP + 1, bool)
    touch[np.intersect1d(ids[:, 0], ids[:, -1])] = True
    sx = np.zeros(NP + 1)
    sy = np.zeros(NP + 1)
    xr = np.arange(W, dtype=np.float64)
    for y0 in range(0, H, band):
        blk = ids[y0:y0 + band]
        bf = blk.ravel().astype(np.int64)
        X = np.tile(xr, blk.shape[0])
        X = X + W * (touch[bf] & (X < W / 2))
        sx += np.bincount(bf, weights=X, minlength=NP + 1)
        sy += np.bincount(bf, weights=np.repeat(np.arange(y0, y0 + blk.shape[0], dtype=np.float64), W),
                          minlength=NP + 1)
    cx = (sx / np.maximum(area, 1)) % W
    cy = sy / np.maximum(area, 1)
    cur = np.ones((H, W), bool)
    cur[:, :-1] &= ids[:, :-1] == ids[:, 1:]
    cur[:, 1:] &= ids[:, 1:] == ids[:, :-1]
    cur[:, -1] &= ids[:, -1] == ids[:, 0]
    cur[:, 0] &= ids[:, 0] == ids[:, -1]
    cur[:-1] &= ids[:-1] == ids[1:]
    cur[1:] &= ids[1:] == ids[:-1]
    cur[0] = False
    cur[-1] = False
    dist = cur.astype(np.uint8)
    tmp = np.empty_like(cur)
    for _ in range(cap - 1):
        np.copyto(tmp, cur)
        tmp[:, 1:] &= cur[:, :-1]
        tmp[:, :-1] &= cur[:, 1:]
        tmp[:, 0] &= cur[:, -1]
        tmp[:, -1] &= cur[:, 0]
        tmp[1:] &= cur[:-1]
        tmp[:-1] &= cur[1:]
        if not tmp.any():
            break
        dist += tmp
        cur, tmp = tmp, cur
    del cur, tmp
    dflat = dist.ravel()
    CB = cap + 1
    hist = np.bincount(flat * CB + dflat, minlength=(NP + 1) * CB).reshape(NP + 1, CB)
    maxd = (CB - 1 - np.argmax(hist[:, ::-1] > 0, axis=1)).astype(np.int64)
    del hist
    cand = np.flatnonzero(dflat == maxd[flat])
    cp = flat[cand]
    cyy, cxx = np.divmod(cand, W)
    dxc = np.abs(cxx - cx[cp])
    dxc = np.minimum(dxc, W - dxc)
    d2 = dxc ** 2 + (cyy - cy[cp]) ** 2
    o = np.lexsort((cand, d2, cp))
    first = np.ones(o.size, bool)
    first[1:] = cp[o][1:] != cp[o][:-1]
    ux = np.zeros(NP + 1, np.int64)
    uy = np.zeros(NP + 1, np.int64)
    ux[cp[o][first]] = cxx[o][first]
    uy[cp[o][first]] = cyy[o][first]
    pid = np.arange(NP + 1)
    r = np.maximum(maxd - 1, 0)
    extra = {}
    for key, dd in secondary.items():
        start = _SECONDARY_START.get(key, 0)
        px = ux.copy()
        py = uy.copy()
        done = np.zeros(NP + 1, bool)
        for j in range(8):
            ddx, ddy = _DIRS[(start + j) % 8]
            norm = math.sqrt(ddx * ddx + ddy * ddy)
            step = np.minimum(dd, r).astype(np.float64)
            qx = (ux + np.round(ddx / norm * step).astype(np.int64)) % W
            qy = np.clip(uy + np.round(ddy / norm * step).astype(np.int64), 0, H - 1)
            ok = (~done) & (ids[qy, qx] == pid) & (dist[qy, qx] >= 2) & (step >= 2)
            px[ok] = qx[ok]
            py[ok] = qy[ok]
            done |= ok
        extra[key] = (px, py)
    del dist
    a1 = ids[:, :-1].ravel().astype(np.int64)
    b1 = ids[:, 1:].ravel().astype(np.int64)
    i1 = np.flatnonzero((~is_sea[a1]) & is_sea[b1])
    sea_px = i1 + 1 + (i1 // (W - 1))
    i1b = np.flatnonzero(is_sea[a1] & (~is_sea[b1]))
    sea_px2 = i1b + (i1b // (W - 1))
    lp = np.concatenate([a1[i1], b1[i1b]])
    sp = np.concatenate([sea_px, sea_px2])
    a2 = ids[:-1].ravel().astype(np.int64)
    b2 = ids[1:].ravel().astype(np.int64)
    j1 = np.flatnonzero((~is_sea[a2]) & is_sea[b2])
    j1b = np.flatnonzero(is_sea[a2] & (~is_sea[b2]))
    lp = np.concatenate([lp, a2[j1], b2[j1b]]).astype(np.int64)
    sp = np.concatenate([sp, j1 + W, j1b])
    nbx = np.full(NP + 1, -1, np.int64)
    nby = np.full(NP + 1, -1, np.int64)
    if lp.size:
        syy, sxx = np.divmod(sp, W)
        ddx_ = np.abs(sxx - ux[lp])
        ddx_ = np.minimum(ddx_, W - ddx_)
        dd_ = ddx_ ** 2 + (syy - uy[lp]) ** 2
        o = np.lexsort((sp, dd_, lp))
        first = np.ones(o.size, bool)
        first[1:] = lp[o][1:] != lp[o][:-1]
        nbx[lp[o][first]] = sxx[o][first]
        nby[lp[o][first]] = syy[o][first]
    text_scale = [round(0.749 * math.pow(max(int(a), 1), 0.214), 2) for a in area.tolist()]
    return {"area": area, "cx": cx, "cy": cy, "ux": ux, "uy": uy, "maxd": maxd, "extra": extra, "nbx": nbx,
            "nby": nby, "text_scale": text_scale}


def generated_text(points: dict, land_count: int, *, header: str = "") -> bytes:
    """``positions.txt`` (CRLF, cp1252) con ``unit``, ``text_position``, ``text_scale``, los puntos de
    construcción y ``building_position`` (``fort``, ``railroad`` y ``naval_base`` en las costeras)."""
    lines: list[str] = [header] if header else []
    ux, uy = points["ux"], points["uy"]
    extra = points["extra"]
    n = len(points["text_scale"]) - 1
    for p in range(1, n + 1):
        lines.append(f"{p} = {{")
        lines.append(f"\tunit = {{ x = {int(ux[p])}.000 y = {int(uy[p])}.000 }}")
        lines.append(f"\ttext_position = {{ x = {int(ux[p])}.000 y = {int(uy[p])}.000 }}")
        lines.append(f"\ttext_scale = {points['text_scale'][p]:.2f}")
        if p <= land_count:
            for key in ("building_construction", "military_construction", "factory"):
                if key in extra:
                    lines.append(f"\t{key} = {{ x = {int(extra[key][0][p])}.000 y = {int(extra[key][1][p])}.000 }}")
            build = []
            for key in ("fort", "railroad"):
                if key in extra:
                    build.append(f"\t\t{key} = {{ x = {int(extra[key][0][p])}.000 y = {int(extra[key][1][p])}.000 }}")
            if points["nbx"][p] >= 0:
                build.append(f"\t\tnaval_base = {{ x = {int(points['nbx'][p])}.000 y = {int(points['nby'][p])}.000 }}")
            if build:
                lines += ["\tbuilding_position = {", *build, "\t}"]
        lines.append("}")
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")
