# Starting wars (`war`)

history/wars/<Name>.txt: one war per file. Each dated block is an event: attackers and defenders join or leave and war goals (war_goal) are set.

- **Files:** `history/wars/*/{name}.txt`
- **Layout:** one file per record, in any subfolder; the whole file is the record
- **Identifier:** the number the file name starts with
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `war:wars`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `name` | text | — | no | Name |

## Text keys

This schema creates no text keys.
