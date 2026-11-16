# Sprites (`sprite`)

Definiciones de spriteTypes en interface/*.gfx: el nombre que usan las ventanas, su textura y sus fotogramas.

- **Archivos:** `interface/*.gfx`
- **Disposición:** entradas dentro de los bloques spriteTypes de cada archivo con la clave spriteType / textSpriteType / corneredTileSpriteType / maskedShieldType / progressbartype / tileSpriteType / PieChartType / LineChartType / BarChartType / scrollingSprite
- **Identificador:** el campo «name»
- **Edición:** se crea, se duplica y se borra desde el Studio

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | texto | — | sí | Nombre. El ejecutable busca muchos elementos por este nombre: no lo cambies en una ventana del juego. |
| `texturefile` | texto | — | no | Textura. Ruta del archivo de imagen (.dds o .tga; el juego prueba también la otra extensión). |
| `noOfFrames` | entero | — | no | Fotogramas. Cuántos fotogramas tiene la textura, en tira horizontal. |
| `effectFile` | texto | — | no | Efecto |
| `clicksound` | texto | — | no | Sonido al pulsar |
| `textureFile1` | texto | — | no | Textura 1 |
| `textureFile2` | texto | — | no | Textura 2 |
| `borderSize` | bloque borderSize | — | no | Borde. Margen interior en píxeles (en un sprite «cornered», las esquinas que no se estiran). |
| `size` | bloque que se conserva tal cual | — | no | Tamaño. Ancho y alto en píxeles. |
| `color` | bloque que se conserva tal cual | — | no | Color |
| `colortwo` | bloque que se conserva tal cual | — | no | Segundo color |
| `loadType` | texto | — | no | Carga |
| `norefcount` | sí o no | — | no | Sin recuento de referencias |
| `allwaystransparent` | sí o no | — | no | Siempre transparente |
| `transparencecheck` | sí o no | — | no | Comprueba la transparencia |
| `horizontal` | sí o no | — | no | Horizontal |
| `flipv` | sí o no | — | no | Volteo vertical |
| `step` | entero | — | no | Paso |
| `linewidth` | entero | — | no | Grosor de línea |

## Claves de texto

Este esquema no crea claves de texto.

## Ejemplo mínimo

```text
spriteType = {
	name = "my_sprite"
	texturefile = "gfx/interface/my_sprite.dds"
}
```
