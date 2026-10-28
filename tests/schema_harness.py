"""Arnés de esquemas (wizard §19.3): las pruebas que genera ``SchemaContract``.

Una subclase de tres líneas (``schema``, ``corpus`` y ``allowed``) prueba un esquema entero:
paridad de sus textos, abrir y guardar sin cambios, ``set`` de cada campo con su ``example``,
claves dinámicas, plantilla válida, claves de localización, compañeros, colocación y
conformidad con el corpus (0 ``unknown_field`` y 0 ``bad_type``). Las pruebas usan el
minijuego sintético y, la de corpus, ``vanilla_root()`` (se omite sin corpus).

``test_docgen`` de §19.3 no se genera: ``docgen`` queda fuera de la lista de archivos del
corte (se pide a Claude en el informe).
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
    CheckContext,
    Entities,
    Field,
    SingleFile,
)
from vic2studio.core.schema.fields import (  # noqa: E402
    DynamicKeys,
    Group,
    Section,
    field_text_key,
)
from vic2studio.core.schema.record import Record, RecordRef  # noqa: E402
from vic2studio.core.texts import load_texts  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _corpus import vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402


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
        game = build_minigame(mod=True)
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
                with self.subTest(record=summary.ref.ident, dynamic=spec.name):
                    before = record.dynamic(spec.name)
                    value_type = spec.value("test_dynamic_key") if callable(spec.value) else spec.value
                    example = value_type.example(self._ctx())
                    with ws.transaction("test.undo_edit", key=spec.name, ident=summary.ref.ident):
                        record.set_dynamic(spec.name, "test_dynamic_key", example)
                    self.assertIn("test_dynamic_key", record.dynamic(spec.name),
                                  f"set_dynamic de {spec.name} no aparece")
                    if spec.only_true:
                        with ws.transaction("test.undo_edit", key=spec.name, ident=summary.ref.ident):
                            record.set_dynamic(spec.name, "test_dynamic_key", False)
                        self.assertNotIn("test_dynamic_key", record.dynamic(spec.name),
                                         f"only_true no borra la clave falsa de {spec.name}")
                        ws.undo()
                    ws.undo()
                    record = self.entities.open(summary.ref)   # deshacer reemplaza el modelo
                    self.assertEqual(record.dynamic(spec.name), before)

    def test_template_validates(self):
        values = dict(self.schema.template("test_created", self.entities.index)) \
            if self.schema.template is not None else {"type": "land"}
        ref = self.entities.create(self.schema.kind, "test_created", values)
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

    def test_companions(self):
        if not self.schema.companions:
            return
        self.entities.create(self.schema.kind, "test_companion",
                             dict(self.schema.template("test_companion", self.entities.index)))
        handle = self.project.ws.open("common/rebel_types.txt")
        document = handle.model.document
        tables = []

        def walk(block):
            for entry in block.entries:
                if entry.key is not None and entry.key.text == "government" \
                        and hasattr(entry.value, "entries"):
                    tables.append(entry.value)
                if hasattr(entry.value, "entries"):
                    walk(entry.value)

        walk(document)
        self.assertTrue(tables, "el minijuego tiene tablas de rebeldes")
        for table in tables:
            self.assertIsNotNone(table.find("test_companion"),
                                 "el compañero no añadió la clave a todas las tablas")
        self.project.ws.undo()
        self.assertEqual(self.project.ws.dirty(), [], "el deshacer no quita la creación")

    def test_placement(self):
        ref = self.entities.create(self.schema.kind, "test_placed",
                                   dict(self.schema.template("test_placed", self.entities.index))
                                   if self.schema.template is not None else {"type": "land"})
        if isinstance(self.schema.layout, SingleFile):
            handle = self.project.ws.open(self.schema.layout.path)
            document = handle.model.document
            self.assertEqual(document.entries[-1].key.text, "test_placed",
                             "lo nuevo no queda al final del archivo")
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
        layout = self.schema.layout
        seen = 0
        for entry in layout.files(project.vfs):
            handle = ws.open(entry.rel)
            document = handle.model.document
            for ident, block, owner in layout.entries(document, entry.rel):
                seen += 1
                record = Record(self.schema, RecordRef(self.schema.kind, ident, entry.rel),
                                handle, block, None if handle.origin is None else handle.origin.layer.kind,
                                ws=ws, entry=owner)
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
