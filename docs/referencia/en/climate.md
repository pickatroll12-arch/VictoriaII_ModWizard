# Climates (`climate`)

Climates in map/climate.txt. Each climate has two entries with the same name: one with its effects and another with the list of its provinces.

- **Files:** `map/climate.txt`
- **Layout:** two entries with the same key per record: its values and its list
- **Identifier:** the block key
- **Editing:** read-only (feeds pickers and catalogues)

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| *effects* | any key: decimal number | — | no | Climate effects |

## Text keys

- `{id}` in localisation/00_<prefix>_regions.csv (optional)
