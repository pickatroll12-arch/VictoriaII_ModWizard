# Terrenos (`terrain`)

Categorías de terreno de map/terrain.txt (bloque «categories»). Solo se leen: dan el modo de mapa de terreno y el selector de terreno.

- **Archivos:** `map/terrain.txt`
- **Disposición:** bloques dentro de «categories» en cada archivo
- **Identificador:** la clave del bloque
- **Edición:** solo lectura (alimenta selectores y catálogos)

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `color` | color RGB { r g b } de 0 a 255 | — | no | Color en el mapa |
| `is_water` | sí o no | — | no | Es agua |
| *effects* | cualquier clave: número decimal | — | no | Efectos del terreno |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_terrain.csv (opcional)
