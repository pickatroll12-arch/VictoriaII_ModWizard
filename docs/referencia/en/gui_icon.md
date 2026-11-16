# Icons (`gui_icon`)

Icons (iconType) in interface/*.gui.

- **Files:** `interface/*.gui`
- **Layout:** iconType elements at any depth of each file's guiTypes
- **Identifier:** its path inside the file (window/element)
- **Editing:** edited from the Studio (neither created nor deleted: the game looks elements up by name)
- **Section:** `interface:windows`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `position` | block position | — | no | Position. Offset in pixels from the parent's anchor (orientation). |
| `orientation` | text | — | no | Orientation. Anchor: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP or CENTER_DOWN. |
| `spriteType` | text | — | no | Sprite. Name of a sprite from interface/*.gfx. |
| `frame` | integer | — | no | Frame |
| `scale` | decimal number | — | no | Scale |
| `rotation` | decimal number | — | no | Rotation |
| `buttonMesh` | text | — | no | Button mesh |

## Text keys

This schema creates no text keys.
