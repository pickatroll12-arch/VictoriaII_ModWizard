# Windows (`gui_window`)

Windows (windowType) in interface/*.gui: position, size, anchor and the elements they contain.

- **Files:** `interface/*.gui`
- **Layout:** windowType elements at any depth of each file's guiTypes
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
| `moveable` | integer | — | no | Moveable |
| `dontRender` | text | — | no | Do not render |
| `horizontalBorder` | text | — | no | Horizontal border |
| `verticalBorder` | text | — | no | Vertical border |
| `fullScreen` | yes or no | — | no | Full screen |
| `upsound` | text | — | no | Open sound |
| `downsound` | text | — | no | Close sound |
| `windowType` | block kept as is | — | no | Child windows |
| `eu3dialogtype` | block kept as is | — | no | Child dialogs |
| `guiButtonType` | block kept as is | — | no | Buttons |
| `iconType` | block kept as is | — | no | Icons |
| `instantTextBoxType` | block kept as is | — | no | Texts |
| `textBoxType` | block kept as is | — | no | Text boxes |
| `checkboxType` | block kept as is | — | no | Check boxes |
| `listboxType` | block kept as is | — | no | Lists |
| `scrollbarType` | block kept as is | — | no | Scrollbar |
| `positionType` | block kept as is | — | no | Positions |
| `OverlappingElementsBoxType` | block kept as is | — | no | Overlapping boxes |
| `editBoxType` | block kept as is | — | no | Edit boxes |
| `shieldtype` | block kept as is | — | no | Shields |

## Text keys

This schema creates no text keys.
