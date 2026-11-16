# Map settings (`default_map`)

map/default.map: the maximum number of provinces, the list of sea provinces (sea_starts) and the names of the map files. It is a single record.

- **Files:** `map/default.map`
- **Layout:** the whole file is a single record
- **Identifier:** fixed: «default_map» (a single record)
- **Editing:** read-only (feeds pickers and catalogues)

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `max_provinces` | integer | — | yes | Maximum provinces. A province id is valid if it is greater than 0 and lower than this number. |
| `sea_starts` | list of: integer | — | yes | Sea provinces |
| `definitions` | text | — | no | Province table |
| `provinces` | text | — | no | Province image |
| `positions` | text | — | no | Positions |
| `terrain` | text | — | no | Terrain image |
| `rivers` | text | — | no | River image |
| `terrain_definition` | text | — | no | Terrain definition |
| `tree_definition` | text | — | no | Tree definition |
| `continent` | text | — | no | Continent file |
| `adjacencies` | text | — | no | Straits file |
| `region` | text | — | no | Region file |
| `region_sea` | text | — | no | Sea region file |
| `province_flag_sprite` | text | — | no | Province flag sprite |

## Text keys

This schema creates no text keys.
