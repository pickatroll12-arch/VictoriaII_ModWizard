# Climas (`climate`)

Climas de map/climate.txt. Cada clima tiene dos entradas con el mismo nombre: una con sus efectos y otra con la lista de sus provincias.

- **Archivos:** `map/climate.txt`
- **Disposición:** dos entradas con la misma clave por registro: sus valores y su lista
- **Identificador:** la clave del bloque
- **Edición:** solo lectura (alimenta selectores y catálogos)

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| *effects* | cualquier clave: número decimal | — | no | Efectos del clima |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_regions.csv (opcional)
