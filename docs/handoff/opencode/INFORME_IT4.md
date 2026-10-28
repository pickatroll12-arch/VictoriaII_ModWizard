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
- **Corpus.** Descargado de la release `recursos-v1` con `gh release download` y descomprimido **fuera** del
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

(ver el commit de la fase)

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
