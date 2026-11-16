# Continents (`continent`)

Continents in map/continent.txt: the province list goes in «provinces» and the rest of the block is its effects. Every land province must be in one.

- **Files:** `map/continent.txt`
- **Layout:** one file with a block per record
- **Identifier:** the block key
- **Editing:** read-only (feeds pickers and catalogues)

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `provinces` | list of: integer | — | yes | Provinces of the continent |
| *effects* | any key: decimal number | — | no | Continent effects |

## Text keys

- `{id}` in localisation/00_<prefix>_regions.csv
