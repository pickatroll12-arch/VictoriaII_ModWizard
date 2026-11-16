# Text boxes (`gui_text`)

Text boxes (textBoxType) in interface/*.gui.

- **Files:** `interface/*.gui`
- **Layout:** textBoxType elements at any depth of each file's guiTypes
- **Identifier:** its path inside the file (window/element)
- **Editing:** edited from the Studio (neither created nor deleted: the game looks elements up by name)
- **Section:** `interface:windows`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `position` | block position | — | no | Position. Offset in pixels from the parent's anchor (orientation). |
| `orientation` | text | — | no | Orientation. Anchor: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP or CENTER_DOWN. |
| `text` | text | — | no | Text. Localisation key or literal text. |
| `font` | text | — | no | Font. Bitmap font from gfx/fonts. |
| `format` | text | — | no | Alignment. left, centre or right. |
| `maxWidth` | integer | — | no | Maximum width |
| `maxHeight` | integer | — | no | Maximum height |
| `fixedsize` | yes or no | — | no | Fixed size |
| `borderSize` | block borderSize | — | no | Border. Inner margin in pixels (for a cornered sprite, the corners that are not stretched). |
| `textureFile` | text | — | no | Texture. Path of the image file (.dds or .tga; the game also tries the other extension). |
| `allwaystransparent` | yes or no | — | no | Always transparent |

## Text keys

This schema creates no text keys.
