# Modifiers (`event_modifier`)

Modifiers in common/event_modifiers.txt that events and decisions apply to countries and provinces: an icon and its effects.

- **Files:** `common/event_modifiers.txt`
- **Layout:** one file with a block per record
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `events:modifiers`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `icon` | integer | — | no | Icon |
| *effects* | any key: decimal number | — | no | Modifier effects |

## Text keys

- `{id}` in localisation/00_<prefix>_modifiers.csv
- `{id}_desc` in localisation/00_<prefix>_modifiers.csv (optional)

## Minimal example

```text
my_event_modifier = {
	icon = 1
	prestige = 1
}
```
