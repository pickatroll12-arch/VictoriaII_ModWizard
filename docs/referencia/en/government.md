# Governments (`government`)

Forms of government in common/governments.txt: allowed ideologies, elections and flag type. Creating one adds it to the target tables of common/rebel_types.txt.

- **Files:** `common/governments.txt`
- **Layout:** one file with a block per record
- **Identifier:** the block key
- **Editing:** created, duplicated and deleted from the Studio
- **Section:** `nations:governments`

## Fields

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| *ideology* | keys from the «ideology» catalogue: yes or no | — | no | Allowed ideologies |
| `election` | yes or no | — | yes | Elections. Whether the government holds elections. |
| `duration` | integer from 1 to 600 (months) | — | no | Duration. How many months between elections. |
| `appoint_ruling_party` | yes or no | — | yes | Appoints the ruling party. Whether the head of state picks the ruling party. |
| `flagType` | one of: monarchy, republic, communist, fascist | — | no | Flag type. Without a value, the game uses TAG.tga. |

## Text keys

- `{id}` in localisation/00_<prefix>_governments.csv
- `{id}_ruler` in localisation/00_<prefix>_governments.csv

## Companions

- Added to every «government» table of common/rebel_types.txt.

## Own checks

- `government_without_ideology`: Why the government allows no ideology
- `government_election_without_duration`: Why: Government … has “election = yes” but no “duration”

## Minimal example

```text
my_government = {
	conservative = yes
	election = no
	appoint_ruling_party = yes
}
```
