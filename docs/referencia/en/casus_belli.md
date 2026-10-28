# Casus belli (`casus_belli`)

War justifications in common/cb_types.txt. Creating one appends it to peace_order; deleting it removes it. Script blocks are edited as code until iteration 7.

- **Files:** `common/cb_types.txt`
- **Layout:** one file with a block per record
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `war:cb`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `sprite_index` | frame of GFX_diplo_wargoal_icons | — | yes | Icon. Frame of GFX_diplo_wargoal_icons. |
| `is_triggered_only` | yes or no | — | no | Triggered only. Whether it is only granted by an effect, not fabricated. |
| `months` | integer (months) | — | no | Months valid. How long the CB lasts once acquired. |
| `truce_months` | integer (months) | — | no | Truce months |
| `war_name` | text key (localisation) | — | no | War name. Base of the NORMAL_ and AGRESSION_ keys, shared by several CBs. |
| `constructing_cb` | yes or no | — | no | Can be fabricated |
| `construction_speed` | decimal number | — | no | Fabrication speed |
| `crisis` | yes or no | — | no | Valid in crises |
| `mutual` | yes or no | — | no | Mutual |
| `great_war_obligatory` | yes or no | — | no | Great War obligatory |
| `all_allowed_states` | yes or no | — | no | All allowed states |
| `always` | yes or no | — | no | Always available |
| `is_civil_war` | yes or no | — | no | Civil war |
| `badboy_factor` | decimal number | — | no | Infamy factor |
| `prestige_factor` | decimal number | — | no | Prestige factor |
| `peace_cost_factor` | decimal number | — | no | Peace cost factor |
| `penalty_factor` | decimal number | — | no | Penalty factor |
| `break_truce_prestige_factor` | decimal number | — | no | Breaking truce: prestige |
| `break_truce_infamy_factor` | decimal number | — | no | Breaking truce: infamy |
| `break_truce_militancy_factor` | decimal number | — | no | Breaking truce: militancy |
| `good_relation_prestige_factor` | decimal number | — | no | Good relations: prestige |
| `good_relation_infamy_factor` | decimal number | — | no | Good relations: infamy |
| `good_relation_militancy_factor` | decimal number | — | no | Good relations: militancy |
| `tws_battle_factor` | decimal number | — | no | Battle factor (war score) |
| `po_add_to_sphere` | yes or no | — | no | Add to sphere |
| `po_annex` | yes or no | — | no | Annex |
| `po_clear_union_sphere` | yes or no | — | no | Clear union sphere |
| `po_colony` | yes or no | — | no | Colony |
| `po_demand_state` | yes or no | — | no | Demand a state |
| `po_destroy_forts` | yes or no | — | no | Destroy forts |
| `po_destroy_naval_bases` | yes or no | — | no | Destroy naval bases |
| `po_disarmament` | yes or no | — | no | Disarmament |
| `po_gunboat` | yes or no | — | no | Gunboat diplomacy |
| `po_install_communist_gov_type` | yes or no | — | no | Install communist government |
| `po_make_puppet` | yes or no | — | no | Make puppet |
| `po_release_puppet` | yes or no | — | no | Release puppet |
| `po_remove_cores` | yes or no | — | no | Remove cores |
| `po_remove_prestige` | yes or no | — | no | Remove prestige |
| `po_reparations` | yes or no | — | no | Reparations |
| `po_status_quo` | yes or no | — | no | Status quo |
| `po_transfer_provinces` | yes or no | — | no | Transfer provinces |
| `po_uninstall_communist_gov_type` | yes or no | — | no | Uninstall communist government |
| `can_use` | script block (edited as code) | — | no | Can be used if |
| `is_valid` | script block (edited as code) | — | no | Is valid if |
| `allowed_states` | script block (edited as code) | — | no | Allowed states |
| `allowed_states_in_crisis` | script block (edited as code) | — | no | Allowed states in crises |
| `allowed_substate_regions` | script block (edited as code) | — | no | Allowed substate regions |
| `allowed_countries` | script block (edited as code) | — | no | Allowed countries |
| `on_add` | script block (edited as code) | — | no | On acquiring |
| `on_po_accepted` | script block (edited as code) | — | no | On peace accepted |

## Text keys

- `{id}` in localisation/00_<prefix>_cb.csv
- `{id}_desc` in localisation/00_<prefix>_cb.csv
- `{id}_setup` in localisation/00_<prefix>_cb.csv
- `{id}_short` in localisation/00_<prefix>_cb.csv

## Companions

- Kept in the «peace_order» list of common/cb_types.txt.

## Own checks

- `cb_remove_cores_needs_transfer`: Why removing cores is not enough on its own

## Minimal example

```text
my_casus_belli = {
	sprite_index = 1
	is_triggered_only = yes
	months = 12
	truce_months = 0
	war_name = "WAR_NAME"
	badboy_factor = 1
	prestige_factor = 1
	peace_cost_factor = 1
	penalty_factor = 1
	break_truce_prestige_factor = 1
	break_truce_infamy_factor = 1
	break_truce_militancy_factor = 1
	good_relation_prestige_factor = 1
	good_relation_infamy_factor = 1
	good_relation_militancy_factor = 1
	po_demand_state = yes
}
```
