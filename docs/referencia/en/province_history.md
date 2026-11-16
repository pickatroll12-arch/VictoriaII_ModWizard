# Province histories (`province_history`)

Histories in history/provinces/<folder>/<id> - <Name>.txt: one file per province, whose id is the number its name starts with. Values change with the date: what is outside the dated blocks holds from the start, and each «date = …» block changes it from that day on.

- **Files:** `history/provinces/*/{id} - {name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `map:world`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `owner` | reference to tag | — | no | Owner |
| `controller` | reference to tag | — | no | Controlled by |
| `add_core` | reference to tag | — | no | Cores. Countries that claim it as their own. Added with add_core and removed with remove_core. |
| `trade_goods` | reference to goods | — | no | Goods produced |
| `life_rating` | integer from 0 to 100 | — | no | Life rating |
| `terrain` | reference to terrain | — | no | Forced terrain. Replaces the terrain that comes from terrain.bmp. Almost no province uses it. |
| `railroad` | integer from 0 to 6 | — | no | Railroad (level) |
| `fort` | integer from 0 to 6 | — | no | Fort (level) |
| `naval_base` | integer from 0 to 6 | — | no | Naval base (level) |
| `colonial` | integer from 0 to 2 | — | no | Colonial. 0: no; 1: protectorate; 2: colony. |
| `colony` | integer from 0 to 2 | — | no | Colony (old key) |
| `is_slave` | yes or no | — | no | Slave state |
| `state_building` | block state_building | — | no | state_building |
| `party_loyalty` | block party_loyalty | — | no | party_loyalty |

## Text keys

- `PROV{id}` in localisation/00_<prefix>_provinces.csv
