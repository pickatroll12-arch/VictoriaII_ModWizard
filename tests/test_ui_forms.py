"""Formularios generados (wizard §13.6, §19.5; ENCARGO_IT4 fases 2 y 3).

Para **cada esquema editable registrado**: se construye su formulario sobre un registro del minijuego, se pone un
valor en cada editor (como el usuario: el editor confirma) y se comprueba el cambio en el registro; además, la
paridad ES/EN de sus textos y la pseudolocalización. También: una edición es una transacción con ``merge_key`` por
campo (teclear dos veces en el mismo campo es un solo paso de deshacer), los campos avanzados, ``visible_if`` y
las variantes, y que un valor que no encaja no ensucia nada.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402
from test_ui_entity import EntityWindowCase  # noqa: E402
from test_ui_smoke import MARK_OPEN, PSEUDO, collect_texts, pseudo_catalog  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.core.schema import RecordRef, registry  # noqa: E402
from vic2studio.core.schema.fields import Field  # noqa: E402
from vic2studio.i18n import set_language, translator  # noqa: E402
from vic2studio.ui.forms import (  # noqa: E402
    ADVANCED,
    EDITORS,
    SIMPLE,
    DynamicChecklist,
    DynamicTable,
    EntityForm,
    FieldEditor,
    FormBuilder,
    TriStateCheck,
    editor_for,
)
from vic2studio.ui.pickers import GoodsAmountsField  # noqa: E402

# Un valor distinto del que trae el minijuego para cada tipo de editor.
EXAMPLES = {"int": 7, "float": 2.5, "bool": True, "date": ClausewitzDate(1840, 2, 3), "word": "NewWord",
            "text": "New text", "enum": None, "ref": None, "color": (11, 22, 33), "list": ["Ana", "Luis Mar"],
            "path": "new.txt", "lockey": "NEW_KEY", "sprite": 4, "picture": "new_picture"}


def example_for(field: Field, session, current=None):
    """Un valor válido y distinto de ``current`` (si no, la edición no cambiaría nada)."""
    widget = field.type.widget
    if widget == "enum":
        return next((v for v in reversed(field.type.values) if v != current), None)
    if widget == "ref":
        names = sorted(session.index.names(field.type.kind))
        return next((n for n in reversed(names) if n != current), None)
    if widget == "bool":
        return not current if isinstance(current, bool) else True
    value = EXAMPLES[widget]
    return value if value != current else None


class ContractTests(unittest.TestCase):
    """Fase 2: las firmas del contrato de la interfaz se construyen."""

    def test_every_value_type_widget_has_an_editor(self):
        widgets = {"int", "float", "bool", "date", "word", "text", "enum", "ref", "color", "list", "path", "lockey",
                   "sprite", "picture"}
        self.assertEqual(set(EDITORS), widgets)
        for schema in registry.all_schemas():
            for field in _fields(schema):
                self.assertIn(field.type.widget, EDITORS, f"{schema.kind}.{field.key}")

    def test_editors_construct_without_a_project(self):
        from vic2studio.core.schema import Bool, Color, Date, Enum, Float, Int, ListOf, LocKey, Text

        for value_type in (Int(0, 10), Float(), Bool(), Date(), Text(), Enum("a", "b"), Color(), ListOf(Text()),
                           LocKey()):
            editor = editor_for(value_type, kind="unit", key="attack")
            self.assertIsInstance(editor, FieldEditor)
            editor.set_value(None)
            self.assertIsNone(editor.value())
            editor.deleteLater()


def _fields(schema):
    from vic2studio.core.schema.fields import Section

    found = []

    def walk(items):
        for item in items:
            if isinstance(item, Section):
                walk(item.items)
            elif isinstance(item, Field):
                found.append(item)

    walk(schema.fields)
    if schema.variants is not None:
        for items in schema.variants.cases.values():
            walk(items)
    return found


class EverySchemaFormTests(EntityWindowCase):
    def first_ref(self, schema):
        summaries = self.window.session.entities.list(schema.kind)
        self.assertTrue(summaries, schema.kind)
        return summaries[0].ref

    def test_each_editor_changes_its_record(self):
        window = self.open_window()
        session = window.session
        editable = [schema for schema in registry.all_schemas() if schema.editable]
        self.assertGreaterEqual(len(editable), 6)
        for schema in editable:
            ref = self.first_ref(schema)
            form = FormBuilder(session, mode=ADVANCED).build(schema, ref)
            self.addCleanup(form.deleteLater)
            record = session.entities.open(ref)
            variant = record._variant_value()
            for row in form.rows:
                item = row.item
                if not isinstance(item, Field) or row.variant not in (None, variant):
                    continue
                if schema.variants is not None and item.key == schema.variants.field:
                    continue   # cambiar el discriminador cambia los campos visibles: tiene su propia prueba
                if item.key == schema.id_field:
                    self.assertFalse(row.editor.isEnabled(), "el id no se cambia en el formulario")
                    continue
                current = session.entities.open(ref).get(item.key, None)
                value = example_for(item, session, current)
                if value is None:
                    continue
                with self.subTest(schema=schema.kind, field=item.key):
                    steps = len(session.history())
                    row.editor._commit(value)
                    reread = session.entities.open(ref)
                    got = reread.get(item.key)
                    self.assertEqual(got, value, "el editor no llegó al registro")
                    self.assertEqual(len(session.history()), steps + 1, "una transacción por edición")
                    self.assertEqual(session.history()[0][0], "forms.undo_edit")
                    window.undo()
                    self.assertNotEqual(session.entities.open(ref).get(item.key, None), value)

    def test_dynamic_editors(self):
        window = self.open_window()
        session = window.session
        # Casillas de ideologías (only_true): marcar añade «= yes», desmarcar la quita.
        form = FormBuilder(session).build(registry.get("government"), RecordRef("government", "council"))
        self.addCleanup(form.deleteLater)
        checklist = form.editor("ideology")
        self.assertIsInstance(checklist, DynamicChecklist)
        self.assertEqual(sorted(checklist.checks), ["conservative", "liberal", "socialist"])
        checklist.checks["liberal"].setChecked(True)
        self.assertEqual(session.entities.open(RecordRef("government", "council")).dynamic("ideology"),
                         {"socialist": True, "liberal": True})
        checklist.checks["socialist"].setChecked(False)
        self.assertEqual(session.entities.open(RecordRef("government", "council")).dynamic("ideology"),
                         {"liberal": True})
        self.assertNotIn("socialist = no", self.text_of("common/governments.txt"))
        # Tabla de bienes de una unidad.
        form = FormBuilder(session).build(registry.get("unit"), RecordRef("unit", "infantry"))
        self.addCleanup(form.deleteLater)
        goods = form.editor("build_cost")
        self.assertIsInstance(goods, GoodsAmountsField)
        goods.good_combo.setCurrentIndex(goods.good_combo.findData("fish"))
        goods.add_button.click()
        self.assertEqual(session.entities.open(RecordRef("unit", "infantry")).dynamic("build_cost"), {"fish": 1.0})
        goods.table.item(0, 1).setText("3")
        self.assertEqual(session.entities.open(RecordRef("unit", "infantry")).dynamic("build_cost"), {"fish": 3.0})
        goods.table.setCurrentCell(0, 0)
        goods.remove_button.click()
        self.assertEqual(session.entities.open(RecordRef("unit", "infantry")).dynamic("build_cost"), {})
        # Catálogo abierto: efectos de un modificador.
        form = FormBuilder(session).build(registry.get("event_modifier"), RecordRef("event_modifier", "good_harvest"))
        self.addCleanup(form.deleteLater)
        table = form.editor("effects")
        self.assertIsInstance(table, DynamicTable)
        table.key_edit.setText("prestige")
        table.add_button.click()
        table.table.item(1, 1).setText("2")
        self.assertEqual(session.entities.open(RecordRef("event_modifier", "good_harvest")).dynamic("effects"),
                         {"farm_rgo_eff": 0.1, "prestige": 2.0})

    def test_typing_in_the_same_field_is_one_undo_step(self):
        window = self.open_window()
        session = window.session
        form = FormBuilder(session).build(registry.get("casus_belli"), RecordRef("casus_belli", "free_people"))
        self.addCleanup(form.deleteLater)
        editor = form.editor("months")
        for text in ("1", "18", "24"):
            editor.edit.setText(text)
            editor.edit.editingFinished.emit()
        self.assertEqual(len(session.history()), 1, "las tres pausas del mismo campo son un paso")
        self.assertIn("months = 24", self.text_of("common/cb_types.txt"))
        form.editor("truce_months").edit.setText("2")
        form.editor("truce_months").edit.editingFinished.emit()
        self.assertEqual(len(session.history()), 2, "otro campo, otro paso")
        window.undo()
        window.undo()
        self.assertEqual(session.dirty_count(), 0)

    def test_bad_value_changes_nothing_and_says_why(self):
        window = self.open_window()
        session = window.session
        form = FormBuilder(session).build(registry.get("culture"), RecordRef("culture", "alander"))
        self.addCleanup(form.deleteLater)
        statuses = []
        form.status_requested.connect(lambda key, fmt: statuses.append(key))
        form.editor("color")._commit((1, 2, 999))
        self.assertEqual(statuses, ["forms.edit_failed"])
        self.assertEqual(session.history(), [])
        self.assertEqual(session.dirty_count(), 0)
        self.assertEqual(form.editor("color").value(), (100, 20, 20), "el formulario vuelve al valor del registro")

    def test_advanced_visible_if_and_variants(self):
        window = self.open_window()
        session = window.session
        form = FormBuilder(session).build(registry.get("casus_belli"), RecordRef("casus_belli", "free_people"))
        self.addCleanup(form.deleteLater)
        self.assertTrue(form.editor("crisis").isHidden(), "avanzado: oculto en modo sencillo")
        self.assertTrue(form.focus_field(("crisis",)))
        self.assertEqual(form.mode, ADVANCED)
        self.assertFalse(form.editor("crisis").isHidden())
        form.set_mode(SIMPLE)
        government = FormBuilder(session).build(registry.get("government"), RecordRef("government", "monarchy"))
        self.addCleanup(government.deleteLater)
        self.assertTrue(government.editor("duration").isHidden(), "sin elecciones no hay duración")
        government.editor("election")._commit(True)
        self.assertFalse(government.editor("duration").isHidden())
        unit = FormBuilder(session).build(registry.get("unit"), RecordRef("unit", "infantry"))
        self.addCleanup(unit.deleteLater)
        self.assertFalse(unit.editor("attack").isHidden())
        self.assertTrue(unit.row("hull").card.isHidden(), "la tarjeta naval no se ve en una terrestre")
        unit.bind(RecordRef("unit", "frigate"))
        self.assertTrue(unit.row("attack").card.isHidden())
        self.assertFalse(unit.row("hull").card.isHidden())

    def test_bool_shows_the_game_default(self):
        editor = TriStateCheck(registry.get("unit").fields[0].items[3].type, kind="unit", key="active")
        self.addCleanup(editor.deleteLater)
        editor.set_value(None)
        self.assertIsNone(editor.value())
        editor.set_default(True)
        self.assertIn("Sí", editor.check.text())


class FormTranslationTests(EntityWindowCase):
    def test_every_form_in_es_en_and_pseudo(self):
        window = self.open_window()
        session = window.session
        translator().register_catalog(PSEUDO, pseudo_catalog())
        for schema in (s for s in registry.all_schemas() if s.editable):
            summaries = session.entities.list(schema.kind)
            form = EntityForm(session, schema, mode=ADVANCED)
            self.addCleanup(form.deleteLater)
            form.bind(summaries[0].ref)
            with self.subTest(schema=schema.kind):
                set_language("es")
                spanish = collect_texts(form)
                set_language("en")
                english = collect_texts(form)
                self.assertEqual(spanish.keys(), english.keys())
                self.assertFalse([v for v in english.values() if v.startswith("schema.")], "claves crudas")
                set_language(PSEUDO)
                untranslated = {k: v for k, v in collect_texts(form).items() if MARK_OPEN not in v}
                self.assertEqual(untranslated, {})
                set_language("es")


if __name__ == "__main__":
    unittest.main()
