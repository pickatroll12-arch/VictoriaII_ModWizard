# Guerras de inicio (`war`)

history/wars/<Nombre>.txt: una guerra por archivo. Cada bloque fechado es un suceso: entran o salen atacantes y defensores y se fijan los objetivos de guerra (war_goal).

- **Archivos:** `history/wars/*/{name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `war:wars`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `name` | texto | — | no | Nombre |

## Claves de texto

Este esquema no crea claves de texto.
