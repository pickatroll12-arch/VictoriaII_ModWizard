"""Fechas de inicio (``common/bookmarks.txt``, §14.10). Vanilla: 2 (H20).

Cada ``bookmark = { name desc date cameraX cameraY }`` se identifica por su ``name``, que es a la vez la
clave de su texto (``GC_NAME``); ``desc`` nombra la del texto largo. Las comillas se conservan. Lo nuevo
va al final del archivo con ``desc = "<id>_DESC"``. Las fechas alimentan el selector de fecha de trabajo; si
una pasa del ``end_date`` de ``defines.lua`` sale ``bookmark_date_outside_defines`` (error), que la
interfaz arregla ampliando ese token.
"""

from __future__ import annotations

from ..schema import (
    Date,
    EntitySchema,
    Field,
    IdSpec,
    Int,
    LocKey,
    LocSpec,
    RepeatedKey,
    Section,
    issue,
    validator,
)


DEFINES = "common/defines.lua"


def read_defines(ws):
    """``LuaDefines`` de ``common/defines.lua`` en la vista efectiva (con lo sin guardar); None si no hay."""
    from ..lua_defines import LuaDefines
    from ..project.codecs import codec_for

    try:
        handle = ws.open(DEFINES)
    except (FileNotFoundError, OSError):
        return None
    try:
        return LuaDefines.from_bytes(codec_for(handle.kind).snapshot(handle.model))
    except (ValueError, LookupError):
        return None


def define_date(defines, key: str):
    """La fecha de ``key`` (``start_date``/``end_date``) de un ``LuaDefines``; None si falta o no es una fecha."""
    from ..clausewitz.nodes import ClausewitzDate

    value = None if defines is None else defines.get(key)
    if value is None:
        return None
    try:
        return ClausewitzDate.parse(value.text.strip())
    except ValueError:
        return None


def set_define_date(ws, key: str, date) -> None:
    """Cambia solo el token de ``key`` en ``defines.lua`` conservando sus comillas (I3, §14.10).

    Va dentro de la transacción de quien llama. ``defines.lua`` aún no tiene códec propio (se abre como
    binario, ``core/project/codecs.py``): los bytes nuevos entran con ``restore_bytes``, que el guardado
    escribe tal cual y el deshacer devuelve. ``KeyError`` si la clave no está.
    """
    from ..lua_defines import LuaDefines
    from ..project.codecs import codec_for

    handle = ws.open(DEFINES)
    defines = LuaDefines.from_bytes(codec_for(handle.kind).snapshot(handle.model))
    current = defines.get(key)
    if current is None:
        raise KeyError(key)
    quote = current.raw[0] if current.raw[:1] in ("'", '"') else ""
    defines.set(key, f"{quote}{date}{quote}")
    ws.restore_bytes(handle, defines.to_bytes())


def defines_dates(ctx):
    """``(start_date, end_date)`` de ``common/defines.lua`` en la vista efectiva; None donde no se lea."""
    if ctx is None:
        return None, None
    if ctx.ws is not None:
        defines = read_defines(ctx.ws)
    elif getattr(ctx, "source", None) is not None:
        from ..lua_defines import LuaDefines
        from ..vfs.paths import VPath

        data = ctx.source.read(VPath.of(DEFINES))
        defines = None if data is None else LuaDefines.from_bytes(data)
    else:
        return None, None
    return define_date(defines, "start_date"), define_date(defines, "end_date")


@validator("bookmark_date_outside_defines", "error")
def date_inside_defines(rec, ctx):
    """El juego no deja empezar fuera del intervalo ``start_date``–``end_date`` de ``defines.lua``."""
    date = rec.get("date", None)
    if date is None or isinstance(date, str):
        return
    start, end = defines_dates(ctx)
    if (start is not None and date < start) or (end is not None and date > end):
        yield issue("bookmark_date_outside_defines", rec, field=("date",), date=str(date),
                    start=str(start or ""), end=str(end or ""))


BOOKMARK = EntitySchema(
    kind="bookmark",
    layout=RepeatedKey("common/bookmarks.txt", "bookmark", "name"),
    ident=IdSpec.FIELD("name"),
    provides="bookmark",
    symbol_attrs=lambda rec: {"date": rec.get("date", None)},
    fields=(
        Section("general", (
            Field("name", LocKey(), required=True),
            Field("desc", LocKey()),
            Field("date", Date(), required=True),
        )),
        Section("camera", (
            Field("cameraX", Int(0)),
            Field("cameraY", Int(0)),
        )),
    ),
    loc=(LocSpec("{id}", "bookmarks"), LocSpec("{id}_DESC", "bookmarks", required=False)),
    validators=(date_inside_defines,),
    template=lambda ident, idx: {"desc": f"{ident}_DESC", "date": _first_date(), "cameraX": 0, "cameraY": 0},
    hall="war", section="bookmarks", order=1, icon="calendar",
)


def _first_date():
    from ..clausewitz.nodes import ClausewitzDate

    return ClausewitzDate(1836, 1, 1)


SCHEMAS = (BOOKMARK,)
