# Culturas (`culture`)

Culturas de common/cultures.txt, cada una dentro de su grupo. Los nombres de pila y apellidos se editan como listas.

- **Archivos:** `common/cultures.txt`
- **Disposición:** bloques dentro de cada grupo del archivo
- **Identificador:** la clave del bloque
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `nations:cultures`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `color` | color RGB { r g b } de 0 a 255 | — | sí | Color |
| `radicalism` | entero de 0 a 100 | — | no | Radicalismo |
| `primary` | referencia a tag | — | no | País principal |
| `first_names` | lista de: texto | — | sí | Nombres de pila |
| `last_names` | lista de: texto | — | sí | Apellidos |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_cultures.csv

## Comprobaciones propias

- `culture_name_not_cp1252`: Por qué este nombre saldrá roto

## Ejemplo mínimo

```text
my_culture = {
	color = { 128 128 128 }
	first_names = { Name }
	last_names = { Surname }
}
```
