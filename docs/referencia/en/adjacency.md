# Straits and crossings (`adjacency`)

Rows of map/adjacencies.csv: straits (two land provinces joined through a sea one), closed crossings between neighbours, and canals.

- **Files:** `map/adjacencies.csv`
- **Layout:** rows of a text table (from;to;type;through;data;comment)
- **Identifier:** the row of the table
- **Editing:** read-only (feeds pickers and catalogues)

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `from` | integer | — | yes | From |
| `to` | integer | — | yes | To |
| `type` | one of: sea, impassable, canal | — | yes | Type |
| `through` | integer | — | no | Through. The sea province crossed by a strait or a canal. |
| `data` | integer | — | no | Data. For a canal, its number. |
| `comment` | text | — | no | Comment |

## Text keys

This schema creates no text keys.
