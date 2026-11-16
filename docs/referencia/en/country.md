# Country files (`country`)

common/countries/<File>.txt: map colour, graphical culture, parties and unit names. The id is the file name, as countries.txt writes it.

- **Files:** `common/countries/*/{name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `nations:countries`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `color` | RGB colour { r g b } from 0 to 255 | — | yes | Map colour |
| `graphical_culture` | reference to graphical_culture | — | yes | Graphical culture |
| `party` | block party | — | no | party |

## Text keys

This schema creates no text keys.
