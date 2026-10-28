# Fechas de inicio (`bookmark`)

Fechas de inicio de common/bookmarks.txt. El nombre es a la vez la clave de su texto. La fecha debe caer entre start_date y end_date de common/defines.lua.

- **Archivos:** `common/bookmarks.txt`
- **Disposición:** bloques «bookmark» repetidos en un archivo
- **Identificador:** el campo «name»
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `war:bookmarks`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | clave de texto (localisation) | — | sí | Nombre (clave) |
| `desc` | clave de texto (localisation) | — | no | Descripción (clave) |
| `date` | fecha (año.mes.día) | — | sí | Fecha |
| `cameraX` | entero | — | no | Cámara X. Coordenada del juego donde se centra el mapa. |
| `cameraY` | entero | — | no | Cámara Y |

## Claves de texto

- `{id}` en localisation/00_<prefijo>_bookmarks.csv
- `{id}_DESC` en localisation/00_<prefijo>_bookmarks.csv (opcional)

## Comprobaciones propias

- `bookmark_date_outside_defines`: Por qué esta fecha de inicio no sirve

## Ejemplo mínimo

```text
bookmark = {
	name = "my_bookmark"
	desc = "my_bookmark_DESC"
	date = 1836.1.1
	cameraX = 0
	cameraY = 0
}
```
