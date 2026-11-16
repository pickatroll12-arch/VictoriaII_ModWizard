# Positions (`gui_position`)

Named points (positionType) in interface/*.gui that the game uses to place things.

- **Files:** `interface/*.gui`
- **Layout:** positionType elements at any depth of each file's guiTypes
- **Identifier:** its path inside the file (window/element)
- **Editing:** edited from the Studio (neither created nor deleted: the game looks elements up by name)
- **Section:** `interface:windows`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `position` | block position | — | no | Position. Offset in pixels from the parent's anchor (orientation). |
| `orientation` | text | — | no | Orientation. Anchor: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP or CENTER_DOWN. |

## Text keys

This schema creates no text keys.
