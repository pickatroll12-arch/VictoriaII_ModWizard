"""Arnés de esquemas (wizard §19.3): las pruebas que genera ``SchemaContract``.

Una subclase de tres líneas (``schema``, ``corpus`` y ``allowed``) prueba un esquema entero:
paridad de sus textos, abrir y guardar sin cambios, ``set`` de cada campo con su ``example``,
claves dinámicas, plantilla válida, claves de localización, compañeros, colocación y
conformidad con el corpus (0 ``unknown_field`` y 0 ``bad_type``). Las pruebas usan el
minijuego sintético y, la de corpus, ``vanilla_root()`` (se omite sin corpus).

Iteración 4 (cierre): se genera también ``test_docgen`` (la página ES/EN del esquema sin claves sin
traducir), ``test_list_finds_records`` y las pruebas de creación se adaptan a cada disposición (al final del
archivo, del grupo o de la lista) y se saltan en los esquemas de solo lectura. El minijuego se construye con
``SCHEMA_GAME_FILES`` (fragmentos sintéticos que solo usan los esquemas, como ``event_modifiers.txt``).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.clausewitz.diagnostics import Severity  # noqa: E402
from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.diffing import counted_diff  # noqa: E402
from vic2studio.core.schema import (  # noqa: E402
    AppendToList,
    CheckContext,
    Entities,
    Field,
    GroupedIn,
    MappingTable,
    RepeatedKey,
    SingleFile,
)
from vic2studio.core.schema.docgen import render as render_doc  # noqa: E402
from vic2studio.core.schema.fields import (  # noqa: E402
    DynamicKeys,
    Group,
    Script,
    Section,
    field_text_key,
)
from vic2studio.core.schema.record import Record, RecordRef  # noqa: E402
from vic2studio.core.texts import load_texts  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _corpus import vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import SCHEMA_GAME_FILES, build_minigame  # noqa: E402


class SchemaContract(unittest.TestCase):
    """Contrato que debe cumplir todo esquema (wizard §19.3).

    ``corpus``: ruta del archivo con los registros del juego (se requiere ``vanilla_root()``).
    ``allowed``: línea base declarada ``{código: número}`` de problemas permitidos en el corpus.
    """

    schema = None                     # EntitySchema (lo pone la subclase)
    corpus = None                     # VPath relativo (opcional)
    allowed = {}                      # línea base declarada

    # --- andamiaje ----------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        if cls.schema is None:
            raise unittest.SkipTest("SchemaContract es la base del arnés; se usa con subclases")

    def setUp(self):
        isolate_appdirs(self)
        game = build_minigame(mod=True, game_files=SCHEMA_GAME_FILES)
        self.addCleanup(game.cleanup)
        self.project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.entities = Entities(self.project.ws, self._index(), self._loc())

    def _index(self):
        return build_index(self.project.vfs.snapshot(), None, {})

    def _loc(self):
        return LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix)

    def _ctx(self):
        return CheckContext(self.project.ws, self.entities.index, self._loc())

    def _snapshot(self, handle) -> bytes:
        return codec_for(handle.kind).snapshot(handle.model)

    @property
    def create_values(self) -> dict:
        """Lo que hace falta además de la plantilla para crear: el grupo en un ``GroupedIn`` de nivel 1."""
        layout = self.schema.layout
        if isinstance(layout, GroupedIn) and layout.level > 0:
            document = self.project.ws.open(layout.path).model.document
            return {"group": next(name for name, _, _ in layout.groups(document))}
        return {}

    def _new_values(self, ident: str) -> dict:
        values = dict(self.schema.template(ident, self.entities.index)) if self.schema.template is not None else {}
        values.update(self.create_values)
        return values

    def _container_of(self, ref):
        """El bloque donde el layout pone lo nuevo, para comprobar que queda al final."""
        record = self.entities.open(ref)
        from vic2studio.core.schema.layouts import parent_block

        return parent_block(record.handle.model.document, record._entry)

    # --- recorridos del esquema ---------------------------------------------------------

    def _flat_fields(self, items) -> list[Field]:
        found = []
        for item in items:
            if isinstance(item, Section):
                found.extend(self._flat_fields(item.items))
            elif isinstance(item, Field):
                found.append(item)
        return found

    def _all_fields(self) -> list[Field]:
        fields = self._flat_fields(self.schema.fields)
        variant = self.schema.variants
        if variant is not None:
            for case in variant.cases.values():
                fields.extend(self._flat_fields(case))
        return fields

    def _all_dynamics(self) -> list[tuple[DynamicKeys, str | None]]:
        found = []

        def walk(items, container):
            for item in items:
                if isinstance(item, Section):
                    walk(item.items, container)
                elif isinstance(item, DynamicKeys):
                    found.append((item, container))
                elif isinstance(item, Group) and item.dynamic is not None:
                    found.append((item.dynamic, item.key))

        walk(self.schema.fields, None)
        return found

    # --- pruebas generadas --------------------------------------------------------------

    def test_texts_es_en(self):
        kind = self.schema.kind
        for lang in ("es", "en"):
            texts = load_texts(lang)
            for section in (item for item in self.schema.fields if isinstance(item, Section)):
                self.assertIn(f"schema.{kind}.section.{section.name}", texts,
                              f"{lang}: falta la sección {section.name}")
            for field in self._all_fields():
                self.assertIn(field_text_key(kind, field.key), texts,
                              f"{lang}: falta el campo {field.key}")
                values = getattr(field.type, "values", ())
                for value in values:
                    snake = field_text_key(kind, field.key).rsplit(".", 1)[-1]
                    self.assertIn(f"schema.{kind}.enum.{snake}.{value}", texts,
                                  f"{lang}: falta el valor {field.key}.{value}")
            for spec, _ in self._all_dynamics():
                self.assertIn(f"schema.{kind}.dynamic.{spec.name}", texts,
                              f"{lang}: faltan las claves dinámicas {spec.name}")
            for view in self.schema.views:
                self.assertIn(f"schema.{kind}.view.{view.key}", texts,
                              f"{lang}: falta la vista {view.key}")
            for key in (f"schema.{kind}.title", f"schema.{kind}.name", f"schema.{kind}.doc"):
                self.assertIn(key, texts, f"{lang}: falta {key}")
            for script in self._all_scripts():
                self.assertIn(field_text_key(kind, script.key), texts, f"{lang}: falta el bloque {script.key}")
            if self.schema.editable:
                for action in ("create", "duplicate", "delete", "rename"):
                    self.assertIn(f"undo.{action}_{kind}", texts, f"{lang}: falta la etiqueta de deshacer")

    def _all_scripts(self) -> list:
        found = []

        def walk(items):
            for item in items:
                if isinstance(item, Section):
                    walk(item.items)
                elif isinstance(item, Script):
                    found.append(item)

        walk(self.schema.fields)
        return found

    def test_docgen(self):
        """docgen da la página ES y EN del esquema sin claves sin traducir (criterio 7)."""
        from vic2studio.core.schema.docgen import _render, _Texts

        for lang in ("es", "en"):
            texts = _Texts(lang)
            page = _render(self.schema, texts)
            self.assertEqual(texts.missing, [], f"{lang}: claves sin traducir en la referencia")
            self.assertIn(f"(`{self.schema.kind}`)", page)
            self.assertEqual(page, render_doc(self.schema, lang), "docgen no es determinista")

    def test_list_finds_records(self):
        """El minijuego tiene registros de este esquema y todos se abren (vista efectiva, I7)."""
        summaries = self.entities.list(self.schema.kind)
        self.assertTrue(summaries, "el minijuego no da registros de este esquema")
        for summary in summaries:
            self.assertEqual(self.entities.open(summary.ref).ref.ident, summary.ref.ident)

    def test_open_save_unchanged(self):
        ws = self.project.ws
        for summary in self.entities.list(self.schema.kind):
            record = self.entities.open(summary.ref)
            record.issues(self._ctx())
            for key in record._index_schema()[0]:
                record.get(key)
            for name in record._index_schema()[2]:
                record.dynamic(name)
            self.assertFalse(ws.dirty(), f"leer {summary.ref} ensucia el documento")
        self.assertTrue(ws.save().nothing_to_save, "guardar tras leer escribe")

    def test_set_each_field(self):
        ws = self.project.ws
        variant_field = self.schema.variants.field if self.schema.variants is not None else None
        for summary in self.entities.list(self.schema.kind):
            fields, _, _ = self.entities.open(summary.ref)._index_schema()
            for key in fields:
                if key == variant_field:
                    continue   # cambiar el discriminador mudaría la variante activa
                record = self.entities.open(summary.ref)   # fresco (deshacer reemplaza el modelo)
                field = fields[key]
                example = field.type.example(self._ctx())
                before = self._snapshot(record.handle)
                with self.subTest(record=summary.ref.ident, field=key):
                    with ws.transaction("test.undo_edit", key=key, ident=summary.ref.ident):
                        record.set(key, example)
                    after = self._snapshot(record.handle)
                    _, lines = counted_diff(record.handle.rel, before, after)
                    self.assertIn(lines, ((0, 0), (1, 0), (1, 1)),
                                  f"set de {key} toca más de una línea")
                    if lines != (0, 0):
                        self.assertEqual(record.get(key), example,
                                         "el valor escrito no se lee igual (roundtrip)")
                    ws.undo()
                    self.assertEqual(self._snapshot(record.handle), before, "deshacer no es exacto")

    def test_dynamic_keys(self):
        ws = self.project.ws
        for summary in self.entities.list(self.schema.kind):
            record = self.entities.open(summary.ref)
            for spec, container in self._all_dynamics():
                catalog = sorted(self.entities.index.names(spec.key_kind))
                key = catalog[0] if catalog else "test_dynamic_key"
                with self.subTest(record=summary.ref.ident, dynamic=spec.name):
                    before = record.dynamic(spec.name)
                    value_type = spec.value(key) if callable(spec.value) else spec.value
                    example = value_type.example(self._ctx())
                    with ws.transaction("test.undo_edit", key=spec.name, ident=summary.ref.ident):
                        record.set_dynamic(spec.name, key, example)
                    self.assertIn(key, record.dynamic(spec.name),
                                  f"set_dynamic de {spec.name} no aparece")
                    if spec.only_true:
                        with ws.transaction("test.undo_edit", key=spec.name, ident=summary.ref.ident):
                            record.set_dynamic(spec.name, key, False)
                        self.assertNotIn(key, record.dynamic(spec.name),
                                         f"only_true no borra la clave falsa de {spec.name}")
                        ws.undo()
                    ws.undo()
                    record = self.entities.open(summary.ref)   # deshacer reemplaza el modelo
                    self.assertEqual(record.dynamic(spec.name), before)

    def test_template_validates(self):
        if not self.schema.editable:
            return
        ref = self.entities.create(self.schema.kind, "test_created", self._new_values("test_created"))
        record = self.entities.open(ref)
        errors = [p for p in record.issues(self._ctx()) if p.severity is Severity.ERROR]
        self.assertEqual(errors, [], "lo nuevo nace con errores")
        self.project.ws.undo()
        self.assertEqual(self.project.ws.dirty(), [], "el deshacer no quita la creación")

    def test_loc_keys(self):
        summary = self.entities.list(self.schema.kind)[0]
        record = self.entities.open(summary.ref)
        expected = [(spec, spec.template.replace("{id}", record.ref.ident)) for spec in self.schema.loc]
        self.assertEqual(record.loc_keys(), expected)

    def _tables(self, rel: str, table_key: str) -> list:
        handle = self.project.ws.open(rel)
        tables = []

        def walk(block):
            for entry in block.entries:
                if entry.key is not None and entry.key.text == table_key and hasattr(entry.value, "entries"):
                    tables.append(entry.value)
                if hasattr(entry.value, "entries"):
                    walk(entry.value)

        walk(handle.model.document)
        return tables

    def test_companions(self):
        """Crear pasa por cada compañero en la misma transacción, borrar quita lo suyo y un deshacer lo
        devuelve todo (I5)."""
        if not self.schema.companions or not self.schema.editable:
            return
        values = dict(self.schema.template("test_companion", self.entities.index)) \
            if self.schema.template is not None else {}
        values.update(self.create_values)
        ref = self.entities.create(self.schema.kind, "test_companion", values)
        self.assertEqual(len(self.project.ws.history()), 1, "crear con compañeros es una sola transacción")
        for companion in self.schema.companions:
            if isinstance(companion, MappingTable):
                tables = self._tables(companion.rel, companion.table)
                self.assertTrue(tables, "el minijuego tiene tablas de rebeldes")
                for table in tables:
                    self.assertIsNotNone(table.find("test_companion"),
                                         "el compañero no añadió la clave a todas las tablas")
            elif isinstance(companion, AppendToList):
                handle = self.project.ws.open(companion.rel)
                block = handle.model.document
                for key in companion.path:
                    block = block.find(key).value
                values = [entry.value.text for entry in block.entries if entry.key is None]
                self.assertEqual(values[-1], "test_companion", "no queda al final de la lista")
        self.entities.delete(ref)
        for companion in self.schema.companions:
            if isinstance(companion, MappingTable):
                for table in self._tables(companion.rel, companion.table):
                    self.assertIsNone(table.find("test_companion"), "borrar no quita la fila de la matriz")
            elif isinstance(companion, AppendToList):
                handle = self.project.ws.open(companion.rel)
                self.assertNotIn(b"test_companion", self._snapshot(handle), "borrar no lo quita de la lista")
        self.project.ws.undo()
        self.project.ws.undo()
        self.assertEqual(self.project.ws.dirty(), [], "el deshacer no quita la creación")

    def test_placement(self):
        if self.schema.editable:
            ref = self.entities.create(self.schema.kind, "test_placed", self._new_values("test_placed"))
            if isinstance(self.schema.layout, (SingleFile, RepeatedKey, GroupedIn)):
                container = self._container_of(ref)
                last = container.entries[-1]
                self.assertIs(last.value, self.entities.open(ref).block,
                              "lo nuevo no queda al final de su archivo o de su grupo")
            self.project.ws.undo()
        # Campo nuevo en un registro existente: queda en su sitio del orden del esquema.
        summary = self.entities.list(self.schema.kind)[0]
        record = self.entities.open(summary.ref)
        ordered = [field.key for field in self._flat_fields(record._effective_fields())]
        candidate = next((key for key in ordered if record.node(key) is None), None)
        if candidate is None:
            return
        with self.project.ws.transaction("test.undo_edit", key=candidate, ident=summary.ref.ident):
            record.set(candidate, next(f for f in self._flat_fields(record._effective_fields())
                                       if f.key == candidate).type.example(self._ctx()))
        block = record.block
        entry = block.find(candidate)
        self.assertIsNotNone(entry, "el campo nuevo no se escribió")
        index = block.entries.index(entry)
        for other in ordered:
            if other == candidate:
                continue
            node = block.find(other)
            if node is None:
                continue
            other_index = block.entries.index(node)
            if ordered.index(other) < ordered.index(candidate):
                self.assertLess(other_index, index, f"{candidate} quedó antes que {other}")
            else:
                self.assertGreater(other_index, index, f"{candidate} quedó después de {other}")
        self.project.ws.undo()

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_corpus_conformance(self):
        game_root = vanilla_root()
        mod_root = Path(tempfile.mkdtemp(prefix="vic2studio-schema-mod-"))
        self.addCleanup(shutil.rmtree, mod_root, True)
        project = Project.open(game_root, mod_root)
        self.addCleanup(project.close, discard=True)
        ws = project.ws
        index = build_index(project.vfs.snapshot(), None, {})   # catálogos de los DynamicKeys (B2)
        layout = self.schema.layout
        seen = 0
        for entry in layout.files(project.vfs):
            handle = ws.open(entry.rel)
            document = handle.model.document
            for ident, block, owner in layout.entries(document, entry.rel):
                seen += 1
                record = Record(self.schema, RecordRef(self.schema.kind, ident, entry.rel),
                                handle, block, None if handle.origin is None else handle.origin.layer.kind,
                                ws=ws, index=index, entry=owner)
                problems = record.issues()
                for code, expected in self.allowed.items():
                    self.assertEqual(sum(1 for p in problems if p.code == code), expected,
                                     f"{ident}: {code}")
                for problem in problems:
                    if problem.code in self.allowed:
                        continue
                    self.assertNotIn(problem.code, ("unknown_field", "bad_type"),
                                     f"{ident}: {problem.code} en {problem.field}")
                for key in record._index_schema()[0]:
                    record.get(key)
                for name in record._index_schema()[2]:
                    record.dynamic(name)
                self.assertFalse(ws.dirty(), f"leer {ident} ensucia el documento")
        self.assertGreater(seen, 0, "el corpus no dio registros")
        self.assertTrue(ws.save().nothing_to_save, "guardar tras leer el corpus escribe")
