# Órdenes de batalla (`oob`)

history/units/<TAG>_oob.txt (y subcarpetas por fecha): ejércitos con sus regimientos, flotas con sus barcos y líderes. La historia del país lo nombra con oob = "<archivo>".

- **Archivos:** `history/units/*/{name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `nations:countries`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `army` | bloque army | — | no | army |
| `navy` | bloque navy | — | no | navy |
| `leader` | bloque leader | — | no | leader |

## Claves de texto

Este esquema no crea claves de texto.
