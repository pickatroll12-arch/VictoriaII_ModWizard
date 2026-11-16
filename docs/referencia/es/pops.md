# Población (`pops`)

Bloques de history/pops/<fecha>/*.txt: uno por provincia y fecha, con un grupo de población (POP) por cada tipo, cultura y religión. Su id es «<fecha>:<provincia>».

- **Archivos:** `history/pops/*/*.txt`
- **Disposición:** bloques de la raíz de cada archivo, agrupados en carpetas
- **Identificador:** «<carpeta>:<clave del bloque>»
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `map:world`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| *pop* | bloques hijos: pop | — | no | Grupos de población |

## Claves de texto

Este esquema no crea claves de texto.
