# Terrains (`terrain`)

Terrain categories in map/terrain.txt (the «categories» block). Read only: they feed the terrain map mode and the terrain picker.

- **Files:** `map/terrain.txt`
- **Layout:** blocks inside «categories» in each file
- **Identifier:** the block key
- **Editing:** read-only (feeds pickers and catalogues)

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `color` | RGB colour { r g b } from 0 to 255 | — | no | Colour on the map |
| `is_water` | yes or no | — | no | Is water |
| *effects* | any key: decimal number | — | no | Terrain effects |

## Text keys

- `{id}` in localisation/00_<prefix>_terrain.csv (optional)
