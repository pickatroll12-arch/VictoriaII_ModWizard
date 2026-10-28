# Culture groups (`culture_group`)

Groups in common/cultures.txt: graphical leader, units, union and whether it is overseas. They contain the cultures.

- **Files:** `common/cultures.txt`
- **Layout:** groups at the root of the file
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `leader` | one of: european, southamerican, russian, arab, asian, indian, nativeamerican, african, polar_bear | — | yes | Leader portraits |
| `unit` | reference to graphical_culture | — | no | Unit graphics |
| `union` | reference to tag | — | no | Union country |
| `is_overseas` | yes or no | — | no | Overseas |
| *culture* | child blocks: culture | — | no | Cultures |

## Text keys

- `{id}` in localisation/00_<prefix>_cultures.csv

## Minimal example

```text
my_culture_group = {
	leader = european
}
```
