"""Contrato del motor de esquemas (ENCARGO_MOTOR.md, fase 1; wizard §10).

Comprueba que la API pública fija se importa con las firmas de §10, que el
ejemplo completo de §10.10 se construye, que ``vic2studio.core.schema`` no
importa Qt y que dos esquemas con el mismo ``kind`` fallan.

Los validadores del ejemplo llevan prefijo ``contract_`` para no chocar con
los códigos reales de ``core/schemas/government.py`` (el registro de
``@validator`` es global y un código repetido es un error): el ejemplo exacto
de §10.10 vive en el esquema real.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.clausewitz.diagnostics import Severity  # noqa: E402
from vic2studio.core.clausewitz.nodes import Block, Scalar  # noqa: E402
from vic2studio.core.schema import (  # noqa: E402
    MISSING,
    Bool,
    Color,
    DynamicKeys,
    Entities,
    EntityInUseError,
    EntitySchema,
    EntitySummary,
    Enum,
    Field,
    Int,
    InvalidIdentError,
    ListOf,
    LocKey,
    LocSpec,
    MappingTable,
    Path,
    Picture,
    Record,
    RecordRef,
    SchemaRegistry,
    Section,
    SingleFile,
    SpriteFrame,
    When,
    from_spec,
    issue,
    registry,
    validator,
)
from vic2studio.core.schema import validate as schema_validate  # noqa: E402

# Mismo ejemplo de wizard §10.10, a nivel de módulo (solo el prefijo ``contract_`` cambia).
@validator("contract_government_without_ideology", "error")
def at_least_one_ideology(rec, ctx):
    if not any(rec.dynamic("ideology").values()):
        yield issue("contract_government_without_ideology", rec)


@validator("contract_government_election_without_duration", "warning")
def election_needs_duration(rec, ctx):
    if rec.get("election", False) and rec.get("duration", None) is None:
        yield issue("contract_government_election_without_duration", rec, field=("duration",))


GOVERNMENT = EntitySchema(
    kind="government",
    layout=SingleFile("common/governments.txt"),
    provides="government",
    symbol_attrs=lambda rec: {
        "ideologies": tuple(k for k, v in rec.dynamic("ideology").items() if v),
        "flag_type": rec.get("flagType", None)},
    fields=(
        Section("ideologies", (DynamicKeys("ideology", "ideology", Bool(),
                                           widget="checklist", only_true=True),)),
        Section("elections", (
            Field("election", Bool(), required=True),
            Field("duration", Int(1, 600, unit="months"), visible_if=When("election", True)),
            Field("appoint_ruling_party", Bool(), required=True),
        )),
        Section("flag", (Field("flagType", Enum("monarchy", "republic", "communist", "fascist")),)),
    ),
    loc=(LocSpec("{id}", "governments"), LocSpec("{id}_ruler", "governments")),
    validators=(at_least_one_ideology, election_needs_duration),
    companions=(MappingTable("common/rebel_types.txt", table="government"),),
    template=lambda ident, idx: {"election": False, "appoint_ruling_party": True,
                                 "ideology": {"conservative": True}},
    hall="nations", section="governments", order=30, icon="crown",
)


class PublicApiTests(unittest.TestCase):
    """La API pública fija de ENCARGO_MOTOR.md importa con esos nombres."""

    def test_public_names_exist(self):
        for name in (MISSING, EntitySchema, Entities, EntitySummary, Record, RecordRef, LocSpec,
                     EntityInUseError, InvalidIdentError, registry):
            self.assertIsNotNone(name)

    def test_missing_is_a_singleton(self):
        self.assertIs(MISSING, MISSING)
        self.assertNotEqual(MISSING, None)

    def test_record_ref_and_summary_shapes(self):
        ref = RecordRef("government", "junta")
        self.assertEqual((ref.kind, ref.ident, ref.rel), ("government", "junta", None))
        summary = EntitySummary(ref, Path("common/governments.txt"))
        self.assertIs(summary.ref, ref)

    def test_unimplemented_contract_raises(self):
        """Las piezas que la iteración 4 no necesita siguen lanzando NotImplementedError, no falsos
        resultados (historia fechada y guion, iteraciones 5–7).

        Iteración 4 (cierre): los hijos, los tipos ricos y ``from_spec`` ya tienen lógica, así que esta
        prueba deja de exigirles NotImplementedError y comprueba en cambio que rechazan lo que no encaja
        con ``ValueError`` (sin falsos resultados)."""
        record = Record.__new__(Record)
        record.schema = EntitySchema(kind="x", layout=SingleFile("y.txt"), fields=())
        record.block = Block()
        for call in (lambda: record.script("trigger"), lambda: record.at(None)):
            with self.assertRaises(NotImplementedError):
                call()
        self.assertEqual(record.children(), [], "sin Children, ningún hijo")
        for value_type in (Color(), ListOf(Int())):
            with self.assertRaises(ValueError):
                value_type.read(Scalar("x"))
        with self.assertRaises(ValueError):
            Path("history").read(Scalar("x"))
        self.assertEqual(LocKey().read(Scalar("x")), "x")
        self.assertEqual(SpriteFrame("s").read(Scalar("3")), 3)
        self.assertEqual(Picture("events").read(Scalar("x")), "x")
        self.assertEqual(from_spec({"type": "int"}), Int())
        with self.assertRaises(ValueError):
            from_spec({"type": "nope"})


class ExampleBuildsTests(unittest.TestCase):
    """El ejemplo completo de §10.10 se construye con esta API."""

    def test_example_of_1010_builds(self):
        self.assertEqual(GOVERNMENT.kind, "government")
        self.assertIsInstance(GOVERNMENT.layout, SingleFile)
        self.assertEqual(GOVERNMENT.layout.path, "common/governments.txt")
        self.assertEqual(len(GOVERNMENT.fields), 3)
        ideologies = GOVERNMENT.fields[0]
        self.assertIsInstance(ideologies, Section)
        dynamic = ideologies.items[0]
        self.assertIsInstance(dynamic, DynamicKeys)
        self.assertTrue(dynamic.only_true)
        self.assertEqual(GOVERNMENT.loc[1].template, "{id}_ruler")
        self.assertEqual(len(GOVERNMENT.validators), 2)
        self.assertEqual(len(GOVERNMENT.companions), 1)
        template = GOVERNMENT.template("junta", None)
        self.assertEqual(template["appoint_ruling_party"], True)

    def test_duplicate_kind_fails(self):
        def twin():
            return EntitySchema(kind="twin", layout=SingleFile("common/x.txt"), fields=())

        fresh = SchemaRegistry()
        fresh.register([twin()])
        with self.assertRaises(ValueError):
            fresh.register([twin()])

    def test_registry_get_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            registry.get("no_existe")

    def test_schema_imports_without_qt(self):
        script = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import vic2studio.core.schema\n"
            "loaded = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6'))\n"
            "print(loaded)\n"
            "sys.exit(1 if loaded else 0)\n"
        )
        done = subprocess.run([sys.executable, "-c", script, str(PROJECT_ROOT / "src")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_validator_registry_records_severity(self):
        self.assertIn("contract_government_without_ideology", schema_validate.VALIDATORS)
        self.assertEqual(schema_validate.VALIDATORS["contract_government_without_ideology"],
                         Severity.ERROR)
        self.assertEqual(schema_validate.VALIDATORS["contract_government_election_without_duration"],
                         Severity.WARNING)

    def test_duplicate_validator_code_fails(self):
        with self.assertRaises(ValueError):
            @validator("contract_government_without_ideology", "error")
            def _repetido(rec, ctx):  # pragma: no cover - nunca se llama
                yield issue("contract_government_without_ideology", rec)


if __name__ == "__main__":
    unittest.main()
