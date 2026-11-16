# Escudos (`gui_shield`)

Escudos de bandera (shieldtype) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos shieldtype a cualquier profundidad de los guiTypes de cada archivo
- **Identificador:** su ruta dentro del archivo (ventana/elemento)
- **Edición:** se edita desde el Studio (ni se crea ni se borra: el juego busca los elementos por su nombre)
- **Sección:** `interface:windows`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | texto | — | sí | Nombre. El ejecutable busca muchos elementos por este nombre: no lo cambies en una ventana del juego. |
| `position` | bloque position | — | no | Posición. Desplazamiento en píxeles desde el anclaje (orientación) del padre. |
| `orientation` | texto | — | no | Orientación. Anclaje: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP o CENTER_DOWN. |
| `spriteType` | texto | — | no | Sprite. Nombre de un sprite de interface/*.gfx. |
| `rotation` | número decimal | — | no | Giro |

## Claves de texto

Este esquema no crea claves de texto.
