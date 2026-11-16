# Lists (`gui_listbox`)

Lists (listboxType) in interface/*.gui.

- **Files:** `interface/*.gui`
- **Layout:** listboxType elements at any depth of each file's guiTypes
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
| `background` | text | — | no | Background |
| `borderSize` | block borderSize | — | no | Border. Inner margin in pixels (for a cornered sprite, the corners that are not stretched). |
| `spacing` | decimal number | — | no | Spacing |
| `offset` | block offset | — | no | Offset |
| `scrollbartype` | text | — | no | Scrollbar |
| `horizontal` | yes or no | — | no | Horizontal |
| `priority` | integer | — | no | Priority |
| `step` | integer | — | no | Step |
| `allwaystransparent` | yes or no | — | no | Always transparent |

## Text keys

This schema creates no text keys.
