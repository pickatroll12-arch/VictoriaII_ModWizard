# Iteración 4, cierre — etapa X1: renombrado seguro y culturas

Rama `wt/it4-x`. Núcleo solamente: no se tocó `ui/**` ni `core/validate/rules/**`.

## Qué se hizo

1. **Renombrado seguro (wizard §15)**: `Entities.rename(ref, new_id)` y su plan de solo lectura
   `Entities.rename_plan(ref, new_id)`. Motor nuevo en `src/vic2studio/core/schema/rename.py`.
2. **`on_rename` de los cuatro compañeros** (`AppendToList`, `MappingTable`, `ActivateUnit`,
   `UnitNamesSlot`), que antes lanzaban `NotImplementedError` (`core/schema/companions.py`).
3. **Culturas (§14.13)**: `Entities.move_to_group(ref, group)`, `Entities.group_kind(kind)` y
   `Entities.groups(kind)`. Crear un grupo ya funcionaba con `create("culture_group", …)`; ahora tiene prueba.
4. Textos ES/EN nuevos en `core/schemas/texts/schema.{es,en}.json` (12 claves cada uno).
5. Pruebas: `tests/test_schema_rename.py` (51 pruebas: minijuego y corpus).

## API para la etapa de interfaz

Todo se importa de `vic2studio.core.schema` (`RenamePlan`, `RenameFile`, `RenameUse`, `LocRename`,
`RenameBlockedError`, `InvalidIdentError`) o de `vic2studio.core.schema.rename` (las constantes).

### Renombrar

```python
Entities.rename_plan(ref: RecordRef, new_ident: str) -> RenamePlan     # no cambia nada (I4)
Entities.rename(ref: RecordRef, new_ident: str) -> RecordRef           # la referencia nueva
```

`RenamePlan` (inmutable):

| Campo | Qué es |
|---|---|
| `ref`, `new_ident` | lo pedido |
| `files: tuple[RenameFile, ...]` | la definición y los usos, por archivo (orden por ruta) |
| `loc: tuple[LocRename, ...]` | las claves de localización que cambian |
| `moved: tuple[VPath, VPath] \| None` | `(archivo viejo, archivo nuevo)` si el archivo cambia de nombre (unidades) |
| `error: Exception \| None` | la excepción con la que `rename` lo rechazaría; `None` si se puede |
| `copies` (propiedad) | los `rel` de `files` que hoy son del juego y se copiarán al mod al guardar |
| `uses` (propiedad) | todos los `RenameUse` sin la definición |
| `allowed` (propiedad) | `error is None` |

- `RenameFile(rel, uses, from_game)`.
- `RenameUse(rel, line, column, role, own)`: `role` es el papel del índice (`casus_belli`, `government`,
  `primary_culture`, `pop_culture`, `activate_unit`, `peace_order`, `rebel_government`…), `"definition"`
  (constante `ROLE_DEFINITION`) para el token que define la entidad, `"unit_names"` para la lista de nombres
  de barcos, o la clave del campo `LocKey` que sigue al id (`desc` de un bookmark). `own=True`: lo mantiene un
  compañero o es del propio registro (no es un uso «de otro»). Línea y columna son las del texto actual.
- `LocRename(old, new, action, rel)`: `action` es `"rename"` (las filas del mod cambian de clave), `"copy"` (la
  clave es del juego o la nombra alguien más: fila nueva en el archivo del mod con los textos de todos los
  idiomas; la vieja se queda) o `"kept"` (la clave nueva ya existe: se usa esa y no se pisa nada). Constantes
  `LOC_RENAME`, `LOC_COPY`, `LOC_KEPT`.

El plan sirve también con un id inválido o a medio escribir: `files` y `copies` no dependen del id nuevo y
`error` trae el motivo. **Abre** los documentos con usos (no los toca: ni sucios ni paso de deshacer); es lo
que `rename` necesita de todos modos.

Errores (en `plan.error` o lanzados por `rename`; en los dos casos no cambia nada):

| Excepción | `.code` | Cuándo |
|---|---|---|
| `InvalidIdentError` | `empty`, `bad_chars`, `reserved`… | los de `ident_problem` (igual que al crear) |
| `InvalidIdentError` | `unchanged` | el id nuevo es el que ya tiene |
| `InvalidIdentError` | `taken` | ya existe en la vista efectiva, otro archivo define un símbolo del mismo tipo con ese nombre, o (unidades) el archivo destino existe |
| `RenameBlockedError` | `game_file` | unidad del juego base, también con copia en el mod (`params["rel"]`) |
| `RenameBlockedError` | `read_only_file` | un archivo con usos no se puede editar, D17 (`params["rel"]`) |
| `RenameBlockedError` | `unresolved_uses` | usos del índice que no son un token de un archivo Clausewitz (`.uses`) |
| `ReadOnlySchemaError` | — | esquema de solo lectura |
| `KeyError` | — | el registro no existe |

`InvalidIdentError.message(lang)` y `RenameBlockedError.message(lang)` dan el texto traducido desde el núcleo
(`schema.ident.<code>` y `schema.rename.blocked.<code>`). La interfaz puede seguir usando su tabla
`entity.ident.<code>`; para `unchanged` y los bloqueos el texto del núcleo ya existe en ES y EN.

Etiquetas de deshacer: `undo.rename_<kind>` con `{ident}` y `{new}` para los siete esquemas editables
(`tests/schema_harness.py` ya lo exige a cada esquema editable nuevo).

### Culturas

```python
Entities.move_to_group(ref: RecordRef, group: str) -> RecordRef
Entities.group_kind(kind: str) -> str | None      # "culture" → "culture_group"; None si no va en grupos
Entities.groups(kind: str) -> list[str]           # grupos en orden de archivo, también los vacíos
Entities.create("culture_group", ident, {"leader": …, "unit": …, "union": …, "is_overseas": …},
                texts={ident: {"en": …, "es": …}})
```

- `move_to_group`: una transacción `undo.move_culture` (`{ident}`, `{group}`); el bloque va al **final** del
  grupo destino con su comentario, su sangría y su formato. Mover al grupo donde ya está no hace nada (ni
  transacción). Grupo que no existe: `InvalidIdentError("no_group")`. Esquema sin grupos (incluido
  `culture_group`): `ValueError`.
- `groups("culture")` es la lista para el desplegable; `Entities.parent(ref)` (ya existía) da el grupo actual.

## Decisiones

1. **Sitios, no texto.** Renombrar es cambiar tokens: `(archivo, camino en el árbol, clave o valor)`. `scan`
   los calcula sin tocar nada y tanto el plan como la aplicación salen del mismo resultado, así que el plan
   dice exactamente lo que se cambia (prueba: plan = archivos sucios después).
2. **Posiciones del texto actual.** El índice va con retraso respecto del `Workspace`. El índice dice *qué
   archivos* mirar; las posiciones se sacan de los bytes actuales de cada uno con los mismos extractores. Se
   miran además todos los documentos Clausewitz abiertos, por si citan el id sin que el índice lo sepa.
3. **Clave y valor.** Se cambia el valor si es el id; la clave, solo si el valor no lo era o la entrada da dos
   referencias (`junta = junta` en la matriz de rebeldes). Así `culture = culture` (una cultura llamada como
   una clave) cambia solo el valor.
4. **Gemelas.** El extractor de `history/pops` guarda una referencia por cultura y archivo. Toda entrada del
   mismo archivo con la misma clave y el mismo valor es el mismo uso y cambia con ella (vanilla: 109
   referencias de una cultura son 1454 tokens).
5. **Compañeros autosuficientes.** Cada `on_rename` recorre lo suyo y no depende de que el motor haya pasado
   antes; el motor ya cubre `peace_order`, la matriz y `activate_unit` por el índice, así que en el flujo
   completo son redundantes e idempotentes. `UnitNamesSlot` es el único que hace algo que el índice no
   conoce; lo declara para el plan con el método opcional `rename_uses(ctx, rec, old)` (solo lectura).
6. **Unidades (`OnePerFile`).** El archivo cambia de nombre con el id (`units/<id>.txt`): el viejo va a la
   papelera al guardar y el nuevo nace con los mismos bytes salvo el token. **Una unidad del juego base se
   bloquea** (`game_file`), igual que su borrado: el mod no puede ocultar el archivo viejo y la unidad vieja
   seguiría existiendo. También se bloquea una copia del mod que tapa un archivo del juego. El motivo sugiere
   duplicar.
7. **Claves de localización.** Solo las `LocSpec` no compartidas. Las del mod se renombran en su fila; las del
   juego, o las que algo más nombra (`refs_to("loc_key", …)`), se copian con todos los idiomas; si la nueva ya
   existe no se pisa. Los campos `LocKey` del registro cuyo valor sigue una plantilla (`desc = "<id>_DESC"`)
   siguen al id; uno con valor propio se queda.
8. **Colisiones.** Además de la vista efectiva del layout, cuenta un símbolo del mismo tipo definido en otro
   archivo (un modificador de `static_modifiers.txt`): sus usos se confundirían.
9. **Bloquear antes que dejar a medias.** Si un uso está en un archivo que no se puede editar o no es un
   token reescribible, se rechaza todo.
10. **Desviación de wizard §10.5**: `rename` devuelve la `RecordRef` nueva (no un `ChangePlan`) y no tiene
    parámetro `update_refs`; el plan sale de `rename_plan`.

## Cambio en una regla de arquitectura (a revisar por el integrador)

`tests/test_arch_writes.py` contaba cualquier `.rename(...)` como `Path.rename`. El núcleo llama a
`LocSync.rename(old, new)` y la interfaz llamará a `Entities.rename(ref, new_id)`: con la regla tal cual, las
dos fallaban. Ahora `.rename` solo cuenta con **un** argumento posicional (`Path.rename(destino)`), como ya
hacía la regla con `.replace(destino)` y `.touch()`. Se añadieron los casos al autotest del detector
(`p.rename(q)` se encuentra; `loc.rename(old, new)` y `entities.rename(ref, 'id')` no). `os.rename` se sigue
detectando por su módulo. Va en un commit aparte para poder revisarlo o revertirlo solo.

## Mutantes (manuales, sobre `tests.test_schema_rename`; todos mueren)

| Mutante | Prueba que lo mata |
|---|---|
| Dos transacciones (las claves de localización en otra) | `test_one_undo_step_returns_the_original_bytes` y 5 más |
| Olvidar las claves de localización | 14 pruebas (`test_keys_of_the_mod_are_renamed_in_place`…) |
| No reescribir los usos del índice | 13 pruebas (`test_it_changes_only_the_id_tokens_of_the_definition_and_its_uses`…) |
| No cambiar valores (solo claves) | 11 pruebas |
| No aplicar los sitios (solo compañeros) | 26 pruebas |
| Sin gemelas | `test_every_pop_of_the_culture_follows_not_only_the_first_of_each_file` |
| Sin mirar los documentos abiertos | `test_uses_in_unsaved_documents_are_rewritten_though_the_index_is_stale` |
| Renombrar las claves compartidas | `test_shared_keys_are_left_alone` |
| `on_rename` vacío en `AppendToList` / `MappingTable` / `ActivateUnit` | su prueba de `CompanionRenameTests` (solo esa: en el flujo completo el motor lo cubre) |
| `on_rename` o `rename_uses` vacío en `UnitNamesSlot` | `CompanionRenameTests` y `test_the_plan_tells_the_move_and_the_ship_names` |
| Mover la cultura regenerando el bloque | `test_the_block_moves_with_its_text_intact` y 2 más |
| Mover sin releer / al mismo grupo con transacción / grupo desconocido | las tres de `CultureMoveTests` |
| No bloquear la unidad del juego base | `test_a_unit_of_the_base_game_is_blocked_with_a_translated_reason`, `ShadowedUnitTests` |
| Cambiar siempre la clave que coincide | `IdThatIsAlsoAKeyTests` (añadida al ver que sobrevivía) |
| No cambiar la clave si el valor coincide | `test_the_plan_groups_the_uses_by_file`, corpus |
| Copiar solo el inglés | `test_keys_of_the_game_are_copied_with_every_language` y 4 más |
| Ignorar que la clave nueva existe / mover la clave que otro usa | `test_an_existing_new_key_is_kept…`, `OwnKeyUsedElsewhereTests` |
| Colisión solo en el layout / aceptar el mismo id / no validar el id | `RejectionTests` |
| No bloquear por solo lectura / por usos sin resolver | `BrokenUseTests`, `test_a_use_that_is_not_a_token_blocks_the_rename` |
| No revivir la lápida / el plan escribe | `test_renaming_through_a_tombstone_revives_the_file_of_the_game` |
| Los `LocKey` no siguen al id / perder las comillas | `BookmarkRenameTests`, `BookmarkOwnDescriptionTests` |
| No borrar el archivo viejo / no mirar el destino / saltarse la regex del layout | `UnitRenameTests` |
| El plan no dice qué se copia del juego | `test_the_plan_groups_the_uses_by_file`, corpus |

## Límites conocidos

1. **Usos en guiones.** El índice no guarda los usos de un CB, un modificador de evento o una unidad dentro
   de eventos y decisiones (`casus_belli = { type = … }`, `add_country_modifier`…). No se reescriben ni salen
   en el plan: renombrar un CB de vanilla citado en eventos deja esas citas con el id viejo. Es el mismo hueco
   que tiene «dónde se usa» y el borrado; se cierra cuando el índice indexe los guiones (iteración 7). La
   interfaz debería avisarlo en el diálogo mientras tanto.
2. **Unidades del juego base** no se renombran (decisión 6).
3. **`Entities.create` acepta ids que el layout `OnePerFile` luego no reconoce** (una unidad con mayúsculas
   crea un archivo que la regex del layout ignora). `rename` sí lo rechaza (`bad_chars`); `create` no se tocó.
4. **`kept` deja huérfana la clave vieja** si era del mod: no se borra porque no se sabe quién más la usa.
5. **`unit_names`**: si un país ya tiene una lista con el id nuevo, la vieja se deja como está.
6. **El plan abre documentos**: en vanilla, el gobierno más usado abre 190 archivos (0,5 s la primera vez,
   0,13 s las siguientes; una cultura con 1454 usos, 1,2 s y 0,6 s). Para llamarlo en cada pulsación conviene
   un temporizador en la interfaz.
7. Solo se reescriben archivos Clausewitz. Un uso en un CSV (ninguno hoy) bloquea con `unresolved_uses`.

## Pruebas pasadas

- `tests.test_schema_rename` con corpus: 51 pruebas, OK.
- `tests.test_schema_*` (12 módulos), `tests.test_locsync`, `tests.test_texts`: OK.
- `tests.test_arch_writes tests.test_i18n tests.test_packaging tests.test_no_paradox_data`: OK.
- `tests.test_ui_entity tests.test_e2e_it4`: OK. `tools/gen_reference.py --check`: sin cambios.
- La batería completa no se corrió (la corre el integrador).
