# Diálogos (`gui_dialog`)

Diálogos (eu3dialogtype) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos eu3dialogtype a cualquier profundidad de los guiTypes de cada archivo
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
| `background` | texto | — | no | Fondo |
| `moveable` | entero | — | no | Se puede mover |
| `dontRender` | texto | — | no | No dibujar |
| `horizontalBorder` | texto | — | no | Borde horizontal |
| `verticalBorder` | texto | — | no | Borde vertical |
| `fullScreen` | sí o no | — | no | Pantalla completa |
| `upsound` | texto | — | no | Sonido al abrir |
| `downsound` | texto | — | no | Sonido al cerrar |
| `windowType` | bloque que se conserva tal cual | — | no | Ventanas hijas |
| `eu3dialogtype` | bloque que se conserva tal cual | — | no | Diálogos hijos |
| `guiButtonType` | bloque que se conserva tal cual | — | no | Botones |
| `iconType` | bloque que se conserva tal cual | — | no | Iconos |
| `instantTextBoxType` | bloque que se conserva tal cual | — | no | Textos |
| `textBoxType` | bloque que se conserva tal cual | — | no | Cajas de texto |
| `checkboxType` | bloque que se conserva tal cual | — | no | Casillas |
| `listboxType` | bloque que se conserva tal cual | — | no | Listas |
| `scrollbarType` | bloque que se conserva tal cual | — | no | Barra de desplazamiento |
| `positionType` | bloque que se conserva tal cual | — | no | Posiciones |
| `OverlappingElementsBoxType` | bloque que se conserva tal cual | — | no | Cajas solapadas |
| `editBoxType` | bloque que se conserva tal cual | — | no | Campos de texto |
| `shieldtype` | bloque que se conserva tal cual | — | no | Escudos |

## Claves de texto

Este esquema no crea claves de texto.
