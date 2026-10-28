# Units (`unit`)

Land and naval units in units/<id>.txt, one type per file. The «type» variant decides the combat fields. They are activated with activate_unit in technologies and inventions.

- **Files:** `units/{id}.txt`
- **Layout:** one file per record
- **Identifier:** the file name
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `war:units`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `icon` | integer | — | no | Icon |
| `type` | one of: land, naval | — | no | Type. Land or naval: decides which fields are shown. |
| `sprite` | word | — | no | Sprite |
| `active` | yes or no | — | no | Active |
| `unit_type` | one of: infantry, cavalry, support, special, big_ship, light_ship, transport | — | no | Category |
| `floating_flag` | yes or no | — | no | Floating flag |
| `priority` | integer | — | no | Priority |
| `max_strength` | integer | — | no | Max strength |
| `default_organisation` | integer | — | no | Default organisation |
| `maximum_speed` | decimal number | — | no | Maximum speed |
| `weighted_value` | decimal number | — | no | Weighted value |
| `build_time` | integer | — | no | Build time |
| `build_cost` | block build_cost · keys from the «goods» catalogue: decimal number | — | no | Build cost |
| `supply_consumption` | decimal number | — | no | Supply consumption |
| `supply_cost` | block supply_cost · keys from the «goods» catalogue: decimal number | — | no | Supply cost |

### Fields when «type» = land

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `sprite_override` | word | — | no | Sprite override |
| `sprite_mount` | word | — | no | Sprite mount |
| `sprite_mount_attach_node` | word | — | no | Mount attach node |
| `primary_culture` | yes or no | — | no | Primary culture only |
| `reconnaissance` | integer | — | no | Reconnaissance |
| `attack` | decimal number | — | no | Attack |
| `defence` | integer | — | no | Defence |
| `discipline` | decimal number | — | no | Discipline |
| `support` | decimal number | — | no | Support |
| `maneuver` | integer | — | no | Manoeuvre |
| `siege` | integer | — | no | Siege |

### Fields when «type» = naval

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `naval_icon` | integer | — | no | Naval icon |
| `sail` | yes or no | — | no | Sail |
| `capital` | yes or no | — | no | Capital ship |
| `colonial_points` | integer | — | no | Colonial points |
| `can_build_overseas` | yes or no | — | no | Buildable overseas |
| `min_port_level` | integer | — | no | Minimum port level |
| `limit_per_port` | integer | — | no | Limit per port |
| `supply_consumption_score` | integer | — | no | Supply consumption score |
| `hull` | integer | — | no | Hull |
| `gun_power` | integer | — | no | Gun power |
| `fire_range` | decimal number | — | no | Fire range |
| `evasion` | decimal number | — | no | Evasion |
| `torpedo_attack` | integer | — | no | Torpedo attack |
| `transport` | yes or no | — | no | Transport |
| `move_sound` | word | — | no | Move sound |
| `select_sound` | word | — | no | Select sound |

## Views

- `war:land`: Land units
- `war:naval`: Naval units

## Text keys

- `{id}` in localisation/00_<prefix>_units.csv
- `{id}_short` in localisation/00_<prefix>_units.csv

## Companions

- Shows which technology or invention activates it (activate_unit).
- When a naval unit is created, offers its name list in the countries (unit_names).

## Minimal example

```text
my_unit = {
	type = land
	active = yes
	unit_type = infantry
	priority = 1
	max_strength = 3
	default_organisation = 30
	maximum_speed = 4
	build_time = 90
	attack = 2
	defence = 2
}
```
