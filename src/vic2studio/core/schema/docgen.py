"""Documentación de los esquemas en Markdown, ES y EN (wizard §10.9).

``render(schema, lang)`` da la página de un esquema: archivos y disposición, identificador, campos (clave,
tipo, valor por defecto, obligatorio y descripción), claves de texto, compañeros, comprobaciones propias y un
ejemplo mínimo construido con la plantilla del esquema. ``render_index(lang)`` da el índice. Todo sale de
los textos del núcleo (``core/schemas/texts``): ``missing_keys`` dice qué claves faltan, y la prueba exige
que no falte ninguna. Este módulo no escribe archivos (``tools/gen_reference.py`` lo hace, fuera de
``src/``) ni lee el juego: documenta el esquema, nunca copia datos de Paradox.
"""

from __future__ import annotations

from .companions import ActivateUnit, AppendToList, MappingTable, UnitNamesSlot
from .entity import EntitySchema
from .fields import MISSING, OPEN_CATALOG, Children, DynamicKeys, Field, Group, Opaque, Script, Section, field_text_key
from .layouts import (
    GroupedIn,
    KeyedAcross,
    KeyedFiles,
    NestedIn,
    OnePerFile,
    PairedKeys,
    RepeatedKey,
    SingleFile,
    Table,
    TypedEntries,
    WholeFile,
)
from .registry import registry


class _Texts:
    """Busca textos y anota las claves que faltan (para ``missing_keys``)."""

    def __init__(self, lang: str) -> None:
        from ..texts import load_texts

        self.lang = lang
        self.catalog = load_texts(lang)
        self.missing: list[str] = []

    def __call__(self, name: str, /, **fmt) -> str:
        template = self.catalog.get(name)
        if template is None:
            self.missing.append(name)
            return name
        import string

        names = {field for _, field, _, _ in string.Formatter().parse(template) if field}
        values = {name: "…" for name in names}   # un título con {gobierno}: en la referencia no hay registro
        values.update(fmt)
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template

    def optional(self, key: str) -> str | None:
        return self.catalog.get(key)


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _layout_text(schema: EntitySchema, t: _Texts) -> tuple[str, str]:
    layout = schema.layout
    if isinstance(layout, OnePerFile):
        return f"{layout.folder}/{layout.new_name}", t("docgen.layout.one_per_file")
    if isinstance(layout, RepeatedKey):
        return layout.path, t("docgen.layout.repeated_key", key=layout.key)
    if isinstance(layout, GroupedIn):
        return layout.path, t(f"docgen.layout.grouped_in_{min(layout.level, 1)}")
    if isinstance(layout, NestedIn):
        if layout.container:
            return layout.glob, t("docgen.layout.nested_in_container", container=layout.container)
        return layout.glob, t("docgen.layout.nested_in")
    if isinstance(layout, SingleFile):
        return layout.path, t("docgen.layout.single_file")
    # Disposiciones del mapa (iteración 5).
    if isinstance(layout, KeyedFiles):
        return f"{layout.folder}/*/{layout.new_name}", t("docgen.layout.keyed_files")
    if isinstance(layout, KeyedAcross):
        return layout.glob, t("docgen.layout.keyed_across")
    if isinstance(layout, PairedKeys):
        return layout.path, t("docgen.layout.paired_keys")
    if isinstance(layout, WholeFile):
        return layout.path, t("docgen.layout.whole_file")
    if isinstance(layout, Table):
        return layout.path, t("docgen.layout.table", columns=";".join(layout.columns))
    if isinstance(layout, TypedEntries):           # eventos (iteración 7)
        return layout.glob, t("docgen.layout.typed_entries", keys=" / ".join(layout.keys))
    return "?", type(layout).__name__


def _ident_text(schema: EntitySchema, t: _Texts) -> str:
    mode = schema.ident.mode
    if mode == "field":
        return t("docgen.ident.field", field=schema.ident.value)
    if isinstance(schema.layout, KeyedFiles):
        return t("docgen.ident.file_key")
    if isinstance(schema.layout, KeyedAcross):
        return t("docgen.ident.folder_key")
    if isinstance(schema.layout, WholeFile):
        return t("docgen.ident.fixed", ident=schema.layout.ident)
    if isinstance(schema.layout, Table):
        return t("docgen.ident.row")
    if mode == "file" or isinstance(schema.layout, OnePerFile):
        return t("docgen.ident.file")
    return t("docgen.ident.key")


def _default_text(field: Field, t: _Texts) -> str:
    if field.default is MISSING:
        return t("docgen.none")
    if isinstance(field.default, bool):
        return "yes" if field.default else "no"
    return str(field.default)


def _description(kind: str, key: str, t: _Texts) -> str:
    base = field_text_key(kind, key)
    label = t(base)
    help_text = t.optional(f"{base}.help")
    return f"{label}. {help_text}" if help_text else label


def _group_text(kind: str, key: str, t: _Texts) -> str:
    """La etiqueta de un bloque repetido o de pesos (``option``, ``mean_time_to_happen``); su clave si no tiene."""
    base = field_text_key(kind, key)
    return _description(kind, key, t) if t.optional(base) else key


def _rows(schema: EntitySchema, items, t: _Texts, lines: list[str]) -> None:
    kind = schema.kind
    for item in items:
        if isinstance(item, Section):
            _rows(schema, item.items, t, lines)
        elif isinstance(item, Field):
            lines.append(f"| `{item.key}` | {_cell(item.type.describe(t.lang))} | {_cell(_default_text(item, t))} | "
                         f"{t('docgen.yes') if item.required else t('docgen.no')} | "
                         f"{_cell(_description(kind, item.key, t))} |")
        elif isinstance(item, DynamicKeys):
            value = item.value if not callable(item.value) else None
            described = value.describe(t.lang) if value is not None else "…"
            what = (t("schema.type.dynamic_open", value=described) if item.key_kind == OPEN_CATALOG
                    else t("schema.type.dynamic", kind=item.key_kind, value=described))
            lines.append(f"| *{item.name}* | {_cell(what)} | {t('docgen.none')} | {t('docgen.no')} | "
                         f"{_cell(t(f'schema.{kind}.dynamic.{item.name}'))} |")
        elif isinstance(item, Group):
            what = t("schema.type.group", key=item.key)
            if item.dynamic is not None:
                value = item.dynamic.value if not callable(item.dynamic.value) else None
                what += " · " + t("schema.type.dynamic", kind=item.dynamic.key_kind,
                                  value=value.describe(t.lang) if value is not None else "…")
            lines.append(f"| `{item.key}` | {_cell(what)} | {t('docgen.none')} | "
                         f"{t('docgen.yes') if item.required else t('docgen.no')} | "
                         f"{_cell(t(f'schema.{kind}.dynamic.{item.dynamic.name}') if item.dynamic else _group_text(kind, item.key, t))} |")
        elif isinstance(item, Script):
            lines.append(f"| `{item.key}` | {_cell(t('schema.type.script'))} | {t('docgen.none')} | "
                         f"{t('docgen.yes') if item.required else t('docgen.no')} | "
                         f"{_cell(_description(kind, item.key, t))} |")
        elif isinstance(item, Opaque):
            lines.append(f"| `{item.key}` | {_cell(t('schema.type.opaque'))} | {t('docgen.none')} | "
                         f"{t('docgen.no')} | {_cell(_description(kind, item.key, t))} |")
        elif isinstance(item, Children):
            lines.append(f"| *{item.schema.kind}* | {_cell(t('schema.type.children', kind=item.schema.kind))} | "
                         f"{t('docgen.none')} | {t('docgen.no')} | {_cell(t(f'schema.{item.schema.kind}.title'))} |")


def _companion_text(companion, t: _Texts) -> str | None:
    if isinstance(companion, AppendToList):
        return t("docgen.companion.append_to_list", path=".".join(companion.path), rel=companion.rel)
    if isinstance(companion, MappingTable):
        return t("docgen.companion.mapping_table", table=companion.table, rel=companion.rel)
    if isinstance(companion, ActivateUnit):
        return t("docgen.companion.activate_unit")
    if isinstance(companion, UnitNamesSlot):
        return t("docgen.companion.unit_names_slot")
    return None


def _validator_codes(schema: EntitySchema) -> list[str]:
    codes = [getattr(fn, "validator_code", None) for fn in schema.validators]
    return [code for code in codes if code]


def _example(schema: EntitySchema) -> str | None:
    from ..clausewitz.nodes import Document
    from ..clausewitz.serializer import format_canonical
    from .record import build_block

    if not schema.editable or schema.template is None:
        return None
    from ..project.model import EVENT_ID_START
    from .record import _find_field
    from .types import Int

    ident = f"my_{schema.kind}"
    if schema.ident.mode == "field":
        id_field = _find_field(schema.fields, schema.ident.value)
        if id_field is not None and isinstance(id_field.type, Int):
            ident = str(EVENT_ID_START)          # un id numérico (``id = 200000000`` de un evento)
    block = build_block(schema, ident, {}, None)
    document = Document()
    from .layouts import RepeatedKey as _Repeated

    key = schema.layout.key if isinstance(schema.layout, _Repeated) else ident
    if isinstance(schema.layout, TypedEntries):
        key = schema.layout.keys[0]
    document.append(key, block)
    return format_canonical(document, indent="\t", newline="\n").rstrip("\n")


def render(schema: EntitySchema, lang: str = "es") -> str:
    """Página Markdown de ``schema`` en ``lang``."""
    t = _Texts(lang)
    return _render(schema, t)


def _render(schema: EntitySchema, t: _Texts) -> str:
    kind = schema.kind
    lines = [f"# {t(f'schema.{kind}.title')} (`{kind}`)", "", t(f"schema.{kind}.doc"), ""]
    path, layout = _layout_text(schema, t)
    lines += [f"- **{t('docgen.files')}:** `{path}`", f"- **{t('docgen.layout')}:** {layout}",
              f"- **{t('docgen.ident')}:** {_ident_text(schema, t)}",
              f"- **{t('docgen.editable')}:** {t('docgen.editable.yes') if schema.editable else t('docgen.editable.no')}"]
    if schema.hall and schema.section and schema.editable:
        lines.append(f"- **{t('docgen.section_in_app')}:** `{schema.hall}:{schema.section}`")
    lines += ["", f"## {t('docgen.fields')}", "",
              f"| {t('docgen.col.key')} | {t('docgen.col.type')} | {t('docgen.col.default')} | "
              f"{t('docgen.col.required')} | {t('docgen.col.description')} |",
              "|---|---|---|---|---|"]
    _rows(schema, schema.fields, t, lines)
    if schema.variants is not None:
        for value, items in schema.variants.cases.items():
            lines += ["", f"### {t('docgen.variant', field=schema.variants.field, value=value)}", "",
                      f"| {t('docgen.col.key')} | {t('docgen.col.type')} | {t('docgen.col.default')} | "
                      f"{t('docgen.col.required')} | {t('docgen.col.description')} |",
                      "|---|---|---|---|---|"]
            _rows(schema, items, t, lines)
    if schema.views:
        lines += ["", f"## {t('docgen.views')}", ""]
        for view in schema.views:
            lines.append(f"- `{schema.hall}:{view.section}`: {t(f'schema.{kind}.view.{view.key}')}")
    lines += ["", f"## {t('docgen.loc')}", ""]
    if schema.loc:
        for spec in schema.loc:
            note = "" if spec.required else f" ({t('docgen.loc.optional')})"
            lines.append(f"- `{spec.template}` {t('docgen.loc.area', area=spec.area)}{note}")
    else:
        lines.append(t("docgen.loc.none"))
    companions = [text for text in (_companion_text(c, t) for c in schema.companions) if text]
    if companions:
        lines += ["", f"## {t('docgen.companions')}", ""] + [f"- {text}" for text in companions]
    codes = _validator_codes(schema)
    if codes:
        lines += ["", f"## {t('docgen.validators')}", ""]
        lines += [f"- `{code}`: {t(f'explain.title.{code}')}" for code in codes]
    example = _example(schema)
    if example is not None:
        lines += ["", f"## {t('docgen.example')}", "", "```text", example, "```"]
    return "\n".join(lines) + "\n"


def render_index(lang: str = "es") -> str:
    """Índice de la referencia: un enlace por esquema."""
    t = _Texts(lang)
    lines = [f"# {t('docgen.index_title')}", "", t("docgen.index_intro"), ""]
    for schema in sorted(registry.all_schemas(), key=lambda s: s.kind):
        lines.append(f"- [{t(f'schema.{schema.kind}.title')}]({schema.kind}.md) (`{schema.kind}`)")
    return "\n".join(lines) + "\n"


def missing_keys(lang: str) -> list[str]:
    """Claves de texto que la referencia de ``lang`` necesita y no existen (vacía si está completa)."""
    t = _Texts(lang)
    for schema in registry.all_schemas():
        _render(schema, t)
        t(f"schema.{schema.kind}.title")   # el índice
    for key in ("docgen.index_title", "docgen.index_intro"):
        t(key)
    return sorted(set(t.missing))


def reference(lang: str) -> dict[str, str]:
    """``{nombre de archivo: contenido}`` de la referencia de ``lang`` (lo que escribe tools/gen_reference.py)."""
    pages = {f"{schema.kind}.md": render(schema, lang) for schema in registry.all_schemas()}
    pages["README.md"] = render_index(lang)
    return pages
