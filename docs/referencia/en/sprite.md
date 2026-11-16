# Sprites (`sprite`)

spriteTypes definitions in interface/*.gfx: the name windows use, its texture and its frames.

- **Files:** `interface/*.gfx`
- **Layout:** entries inside the spriteTypes blocks of each file keyed spriteType / textSpriteType / corneredTileSpriteType / maskedShieldType / progressbartype / tileSpriteType / PieChartType / LineChartType / BarChartType / scrollingSprite
- **Identifier:** the «name» field
- **Editing:** created, duplicated and deleted from the Studio

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `texturefile` | text | — | no | Texture. Path of the image file (.dds or .tga; the game also tries the other extension). |
| `noOfFrames` | integer | — | no | Frames. How many frames the texture has, as a horizontal strip. |
| `effectFile` | text | — | no | Effect |
| `clicksound` | text | — | no | Click sound |
| `textureFile1` | text | — | no | Texture 1 |
| `textureFile2` | text | — | no | Texture 2 |
| `borderSize` | block borderSize | — | no | Border. Inner margin in pixels (for a cornered sprite, the corners that are not stretched). |
| `size` | block kept as is | — | no | Size. Width and height in pixels. |
| `color` | block kept as is | — | no | Colour |
| `colortwo` | block kept as is | — | no | Second colour |
| `loadType` | text | — | no | Load type |
| `norefcount` | yes or no | — | no | No reference count |
| `allwaystransparent` | yes or no | — | no | Always transparent |
| `transparencecheck` | yes or no | — | no | Transparency check |
| `horizontal` | yes or no | — | no | Horizontal |
| `flipv` | yes or no | — | no | Vertical flip |
| `step` | integer | — | no | Step |
| `linewidth` | integer | — | no | Line width |

## Text keys

This schema creates no text keys.

## Minimal example

```text
spriteType = {
	name = "my_sprite"
	texturefile = "gfx/interface/my_sprite.dds"
}
```
