# Buttons (`gui_button`)

Buttons (guiButtonType) in interface/*.gui.

- **Files:** `interface/*.gui`
- **Layout:** guiButtonType elements at any depth of each file's guiTypes
- **Identifier:** its path inside the file (window/element)
- **Editing:** edited from the Studio (neither created nor deleted: the game looks elements up by name)
- **Section:** `interface:windows`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `position` | block position | — | no | Position. Offset in pixels from the parent's anchor (orientation). |
| `orientation` | text | — | no | Orientation. Anchor: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP or CENTER_DOWN. |
| `quadTextureSprite` | text | — | no | Button sprite. Sprite from interface/*.gfx; its frames are the button states. |
| `spriteType` | text | — | no | Sprite. Name of a sprite from interface/*.gfx. |
| `buttonText` | text | — | no | Button text. Localisation key or literal text. |
| `buttonFont` | text | — | no | Button font |
| `format` | text | — | no | Alignment. left, centre or right. |
| `size` | block size | — | no | Size. Width and height in pixels. |
| `tooltip` | text | — | no | Tooltip |
| `tooltipText` | text | — | no | Tooltip text |
| `delayedTooltipText` | text | — | no | Delayed tooltip |
| `shortcut` | text | — | no | Shortcut |
| `clicksound` | text | — | no | Click sound |
| `parent` | text | — | no | Parent |
| `rotation` | decimal number | — | no | Rotation |

## Text keys

This schema creates no text keys.
