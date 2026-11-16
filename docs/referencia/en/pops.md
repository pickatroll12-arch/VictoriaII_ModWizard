# Population (`pops`)

Blocks in history/pops/<date>/*.txt: one per province and date, with one population group (POP) for each type, culture and religion. Its id is «<date>:<province>».

- **Files:** `history/pops/*/*.txt`
- **Layout:** blocks at the root of each file, grouped in folders
- **Identifier:** «<folder>:<block key>»
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `map:world`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| *pop* | child blocks: pop | — | no | Population groups |

## Text keys

This schema creates no text keys.
