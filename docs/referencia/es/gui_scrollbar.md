# Barras de desplazamiento (`gui_scrollbar`)

Barras de desplazamiento (scrollbarType) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos scrollbarType a cualquier profundidad de los guiTypes de cada archivo
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
| `borderSize` | bloque borderSize | — | no | Borde. Margen interior en píxeles (en un sprite «cornered», las esquinas que no se estiran). |
| `slider` | texto | — | no | Deslizador |
| `track` | texto | — | no | Guía |
| `leftbutton` | texto | — | no | Botón izquierdo |
| `rightbutton` | texto | — | no | Botón derecho |
| `horizontal` | entero | — | no | Horizontal |
| `priority` | entero | — | no | Prioridad |
| `maxvalue` | entero | — | no | Valor máximo |
| `minvalue` | entero | — | no | Valor mínimo |
| `stepsize` | número decimal | — | no | Incremento |
| `startvalue` | número decimal | — | no | Valor inicial |
| `userangelimit` | sí o no | — | no | Usa límites |
| `rangelimitmin` | entero | — | no | Límite mínimo |
| `rangelimitmax` | entero | — | no | Límite máximo |
| `rangelimitminicon` | texto | — | no | Icono del mínimo |
| `rangelimitmaxicon` | texto | — | no | Icono del máximo |
| `lockable` | sí o no | — | no | Bloqueable |
| `guiButtonType` | bloque que se conserva tal cual | — | no | Botones |
| `iconType` | bloque que se conserva tal cual | — | no | Iconos |

## Claves de texto

Este esquema no crea claves de texto.
