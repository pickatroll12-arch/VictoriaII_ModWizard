# Campos de texto (`gui_editbox`)

Campos de texto editables (editBoxType) de interface/*.gui.

- **Archivos:** `interface/*.gui`
- **Disposición:** elementos editBoxType a cualquier profundidad de los guiTypes de cada archivo
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
| `font` | texto | — | no | Fuente. Fuente de mapa de bits de gfx/fonts. |
| `text` | texto | — | no | Texto. Clave de localización o texto literal. |
| `borderSize` | bloque borderSize | — | no | Borde. Margen interior en píxeles (en un sprite «cornered», las esquinas que no se estiran). |
| `textureFile` | texto | — | no | Textura. Ruta del archivo de imagen (.dds o .tga; el juego prueba también la otra extensión). |

## Claves de texto

Este esquema no crea claves de texto.
