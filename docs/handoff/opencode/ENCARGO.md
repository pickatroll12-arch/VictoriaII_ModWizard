# Encargo: iteración 4, mitad de núcleo (agente A)

Eres el **agente A** de la iteración 4 de Victoria II Mod Studio. Construyes el **motor de esquemas**
(`core/schema`), los **esquemas** de 7 archivos (`core/schemas`), su **arnés de pruebas** y la **referencia
generada**. No escribes interfaz: los formularios, el editor de entidades, los selectores y las salas los hace
Claude Code después (agente B), sobre tu API pública.

Lee antes de escribir código, en este orden: `docs/handoff/opencode/REGLAS.md`, `docs/handoff/opencode/PRUEBAS.md`,
y de `docs/diseno/wizard.md` las secciones **§3** (invariantes), **§10 entera** (tu especificación: tipos, campos,
entidad, disposiciones, registros, historia, colocación, compañeros, recetas, textos y docgen, con el ejemplo
completo del gobierno en §10.10), **§19.3** (el arnés), **§20** (trabajo con 2 agentes) y **§22, iteración 4**
(entregables y criterios). Para el código existente, `ARCHITECTURE.md` §2.2–2.7. Lo que no esté en §10 lo decides tú
con la opción más conservadora y lo anotas en `INFORME.md` como desviación.

## Qué ya existe y debes usar (no lo reimplementes)

| Necesitas | Está en | Notas |
|---|---|---|
| Árbol Clausewitz sin pérdidas | `core/clausewitz/nodes.py` (`Document`, `Block`, `Entry`, `Scalar`, `ClausewitzDate`) y `parser.parse` → `ParseResult` | Editar con `Block.set/append/insert_before/insert_after/remove_entry/move`: el serializador solo reescribe lo tocado (I3). `Scalar(text, quoted)`. |
| Documentos y transacciones | `core/project/workspace.py` (`Workspace.open/peek/create/delete/replace_model/replace_text/transaction`) y `core/project/project.py` (`Project.edit(label, **fmt)`, `Project.ws`, `Project.vfs`) | `ws.open(rel).model` de un `.txt` es un `ParseResult`. Toda escritura va dentro de **una** transacción: un Ctrl+Z la deshace entera. Abrir un archivo heredado y cambiarlo lo copia al mod al guardar. |
| Ejemplo de edición real | `core/validate/fixes.py` (`_register_tag`, `run_edits`, `current`) | Así se inserta una línea respetando comentarios y se aplica en una transacción. |
| Índice de símbolos | `core/index/index.py` (`SymbolIndex.get/lookup/exists/names/symbols/refs_to/defs_in/attrs`) y `core/index/model.py` (`KIND_GOVERNMENT`, `KIND_CB`, `KIND_BOOKMARK`, `KIND_CULTURE`, `KIND_CULTURE_GROUP`, `KIND_UNIT_TYPE`, `KIND_MODIFIER`, `KIND_REBEL_TYPE`…) | Los extractores de esas familias ya existen en `core/index/extractors/{politics,war,culture,economy}.py`. `Ref`, `FromSymbol` y los usos que bloquean un borrado salen de aquí. **No dupliques extractores**: si un esquema declara `provides=`, comprueba que coincide con el `KIND_*` que ya indexa el extractor. |
| Localización | `core/locsync.py` (`LocSync.ensure(keys, area=)`, `rename`, `delete`, `text`, `missing`, `target_file`) | Se construye en `ui/session.py:534`; en núcleo y pruebas, construye uno igual sobre `project.ws` y `project.vfs`. `LocSpec` crea claves con `ensure`, que escribe en `localisation/00_<prefijo>_<área>.csv`. |
| Validación existente | `core/validate` (91 códigos, reglas por `@rule`, textos `issue.*`/`explain.*`; `model.Problem`) | El motor añade `core/schema/validate.py` con `@validator`; sus problemas usan el mismo `Problem`. Los códigos de esquema (`unknown_field`, `bad_type`, `duplicate_field`, `required_missing`…) siguen la regla de textos de REGLAS.md §4. |
| Reglas del juego | `core/rules/{ids,names,colors,game}.py` | Validación de ids nuevos, colores y nombres reservados. |
| Fixtures | `tests/_minigame.py` (`build_minigame`, `GAME_FILES`) y `tests/_corpus.py` (`vanilla_root()`, `copy_user_mod`) | El minijuego trae `governments.txt`, `cb_types.txt`, `bookmarks.txt`, `cultures.txt`, `rebel_types.txt`, `units/infantry.txt` y `units/frigate.txt`. **No** trae `event_modifiers.txt`. |

## Tus archivos (y solo estos)

```
src/vic2studio/core/schema/{__init__,types,fields,entity,layouts,record,history,placement,companions,recipes,
                            validate,texts,docgen,registry,__main__}.py
src/vic2studio/core/schemas/{__init__,government,casus_belli,bookmark,culture,unit,event_modifier,readonly}.py
src/vic2studio/core/schemas/texts/<kind>.{es,en}.json
tests/schema_harness.py
tests/test_schema_*.py
docs/referencia/**                        (generada, no a mano)
tools/gen_reference.py
docs/handoff/opencode/INFORME.md
```

Además, con cuidado y anotándolo en el informe: **añadir** (nunca cambiar) entradas a `tests/_minigame.py` si un
esquema necesita un archivo que el minijuego no trae (`common/event_modifiers.txt`), y **una** clave por archivo de
textos nuevo en `SMOKE_KEYS` de `src/vic2studio/app.py` (REGLAS.md §5). Nada más fuera de esta lista: si crees que
hace falta tocar otro archivo, anótalo en el informe como petición para Claude y sigue sin tocarlo.

## Fases

Cada fase termina con: las pruebas de la fase en verde, **la batería completa en verde** con Python 3.12
(`OK (skipped=N)`, N ≤ 31 + las tuyas de corpus si no tienes corpus), `INFORME.md` actualizado, un commit y un
`git push -u origin opencode/it4-nucleo`. Si el usuario corta entre fases, no se pierde nada.

### Fase 0 — Orientación (~$5)

1. Comprueba la rama (`git branch --show-current` = `opencode/it4-nucleo`; si no, créala desde la actual).
2. Pasa la batería completa (PRUEBAS.md §1). Debe dar `OK (skipped=31)` sin corpus. Si no, **para** y díselo al
   usuario: el problema es del entorno.
3. Lee lo de arriba. Lee de verdad `core/clausewitz/nodes.py` (la API de edición), `core/project/workspace.py`
   (`transaction`, `open`, `create`, `replace_model`) y `core/validate/fixes.py` hasta `_register_tag`.
4. Rellena en `INFORME.md` la sección «Entorno» (sistema, Python, PySide6, corpus sí/no) y haz commit.

### Fase 1 — Contrato (~$10; esfuerzo alto)

El «paso 0» de §20: las firmas de §10 sin implementar, para que el agente B pueda empezar en paralelo.

- `core/schema/{types,fields,entity,layouts,record,history,placement,companions,recipes}.py`: las dataclasses
  congeladas y los `Protocol` tal como los describe §10 (nombres de §10, firmas con tipos, docstrings en español
  que digan qué hace cada cosa y qué hechos del corpus la motivan). Los métodos con lógica lanzan
  `NotImplementedError`.
- `core/schema/__init__.py`: la API pública (lo que importa el ejemplo de §10.10, más `Record`, `RecordRef`,
  `Entities`, `registry.all_schemas()`, `registry.get(kind)`).
- `core/schema/registry.py`: el descubrimiento por `pkgutil.iter_modules` sobre `core/schemas` ya funcional
  (módulos que exportan `SCHEMAS` y, opcional, `RECIPES`); prueba de que dos esquemas con el mismo `kind` fallan.
- `tests/test_schema_contract.py`: importa todo, comprueba que el ejemplo de §10.10 se **construye** (aunque no
  funcione) y que `core/schema` no importa Qt.
- Un `implemented(func, *args)` en `tests/schema_harness.py` (verdadero si llamar no lanza `NotImplementedError`)
  para que B marque con `skipUnless` las pruebas que dependen de lo tuyo.

Criterio de la fase: el ejemplo de §10.10, copiado tal cual, se construye sin errores.

### Fase 2 — El motor (~$35)

Implementa en este orden, cada pieza con sus pruebas sobre el minijuego antes de pasar a la siguiente:

1. **Tipos** (`types.py`): `parse(scalar|block) -> valor | BadType` y `render(valor) -> Scalar|Block` sin pérdida
   (un `Float` que no cambia conserva su texto original: `1.0` no se reescribe como `1`), `example()` para el arnés.
2. **Campos y entidad** (`fields.py`, `entity.py`): lectura de un bloque a valores por campo; `Opaque` y las claves
   desconocidas se conservan intactas en «Otros campos»; `unknown_field`, `bad_type`, `duplicate_field`,
   `required_missing` como `Problem`.
3. **Disposiciones** (`layouts.py`): como mínimo las que usan tus 7 esquemas (`SingleFile` con `skip`,
   `RepeatedKey` para bookmarks, `GroupedIn` para culturas en sus grupos, `OnePerFile` para unidades). Las demás,
   firmas con `NotImplementedError` y una línea en el informe.
4. **Registros** (`record.py`): `Entities(project, index, locsync)` con `list(kind)`, `get(ref)`, `set(ref, path,
   valor)`, `create(kind, id, *, template=None, based_on=None)`, `duplicate`, `rename`, `delete`. **Cada operación
   es una sola transacción** (incluidos compañeros y claves de localización). `delete` de algo usado (`refs_to`)
   lanza un error con los usos y no toca nada. `set` cambia solo la entrada tocada.
5. **Colocación** (`placement.py`): las 6 reglas de §10.7 (dónde va un registro nuevo).
6. **Compañeros** (`companions.py`): `AppendToList` (peace_order), `MappingTable` (las 14 tablas de
   `rebel_types.txt`), `ActivateUnit`, `UnitNamesSlot`; `RegisterTag` puede quedarse en firma (es de la
   iteración 6). Cada uno con `on_create`, `on_rename` y `on_delete`.
7. **Recetas** (`recipes.py`): `Recipe.plan()` (qué archivos y líneas cambiará, sin tocar nada: I4) y `apply()`.
8. **Historia** (`history.py`): solo si te sobra; ningún esquema de esta iteración la necesita. Si no, firmas.
9. **Validadores** (`validate.py`): `@validator(code, severity)`, `issue(...)` y
   `schema_problems(project, index, *, kinds=None, cancelled=None) -> list[Problem]`, que devuelve el mismo
   `Problem` de `core/validate`. **No los registres con `@rule`** de `core/validate`: `test_validate_rules` exige un
   caso por regla registrada y ese archivo no es tuyo. Conectar `schema_problems` a F7 es trabajo de integración
   de Claude; tú lo dejas listo y probado.

### Fase 3 — Los esquemas y los criterios de núcleo (~$25)

`core/schemas/{government,casus_belli,bookmark,culture,unit,event_modifier,readonly}.py` con sus textos ES/EN y un
`tests/test_schema_<kind>.py` de **3 líneas** cada uno (subclase de `SchemaContract`, §19.3). Antes, el arnés
`tests/schema_harness.py` que genera solas las pruebas de §19.3. Los hechos de cada archivo están en wizard §2
(H16 gobiernos, H17 casus belli…) y §14.9–14.13; las cifras de vanilla en §19.4.

Pruebas de criterio que debes dejar (en `tests/test_schema_criteria.py`; los marcados «corpus» con
`skipUnless(vanilla_root())`):

| Criterio (§22 it. 4) | Qué compruebas |
|---|---|
| 1 (corpus) | 8 gobiernos, 31 CB, 2 bookmarks, 34 grupos y 226 culturas, 21 unidades: 0 `unknown_field` y 0 `bad_type`; abrir y guardar sin cambios no escribe nada |
| 2 (corpus y minijuego) | cambiar `attack` de infantry modifica **una sola línea** de `units/infantry.txt` (compara con `difflib`) |
| 3 (minijuego) | crear `my_cb` lo añade **al final** de `peace_order` y crea sus 4 claves (`my_cb`, `my_cb_desc`, `my_cb_setup`, `my_cb_short`) en `localisation/00_<P>_cb.csv`; borrarlo mientras una guerra lo usa se bloquea y devuelve los usos; un solo `undo` deshace la creación entera |
| 4 (corpus y minijuego) | crear `junta` copia `governments.txt` y `rebel_types.txt` al mod, la añade a las 14 tablas (minijuego: a las que tenga) y crea `junta` y `junta_ruler`; `election = yes` sin `duration` da `government_election_without_duration` |
| 5 | unidades terrestres y navales: **un** esquema con dos `View`; «basada en infantry» crea `units/<id>.txt` y las claves `<id>` y `<id>_short` |
| 6 | `event_modifier` no toca nada de `ui/` y su prueba es una subclase de 3 líneas |

Si un criterio no sale, **no lo marques como hecho**: deja la prueba con `expectedFailure` y explica en el informe
qué falta.

### Fase 4 — Documentación generada (~$10)

`core/schema/docgen.py` (`render_reference(schema, lang) -> str`, `reference_files(lang) -> dict[str, str]`) y
`python -m vic2studio.core.schema doc <kind> [--lang es|en]`, más `check` (valida todos los esquemas
registrados), `list` y `show <kind>` (§10.9). **La CLI escribe solo en la salida estándar**: `test_arch_writes`
prohíbe escribir archivos desde `src/` fuera del diario (REGLAS.md §2). Para la carpeta, un script
`tools/gen_reference.py` (fuera de `src/`, como `tools/screenshot.py`) que escribe `docs/referencia/es/*.md` y
`docs/referencia/en/*.md` con `reference_files`; súbelos. Pruebas: ninguna clave sin traducir (criterio 7),
estable (dos veces da los mismos bytes) y `docs/referencia/` coincide con lo que genera hoy (si cambias un esquema,
se regenera), y `check` sale con 0.

Si al acabar la fase 3 el gasto pasa de **$80**, sáltate esta fase y ve a la 5: la hará Claude.

### Fase 5 — Baterías, informe y entrega (~$10)

1. La batería completa con **Python 3.12 y 3.10** (PRUEBAS.md §2). Con corpus, también con `VIC2_CORPUS`.
2. **Mutantes a mano** (PRUEBAS.md §4): al menos 8, uno por pieza importante del motor (por ejemplo, que `set`
   reescriba el bloque entero, que `create` abra dos transacciones, que `AppendToList` inserte al principio, que
   docgen omita una clave). Cada mutante debe hacer fallar alguna prueba; si sobrevive, añade la prueba.
3. Rellena `INFORME.md` entero, sin adornos: lo hecho, lo que no, las desviaciones de §10 y las dudas.
4. Commit y push. **No abras PR** ni toques `main` ni `claude/keen-fermi-nw8itc`.

## Cuándo parar y preguntar

- La batería falla en la fase 0 → para.
- Te atascas más de 3 intentos en la misma prueba → anótalo en el informe y sigue con lo siguiente.
- Algo de §10 contradice al código existente o al corpus → gana el corpus; anota la desviación y sigue.
- Para cualquier cosa que no sepas decidir, la opción más conservadora (no escribir, no borrar, no cambiar API
  existente) y una línea en «Dudas abiertas».
