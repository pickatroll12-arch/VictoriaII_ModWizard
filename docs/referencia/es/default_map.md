# Ajustes del mapa (`default_map`)

map/default.map: el número máximo de provincias, la lista de provincias de mar (sea_starts) y los nombres de los archivos del mapa. Es un único registro.

- **Archivos:** `map/default.map`
- **Disposición:** el archivo entero es un único registro
- **Identificador:** fijo: «default_map» (un único registro)
- **Edición:** solo lectura (alimenta selectores y catálogos)

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `max_provinces` | entero | — | sí | Máximo de provincias. Un id de provincia vale si es mayor que 0 y menor que este número. |
| `sea_starts` | lista de: entero | — | sí | Provincias de mar |
| `definitions` | texto | — | no | Tabla de provincias |
| `provinces` | texto | — | no | Imagen de provincias |
| `positions` | texto | — | no | Posiciones |
| `terrain` | texto | — | no | Imagen de terreno |
| `rivers` | texto | — | no | Imagen de ríos |
| `terrain_definition` | texto | — | no | Definición de terrenos |
| `tree_definition` | texto | — | no | Definición de árboles |
| `continent` | texto | — | no | Archivo de continentes |
| `adjacencies` | texto | — | no | Archivo de estrechos |
| `region` | texto | — | no | Archivo de regiones |
| `region_sea` | texto | — | no | Archivo de regiones de mar |
| `province_flag_sprite` | texto | — | no | Sprite de banderas de provincia |

## Claves de texto

Este esquema no crea claves de texto.
