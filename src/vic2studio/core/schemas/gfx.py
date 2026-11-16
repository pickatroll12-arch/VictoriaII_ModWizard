"""Sprites de la interfaz (``interface/*.gfx``): las definiciones de ``spriteTypes`` (wizard §17.1, §17.3).

Vanilla: 66 archivos, 47 con ``spriteTypes``, sin errores de sintaxis. Dentro de ``spriteTypes`` hay 1 264
definiciones: 1 067 ``spriteType``, 88 ``textSpriteType``, 48 ``progressbartype``, 27
``corneredTileSpriteType``, 17 ``maskedShieldType``, 10 ``PieChartType``, 4 ``LineChartType`` y una de
``tileSpriteType``, ``BarChartType`` y ``scrollingSprite``. Las claves y los nombres se buscan sin distinguir
mayúsculas (``textureFile``/``texturefile``, H23), así que el esquema es ``ignore_case``.

Decisiones del esquema:

- **Un esquema para todos los tipos**: comparten el nombre (el id), la textura y las banderas de carga; lo que
  es propio de un tipo (``borderSize`` del ``corneredTile``, ``textureFile1``/``textureFile2`` de las barras y
  escudos) es opcional. El tipo es la clave de la entrada (``Record.entity_key``).
- **Lo nuevo** va al final de ``spriteTypes`` en ``interface/<P>_studio.gfx`` (que se crea con su contenedor si
  no existe): lo usa «Nuevo sprite» (``core.gui.sprites``), que además escribe la textura DDS.
- ``size`` es un bloque ``{ x y }`` en casi todos los tipos y un número en ``PieChartType``: se conserva como
  código (``Opaque``). Lo que el catálogo de sprites necesita lo lee ``core.gui.SpriteDB``.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    EntitySchema,
    Field,
    Group,
    IdRule,
    IdSpec,
    Int,
    Opaque,
    Section,
    Text,
    TypedEntries,
)

SPRITE_KEYS = (
    "spriteType", "textSpriteType", "corneredTileSpriteType", "maskedShieldType", "progressbartype",
    "tileSpriteType", "PieChartType", "LineChartType", "BarChartType", "scrollingSprite",
)
TYPE_FIELD = "type"
NEW_FILE = "interface/{prefix}_studio.gfx"
CONTAINER = "spriteTypes"


def _xy(key: str) -> Group:
    return Group(key, (Field("x", Int()), Field("y", Int())))


def _template(ident: str, index) -> dict:
    return {TYPE_FIELD: "spriteType", "texturefile": f"gfx/interface/{ident}.dds"}


SPRITE = EntitySchema(
    kind="sprite",
    layout=TypedEntries("interface/*.gfx", SPRITE_KEYS, "name", NEW_FILE, type_field=TYPE_FIELD,
                        container=CONTAINER),
    ident=IdSpec.FIELD("name"),
    ident_rule=IdRule.WORD,
    provides="sprite",
    fields=(
        Section("general", (
            Field("name", Text(), required=True),
            Field("texturefile", Text()),
            Field("noOfFrames", Int(1)),
            Field("effectFile", Text(), advanced=True),
            Field("clicksound", Text(), advanced=True),
        )),
        Section("textures", (
            Field("textureFile1", Text()),
            Field("textureFile2", Text()),
            _xy("borderSize"),
            Opaque("size"),
            Opaque("color"),
            Opaque("colortwo"),
        ), collapsed=True),
        Section("loading", (
            Field("loadType", Text(), advanced=True),
            Field("norefcount", Bool(), advanced=True),
            Field("allwaystransparent", Bool(), advanced=True),
            Field("transparencecheck", Bool(), advanced=True),
            Field("horizontal", Bool(), advanced=True),
            Field("flipv", Bool(), advanced=True),
            Field("step", Int(), advanced=True),
            Field("linewidth", Int(), advanced=True),
        ), collapsed=True),
    ),
    template=_template,
    ignore_case=True,
    icon="file_image",
)

SCHEMAS = (SPRITE,)
