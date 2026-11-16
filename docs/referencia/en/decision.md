# Decisions (`decision`)

Decisions from decisions/*.txt: when they appear, when they can be taken and what they do.

- **Files:** `decisions/*.txt`
- **Layout:** blocks inside «political_decisions» in each file
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `events:decisions`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `picture` | picture from gfx/pictures/decisions | — | no | Picture. gfx/pictures/decisions/<picture>.dds, 95×95. If missing, the game uses the one named after the id. |
| `alert` | yes or no | yes | no | Alerts when it can be taken |
| `news` | yes or no | — | no | Appears in the news |
| `news_desc_long` | text key (localisation) | — | no | Long news text |
| `news_desc_medium` | text key (localisation) | — | no | Medium news text |
| `news_desc_short` | text key (localisation) | — | no | Short news text |
| `potential` | script block (condition or effect builder) | — | yes | When it shows up |
| `allow` | script block (condition or effect builder) | — | yes | When it can be taken |
| `effect` | script block (condition or effect builder) | — | yes | What it does |
| `ai_will_do` | block ai_will_do | — | no | AI interest |

## Text keys

- `{id}_title` in localisation/00_<prefix>_decisions.csv
- `{id}_desc` in localisation/00_<prefix>_decisions.csv

## Minimal example

```text
my_decision = {
	potential = { }
	allow = { }
	effect = { }
}
```
