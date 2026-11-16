# Events (`event`)

Country and province events from events/*.txt: when they fire, the text they show and what each option does.

- **Files:** `events/*.txt`
- **Layout:** root entries of each file keyed country_event / province_event
- **Identifier:** the «id» field
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `events:events`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `id` | integer | — | yes | Id. The event’s unique number. New events take the first free one in the project’s range. |
| `title` | text key (localisation) | — | yes | Title. Text key of the title (EVTNAME<id>). A plain-prose title also works. |
| `desc` | text key (localisation) | — | yes | Description. Text key of the description (EVTDESC<id>). |
| `picture` | picture from gfx/pictures/events | — | no | Picture. gfx/pictures/events/<picture>.tga, 521×203. |
| `is_triggered_only` | yes or no | — | no | Only triggered by another event or decision. No MTTH of its own: a new event starts like this so it does not fire for every country. |
| `fire_only_once` | yes or no | — | no | Only once per game |
| `major` | yes or no | — | no | Major event (everyone sees it) |
| `allow_multiple_instances` | yes or no | — | no | Allows several at once |
| `election` | yes or no | — | no | Election event |
| `issue_group` | reference to issue_group | — | no | Election issue group |
| `news` | yes or no | — | no | Appears in the news |
| `news_title` | text key (localisation) | — | no | Headline |
| `news_desc_long` | text key (localisation) | — | no | Long news text |
| `news_desc_medium` | text key (localisation) | — | no | Medium news text |
| `news_desc_short` | text key (localisation) | — | no | Short news text |
| `trigger` | script block (condition or effect builder) | — | no | Conditions |
| `mean_time_to_happen` | block mean_time_to_happen | — | no | Mean time to happen |
| `immediate` | script block (condition or effect builder) | — | no | Immediate effects |
| `option` | block option | — | yes | Option |

## Views

- `events:events`: Country events
- `events:events`: Province events

## Text keys

- `EVTNAME{id}` in localisation/00_<prefix>_events.csv
- `EVTDESC{id}` in localisation/00_<prefix>_events.csv
- `EVTOPT{letter}{id}` in localisation/00_<prefix>_events.csv

## Minimal example

```text
country_event = {
	id = 200000000
	title = "EVTNAME200000000"
	desc = "EVTDESC200000000"
	is_triggered_only = yes
	option = {
		name = "EVTOPTA200000000"
	}
	option = {
		name = "EVTOPTB200000000"
	}
}
```
