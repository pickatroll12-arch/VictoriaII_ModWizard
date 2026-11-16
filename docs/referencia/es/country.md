# Archivos de país (`country`)

common/countries/<Archivo>.txt: color de mapa, cultura gráfica, partidos y nombres de unidades. El id es el nombre del archivo, tal como lo escribe countries.txt.

- **Archivos:** `common/countries/*/{name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `nations:countries`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `color` | color RGB { r g b } de 0 a 255 | — | sí | Color del mapa |
| `graphical_culture` | referencia a graphical_culture | — | sí | Cultura gráfica |
| `party` | bloque party | — | no | party |

## Claves de texto

Este esquema no crea claves de texto.
