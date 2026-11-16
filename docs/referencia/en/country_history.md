# Country histories (`country_history`)

history/countries/<TAG> - <Name>.txt: the state of the country on each date. What is outside the dated blocks holds from the start and each "date = …" block changes it from that day.

- **Files:** `history/countries/*/{id} - {name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `nations:countries`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `capital` | reference to province | — | no | Capital |
| `primary_culture` | reference to culture | — | no | Primary culture |
| `culture` | reference to culture | — | no | Accepted cultures |
| `religion` | reference to religion | — | no | Religion |
| `civilized` | yes or no | — | no | Civilised |
| `government` | reference to government | — | no | Government |
| `ruling_party` | word | — | no | Ruling party |
| `last_election` | date (year.month.day) | — | no | Last election |
| `plurality` | decimal number | — | no | Plurality |
| `prestige` | decimal number | — | no | Prestige |
| `nationalvalue` | reference to national_value | — | no | National value |
| *upper_house* | keys from the «ideology» catalogue: decimal number | — | no | Upper house |
| `literacy` | decimal number | — | no | Literacy. From 0 to 1 (0.8 is 80%). |
| `non_state_culture_literacy` | decimal number | — | no | Literacy of non-accepted cultures |
| `consciousness` | decimal number | — | no | Consciousness |
| `nonstate_consciousness` | decimal number | — | no | Colonial consciousness |
| `schools` | reference to tech_school | — | no | Technology school |
| `oob` | text | — | no | Order of battle. File in history/units with its armies, fleets and leaders. |
| *technology* | keys from the «technology» catalogue: integer from 0 to 1 | — | no | Known technologies |

## Text keys

This schema creates no text keys.
