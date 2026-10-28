# Informe — Corte vertical del motor de esquemas (`opencode/it4-motor`)

Agente A de la iteración 4 con alcance reducido: contrato de `docs/diseno/wizard.md` §10 e
implementación punta a punta de `government` y `unit` (ENCARGO_MOTOR.md).

## Fase 0 — Orientación

### Entorno

- **Sistema.** Linux (contenedor), fecha 2026-10-28.
- **Rama.** `opencode/it4-motor`, creada desde `claude/keen-fermi-nw8itc` (sin cambios locales).
- **Python.**
  - Del sistema: 3.14.7 (PRUEBAS.md avisa de no usarlo: «nadie ha pasado la batería con él»).
  - Entorno de trabajo: `.venv/` con Python **3.12.13**, PySide6 6.11.2, numpy y Pillow
    (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`). Todo lo que sigue usa
    `.venv/bin/python`. Python 3.10 existe (`~/.local/bin/python3.10`, 3.10.20) pero sin dependencias;
    se preparará en la fase 4 para la doble batería.
- **Corpus.** Disponible fuera del repositorio (no se sube nada de Paradox):
  - juego vanilla: `~/Documentos/VIIMOD_EDITOR/Victoria.II.v3.04.Inclu.ALL.DLC` (con `map/default.map`,
    `common/governments.txt` y las 21 unidades de `units/`);
  - copia del mod grande (VSM / ShagoMod): `~/Documentos/VIIMOD_EDITOR/VictoriaShagoMod_for testing
    purposes (1)/` (raíz de corpus con `VSM/` y `VSM.mod`).
  - Se usarán con `VIC2_GAME` y `VIC2_CORPUS` tal como pide PRUEBAS.md §4; las pruebas de corpus solo
    trabajan sobre copias temporales (`tests/_corpus.py`).

### Línea base

- **Batería de partida** (antes de tocar nada), con el venv de Python 3.12.13: **1498 pruebas,
  `FAILED (failures=4, skipped=32)`**; los 4 fallos son 3 pruebas de disposición de interfaz:
  - `test_ui_palette.BannerTests.test_it_folds_at_1100_px_and_shows_everything_at_1920` (es y en, cuenta doble);
  - `test_ui_smoke.MainWindowTests.test_rail_is_a_column_with_room_and_a_strip_when_narrow`.
  Con Python 3.14.7 del sistema el resultado es el mismo (mismos 3 fallos).
- **Diagnóstico.** Son exactamente los fallos que PRUEBAS.md §5 declara como «fallos conocidos que no
  son tuyos»: miden que un texto «cabe» con las fuentes DejaVu del sistema; en este entorno las
  familias serif del tema no están (o gana otra, p. ej. Noto Serif, antes que DejaVu Serif) y las
  métricas difieren. No tocan `core/` ni el motor de esquemas. Se anotan y **no se darán por buenas**
  (Claude las pasa en su entorno de referencia): la línea base a vigilar en las fases siguientes es
  «1495 verdes + estos 3 fallos de disposición + 32 omitidas», y toda prueba nueva debe estar en verde.
- Las omitidas son 31 de corpus + 1 de empaquetado (PRUEBAS.md §3); con corpus quedarán menos.

### Lectura realizada

- `AGENTS.md`, `REGLAS.md` y `PRUEBAS.md` enteros; `ENCARGO.md` (tabla «Qué ya existe y debes usar»).
- `docs/diseno/wizard.md`: §2 (H16, H18), §3, §10 entera, §14.4/§14.11/§14.12, §19.3, §22 (iteración 4).
- `ARCHITECTURE.md` §2.2–2.7.
- Código real: `core/clausewitz/nodes.py` entero (API de edición sin pérdidas: `Block.set/append/
  insert_before/insert_after/remove_entry/move`, `Entry`, `Scalar`), `core/project/workspace.py`
  entero (`transaction`, `open`, `create`, `touch`, `delete`, `undo`, `save`), `core/validate/fixes.py`
  hasta `_register_tag` (patrón bytes efectivos → `replace_text` en una transacción), más la API de
  `core/locsync.py` (`LocSync.ensure/rename/delete/target_file`) y `core/index/index.py`
  (`SymbolIndex.refs_to/exists/get/attrs`).

### Notas que condicionan el trabajo

- `history.py` y `recipes.py` quedan solo como contrato (firmas de §10 que lanzan
  `NotImplementedError`); ni `government` ni `unit` los necesitan.
- `tests/_minigame.py` ya trae `governments.txt`, `rebel_types.txt` y `units/{infantry,frigate}.txt`
  (fixtures sintéticos inventados); los criterios 1, 2 y 4 usan el corpus real sobre copias.
- El corpus real gana sobre §2/§14 en caso de conflicto; cualquier desviación se anota aquí.

## Fase 1 — Contrato (hecho)

**Entregado.** `core/schema/` con las firmas de §10.1–10.8, dataclasses congeladas, docstrings
en español y `NotImplementedError` donde no hay lógica todavía:

- `types.py`: `ValueType` (read/write/check/example/describe), `Int`, `Float`, `Bool`, `Date`,
  `Word`, `Text`, `Enum`, `Ref`, `Color`, `ListOf`, `Path`, `LocKey`, `SpriteFrame`, `Picture`,
  `FromSymbol` y `from_spec`.
- `fields.py`: `MISSING`, `Field`, `Group`, `DynamicKeys`, `Values`, `Children`, `Script`,
  `Opaque`, `Section`, `FieldLike`, `Condition`/`When`, `SetOps`, `Scope`, `REMAINING_BLOCKS`.
- `entity.py`: `LocSpec`, `HistorySpec`, `Variant`, `View`, `EntitySchema`, `IdSpec`
  (KEY/FIELD/FILE/COMPOSITE), `IdRule` (WORD/TAG/SNAKE/INT_RANGE).
- `layouts.py`: `FileLayout` (Protocol, merge=LoadMode de la VFS), `BlockPath`, `SingleFile`,
  `OnePerFile`, más `PairedKeys`/`RepeatedKey`/`GroupedIn`/`Registry`/`NestedIn`/`TypedEntries`/
  `KeyedAcross`/`Table`/`Descriptor` como contrato.
- `record.py`: `RecordRef`, `EntitySummary`, `Record` (API fija + los métodos extra de §10.5),
  `Entities`, `InvalidIdentError` (con `.code`) y `EntityInUseError` (con `.uses`).
- `history.py` y `recipes.py`: solo contrato (como pide el encargo). `placement.py`: `SchemaOrder`
  e `insertion_index`/`registry_index` (reglas de §10.7).
- `companions.py`: `Companion` (Protocol), `EditContext`, `RegisterTag`, `AppendToList`,
  `MappingTable` (con `Ask()`), `ActivateUnit`, `UnitNamesSlot`.
- `validate.py`: `@validator(código, gravedad)` (gravedad ES/EN por Severity de core.clausewitz),
  `issue(código, rec, field=…)` → `Problem` de `core/validate/model.py`, `CheckContext`.
- `registry.py`: descubrimiento por `pkgutil` sobre `core/schemas` (módulos con `SCHEMAS` y,
  opcional, `RECIPES`), `registry.get(kind)` (`KeyError`), `registry.all_schemas()`, dos esquemas
  con el mismo `kind` → `ValueError`. Paquete `core/schemas/__init__.py` creado.
- `tests/test_schema_contract.py`: 10 pruebas en verde — la API pública fija importa, el ejemplo
  de §10.10 se construye (con prefijo `contract_` en los códigos de validador para no chocar con
  los reales del esquema `government`; se explica en el docstring), `core/schema` no importa Qt
  (subproceso), dos esquemas con el mismo `kind` fallan y el contrato no implementado lanza
  `NotImplementedError`.

**Reglas.** Las 4 pruebas de reglas pasan (`test_arch_writes test_i18n test_packaging
test_no_paradox_data`: `OK (skipped=1)`), así que el paquete nuevo respeta las capas, la sintaxis
3.10 y los textos.

**Batería completa al cerrar la fase.** 1508 pruebas, `failures=5`: los 4 de la línea base
(3 pruebas de disposición por fuentes) + 1 que no quedó identificado (el registro solo guarda el
final del pipeline y la máquina estaba cargada durante la pasada). `tests.test_schema_contract`
pasa entero en solitario y el contrato no toca nada fuera de `core/schema` y su prueba, así que lo
más probable es el fallo de latencia conocido de PRUEBAS.md §5; se confirma en la batería de
cierre de la fase 2.

## Fase 2 — Motor (hecho)

- **Tipos** (`types.py`): `Int`, `Float`, `Bool`, `Word`, `Text`, `Enum`, `Date` con lectura y
  escritura sin pérdidas. `Float.write` conserva los decimales del texto anterior (``4.00`` → 5
  → ``5.00``; ``8`` → 9 → ``9``, como en vanilla). `FromSymbol.resolve` usa el índice.
  `Ref.read/write/check` parcial (sus esquemas no lo usan aún); `Color`, `ListOf`, `Path`,
  `LocKey`, `SpriteFrame`, `Picture` y `from_spec` siguen como contrato.
- **Campos, secciones, dinámicos, variantes y vistas** (`record.py`): `Record` implementa la API
  fija (`get/set/dynamic/set_dynamic/unknown/issues/loc_keys`) más `node/get_all/add/remove/
  group(s)/add_group`; `issues` emite `duplicate_field` (código de core/validate),
  `bad_type`, `required_missing` y `unknown_field` y corre los validadores del esquema.
  `DynamicKeys` suelto vive en la raíz (gobierno); el de un `Group` (``build_cost``,
  ``supply_cost``), en el bloque del grupo. `Variant` añade los campos de la variante activa
  según ``type``; `View` filtra `list`. Toda mutación pasa por `ws.touch` (transacción de quien
  llama); leer no escribe (I4).
- **Disposiciones** (`layouts.py`): `SingleFile` (gobiernos: lo nuevo al final del documento) y
  `OnePerFile` (unidades: archivo nuevo ``units/<id>.txt``, id del nombre con el regex).
- **Colocación** (`placement.py`): `insertion_index` (orden del esquema + bloques fechados),
  `dynamic_insert_index` (tras la última clave del catálogo) y `registry_index`.
- **`Entities`** (`record.py`): `list` (índice, vista efectiva, filtro por vista), `open`
  (documento efectivo, registro por el layout), `create`/`duplicate`/`delete` en una transacción
  propia con archivo + compañeros + claves (un `undo` lo deshace todo, I5), `where_used`.
  `InvalidIdentError` (empty/bad_chars/taken) y `EntityInUseError` (con `.uses`) sin efectos.
- **`validate.py`**: `@validator`/`issue` sobre el `Problem` real; `SEVERITY_FALLBACK` para los
  códigos del motor (unknown_field aviso, bad_type/required_missing error; duplicate_field aviso,
  como en core/validate).
- **`companions.py`**: `MappingTable` real (la matriz de rebeldes: tablas en cualquier nivel —
  en vanilla están anidadas bajo cada tipo de rebelde, no en la raíz como decía H16 —; crear
  añade la clave a todas con el propio id como destino propuesto, borrar la quita, `check` da
  `government_missing_in_rebel_map`). El resto de compañeros, contrato.
- **Errores encontrados y corregidos al probar**: `create`/`duplicate` mutaban el documento sin
  `ws.touch`, con lo que la transacción no capturaba el archivo (ni undo ni guardado lo veían):
  corregido y cubierto por los criterios 3 y 4.

## Fase 3 — Esquemas y criterios (hecho)

- **`core/schemas/government.py`**: el ejemplo de §10.10 tal cual, con `government_without_ideology`
  (error, nuevo) y `government_election_without_duration` (aviso, código y textos de
  core/validate; caso real de VSM `absolute_monarchy`), compañero `MappingTable` y plantilla.
- **`core/schemas/unit.py`**: campos comunes + `Variant` por ``type`` (land/naval) + dos `View`;
  `build_cost`/`supply_cost` como `Group` con `DynamicKeys` de bienes; el esquema cubre las 21
  unidades de vanilla sin `unknown_field` ni `bad_type` (verificado contra el corpus).
- **Textos** (`core/schemas/texts/`): `schema`, `government` y `unit` × `es/en` (paridad 435/435,
  sin duplicados con los existentes). Desviación de §10.9: las etiquetas de los valores `Enum`
  son `schema.<kind>.enum.<campo>.<valor>` (la dataclass `Enum` no lleva nombre propio).
- **`tests/schema_harness.py`**: `SchemaContract` (§19.3) con textos, abrir-guardar-sin-cambios,
  set de cada campo, dinámicos, plantilla válida, claves de localización, compañeros, colocación
  y conformidad con el corpus (0 `unknown_field`, 0 `bad_type`). `test_docgen` no se genera:
  `docgen` no está en la lista de archivos del corte (petición para Claude).
- **`tests/test_schema_government.py` / `test_schema_unit.py`**: subclases de 3 líneas.
- **`tests/test_schema_criteria.py`**: los 6 criterios — con corpus: 8 gobiernos + 21 unidades
  conformes y sin escritura al leer (1); `set attack` de infantry cambia una sola línea, CRLF y
  comentarios intactos (2); clave desconocida y comentario sobreviven a `set` de
  `maximum_speed` y ``4.00`` queda ``5.00`` (6). Con minijuego: `duplicate(infantry, my_unit)`
  crea `units/my_unit.txt` y las claves en una transacción, undo lo quita todo (3);
  `create("government", "junta")` copia governments.txt al mod con junta al final, crea las
  claves y `election=yes` sin `duration` da el aviso (4); `delete(infantry)` bloquea con el
  `activate_unit` de la tecnología y borrar `my_unit` funciona y se deshace (5).
- **`SMOKE_KEYS`** de `src/vic2studio/app.py`: una clave por archivo de textos nuevo (3), único
  cambio fuera de la lista (permitido por REGLAS.md §5).

**Resultado con corpus**: `tests.test_schema_*` al completo en verde (24 pruebas + criterios),
incluida la conformidad con el corpus real.

## Fase 4 — Cierre (hecho)

**Mutantes a mano (PRUEBAS.md §6), 12 piezas, todos matados por las pruebas:**

1. `Float.write` sin conservar decimales → `test_criterion6_unknown_and_comment_survive` (5.00).
2. `Bool.write` con yes/no invertidos → `test_set_each_field` del arnés (roundtrip «lo escrito se lee igual»).
3. `Record.set` insertando al principio → `test_placement` del arnés.
4. `SingleFile.insert` al principio → `test_placement` + criterio 4 (junta al final).
5. `Variant` con clave «sea» en vez de «land» → `test_corpus_conformance` de unit (con corpus).
6. Validador `government_without_ideology` con la condición invertida → `test_template_validates`.
7. `only_true` escribiendo en vez de borrar → `test_dynamic_keys` del arnés.
8. `create` con las claves de localización en otra transacción (dos pasos) → criterio 4 (una sola).
9. `create` sin las claves de localización → criterio 4.
10. `duplicate` sin `ws.touch` → criterio 3 (el deshacer no lo quita todo).
11. `MappingTable` añadiendo solo a la primera tabla → `test_companions` del arnés.
12. `delete` sin comprobar los usos → criterio 5.

**Baterías.** Resultados de cierre (los fallos ajenos se confirman en la rama base con el mismo
entorno y corpus):

- Línea base: 4 fallos de disposición de UI por las fuentes del sistema (PRUEBAS.md §5).
- `test_tasks...garbage_frozen...`: falla igual en la rama base (Python 3.12 + PySide6 por pip,
  el caso declarado en PRUEBAS.md §5).
- `test_ui_integration...validating_a_large_file...`: latencia; con 3.12 pasa en solitario; con
  3.10 falla también en solitario y en la rama base (es de la máquina, no del corte).
- Con corpus: `test_modcheck.UserModTests`, los dos de VSM de `test_ui_integration` y los
  aleatorios de `test_clausewitz_edit`/`test_clausewitz_fuzz` fallan **también en la rama base**
  con este corpus: la copia local del VSM ya no tiene los dos bloques sin cerrar de H14 (el
  usuario la ha cambiado o es otra versión) y algún archivo del juego local difiere del de
  referencia. No son de este corte.
- Incidente propio, corregido: un mutante restaurado en el mismo segundo dejó un `.pyc` con el
  bytecode mutado y una batería intermedia corrió con él; se limpia `__pycache__` y las
  baterías de cierre corren con `-B`. Ninguna prueba quedó rota.

- **Batería de cierre con Python 3.12** (`.venv`, `-B`, caché limpia): 1532 pruebas,
  `failures=4`, `skipped=38` — los 4 son de línea base/entorno: 3 de disposición por fuentes y
  `test_tasks...garbage_frozen...` (falla igual en la rama base, PRUEBAS.md §5). Ninguno del corte.
- **Batería con Python 3.10** (`.venv310`, PySide6 6.11.3, `-B`): 1532 pruebas, `failures=4`,
  `skipped=38` — 3 de disposición por fuentes y
  `test_ui_integration...validating_a_large_file...` (latencia; falla también en solitario y en
  la rama base con 3.10: es de la máquina, no del corte). Con 3.10, `test_tasks` pasa.

## Desviaciones de §10, decisiones y peticiones

**Desviaciones (anotadas, con su porqué):**

1. Las etiquetas de los valores `Enum` son `schema.<kind>.enum.<campo>.<valor>`
   (p. ej. `schema.unit.enum.type.land`): la dataclass `Enum(*values)` de §10.2 no lleva nombre
   propio, así que no hay «<enum>» que usar como sugiere §10.9; el nombre del campo lo
   distingue sin colisiones.
2. `MappingTable` busca las tablas en cualquier nivel del archivo: en vanilla están **anidadas**
   bajo cada tipo de rebelde (`reactionary_rebels = { government = { … } }`), no en la raíz
   como dice H16 (verificado en el corpus).
3. `test_docgen` del arnés (§19.3) no se genera: `docgen` y `__main__` no están en la lista de
   archivos del corte (se pide abajo).
4. `Record.get` de un valor que no encaja con su tipo devuelve el texto crudo en vez de lanzar:
   el `bad_type` lo reporta `issues` con su línea, y los validadores del esquema no abortan.

**Decisiones de diseño (razonadas):**

1. `DynamicKeys` suelto vive en la raíz del registro (gobierno: las ideologías); el de un
   `Group` vive en el bloque del grupo (`build_cost`/`supply_cost` son `Group` con `fields=()` y
   `dynamic`). Así se cubren los dos usos reales sin añadir campos a la dataclass de §10.2.
2. `dynamic()` devuelve todas las claves no fijas del bloque destino, estén o no en el índice:
   la vista refleja el archivo (I6, I7) y el catálogo del índice queda para el widget.
3. Los compañeros no corren en `duplicate` (el `Companion` no tiene `on_duplicate`); las claves
   de localización se copian de la localización efectiva (los idiomas con texto).
4. Ids nuevos (`IdRule.WORD`): `[A-Za-z][A-Za-z0-9_]*`; códigos `empty`, `bad_chars`, `taken`.
5. `Float.write` con 0 decimales previos escribe entero («8», como vanilla) y con N decimales,
   con N («4.00» → «5.00»).
6. `SingleFile.insert` añade al final: la clave es el id y no tiene orden de esquema (H16, y así
   lo hace el usuario). El orden del esquema se aplica a las claves de dentro de un bloque.
7. «Leer no escribe» se comprueba en cada prueba del arnés y de los criterios (issues, get,
   dynamic + `save().nothing_to_save`).

**Peticiones para Claude (fuera de la lista de archivos del corte):**

1. `core/schema/docgen.py` y `__main__.py` (§10.9): generación de `docs/referencia/`, CLI
   `check/list/show`, y con ellos el `test_docgen` del arnés.
2. Compañeros de unidades (§14.4, §14.12): `ActivateUnit` (ver/cambiar la tecnología que la
   activa) y `UnitNamesSlot` (lista de nombres navales), hoy contrato.
3. Validación `unit_never_active` (§14.4, info) y `min_port_level` frente al `max_level` de
   `naval_base` (§14.12): quedan fuera de los criterios del corte.
4. Etiquetas `undo.*` de otros esquemas futuros: la convención es
   `undo.<crear|duplicar|borrar>_<kind>` con textos en `schema.{es,en}.json`.

**Dudas para el usuario / a verificar en el juego:**

1. `active` falta en `manowar`, `frigate` y `clipper_transport` de vanilla: lo trato opcional
   (sin valor por defecto). ¿El juego asume `yes`?
2. Ídem `floating_flag` (falta en algunos): ¿asume `no`?
3. `government_election_without_duration` ya existía en `core/validate` como aviso; el esquema
   reutiliza ese código y sus textos (no se duplican).

## Corrección tras la revisión

Sobre la misma rama, un commit por punto, cada uno con su prueba:

- **B1 (`38b0f39`).** `Entities.list` y la comprobación de id ocupado siguen la vista efectiva
  (I7): los documentos abiertos con cambios (nuevos, sucios o borrados) se enumeran con el
  layout sobre el documento efectivo y ganan sobre el índice. Ocho pruebas nuevas (los cuatro
  casos con `unit` y con `government`): lo creado sin guardar sale; un segundo
  `create`/`duplicate` lanza `InvalidIdentError("taken")` sin efectos; borrar y deshacer lo
  quita y lo devuelve; `ws.delete` de un archivo del mod lo quita.
- **B2 (`672e99e`).** Las claves de un `DynamicKeys` son solo las de su `key_kind` en el índice
  (`Record` recibe el índice): `electoin = yes` da `unknown_field` y no cuenta como ideología.
  El arnés de dinámicos usa una clave real del catálogo y el conformance del corpus cataloga
  ideologías y bienes con el índice real.
- **M1 (`d44d1b1`).** `duplicate` ejecuta el `on_create` de los compañeros en su transacción:
  duplicar un gobierno añade la clave a las 2 tablas del minijuego y a las 14 de vanilla
  (`duplicate(democracy, "democracia2")`), y un undo lo quita todo.
- **M2 (`062c421`).** `duplicate` conserva el formato del origen: `Block.clone` es «sin formato
  de origen» por diseño (tokens privados), así que se reparsea el texto del documento y se toma
  la entrada homóloga con sus tokens leídos; el bloque duplicado es byte a byte el original
  salvo la clave (líneas en blanco y sangría incluidas).
- **Huecos (`0ce0019`).** Tres pruebas nuevas: el comentario de final de línea
  (`election = yes  # election = no`, H14) sobrevive a `set` de otro campo; las vistas dan 11
  unidades land y 10 naval en vanilla sin solaparse; y `attack = abc` en una unidad sintética
  da `bad_type`.

**Mutantes de la corrección.** Repetidos los 12 del cierre y añadidos tres, todos matados:
`list` sin la vista del Workspace (B1), `DynamicKeys` aceptando cualquier clave (B2) y
`duplicate` sin compañeros (M1).

**Baterías.** Con `-B` y caché limpia:

- **3.12**: 1535 pruebas, `failures=5` — los de línea base/entorno (3 de disposición por
  fuentes, `test_tasks` de PRUEBAS.md §5 verificado en la rama base, y el de latencia de
  `test_ui_integration`). **Ninguno del corte.**
- **3.10**: 1535 pruebas, `failures=4` — 3 de disposición y el de latencia (falla también en
  la rama base con 3.10). **Ninguno del corte.**
- Con corpus: las 50 pruebas del motor (criterios, arnés con conformidad, vista efectiva y
  correcciones) en verde, incluidas las 14 tablas de M1 y el formato de M2.

## Fases siguientes

(Ninguna: corte terminado.)
