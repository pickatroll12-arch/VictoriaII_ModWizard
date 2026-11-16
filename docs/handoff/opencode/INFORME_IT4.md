# Informe — Iteración 4 completa (`opencode/it4-claude`)

Encargo: `docs/handoff/opencode/ENCARGO_IT4.md` (commit `9927674`). Una sola sesión de OpenCode hace de los dos
agentes de wizard §20, por fases.

## Fase 0 — Orientación

### Entorno

- **Sistema.** Linux (Fedora/KDE, sin contenedor), 28-10-2026.
- **Rama.** `opencode/it4-claude`, creada desde `9927674` (`claude/keen-fermi-nw8itc`): es `main` con el PR #12
  fusionado más el commit del handoff (`main` aún no lo trae), así que el código de partida es el de `main`.
- **Python.** `.venv` con 3.12.13 (PySide6 por pip) y `.venv310` con 3.10.20. El del sistema es 3.14.7 y no se
  usa para las baterías (PRUEBAS.md §2).
- **Corpus.** Copia local del usuario, descomprimida **fuera** del
  repositorio, en `~/vic2corpus/{vanilla,Plantilla Mod,ShagoMod}` (8 861 archivos en `vanilla`), como dice
  CONTINUAR §4. Las pruebas de corpus usan
  `VIC2_CORPUS="$HOME/vic2corpus/vanilla:$HOME/vic2corpus/Plantilla Mod:$HOME/vic2corpus/ShagoMod"` y solo
  trabajan sobre copias temporales.

### Línea base (antes de tocar nada)

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests` sin corpus:

```text
Ran 1588 tests in 239.435s
FAILED (failures=4, skipped=41)
```

No es el `OK (skipped=40)` de referencia, pero las diferencias son todas del entorno y ya estaban en los
informes anteriores (INFORME_MOTOR y INFORME_EDITOR, misma máquina):

| Prueba | Motivo |
|---|---|
| `test_ui_palette.BannerTests.test_it_folds_at_1100_px_and_shows_everything_at_1920` (es y en) | Disposición: «saveButton recortado» con las fuentes del sistema (PRUEBAS.md §5). |
| `test_ui_smoke.MainWindowTests.test_rail_is_a_column_with_room_and_a_strip_when_narrow` | Disposición: «Regiones» recortado en la franja (PRUEBAS.md §5). |
| `test_tasks.GarbageCollectorTests.test_garbage_frozen_with_a_large_result_is_collected_once_it_is_released` | Python 3.12 + PySide6 por pip (PRUEBAS.md §5). |
| 1 omitida de más | `hace falta poder crear una carpeta en la raíz del disco`: esta máquina no deja crear carpetas en `/`. |

El usuario pidió trabajar sin pausas, así que en vez de parar (como dice «Cuándo parar») lo anoto aquí y tomo
como línea base a vigilar «1584 verdes + esos 4 fallos de entorno + 41 omitidas». Ninguna prueba de disposición
se da por buena en este entorno: Claude las pasa en el de referencia.

### Lectura

AGENTS, REGLAS, PRUEBAS, CONTINUAR (§0, §3, §5.4 y §6 enteros), wizard §0, §3, §10, §13, §14.4, §14.9–14.13,
§19.3, §19.5, §20, §22 y §24, ARCHITECTURE §2 y §5, `INFORME_MOTOR.md` e `INFORME_EDITOR.md` enteros, y el
código: `core/schema/**`, `core/schemas/**`, el arnés, `ui/session.py`, `ui/halls/**`, `ui/shell/hall.py`,
`ui/main_window.py`, `ui/viewers/script_editor.py`, `ui/halls/project/{files,descriptor}.py`,
`core/project/workspace.py` (transacciones, LRU, `revert`, `restore_bytes`, guardado) y
`core/validate/{validator,context}.py`.

## Decisiones de diseño 1–4

### 1. De dónde salen las secciones

Las secciones de entidades salen del **registro de esquemas**: `ui/halls/registry.discover_halls` añade a cada
sala una `SectionSpec` por esquema editable con `hall` y `section` (una por `View` si el esquema tiene vistas),
con `order` = `EntitySchema.order` (+ el índice de la vista), el icono del esquema, el título
`schema.<kind>.title` (o `schema.<kind>.view.<vista>`) y como `factory` el `EntityEditorPage` del esquema. Si la
sala ya declara una sección con esa clave (las planificadas de las listas `SECTIONS`), **la del esquema la
sustituye**. Así:

- las claves de las capturas y de la hoja de ruta se conservan: `nations:cultures`, `nations:governments`,
  `war:bookmarks`, `war:cb`, `war:land`, `war:naval` y `events:modifiers`. Para eso `unit` declara sus vistas
  con `section="land"` y `"naval"` (antes `units_land`/`units_naval`, que nadie más usaba);
- las tarjetas planificadas se quedan en las listas como **reserva**: sin el esquema (por ejemplo, quitando
  `event_modifier.py`), la sección vuelve a ser la tarjeta «en desarrollo», y sus textos siguen en uso;
- añadir `event_modifier` no tocó ningún archivo de `ui/` (criterio 6, con prueba que lo comprueba).

Las pruebas de la hoja de ruta que listaban esas secciones como planificadas (`test_ui_roadmap`,
`test_ui_smoke`) se actualizan de forma explícita en la fase 4.

### 2. La pestaña Código

Se reutiliza **`ScriptEditor` sin cambiarlo**, sobre el archivo entero de la entidad, con el cursor y el scroll en
la línea del bloque. Editar allí es `replace_text` (que es `replace_model` con el códec) con `merge_key` por
archivo, empalme sin pérdidas y deshacer de la aplicación: todo lo que ya garantizan sus pruebas. Acotarlo al
bloque obligaría a reescribir el empalme (el bloque cambia de posición al editar) y a duplicar la lógica de solo
lectura; con el archivo entero el modder ve además el contexto. El formulario se vuelve a enlazar con
`documentsChanged` cuando el texto cambia.

### 3. Los problemas de esquema en F7

`core/schema/validate.schema_problems(ctx)` recorre los registros de cada esquema editable sobre el
`ValidationContext` (instantánea inmutable con lo sin guardar, I12) y devuelve sus `Problem`
(`bad_type`, `unknown_field`, `required_missing`, los validadores propios y los compañeros que no necesitan el
`Workspace`). Los de archivos que no son del mod salen `inherited` (I11). `Session` los añade al informe en la
misma tarea de validación (`ValidationEngine.validate`), sin tocar `core/validate/**`: `test_validate_rules`
sigue exigiendo un caso por `@rule` y no ve reglas nuevas. Un problema de esquema que repite uno global (mismo
código, archivo y línea o entidad, como `government_election_without_duration`) se descarta. Salen en F7 y en
el panel con su texto `issue.<código>`, su «¿Por qué?» (`explain.title/outcome.<código>`) y, al abrirlos, llevan
a la entidad y al campo.

### 4. El índice tras guardar

Hoy `Session` reindexa con retraso (`REINDEX_DELAY_MS`) y el guardado no pide reindexar nada (solo marca un
cambio estructural), así que entre guardar y releer el índice no conoce lo creado. `Entities.list` ya no superpone
solo los documentos con cambios, sino **todos los documentos abiertos del layout** (también los limpios, que son
justo lo recién guardado): la vista sale bien aunque el índice vaya por detrás, y cuando el `Workspace` expulsa un
documento limpio de su LRU el índice ya lo tiene. Prueba: `EffectiveAfterSaveTests` (crear, guardar y listar con el
índice viejo) y la de punta a punta.

## Fase 1 — El resto del núcleo



**Entregado.**

- **Disposiciones** (`core/schema/layouts.py`): `RepeatedKey` (bookmarks, id en `name`), `GroupedIn` de nivel 0
  y 1 (grupos e hijos: culturas, ideologías, bienes, reformas), `NestedIn` con contenedor raíz (tecnologías e
  invenciones). Todas dan además `touches(rel)` y `context_rels(ctx)`. Ayudantes `entry_path`, `parent_block` y
  `follow_path` para seguir un bloque dentro de un grupo (duplicar con formato y re-enlazar un `Record`).
- **Tipos** (`types.py`): `Color` y `ListOf` editan su bloque **en su sitio** (añadir un nombre a `first_names`
  toca una línea; lo que sigue conserva sus comillas), `Path`, `LocKey`, `SpriteFrame`, `Picture` y `from_spec`.
  `Text` pone comillas solo si hacen falta (o si ya las tenía).
- **`Record`**: `children()`, claves de `Script`/`Opaque` como cubiertas, catálogo abierto (`OPEN_CATALOG`) para
  los efectos de los modificadores, `unknown="keep"` para los catálogos de solo lectura, compañeros en `issues`,
  validación antes de `touch` (un valor que no encaja no ensucia nada) y re-enlace: si el documento ya no es el
  abierto (LRU) o es una lápida, mutar lo vuelve a abrir, reviviéndolo.
- **`Entities`**: vista efectiva con todos los documentos abiertos (decisión 4); lápida de una copia del mod que
  deja ver el archivo del juego; `restore_vanilla` (§10.5) en sus tres casos; `origin_of` (cintas de §13.5);
  `parent`; `where_used` sin las referencias que mantienen los propios compañeros (`own_roles`: `peace_order`, las
  filas de la matriz); `ReadOnlySchemaError` en los esquemas `editable=False`; crear en un grupo
  (`InvalidIdentError("no_group")` sin efectos); `build_block` como función del módulo (la usa docgen).
- **Compañeros**: `AppendToList` (al final de la lista; borrar quita todas las apariciones), `ActivateUnit`
  (`sources`, `activate_in` y `unit_never_active`, información), `UnitNamesSlot` (`candidates`, `add_to`; crear no
  cambia nada solo) y `MappingTable.rows`/`set_target` para la matriz de rebeldes de la interfaz.
- **Esquemas** con textos ES/EN y su prueba de 3 líneas: `casus_belli` (31 en vanilla, 5 secciones, 18 `po_*`,
  guion como `Script`, `cb_remove_cores_needs_transfer`), `bookmark` (`bookmark_date_outside_defines`, también en
  segundo plano), `culture` y `culture_group` (`culture_name_not_cp1252`), `event_modifier` (fragmento sintético
  en `tests/_minigame.py` como `SCHEMA_GAME_FILES`, solo añadido) y `readonly` (6 catálogos). `unit` gana sus dos
  compañeros y plantilla, y sus vistas pasan a las secciones `land`/`naval` (decisión 1).
- **`defines.lua`** (en `core/schemas/bookmark.py`): `read_defines`, `define_date` y `set_define_date`, que cambia
  solo el token y entra con `restore_bytes` (el archivo aún no tiene códec propio y `test_project_codecs` exige
  que siga siendo binario).
- **Validación en segundo plano** (`schema_problems`, decisión 3) y su conexión en `ui/session.py`
  (`with_schema_problems`).
- **docgen y CLI**: `core/schema/docgen.py` (`render`, `render_index`, `missing_keys`, `reference`),
  `python -m vic2studio.core.schema list|show|doc|check` (salida estándar; `check` no escribe) y
  `tools/gen_reference.py` (escribe `docs/referencia/{es,en}/`, 14 páginas por idioma; `--check` para la prueba).
- **Arnés**: `test_docgen`, `test_list_finds_records`, compañeros genéricos (matriz y lista), colocación al final
  del archivo, del grupo o de la lista, creación saltada en los de solo lectura. Las subclases importan el módulo
  (`schema_harness.SchemaContract`) para que la clase base no se cuente como omitida en cada archivo.
- **Pruebas nuevas**: `test_schema_{casus_belli,bookmark,culture,event_modifier,readonly,it4}.py` y la clase
  `It4CriteriaTests` de `test_schema_criteria.py` (criterios 1, 3, 6 y 7).

**Pruebas existentes que cambian (y por qué).**

- `test_schema_contract.test_unimplemented_contract_raises`: exigía `NotImplementedError` a los hijos, los tipos
  ricos y `from_spec`, que ahora tienen lógica. Sigue exigiéndolo a la historia y el guion, y además comprueba
  que los tipos rechazan con `ValueError` lo que no encaja.
- `test_schema_effective.test_ws_delete_of_the_mod_governments_file_removes_it_from_the_list`: exigía una lista
  vacía tras borrar la copia del mod, que era el límite de CONTINUAR §6. Ahora exige los gobiernos del juego y no
  el de la copia (lo que cargaría el juego, I7).

**Batería de la fase** (3.12, sin corpus, `-B`): 1744 pruebas, `FAILED (failures=4, skipped=52)`: los mismos 4
fallos de entorno de la línea base. Con corpus, `test_schema_*` (177 pruebas) en verde, también la conformidad
de los esquemas nuevos con vanilla. Las de reglas (`test_arch_writes test_i18n test_packaging
test_no_paradox_data test_validate_rules`) en verde.

**Gasto aproximado:** fases 0 y 1, unos 25 USD.

## Fase 2 — Contrato de la interfaz

Las firmas de §13.6–13.7 quedan escritas y probadas antes de los formularios (y las fases 3 y 4 construyen sobre
ellas sin cambiarlas):

- `ui/forms/editors.py`: `FieldState`, `FieldEditor` (`set_value`, `value`, `set_default`, `set_read_only`,
  `commit_pending`, señal `value_committed`), el registro `EDITORS` con un editor por `ValueType.widget` (los 14) y
  `editor_for`.
- `ui/forms/form.py`: `FormBuilder(session, mode).build(schema, ref)` y `EntityForm` (`bind`, `focus_field`,
  `set_mode`, `commit_pending`, `retranslate`; señales `record_changed`, `code_requested`, `status_requested`).
- `ui/entity/navigator.py`: `EntityNavigator` (`refresh`, `current_ref`, `select`; señales `current_changed`,
  `new_requested`, `duplicate_requested`, `delete_requested`, `restore_requested`) y
  `ui/entity/editor_page.py`: `EntityEditorPage` y `entity_section_factory`.
- `ui/pickers`: `SymbolPicker`, `DateEdit`, `ColorField`, `GoodsAmountsField`, `NameListEditor` y
  `SpriteFramePicker`, todos con `value()`, `set_value()`, `value_committed` y `retranslate()`.

Pruebas de que se construyen: `test_ui_forms.ContractTests` (cada widget de cada campo de cada esquema tiene
editor; los editores se construyen sin proyecto) y `test_ui_pickers` (cada selector).

Desviación de §13.6: los números se editan en una línea con validador, no en `QSpinBox`: así «vacío» (sin valor,
el juego usa su valor por defecto) es un estado real.

## Fase 3 — Formularios y selectores

- **`Section`** es una tarjeta de pergamino plegable (`SectionCard`); **`Field`**, una fila «Etiqueta (clave)»
  (P4) con la ayuda como tooltip; el valor por defecto del juego sale en gris (texto de ayuda del editor o la
  casilla de tres estados «Sin valor (el juego usa «Sí»)»); `advanced` se oculta en modo sencillo y `focus_field`
  pasa a avanzado si hace falta; `visible_if` (la duración solo con elecciones) y las variantes (la tarjeta naval
  solo en las navales) se aplican al enlazar.
- **Claves dinámicas**: casillas (`DynamicChecklist`, ideologías, `only_true`), tabla de bienes
  (`GoodsAmountsField` para los `Group` con dinámicas: costes de las unidades) y tabla clave/valor
  (`DynamicTable`, catálogo abierto de los modificadores).
- **Guion**: `CodeOnlyEditor`, botón «Editar como código…» que abre la pestaña Código en la línea del bloque.
- **Campos de localización**: la pestaña Textos (`LocTextsPanel`, fase 4) edita las `LocSpec` en ES y EN.
- **Edición** = `Session.edit(N_("forms.undo_edit"), merge_key="form.<kind>.<id>.<campo>")` + `Record.set` o
  `set_dynamic`. Teclear en el mismo campo se funde en un paso (`test_typing_in_the_same_field_is_one_undo_step`);
  un valor que no encaja no ensucia nada y lo dice en la barra de estado (`Record.set` valida antes de `touch`).
- El campo que da el id (`name` de un bookmark) no se edita en el formulario: cambiarlo sería renombrar (§15).
- **Pruebas (§19.5)** en `test_ui_forms.py`: el formulario de **cada esquema editable registrado** sobre un
  registro del minijuego, un valor en cada editor y su cambio en el registro (una transacción y deshacer), las
  dinámicas, el `merge_key`, los valores malos, avanzados/`visible_if`/variantes, y ES/EN + pseudolocalización de
  cada formulario.

## Fase 4 — Editor de entidades y secciones

- **Secciones desde el registro** (decisión 1): `ui/halls/registry.py` (`schema_sections`,
  `merge_schema_sections`). Naciones › Culturas y Gobiernos; Guerra › Fechas de inicio, Casus belli, Unidades
  terrestres y navales; Eventos › Modificadores (sale sola: ningún archivo de `ui/` nombra `event_modifier`, y una
  prueba lo comprueba). Cada una lleva su contador (registros de la vista efectiva).
- **Navegador**: lista con filtro y cinta de origen («Juego base», «Mod», «Mod, sustituye al juego», «Nuevo»);
  en las culturas, árbol por grupo (elegir un grupo abre el formulario de `culture_group`). Nuevo (plantilla o
  «basado en…», en el grupo elegido), Duplicar, Borrar (con usos se bloquea y los enseña, `UsesDialog`) y Restaurar
  (`restore_vanilla`). Cada operación es un paso de deshacer.
- **Editor** con las pestañas Formulario (y la lista de problemas del registro: doble clic lleva al campo), Textos,
  Usos (doble clic abre el uso en su línea), Código (decisión 2) y Otros campos; Rebeldes en los gobiernos.
- **Matriz de rebeldes** (`RebelMatrix`): tipo de rebelde × gobierno de destino; al crear un gobierno se abre esa
  pestaña con el destino propuesto (el propio id) y cada cambio es un paso.
- **`end_date`** (`EndDatePanel`, en Fechas de inicio): cambiar la fecha toca solo ese token de `defines.lua` y
  «Ampliar end_date» la lleva a la última fecha de inicio que se pasa.
- **`UnitNamesSlot`**: al crear una unidad naval se ofrecen los países con `unit_names` (`UnitNamesDialog`).
- **Ctrl+K**: un símbolo con esquema abre su editor (`MainWindow.open_entity`): cada unidad en la sección de su
  vista, un grupo de culturas en Culturas. **F7**: un problema con entidad lleva a su editor y a su campo; uno de un
  archivo con cambios sin guardar se abre en el editor de texto de Archivos, que enseña la memoria, en su línea
  (antes se negaba: límite de CONTINUAR §6).

**Cambios fuera de la lista (mínimos):**

- `ui/main_window.py`: `entity_pages`, `open_entity`, `_entity_section`, `_open_in_memory` (y `open_location`,
  `open_problem`, `open_symbol` y `commit_edits` los usan); `exec_dialog` y «Usos» de las páginas de entidades.
- `ui/halls/project/home.py`: las tarjetas «Nueva unidad», «Nuevo gobierno» y «Nueva cultura» de Inicio pasan de
  «llega en la iteración 4» a «lista» (3 valores de `FLOWS`): `test_ui_shell` exige que la tarjeta y la sección
  digan lo mismo.
- `SMOKE_KEYS` de `app.py`: una clave por archivo de textos nuevo (5 del núcleo y 3 fragmentos de i18n).

**Pruebas existentes que cambian, de forma explícita:**

- `test_ui_roadmap`: `PLAN`/`READY` pasan las 7 secciones de entidades a «listas».
- `test_ui_smoke.test_contract`: la comprobación de una tarjeta planificada pasa de `war:cb` a `war:wars`.
- `test_ui_shell.test_fragments_are_flat_utf8_json_without_bom`: la lista de fragmentos incluye `entity`,
  `forms` y `pickers`.
- `test_ui_review_it3.InMemoryTests`: las dos pruebas exigían que un símbolo o un problema de un documento sin
  guardar **se negara**; el encargo pide abrirlo en el editor. Ahora exigen que se abra el documento en memoria en
  su línea (y siguen exigiendo que nunca se abra el archivo del disco).

Pruebas nuevas: `test_ui_entity.py` (registro de secciones, listas y contadores, pestañas, crear y deshacer,
diálogo de id, borrado bloqueado, matriz, unidad naval con nombres, árbol de culturas, `end_date`, restaurar,
solo lectura, Ctrl+K, F7 al campo, ES/EN y pseudolocalización de las 7 secciones).

## Fase 5 — Integración y punta a punta

- **`Session.entities`** (`ui/session.py`): el `Entities` del proyecto abierto sobre el `Workspace` vivo, con el
  índice que haya (sin índice recorre los archivos del layout); se olvida al cerrar; en solo lectura las páginas
  deshabilitan todo lo que escribe. Las operaciones de las páginas van dentro de `Session.edit` con la misma
  etiqueta que su transacción de `Entities`, así que la ventana se entera al acabar (contador, título con `*`).
- **Índice tras guardar** (decisión 4): ver arriba; probado en el núcleo y desde la ventana (criterio 3: tras
  Ctrl+S, `my_cb` sigue en la lista).
- **`test_e2e_it4.py`** con la ventana, la `Session` y el `Project` reales: criterio 3 (diálogo «Nuevo», 4 claves,
  borrado bloqueado con el uso, un Ctrl+Z, rehacer y guardar: el CSV del mod con las 4 claves), criterio 4
  (`junta` copia los dos archivos al mod, matriz, claves, el aviso en el formulario y una sola vez en F7, que lleva
  al editor), criterio 5 («basada en infantry»: `units/guard.txt` y sus dos claves, solo en terrestres), criterio 2
  desde el formulario, abrir y guardar sin cambios no escribe nada, y Ctrl+Z justo después de teclear. Con corpus,
  el criterio 2 sobre una copia de vanilla (11 + 10 unidades, 31 CB, 226 culturas en la ventana).
- **Límite de la lápida** (CONTINUAR §6): resuelto con `restore_vanilla` y la lectura de la capa de debajo.
- **Corrección encontrada en la punta a punta**: `peace_order` quedaba `annex my_cb` en la misma línea (el
  serializador continúa una lista de valores sueltos). `AppendToList` ahora, si la lista lleva un valor por línea,
  empalma una línea propia con la sangría y el salto de la anterior (prueba con el minijuego y con vanilla).

**Batería de las fases 2–5** (3.12, sin corpus, `-B`): 1788 pruebas, `FAILED (failures=4, skipped=54)`: los 4
fallos de entorno de la línea base y solo omitidas de corpus. Con corpus, `test_schema_*`, `test_schema_criteria` y
`test_e2e_it4` en verde.

**Gasto aproximado:** fase 2, unos 8 USD; fase 3, unos 15 USD; fase 4, unos 20 USD; fase 5, unos 8 USD.

## Fase 6 — Revisión adversarial y cierre

### Revisión (las pruebas, antes de creerse el arreglo)

`tests/test_schema_review_it4.py` y ampliaciones de las pruebas de la ventana:

| Caso | Resultado |
|---|---|
| `peace_order` con saltos LF, con `\r` sueltos y en una sola línea | Ya iba bien tras el arreglo de la fase 5; quedan fijados (LF y CR se conservan; en una línea, sigue en una línea). |
| Gobiernos `nombre =\r\n{` con `election = yes  # election = no` (VSM): duplicar y cambiar un campo | Bien: la copia conserva el formato y el comentario; el original no cambia ni un byte. |
| Errores sin efectos: valores que no encajan, ids malos o repetidos, un compañero que falla a mitad de crear | Bien: nada sucio, nada en el historial, las claves de texto también se deshacen. |
| Un valor malo en un documento que no se puede tocar | Bien, y la prueba mata al mutante 7: el error es el del valor (se valida antes de `touch`). |
| Restaurar sin versión del juego | `KeyError` sin efectos. |
| Borrar una cultura dentro de su grupo y deshacer | Solo su bloque; deshacer devuelve el archivo exacto. |
| Cambiar `type` de una unidad | La vista la cambia de sección al momento; deshacer la devuelve. |
| Leer todas las listas, abrir, `issues`, `where_used`, `origin_of`, `can_restore_vanilla` | No ensucia nada, guardar no escribe, no aparece `.vic2studio/` (I4). |
| Duplicar un gobierno visto a través de la lápida de su copia del mod | Revive el documento con el contenido del juego y añade la copia. |
| Catálogos de solo lectura | Sin avisos de claves desconocidas (si no, F7 se llenaría de las de tecnologías e invenciones). |
| Latencia con vanilla: listar y abrir 50 registros de culturas, CB, unidades y gobiernos | < 0,5 s cada uno en el hilo de la interfaz. |
| **Capturas** | Encontraron dos fallos reales, ya corregidos con su prueba: el mensaje de `government_missing_in_rebel_map` del compañero salía con `{government}` y `{rebel}` sin rellenar (faltaba `rebel`; ahora un problema por tabla, con su línea), y el árbol de culturas recortaba los ids. |
| El formulario volvía a escribir el texto (y movía el cursor) al re-enlazar tras cada pausa al teclear | Corregido: solo si el valor cambió. La pestaña Textos ya no se puede editar en un proyecto de solo lectura. |

### Mutantes (`PRUEBAS.md` §6), todos detectados

| # | Archivo | Mutante | Lo mató |
|---|---|---|---|
| 1 | `core/schema/companions.py` | `my_cb` antes del último valor de `peace_order` | `It4CriteriaTests.test_criterion3_my_cb` |
| 2 | `core/schema/companions.py` | `AppendToList.on_delete` no quita nada | `CasusBelliContract.test_companions` |
| 3 | `core/schema/record.py` | `where_used` sin quitar las referencias de los compañeros | `CompanionTests.test_delete_ignores_own_references_but_not_real_uses` |
| 4 | `core/schema/record.py` | la vista efectiva solo con los documentos sucios (como antes) | `EffectiveAfterSaveTests.test_create_save_list_with_a_stale_index` |
| 5 | `core/schema/record.py` | la lápida tapa el archivo del juego (como antes) | `RestoreVanillaTests.test_deleting_the_mod_copy_shows_the_game_file` |
| 6 | `core/schema/types.py` | `ListOf` reescribe el bloque entero | `RichTypesTests.test_list_edits_in_place` |
| 7 | `core/schema/record.py` | `Record.set` sin validar antes de `touch` | `test_a_bad_value_is_refused_before_touching_the_document` (**añadida**: el primer intento sobrevivió porque la transacción revierte igual) |
| 8 | `core/schema/validate.py` | lo sin guardar de un archivo del juego, heredado | `BackgroundValidationTests` |
| 9 | `core/schema/layouts.py` | `GroupedIn` inserta al principio del grupo | `LayoutTests.test_create_culture_goes_to_the_end_of_its_group` |
| 10 | `core/schema/docgen.py` | la referencia sin el ejemplo mínimo | `test_criterion7_reference_is_complete_and_up_to_date` (`--check`) |
| 11 | `ui/forms/form.py` | `merge_key` distinto en cada edición | `test_typing_in_the_same_field_is_one_undo_step` (el primer intento, con `id(object())`, repetía el id y no era un mutante) |
| 12 | `ui/halls/registry.py` | la sección del esquema no sustituye a la planificada | `RegistrySectionTests.test_a_new_schema_appears_without_touching_ui` |
| 13 | `ui/main_window.py` | F7 no abre el editor de la entidad | `NavigationTests.test_f7_problem_of_an_entity_leads_to_its_field` |
| 14 | `ui/entity/editor_page.py` | Borrar con `force=True` | `test_delete_with_uses_is_blocked_and_shows_them` |
| 15 | `ui/session.py` | sin quitar los problemas repetidos con la validación global | `test_criterion4_junta` («una vez») |
| 16 | `ui/pickers/fields.py` | `NameListEditor` confirma nombres que no caben en cp1252 | `NameListTests.test_split_dedupe_and_cp1252` |
| 17 | `core/schema/record.py` | `unknown="keep"` sin efecto | `test_read_only_catalogues_do_not_warn_about_their_keys` (**añadida**: sin corpus sobrevivía) |
| 18 | `ui/main_window.py` | lo que está en memoria se vuelve a negar | `InMemoryTests` |

El guion de los mutantes aplica cada cambio, pasa solo las pruebas de su pieza con `-B` y restaura el archivo;
`git status` limpio después de cada tanda.

### Capturas

`docs/capturas/27`–`38`: las 6 secciones en español a 1100×700 y en inglés a 1920×1080 (Culturas, Gobiernos,
Fechas de inicio, Casus belli, Unidades terrestres y navales), con `tools/screenshot.py --no-game-art` sobre un
minijuego sintético (sin datos de Paradox), revisadas una a una.

## Criterios de aceptación (wizard §22, iteración 4)

| # | Criterio | Estado | Pruebas |
|---|---|---|---|
| 1 | Conformidad con vanilla sin `unknown_field` ni `bad_type`: 8 gobiernos, 31 CB, 2 bookmarks, 34 grupos y 226 culturas, y 21 unidades; abrir y guardar sin cambios no escribe | **Cumple** (con corpus) | `test_schema_criteria.It4CriteriaTests.test_criterion1_all_schemas_conform_to_vanilla`, `test_corpus_conformance` de cada esquema, `test_e2e_it4.test_open_and_save_without_changes_writes_nothing` |
| 2 | Cambiar `attack` de infantry modifica una sola línea | **Cumple**, también desde la interfaz | `test_criterion2_set_attack_single_line`, `test_e2e_it4.test_criterion2_attack_from_the_form_changes_one_line`, `VanillaWindowTests.test_criterion2_on_a_copy_of_vanilla` |
| 3 | `my_cb` al final de `peace_order`, 4 claves en `00_<P>_cb.csv`, borrado bloqueado con usos, un Ctrl+Z | **Cumple**, núcleo e interfaz | `test_criterion3_my_cb`, `test_criterion3_my_cb_on_vanilla`, `test_e2e_it4.test_criterion3_my_cb` |
| 4 | `junta`: copia los dos archivos, 14 tablas (2 en el minijuego), `junta` y `junta_ruler`, aviso de `election` sin `duration` | **Cumple**, núcleo e interfaz | `test_criterion4_create_government`, `test_duplicate_democracy_fills_all_14_tables`, `test_e2e_it4.test_criterion4_junta` |
| 5 | Terrestres y navales en dos secciones de un esquema; «basada en infantry» crea `units/<id>.txt` y `<id>`, `<id>_short` | **Cumple** | `test_vanilla_views_are_11_land_and_10_naval`, `test_e2e_it4.test_criterion5_unit_based_on_infantry`, `SectionWindowTests.test_naval_unit_based_on_frigate_offers_unit_names` |
| 6 | `event_modifier` sin tocar `ui/`; su prueba es una subclase de 3 líneas | **Cumple** | `test_criterion6_event_modifier_touches_no_ui_file`, `RegistrySectionTests` |
| 7 | Referencia ES/EN sin claves sin traducir; capturas ES/EN de las 6 secciones; verificación adversarial | **Cumple** | `test_criterion7_reference_is_complete_and_up_to_date`, `test_docgen` de cada esquema, `docs/capturas/27`–`38`, `test_schema_review_it4.py` |

## Desviaciones de §10 y §13

1. `DynamicKeys.key_kind = OPEN_CATALOG` (`"*"`): catálogo abierto para los efectos de los modificadores, que el
   índice no cataloga (§10.2 solo prevé catálogos del índice).
2. `GroupedIn(path, level=0|1)` y `NestedIn(glob, "", …)` con contenedor raíz: §10.4 no dice cómo se distinguen
   padre e hijos ni prevé archivos de tecnologías con varias entidades sin contenedor.
3. Las disposiciones dan además `touches(rel)` y `context_rels(ctx)`.
4. `RecordRef` de los grupos de culturas usa el esquema `culture_group` dentro de la sección de culturas (el árbol
   por grupo de §14.13).
5. `bookmark`: el id es `name` (`IdSpec.FIELD`), con `LocSpec("{id}")` y `LocSpec("{id}_DESC", required=False)`:
   en vanilla `GC_NAME` describe con `GC_DESC`, así que la segunda clave solo es la propuesta para los nuevos.
6. `casus_belli` no declara `NORMAL_/AGRESSION_<war_name>` como `LocSpec`: la plantilla de §10.3 solo reemplaza
   `{id}` y son claves compartidas que no se crean ni se borran con ningún CB.
7. Los números se editan en una línea con validador, no en `QSpinBox` (vacío = sin valor).
8. La pestaña Código usa el `ScriptEditor` sobre el archivo entero (decisión 2), no el `ClausewitzViewer` sobre el
   bloque de §13.5.
9. `end_date` entra con `Workspace.restore_bytes`: `defines.lua` no tiene códec propio y `test_project_codecs`
   exige que siga así.
10. Las etiquetas de los valores `Enum` siguen la convención del corte (`schema.<kind>.enum.<campo>.<valor>`).

## Límites conocidos nuevos

- **Renombrar** (§15) no existe: ni el botón ni `Entities.rename`; el `name` de un bookmark no se edita en el
  formulario.
- **Historia fechada** (`history.py`) y **guion** (`Record.script`) siguen como contrato: los bloques de guion de
  los CB se editan en la pestaña Código.
- **Vistas con muchas entidades**: `Entities.list(view=…)` abre cada registro para aplicar el filtro; con las 21
  unidades de vanilla es inmediato, pero un esquema con cientos de archivos y vistas lo notaría.
- La hoja de ruta de Inicio sigue diciendo «iteración 3 en curso» (`CURRENT_ITERATION` de `ui/pages/planned.py`,
  fuera de la lista de archivos): ver peticiones.
- `test_ui_integration…test_validating_a_large_file_keeps_the_interface_responsive` falla con corpus en esta
  máquina **también en la rama de partida** (comprobado con un `git worktree` de `9927674`): es de la máquina.

## Peticiones y dudas para el usuario

1. **Hoja de ruta.** `ui/pages/planned.py: CURRENT_ITERATION = 3`: con la iteración 4 integrada debería pasar a 4 o
   5 (y `test_ui_roadmap` con ella). No lo toqué porque no está en la lista y cambia algo visible.
2. **`[verificar en juego]`**: ¿el juego exige `first_names`/`last_names` en una cultura? Los marco obligatorios
   (los 226 de vanilla los llevan).
3. **Códec LUA**: el editor de `end_date` funciona sobre el documento binario; un códec propio de `defines.lua` en
   `core/project/codecs.py` lo dejaría más limpio (cambia `test_project_codecs`).
4. La línea base de este entorno no es `OK (skipped=40)` (4 fallos de fuentes y de PySide6 por pip, y una omitida
   por no poder crear carpetas en `/`), como en las rondas anteriores en esta misma máquina.

## Baterías de cierre

| Combinación | Resultado |
|---|---|
| Python 3.12.13 + PySide6 6.12.0, sin corpus, `-B` (fase 4–5) | 1788 pruebas, `FAILED (failures=4, skipped=54)`: los 4 de la línea base (3 de fuentes y `test_tasks…garbage_frozen…`); solo omitidas de corpus |
| Python 3.12.13 + PySide6 6.12.0, **con corpus** (vanilla, Plantilla Mod y una copia de ShagoMod), `-B` | 1802 pruebas, `FAILED (failures=6, skipped=1)`: los 4 de la línea base; `test_ui_integration…validating_a_large_file…` (latencia, falla igual en `9927674` en esta máquina), y `test_ui_palette.CorpusCriterion7Tests` «north_german», que esperaba el archivo y ahora abre el editor de la cultura: actualizada de forma explícita (el criterio 7 de la iteración 3 ya decía «o el editor de la entidad cuando exista») y en verde al repetirla. La omitida es la de crear una carpeta en la raíz del disco. Ningún `.vic2studio/` quedó en el corpus. |
| Python 3.10.20 + PySide6 6.11.3, sin corpus, `-B` | 1803 pruebas, `FAILED (failures=4, skipped=55)`: 3 de fuentes y la de latencia de `test_ui_integration` (también falla en la rama de partida con 3.10, como anotó INFORME_MOTOR). `test_tasks` pasa con 3.10. |

## Gasto y tiempo

- Tiempo total de la sesión: unas 1 h 35 min de reloj (28-10-2026, de las 13:58 a las 15:33, hora local), baterías
  incluidas.
- Gasto aproximado por fase (estimación por el volumen de contexto y de salida, no medida en la consola): fase 0,
  unos 4 USD; fase 1, unos 22 USD; fase 2, unos 8 USD; fase 3, unos 15 USD; fase 4, unos 20 USD; fase 5, unos 8
  USD; fase 6, unos 15 USD. **Total aproximado: 90–95 USD**, por debajo del tope de 150 USD.

## Revisión e integración (Claude Code, 28-10-2026)

Puntuación con 22 comprobaciones ocultas selladas antes de mirar la rama (sha256 `581e042f…4380`), el corpus real
en copias y 12 mutantes también decididos de antemano:

| Parte | Nota |
|---|---|
| Comprobaciones ocultas | 37/40 (41 de 44 puntos) |
| Criterios | 14/15 |
| Diseño | 13/15 |
| Invariantes y arquitectura | 10/10 |
| Calidad de las pruebas | 10/10 (11 de 11 mutantes; un duodécimo era equivalente) |
| Honestidad del informe | 9/10 |
| **Total** | **93/100 a la primera, sin rondas de corrección** |

- **Comprobaciones ocultas: lo que salió bien.**
  - Recuentos y conformidad con vanilla.
  - Sin pérdidas, y leer no escribe.
  - `my_cb`: al final de `peace_order`, con sus 4 claves y deshecho de una vez.
  - La autorreferencia de `peace_order` no bloquea el borrado: hay 27 CB sin más usos que esa línea.
  - La cultura duplicada se queda en su grupo.
  - docgen.
  - Los problemas de esquema llegan a F7.
  - Las 7 secciones salen por descubrimiento y abren con sus filas; Ctrl+K abre la entidad.
  - Siguen en verde las 26 comprobaciones de las rondas del motor.
- **Comprobaciones ocultas: los tres puntos perdidos.**
  - N12, a medias: el criterio 6 se cumple (ningún archivo de `ui/` nombra `event_modifier`), pero el commit que lo
    añade también toca `ui/session.py` por la decisión 3, así que no se demuestra por commits.
  - B1 y B2: la prueba de disposición desfasada que se explica abajo.
- **Tu mod.** Los 7 esquemas editables recorren una copia de VSM (463 registros) en 0,4 s y dan un único problema
  propio, `absolute_monarchy` sin `duration`, sin falsos positivos.
- **Gasto real: $32,91 en 1 h 35 min** (según OpenCode). La estimación de este informe, $90–95, se pasó de casi
  el triple.

Cambios de Claude al integrar:

- **`test_ui_smoke…test_rail_is_a_column_with_room_and_a_strip_when_narrow`.** La comprobación final se hacía en
  el último idioma del bucle, el inglés. Desde esta iteración, en inglés la franja de Guerra cabe en una línea,
  porque cuatro secciones llevan un contador en vez de «It. N». Ahora fija el español, donde Guerra sigue en placas
  altas, y prueba así las dos alturas. En este equipo fallaba de partida por las fuentes, así que no se podía ver.
- **`CURRENT_ITERATION = 5`** (hoja de ruta: la 4 hecha y la 5 en curso). `test_ui_roadmap` admite secciones
  planificadas para la iteración en curso: las del mapa.
- **`python -m vic2studio.core.schema doc --kind …`** ya no empieza con una línea en blanco.
- **Decisiones del usuario sobre las dos dudas** (CONTINUAR §2):
  - `first_names` y `last_names` siguen obligatorios;
  - `defines.lua` se queda sin códec propio, porque no compensa: un códec tocaría el núcleo del proyecto.
