# Cultures (`culture`)

Cultures in common/cultures.txt, each inside its group. First names and last names are edited as lists.

- **Files:** `common/cultures.txt`
- **Layout:** blocks inside each group of the file
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `nations:cultures`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `color` | RGB colour { r g b } from 0 to 255 | — | yes | Colour |
| `radicalism` | integer from 0 to 100 | — | no | Radicalism |
| `primary` | reference to tag | — | no | Primary country |
| `first_names` | list of: text | — | yes | First names |
| `last_names` | list of: text | — | yes | Last names |

## Text keys

- `{id}` in localisation/00_<prefix>_cultures.csv

## Own checks

- `culture_name_not_cp1252`: Why this name will look broken

## Minimal example

```text
my_culture = {
	color = { 128 128 128 }
	first_names = { Name }
	last_names = { Surname }
}
```
