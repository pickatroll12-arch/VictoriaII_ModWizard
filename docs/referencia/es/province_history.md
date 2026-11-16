# Historias de provincia (`province_history`)

Historias de history/provinces/<carpeta>/<id> - <Nombre>.txt: un archivo por provincia, cuyo id es el número con que empieza el nombre. Los valores cambian con la fecha: lo de fuera de los bloques fechados vale desde el inicio y cada bloque «fecha = …» lo cambia desde ese día.

- **Archivos:** `history/provinces/*/{id} - {name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `map:world`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `owner` | referencia a tag | — | no | Dueño |
| `controller` | referencia a tag | — | no | Quien la controla |
| `add_core` | referencia a tag | — | no | Núcleos. Países que la reclaman como propia. Se añaden con add_core y se quitan con remove_core. |
| `trade_goods` | referencia a goods | — | no | Bien que produce |
| `life_rating` | entero de 0 a 100 | — | no | Habitabilidad |
| `terrain` | referencia a terrain | — | no | Terreno forzado. Sustituye al terreno que sale de terrain.bmp. Casi ninguna provincia lo usa. |
| `railroad` | entero de 0 a 6 | — | no | Ferrocarril (nivel) |
| `fort` | entero de 0 a 6 | — | no | Fuerte (nivel) |
| `naval_base` | entero de 0 a 6 | — | no | Base naval (nivel) |
| `colonial` | entero de 0 a 2 | — | no | Colonial. 0: no; 1: protectorado; 2: colonia. |
| `colony` | entero de 0 a 2 | — | no | Colonia (clave antigua) |
| `is_slave` | sí o no | — | no | Estado esclavista |
| `state_building` | bloque state_building | — | no | state_building |
| `party_loyalty` | bloque party_loyalty | — | no | party_loyalty |

## Claves de texto

- `PROV{id}` en localisation/00_<prefijo>_provinces.csv
