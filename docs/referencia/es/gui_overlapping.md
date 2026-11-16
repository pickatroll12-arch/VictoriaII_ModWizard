# Cajas solapadas (`gui_overlapping`)

Cajas de elementos solapados (OverlappingElementsBoxType) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos OverlappingElementsBoxType a cualquier profundidad de los guiTypes de cada archivo
- **Identificador:** su ruta dentro del archivo (ventana/elemento)
- **Edición:** se edita desde el Studio (ni se crea ni se borra: el juego busca los elementos por su nombre)
- **Sección:** `interface:windows`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | texto | — | sí | Nombre. El ejecutable busca muchos elementos por este nombre: no lo cambies en una ventana del juego. |
| `position` | bloque position | — | no | Posición. Desplazamiento en píxeles desde el anclaje (orientación) del padre. |
| `orientation` | texto | — | no | Orientación. Anclaje: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP o CENTER_DOWN. |
| `size` | bloque size | — | no | Tamaño. Ancho y alto en píxeles. |
| `format` | texto | — | no | Alineación. left, centre o right. |
| `spacing` | número decimal | — | no | Separación |

## Claves de texto

Este esquema no crea claves de texto.
