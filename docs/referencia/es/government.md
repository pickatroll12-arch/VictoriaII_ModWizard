# Gobiernos (`government`)

Formas de gobierno de common/governments.txt: ideologías permitidas, elecciones y tipo de bandera. Al crear uno se añade a las tablas de destino de common/rebel_types.txt.

- **Archivos:** `common/governments.txt`
- **Disposición:** un archivo con un bloque por registro
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `nations:governments`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| *ideology* | claves del catálogo «ideology»: sí o no | — | no | Ideologías permitidas |
| `election` | sí o no | — | sí | Elecciones. Si el gobierno celebra elecciones. |
| `duration` | entero de 1 a 600 (meses) | — | no | Duración. Cada cuántos meses hay elecciones. |
| `appoint_ruling_party` | sí o no | — | sí | Nombra el partido gobernante. Si el jefe del estado elige el partido gobernante. |
| `flagType` | uno de: monarchy, republic, communist, fascist | — | no | Tipo de bandera. Sin valor, el juego usa TAG.tga. |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_governments.csv
- `{id}_ruler` en localisation/00_<prefijo>_governments.csv

## Compañeros

- Se añade a cada tabla «government» de common/rebel_types.txt.

## Comprobaciones propias

- `government_without_ideology`: Por qué el gobierno no admite ideologías
- `government_election_without_duration`: Por qué: El gobierno … tiene «election = yes» pero no «duration»

## Ejemplo mínimo

```text
my_government = {
	conservative = yes
	election = no
	appoint_ruling_party = yes
}
```
