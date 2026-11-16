# Casillas (`gui_checkbox`)

Casillas (checkboxType) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos checkboxType a cualquier profundidad de los guiTypes de cada archivo
- **Identificador:** su ruta dentro del archivo (ventana/elemento)
- **Edición:** se edita desde el Studio (ni se crea ni se borra: el juego busca los elementos por su nombre)
- **Sección:** `interface:windows`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | texto | — | sí | Nombre. El ejecutable busca muchos elementos por este nombre: no lo cambies en una ventana del juego. |
| `position` | bloque position | — | no | Posición. Desplazamiento en píxeles desde el anclaje (orientación) del padre. |
| `orientation` | texto | — | no | Orientación. Anclaje: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP o CENTER_DOWN. |
| `quadTextureSprite` | texto | — | no | Sprite del botón. Sprite de interface/*.gfx; sus fotogramas son los estados del botón. |
| `buttonText` | texto | — | no | Texto del botón. Clave de localización o texto literal. |
| `buttonFont` | texto | — | no | Fuente del botón |
| `tooltip` | texto | — | no | Ayuda emergente |
| `tooltipText` | texto | — | no | Texto de la ayuda |
| `delayedTooltipText` | texto | — | no | Ayuda retardada |
| `shortcut` | texto | — | no | Atajo |

## Claves de texto

Este esquema no crea claves de texto.
