"""Casus belli (``common/cb_types.txt``). Vanilla: 31, sin problemas de esquema (H17, §14.9).

El archivo empieza con ``peace_order = { … }`` (la lista no es un CB: ``SingleFile`` la salta) y sigue con un
bloque por CB. Crear un CB lo añade al **final** de ``peace_order`` (compañero ``AppendToList``) y borrarlo
lo quita. Los bloques de guion (``can_use``, ``on_add``…) se conservan y se editan como código hasta la
iteración 7. Textos: ``<cb>``, ``<cb>_desc``, ``<cb>_setup`` y ``<cb>_short`` en ``00_<P>_cb.csv``; los
``NORMAL_``/``AGRESSION_<war_name>`` los comparten varios CB y no se crean ni se borran con ninguno.
"""

from __future__ import annotations

from ..schema import (
    AppendToList,
    Bool,
    EntitySchema,
    Field,
    Float,
    Int,
    LocKey,
    LocSpec,
    Script,
    Section,
    SingleFile,
    SpriteFrame,
    issue,
    validator,
)

PEACE_OPTIONS = (
    "po_add_to_sphere", "po_annex", "po_clear_union_sphere", "po_colony", "po_demand_state", "po_destroy_forts",
    "po_destroy_naval_bases", "po_disarmament", "po_gunboat", "po_install_communist_gov_type", "po_make_puppet",
    "po_release_puppet", "po_remove_cores", "po_remove_prestige", "po_reparations", "po_status_quo",
    "po_transfer_provinces", "po_uninstall_communist_gov_type",
)

# Lo que la cabecera de cb_types.txt exige para po_remove_cores (§14.9).
_CORES_NEED = ("po_transfer_provinces", "po_demand_state", "po_annex")

_FACTORS = ("badboy_factor", "prestige_factor", "peace_cost_factor", "penalty_factor",
            "break_truce_prestige_factor", "break_truce_infamy_factor", "break_truce_militancy_factor",
            "good_relation_prestige_factor", "good_relation_infamy_factor", "good_relation_militancy_factor",
            "tws_battle_factor")


@validator("cb_remove_cores_needs_transfer", "warning")
def remove_cores_needs_transfer(rec, ctx):
    """``po_remove_cores`` sin una opción que transfiera territorio no hace nada en la paz."""
    if rec.get("po_remove_cores", False) is True and not any(rec.get(key, False) is True for key in _CORES_NEED):
        yield issue("cb_remove_cores_needs_transfer", rec, field=("po_remove_cores",))


CASUS_BELLI = EntitySchema(
    kind="casus_belli",
    layout=SingleFile("common/cb_types.txt", skip=("peace_order",)),
    provides="cb",
    symbol_attrs=lambda rec: {"sprite_index": rec.get("sprite_index", None)},
    fields=(
        Section("general", (
            Field("sprite_index", SpriteFrame("GFX_diplo_wargoal_icons"), required=True),
            Field("is_triggered_only", Bool()),
            Field("months", Int(0, unit="months")),
            Field("truce_months", Int(0, unit="months")),
            Field("war_name", LocKey()),
            Field("constructing_cb", Bool(), advanced=True),
            Field("construction_speed", Float(0), advanced=True),
            Field("crisis", Bool(), advanced=True),
            Field("mutual", Bool(), advanced=True),
            Field("great_war_obligatory", Bool(), advanced=True),
            Field("all_allowed_states", Bool(), advanced=True),
            Field("always", Bool(), advanced=True),
            Field("is_civil_war", Bool(), advanced=True),
        )),
        Section("factors", tuple(Field(key, Float(0)) for key in _FACTORS)),
        Section("peace_options", tuple(Field(key, Bool()) for key in PEACE_OPTIONS)),
        Section("conditions", (
            Script("can_use", "condition"),
            Script("is_valid", "condition"),
            Script("allowed_states", "condition"),
            Script("allowed_states_in_crisis", "condition"),
            Script("allowed_substate_regions", "condition"),
            Script("allowed_countries", "condition"),
        ), collapsed=True),
        Section("effects", (
            Script("on_add", "effect"),
            Script("on_po_accepted", "effect"),
        ), collapsed=True),
    ),
    loc=(LocSpec("{id}", "cb"), LocSpec("{id}_desc", "cb"), LocSpec("{id}_setup", "cb"),
         LocSpec("{id}_short", "cb")),
    validators=(remove_cores_needs_transfer,),
    companions=(AppendToList("common/cb_types.txt", ("peace_order",)),),
    template=lambda ident, idx: {
        "sprite_index": 1, "is_triggered_only": True, "months": 12, "truce_months": 0, "war_name": "WAR_NAME",
        "badboy_factor": 1.0, "prestige_factor": 1.0, "peace_cost_factor": 1.0, "penalty_factor": 1.0,
        "break_truce_prestige_factor": 1.0, "break_truce_infamy_factor": 1.0,
        "break_truce_militancy_factor": 1.0, "good_relation_prestige_factor": 1.0,
        "good_relation_infamy_factor": 1.0, "good_relation_militancy_factor": 1.0,
        "po_demand_state": True},
    hall="war", section="cb", order=4, icon="scroll_seal",
)

SCHEMAS = (CASUS_BELLI,)
