"""Formas de gobierno (``common/governments.txt``). Vanilla: 8, sin problemas (H16).

El bloque declara las ideologías que admite como claves ``<ideología> = yes`` en la raíz, las
elecciones (``election``, ``duration`` si las hay), ``appoint_ruling_party`` y ``flagType``;
sin ``flagType`` el juego usa ``TAG.tga`` (``democracy``). ``rebel_types.txt`` lleva 14 tablas
``government = { <gob> = <gob destino> }``: el compañero ``MappingTable`` las mantiene.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    DynamicKeys,
    EntitySchema,
    Enum,
    Field,
    Int,
    LocSpec,
    MappingTable,
    Section,
    SingleFile,
    When,
    issue,
    validator,
)


@validator("government_without_ideology", "error")
def at_least_one_ideology(rec, ctx):
    """Sin ideologías, ningún partido puede gobernar con esta forma de gobierno (H16)."""
    if not any(rec.dynamic("ideology").values()):
        yield issue("government_without_ideology", rec)


@validator("government_election_without_duration", "warning")
def election_needs_duration(rec, ctx):
    """Caso real: ``absolute_monarchy`` del mod del usuario con ``election = yes`` y sin
    ``duration`` (H14). El código y sus textos ya existen en ``core/validate``."""
    if rec.get("election", False) and rec.get("duration", None) is None:
        yield issue("government_election_without_duration", rec, field=("duration",))


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
        Section("flag", (Field("flagType", Enum("monarchy", "republic", "communist",
                                                "fascist")),)),
    ),
    loc=(LocSpec("{id}", "governments"), LocSpec("{id}_ruler", "governments")),
    validators=(at_least_one_ideology, election_needs_duration),
    companions=(MappingTable("common/rebel_types.txt", table="government"),),
    template=lambda ident, idx: {"election": False, "appoint_ruling_party": True,
                                 "ideology": {"conservative": True}},
    hall="nations", section="governments", order=30, icon="crown",
)

SCHEMAS = (GOVERNMENT,)
