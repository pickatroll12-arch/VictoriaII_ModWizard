# Orders of battle (`oob`)

history/units/<TAG>_oob.txt (and dated subfolders): armies with their regiments, fleets with their ships, and leaders. The country history names it with oob = "<file>".

- **Files:** `history/units/*/{name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `nations:countries`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `army` | block army | — | no | army |
| `navy` | block navy | — | no | navy |
| `leader` | block leader | — | no | leader |

## Text keys

This schema creates no text keys.
