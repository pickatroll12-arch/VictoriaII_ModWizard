"""Elementos de las ventanas del juego (``interface/*.gui``): un esquema por tipo (wizard §17.2).

Vanilla: 59 archivos, 54 con ``guiTypes``, sin errores de sintaxis. Elementos, por tipo (en minúsculas):
``instantTextBoxType`` 1 591, ``guiButtonType`` 1 178, ``iconType`` 1 094, ``windowType`` 523,
``checkboxType`` 113, ``listboxType`` 100, ``textBoxType`` 89, ``positionType`` 73,
``OverlappingElementsBoxType`` 58, ``scrollbarType`` 47, ``shieldtype`` 24, ``editBoxType`` 21 y
``eu3dialogtype`` 17. El ejecutable lee claves y nombres sin distinguir mayúsculas (``Orientation`` y
``orientation`` conviven, H23): todos los esquemas son ``ignore_case``.

Decisiones del esquema:

- **Un esquema por tipo**, con los campos que ese tipo usa en vanilla (``gui_window``, ``gui_button``…). Los
  forma ``_element_schema`` a partir de una tabla: así el formulario de propiedades del lienzo enseña solo lo
  que tiene sentido para el elemento elegido.
- **Disposición ``GuiElements``**: un registro es un elemento a cualquier profundidad; su id es su ruta
  (``ventana/hijo``), única dentro del archivo. No se crean ni se borran elementos desde el formulario: el
  ejecutable busca muchos por nombre (§17.4) y no abriría ventanas nuevas.
- **Los hijos** de una ventana, un diálogo o una barra de desplazamiento son elementos con su propio esquema:
  aquí se declaran como ``Opaque`` (se conservan y no son desconocidos).
- ``orientation`` es texto libre: vanilla tiene ``UPPERL_LEFT``, que el juego trata como ``UPPER_LEFT``; lo
  avisa la regla ``gui_orientation_unknown``, no el tipo del campo.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    EntitySchema,
    Field,
    Float,
    GuiElements,
    Group,
    Int,
    Opaque,
    Section,
    Text,
)

GUI_GLOB = "interface/*.gui"

# Clave de cada tipo de elemento (con la grafía más común de vanilla) → kind del esquema.
ELEMENT_KINDS: dict[str, str] = {
    "windowType": "gui_window",
    "eu3dialogtype": "gui_dialog",
    "guiButtonType": "gui_button",
    "iconType": "gui_icon",
    "instantTextBoxType": "gui_instant_text",
    "textBoxType": "gui_text",
    "checkboxType": "gui_checkbox",
    "listboxType": "gui_listbox",
    "scrollbarType": "gui_scrollbar",
    "positionType": "gui_position",
    "OverlappingElementsBoxType": "gui_overlapping",
    "editBoxType": "gui_editbox",
    "shieldtype": "gui_shield",
}
KIND_OF_TYPE = {key.lower(): kind for key, kind in ELEMENT_KINDS.items()}


def _xy(key: str) -> Group:
    return Group(key, (Field("x", Float()), Field("y", Float())))


# Campos comunes y propios, por nombre. ``position`` y ``size`` los edita también el lienzo.
_FIELDS = {
    "name": Field("name", Text(), required=True),
    "position": _xy("position"),
    "size": _xy("size"),
    "orientation": Field("orientation", Text()),
    "spriteType": Field("spriteType", Text()),
    "quadTextureSprite": Field("quadTextureSprite", Text()),
    "buttonText": Field("buttonText", Text()),
    "buttonFont": Field("buttonFont", Text()),
    "text": Field("text", Text()),
    "font": Field("font", Text()),
    "format": Field("format", Text()),
    "maxWidth": Field("maxWidth", Int()),
    "maxHeight": Field("maxHeight", Int()),
    "fixedsize": Field("fixedsize", Bool()),
    "borderSize": _xy("borderSize"),
    "textureFile": Field("textureFile", Text(), advanced=True),
    "background": Field("background", Text()),
    "moveable": Field("moveable", Int(), advanced=True),
    "dontRender": Field("dontRender", Text(), advanced=True),
    "horizontalBorder": Field("horizontalBorder", Text(), advanced=True),
    "verticalBorder": Field("verticalBorder", Text(), advanced=True),
    "fullScreen": Field("fullScreen", Bool(), advanced=True),
    "upsound": Field("upsound", Text(), advanced=True),
    "downsound": Field("downsound", Text(), advanced=True),
    "tooltip": Field("tooltip", Text(), advanced=True),
    "tooltipText": Field("tooltipText", Text(), advanced=True),
    "delayedTooltipText": Field("delayedTooltipText", Text(), advanced=True),
    "shortcut": Field("shortcut", Text(), advanced=True),
    "clicksound": Field("clicksound", Text(), advanced=True),
    "parent": Field("parent", Text(), advanced=True),
    "rotation": Field("rotation", Float(), advanced=True),
    "scale": Field("scale", Float(), advanced=True),
    "frame": Field("frame", Int(), advanced=True),
    "buttonMesh": Field("buttonMesh", Text(), advanced=True),
    "allwaystransparent": Field("allwaystransparent", Bool(), advanced=True),
    "spacing": Field("spacing", Float()),
    "scrollbartype": Field("scrollbartype", Text()),
    "horizontal_bool": Field("horizontal", Bool()),
    "horizontal_int": Field("horizontal", Int()),
    "priority": Field("priority", Int(), advanced=True),
    "step": Field("step", Int(), advanced=True),
    "offset": _xy("offset"),
    "slider": Field("slider", Text()),
    "track": Field("track", Text()),
    "leftbutton": Field("leftbutton", Text()),
    "rightbutton": Field("rightbutton", Text()),
    "maxvalue": Field("maxvalue", Int()),
    "minvalue": Field("minvalue", Int()),
    "stepsize": Field("stepsize", Float()),
    "startvalue": Field("startvalue", Float()),
    "userangelimit": Field("userangelimit", Bool(), advanced=True),
    "rangelimitmin": Field("rangelimitmin", Int(), advanced=True),
    "rangelimitmax": Field("rangelimitmax", Int(), advanced=True),
    "rangelimitminicon": Field("rangelimitminicon", Text(), advanced=True),
    "rangelimitmaxicon": Field("rangelimitmaxicon", Text(), advanced=True),
    "lockable": Field("lockable", Bool(), advanced=True),
}

_WINDOW = ("background", "moveable", "dontRender", "horizontalBorder", "verticalBorder", "fullScreen", "upsound",
           "downsound")
_TEXT_BOX = ("text", "font", "format", "maxWidth", "maxHeight", "fixedsize", "borderSize", "textureFile",
             "allwaystransparent")
_TOOLTIP = ("tooltip", "tooltipText", "delayedTooltipText", "shortcut")

# kind → (campos de «Aspecto», campos de «Comportamiento», hijos que son elementos)
_TABLE: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "gui_window": (("size",), _WINDOW, tuple(ELEMENT_KINDS)),
    "gui_dialog": (("size",), _WINDOW, tuple(ELEMENT_KINDS)),
    "gui_button": (("quadTextureSprite", "spriteType", "buttonText", "buttonFont", "format", "size"),
                   (*_TOOLTIP, "clicksound", "parent", "rotation"), ()),
    "gui_icon": (("spriteType", "frame", "scale", "rotation"), ("buttonMesh",), ()),
    "gui_instant_text": (_TEXT_BOX, (), ()),
    "gui_text": (_TEXT_BOX, (), ()),
    "gui_checkbox": (("quadTextureSprite", "buttonText", "buttonFont"), _TOOLTIP, ()),
    "gui_listbox": (("size", "background", "borderSize", "spacing", "offset"),
                    ("scrollbartype", "horizontal_bool", "priority", "step", "allwaystransparent"), ()),
    "gui_scrollbar": (("size", "borderSize", "slider", "track", "leftbutton", "rightbutton"),
                      ("horizontal_int", "priority", "maxvalue", "minvalue", "stepsize", "startvalue",
                       "userangelimit", "rangelimitmin", "rangelimitmax", "rangelimitminicon",
                       "rangelimitmaxicon", "lockable"), ("guiButtonType", "iconType")),
    "gui_position": ((), (), ()),
    "gui_overlapping": (("size", "format", "spacing"), (), ()),
    "gui_editbox": (("size", "font", "text", "borderSize", "textureFile"), (), ()),
    "gui_shield": (("spriteType", "rotation"), (), ()),
}


def _element_schema(type_key: str, kind: str, order: int) -> EntitySchema:
    look, behaviour, children = _TABLE[kind]
    sections = [Section("general", (_FIELDS["name"], _FIELDS["position"], _FIELDS["orientation"]))]
    if look:
        sections.append(Section("look", tuple(_FIELDS[name] for name in look)))
    if behaviour:
        sections.append(Section("behaviour", tuple(_FIELDS[name] for name in behaviour), collapsed=True))
    if children:
        sections.append(Section("children", tuple(Opaque(child) for child in children), collapsed=True))
    return EntitySchema(
        kind=kind,
        layout=GuiElements(GUI_GLOB, (type_key,)),
        fields=tuple(sections),
        ignore_case=True,
        hall="interface", section="windows", order=order, icon="window",
    )


SCHEMAS = tuple(_element_schema(key, kind, order) for order, (key, kind) in enumerate(ELEMENT_KINDS.items(), 1))
