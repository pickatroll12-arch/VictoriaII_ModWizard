# Continentes (`continent`)

Continentes de map/continent.txt: la lista de provincias va en «provinces» y el resto del bloque son sus efectos. Toda provincia de tierra debe estar en uno.

- **Archivos:** `map/continent.txt`
- **Disposición:** un archivo con un bloque por registro
- **Identificador:** la clave del bloque
- **Edición:** solo lectura (alimenta selectores y catálogos)

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `provinces` | lista de: entero | — | sí | Provincias del continente |
| *effects* | cualquier clave: número decimal | — | no | Efectos del continente |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_regions.csv
