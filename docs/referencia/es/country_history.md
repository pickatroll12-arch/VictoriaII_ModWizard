# Historias de país (`country_history`)

history/countries/<TAG> - <Nombre>.txt: el estado del país en cada fecha. Lo de fuera de los bloques fechados vale desde el inicio y cada bloque «fecha = …» lo cambia desde ese día.

- **Archivos:** `history/countries/*/{id} - {name}.txt`
- **Disposición:** un archivo por registro, en cualquier subcarpeta; el archivo entero es el registro
- **Identificador:** el número con que empieza el nombre del archivo
- **Edición:** se crea, se duplica y se borra desde el Studio
- **Sección:** `nations:countries`

## Campos

| Clave | Tipo | Por defecto | Obligatorio | Descripción |
|---|---|---|---|---|
| `capital` | referencia a province | — | no | Capital |
| `primary_culture` | referencia a culture | — | no | Cultura principal |
| `culture` | referencia a culture | — | no | Culturas aceptadas |
| `religion` | referencia a religion | — | no | Religión |
| `civilized` | sí o no | — | no | Civilizado |
| `government` | referencia a government | — | no | Gobierno |
| `ruling_party` | palabra | — | no | Partido gobernante |
| `last_election` | fecha (año.mes.día) | — | no | Últimas elecciones |
| `plurality` | número decimal | — | no | Pluralidad |
| `prestige` | número decimal | — | no | Prestigio |
| `nationalvalue` | referencia a national_value | — | no | Valor nacional |
| *upper_house* | claves del catálogo «ideology»: número decimal | — | no | Cámara alta |
| `literacy` | número decimal | — | no | Alfabetización. De 0 a 1 (0,8 es un 80 %). |
| `non_state_culture_literacy` | número decimal | — | no | Alfabetización de culturas no aceptadas |
| `consciousness` | número decimal | — | no | Conciencia |
| `nonstate_consciousness` | número decimal | — | no | Conciencia en colonias |
| `schools` | referencia a tech_school | — | no | Escuela tecnológica |
| `oob` | texto | — | no | Orden de batalla. Archivo de history/units con sus ejércitos, flotas y líderes. |
| *technology* | claves del catálogo «technology»: entero de 0 a 1 | — | no | Tecnologías conocidas |

## Claves de texto

Este esquema no crea claves de texto.
