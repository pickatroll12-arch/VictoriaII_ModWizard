# Estrechos y pasos (`adjacency`)

Filas de map/adjacencies.csv: estrechos (dos provincias de tierra unidas a través de una de mar), pasos cerrados entre vecinas y canales.

- **Archivos:** `map/adjacencies.csv`
- **Disposición:** filas de una tabla de texto (from;to;type;through;data;comment)
- **Identificador:** la fila de la tabla
- **Edición:** solo lectura (alimenta selectores y catálogos)

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `from` | entero | — | sí | Desde |
| `to` | entero | — | sí | Hasta |
| `type` | uno de: sea, impassable, canal | — | sí | Tipo |
| `through` | entero | — | no | A través de. La provincia de mar que se cruza en un estrecho o un canal. |
| `data` | entero | — | no | Dato. En un canal, su número. |
| `comment` | texto | — | no | Comentario |

## Claves de texto

Este esquema no crea claves de texto.
