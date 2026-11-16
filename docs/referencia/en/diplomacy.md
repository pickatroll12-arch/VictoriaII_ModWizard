# Starting diplomacy (`diplomacy`)

history/diplomacy/*.txt: alliances, vassals, substates, unions and guarantees, each with first, second, start_date and end_date.

- **Files:** `history/diplomacy/*/{name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `war:diplomacy`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `alliance` | block alliance | — | no | alliance |
| `vassal` | block vassal | — | no | vassal |
| `substate` | block substate | — | no | substate |
| `union` | block union | — | no | union |
| `guarantee` | block guarantee | — | no | guarantee |

## Text keys

This schema creates no text keys.
