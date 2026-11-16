# Diplomacia de inicio (`diplomacy`)

history/diplomacy/*.txt: alianzas, vasallos, subestados, uniones y garantías, cada una con first, second, start_date y end_date.

- **Archivos:** `history/diplomacy/*/{name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `war:diplomacy`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `alliance` | bloque alliance | — | no | alliance |
| `vassal` | bloque vassal | — | no | vassal |
| `substate` | bloque substate | — | no | substate |
| `union` | bloque union | — | no | union |
| `guarantee` | bloque guarantee | — | no | guarantee |

## Claves de texto

Este esquema no crea claves de texto.
