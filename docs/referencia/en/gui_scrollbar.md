# Scrollbars (`gui_scrollbar`)

Scrollbars (scrollbarType) in interface/*.gui.

- **Files:** `interface/*.gui`
- **Layout:** scrollbarType elements at any depth of each file's guiTypes
- **Identifier:** its path inside the file (window/element)
- **Editing:** edited from the Studio (neither created nor deleted: the game looks elements up by name)
- **Section:** `interface:windows`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | yes | Name. The game looks up many elements by this name: do not change it in a game window. |
| `position` | block position | — | no | Position. Offset in pixels from the parent's anchor (orientation). |
| `orientation` | text | — | no | Orientation. Anchor: UPPER_LEFT, UPPER_RIGHT, LOWER_LEFT, LOWER_RIGHT, CENTER, CENTER_UP or CENTER_DOWN. |
| `size` | block size | — | no | Size. Width and height in pixels. |
| `borderSize` | block borderSize | — | no | Border. Inner margin in pixels (for a cornered sprite, the corners that are not stretched). |
| `slider` | text | — | no | Slider |
| `track` | text | — | no | Track |
| `leftbutton` | text | — | no | Left button |
| `rightbutton` | text | — | no | Right button |
| `horizontal` | integer | — | no | Horizontal |
| `priority` | integer | — | no | Priority |
| `maxvalue` | integer | — | no | Maximum value |
| `minvalue` | integer | — | no | Minimum value |
| `stepsize` | decimal number | — | no | Step size |
| `startvalue` | decimal number | — | no | Start value |
| `userangelimit` | yes or no | — | no | Uses range limit |
| `rangelimitmin` | integer | — | no | Range minimum |
| `rangelimitmax` | integer | — | no | Range maximum |
| `rangelimitminicon` | text | — | no | Minimum icon |
| `rangelimitmaxicon` | text | — | no | Maximum icon |
| `lockable` | yes or no | — | no | Lockable |
| `guiButtonType` | block kept as is | — | no | Buttons |
| `iconType` | block kept as is | — | no | Icons |

## Text keys

This schema creates no text keys.
