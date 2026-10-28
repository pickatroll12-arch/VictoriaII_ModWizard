# Start dates (`bookmark`)

Start dates in common/bookmarks.txt. The name is also the key of its text. The date must fall between start_date and end_date in common/defines.lua.

- **Files:** `common/bookmarks.txt`
- **Layout:** repeated «bookmark» blocks in one file
- **Identifier:** the «name» field
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `war:bookmarks`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text key (localisation) | — | yes | Name (key) |
| `desc` | text key (localisation) | — | no | Description (key) |
| `date` | date (year.month.day) | — | yes | Date |
| `cameraX` | integer | — | no | Camera X. Game coordinate where the map is centred. |
| `cameraY` | integer | — | no | Camera Y |

## Text keys

- `{id}` in localisation/00_<prefix>_bookmarks.csv
- `{id}_DESC` in localisation/00_<prefix>_bookmarks.csv (optional)

## Own checks

- `bookmark_date_outside_defines`: Why this start date does not work

## Minimal example

```text
bookmark = {
	name = "my_bookmark"
	desc = "my_bookmark_DESC"
	date = 1836.1.1
	cameraX = 0
	cameraY = 0
}
```
