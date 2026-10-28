# Encargo: terminar la iteración 4 (Claude en OpenCode)

Eres Claude, trabajando en OpenCode con la API. Tu trabajo es **terminar la iteración 4** de Victoria II Mod
Studio: el resto del núcleo, toda la interfaz, la integración, tu propia revisión adversarial y el cierre. Aquí
haces de los dos agentes de wizard §20 a la vez, por fases. Claude Code revisará tu rama después con
comprobaciones ocultas, el corpus real y mutantes, como revisó las anteriores. Lo que no esté probado no cuenta.

## Estado de partida (no lo rehagas)

- **Iteraciones 1–3 cerradas.** Hay alfa 0.1.0 empaquetada para Linux y Windows.
- **Editor de texto** de Proyecto › Archivos (`ui/viewers/script_editor.py`, `core/textsplice.py`). Lo hizo un
  agente; el informe está en `docs/handoff/opencode/INFORME_EDITOR.md`.
- **Corte vertical del motor de esquemas**, puntuado 93/100. Ya existe:
  - `core/schema/` con el contrato completo de §10;
  - `Record` y `Entities`, con la vista efectiva, una transacción por operación e ids validados;
  - `SingleFile`, `OnePerFile` y `MappingTable`;
  - los esquemas `government` y `unit`;
  - el arnés `tests/schema_harness.py`.

  **Lee `docs/handoff/opencode/INFORME_MOTOR.md` entero**: tiene las decisiones de diseño, las desviaciones de §10
  y los límites que dejó. Lo que está en `NotImplementedError` es tuyo.
- **Batería de partida:** 1588 pruebas, `OK (skipped=40)` sin corpus. Con el corpus no se omite nada salvo la clase
  base del arnés.

## Lee antes de escribir código

1. `AGENTS.md`, `docs/handoff/opencode/REGLAS.md` y `docs/handoff/opencode/PRUEBAS.md`. Las reglas valen todas,
   salvo la lista de archivos: aquí la iteración 4 entera es tuya (ver «Archivos»).
2. `CONTINUAR_EN_CLAUDE_CODE.md`: §0, §3, §5.4 y **§6 (límites conocidos)**.
3. `docs/diseno/wizard.md`:
   - §0, §3, §10, §13 (sobre todo §13.5–13.7: editor genérico, formularios y selectores) y §14.4;
   - §14.9–14.13, §19.3, §19.5, §20, **§22 (iteración 4)** y **§24 (decisiones del usuario, que mandan)**.
4. `ARCHITECTURE.md` §2 y §5.
5. El código que vas a usar, leído de verdad:
   - `core/schema/__init__.py` y `core/schema/record.py`;
   - `ui/session.py` (`edit`, `documentsChanged`, `rebuild_index`, `locsync`);
   - `ui/halls/registry.py` (`SectionSpec` ya prevé `schema_kind` y `view`);
   - `ui/halls/{nations,war}/__init__.py`, `ui/main_window.py` (`open_symbol`, `open_location`, `commit_edits`);
   - `ui/viewers/script_editor.py` y `ui/halls/project/descriptor.py`, el patrón de edición con `merge_key`.

## Rama

Parte de `main` si ya está fusionado el PR #12; si no, de `claude/keen-fermi-nw8itc`. Crea
`opencode/it4-claude`, y haz commit y `git push -u origin opencode/it4-claude` al final de **cada fase**. No abras
PR ni toques otras ramas.

## Archivos

Son tuyos todos los entregables de la iteración 4 en §22:
- `core/schema/**`, `core/schemas/**`, `tests/schema_harness.py` y `tests/test_schema_*.py`;
- `docs/referencia/**` y `tools/gen_reference.py`;
- `ui/forms/**`, `ui/entity/**` y `ui/pickers/**`;
- `ui/halls/{nations,war,events}/__init__.py` y `ui/widgets/icons_extra/{nations,war}.py`;
- `i18n/{es,en}/{forms,entity,pickers}.json` y `tests/test_ui_{forms,entity,pickers}.py`;
- `tests/test_e2e_it4.py` y `docs/capturas/` (las capturas nuevas).

También puedes tocar, **con cambios mínimos y explicados en el informe**:
- `ui/session.py` (que la sesión tenga sus `Entities`);
- `ui/main_window.py`;
- `ui/halls/registry.py`;
- `i18n/__init__.py`;
- `tests/_minigame.py`, solo añadiendo, nunca cambiando lo que hay: otras pruebas cuentan sus entradas;
- `SMOKE_KEYS` en `src/vic2studio/app.py`;
- los documentos `README.md`, `ARCHITECTURE.md` y `CONTINUAR_EN_CLAUDE_CODE.md`.

No toques `core/project/**`, `core/clausewitz/**`, `core/vfs/**` ni `core/index/**` salvo un fallo demostrado con
una prueba. Si pasa, va en un commit propio y en el informe.

## Decisiones de diseño que tienes que tomar (y razonar en el informe)

1. **De dónde salen las secciones.** El criterio 6 exige que añadir el esquema `event_modifier` **no toque ningún
   archivo de `ui/`**. Por eso las secciones de entidades tienen que salir del registro de esquemas
   (`EntitySchema.hall`, `section`, `order`, `icon` y sus `View`), no de las listas `SECTIONS` de cada sala.
   - Hoy `unit` declara `section="units"` y sus vistas, `"units_land"` y `"units_naval"`.
   - Las salas tienen secciones planificadas `war:land`, `war:naval`, `war:cb`, `war:bookmarks`,
     `nations:cultures` y `nations:governments`.

   Unifícalo conservando las claves que usan las capturas y las pruebas de la hoja de ruta, o cámbialas de forma
   explícita y actualiza esas pruebas.
2. **La pestaña Código del editor de entidades.** El diseño (§13.5) dice que reutiliza el visor sobre el bloque
   de la entidad y que editar es `replace_model`. Ya existe `ScriptEditor`, con empalme sin pérdidas y deshacer
   correcto. Decide si lo reutilizas, acotado al bloque o al archivo con la posición del bloque, y no rompas lo
   que ya garantiza (sus pruebas).
3. **Los problemas de esquema en F7.** `core/schema/validate.py` tiene `schema_problems`, pero no está conectado
   al validador. `test_validate_rules` exige un caso por cada regla registrada con `@rule`. Conéctalo sin romper
   eso; por ejemplo, el motor de validación añade los problemas de esquema como una familia más. Que salgan en F7
   y en el panel con su texto, su «¿Por qué?» y su arreglo si lo tienen.
4. **El índice tras guardar.** `Entities.list` superpone los documentos con cambios al índice. Al guardar, los
   documentos quedan limpios y el índice tiene que estar ya al día. Comprueba qué hace hoy `Session` tras guardar,
   y prueba que crear, guardar y volver a listar sigue mostrando la entidad.

## Fases

Cada fase termina con:
- sus pruebas en verde;
- **la batería completa en verde** con Python 3.12 o 3.13 (sin corpus: solo omitidas de corpus);
- una entrada en `docs/handoff/opencode/INFORME_IT4.md`;
- commit y push.

El presupuesto es orientativo, con Opus 5.5. Si una fase pasa de 1,5 veces el suyo, para, anota en el informe
por qué y pregunta al usuario.

### Fase 0. Orientación (~$3)

Rama, batería de partida y lectura. Escribe en el informe el entorno, la línea base y tus decisiones 1–4 en
borrador.

### Fase 1. El resto del núcleo (~$20)

- **Esquemas, con sus textos ES/EN y una prueba de 3 líneas cada uno (§19.3):**
  - `casus_belli`: `SingleFile` sin `peace_order`, más el compañero `AppendToList` sobre `peace_order`;
  - `bookmark`: `RepeatedKey`, con id `name`;
  - `culture`: `GroupedIn`, grupos y culturas, con `Children`;
  - `event_modifier`: añade su fragmento a `tests/_minigame.py`, que no lo trae;
  - `readonly`: tecnologías, invenciones, ideologías, reformas, bienes y edificios, con `editable=False`.

  Implementa las disposiciones que falten.
- **Compañeros** `ActivateUnit` y `UnitNamesSlot` (§10.8, §14.4, §14.12).
- **`docgen.py` y `__main__.py`** (`check`, `list`, `show` y `doc` en la salida estándar), más
  `tools/gen_reference.py`, que escribe `docs/referencia/{es,en}/`. Recuerda que `test_arch_writes` prohíbe
  escribir desde `src/`.
- **Criterios de núcleo** en `tests/test_schema_criteria.py`:
  - 1: 31 CB, 2 bookmarks, 34 grupos y 226 culturas, con corpus;
  - 3: `my_cb` al final de `peace_order`, con 4 claves en `localisation/00_<P>_cb.csv`;
  - 6 y 7.

### Fase 2. Contrato de la interfaz (~$8)

Antes de los formularios, deja escritas y probadas las firmas, con prueba de que se construyen:
- `FormBuilder` y el registro `EDITORS`, un editor por `ValueType.widget`;
- `EntityEditorPage`, el navegador y sus señales;
- los selectores (`SymbolPicker`, `DateEdit`, `ColorField`, `GoodsAmountsField`, `NameListEditor` y
  `SpriteFramePicker`).

Con esto, el resto de fases construye sobre algo fijo.

### Fase 3. Formularios y selectores (~$30)

- `ui/forms/**`:
  - `Section`, que se ve como una tarjeta;
  - `Field`, con `visible_if`, `default` en gris y `advanced`;
  - `Group` repetible como tabla;
  - `DynamicKeys` como lista de casillas, rejilla o tabla;
  - campos de localización.
- `ui/pickers/**`.
- Cada edición de un campo es **una transacción con `merge_key`** por campo, igual que el descriptor. Teclear
  en el mismo campo se funde en un paso de deshacer.
- Pruebas (§19.5): construir el formulario de **cada esquema registrado**, poner un valor en cada editor y
  comprobar el cambio en el registro, la paridad ES/EN y la pseudolocalización.

### Fase 4. Editor de entidades y secciones (~$30)

- **Navegador:** lista con filtro y vistas, y los botones Nuevo (plantilla o «basar en…»), Duplicar y Borrar. Si
  la entidad tiene usos, el borrado se bloquea y los enseña.
- **Editor con las pestañas** Formulario, Textos, Usos, Código y Otros campos (§13.5).
- **Secciones:** Naciones › Culturas y Gobiernos; Guerra › Fechas de inicio, Casus belli, Unidades terrestres y
  Unidades navales; y la del `event_modifier`, que debe aparecer sola.
- **Matriz de rebeldes** (las 14 tablas de `rebel_types.txt`) y **editor mínimo de `end_date`** en `defines.lua`
  (`core/lua_defines.py` ya edita sin pérdidas).
- **Ctrl+K:** un símbolo con esquema abre su editor de entidad (`MainWindow.open_symbol`), no su archivo.
- **F7:** un problema de una entidad lleva a su campo. Un problema de un archivo con cambios sin guardar lo abre
  en el editor, que enseña la memoria, en vez de negarse. Es un límite de `CONTINUAR` §6.

### Fase 5. Integración y prueba de punta a punta (~$15)

- `Session` crea y mantiene sus `Entities`: al abrir y cerrar el proyecto, en solo lectura y con el índice al día
  tras guardar (decisión 4).
- `tests/test_e2e_it4.py`, con la ventana real y un `Project` real sobre el minijuego. Los criterios 3, 4 y 5 se
  hacen desde la interfaz: crear `my_cb`, Ctrl+Z y guardar; crear `junta`, con las 14 tablas y el aviso; una
  unidad «basada en infantry».
- El límite de `CONTINUAR` §6 sobre borrar la copia del mod de algo que también está en vanilla: arréglalo si
  cabe (`restore_vanilla`, §10.5). Si no, déjalo anotado.

### Fase 6. Revisión adversarial y cierre (~$15)

- **Revísate como lo haría otro:** busca casos que rompan tus garantías (sin pérdidas, I4, I5, I7, I12, errores
  sin efectos, vistas) y escribe la prueba **antes** de creerte el arreglo.
- **Al menos 15 mutantes** a mano (`PRUEBAS.md` §6), repartidos entre núcleo e interfaz.
- **Baterías:** Python 3.12 o 3.13 **con corpus** (en copias) y Python 3.10 sin corpus.
- **Capturas ES/EN de las 6 secciones** con `tools/screenshot.py`: español a 1100×700 e inglés a 1920×1080, en
  `docs/capturas/`.
- **Documentos al día:** README, ARCHITECTURE, CONTINUAR y la nota de criterios de §22 si cambia algo.
- `INFORME_IT4.md` completo.

## Criterios de aceptación (wizard §22, iteración 4)

| # | Criterio | Estado de partida |
|---|---|---|
| 1 | Conformidad con vanilla sin `unknown_field` ni `bad_type`: 8 gobiernos, 31 CB, 2 bookmarks, 34 grupos y 226 culturas, y 21 unidades. Abrir y guardar sin cambios no escribe nada. | Gobiernos y unidades, hechos |
| 2 | Cambiar `attack` de infantry modifica una sola línea de `units/infantry.txt` | Hecho en el núcleo; falta desde la interfaz |
| 3 | Crear `my_cb` lo añade al final de `peace_order` y crea sus 4 claves en `localisation/00_<P>_cb.csv`. Borrarlo mientras se usa se bloquea y enseña los usos. Un solo Ctrl+Z deshace la creación entera. | Falta |
| 4 | Crear `junta` copia `governments.txt` y `rebel_types.txt` al mod, la añade a las 14 tablas y crea `junta` y `junta_ruler`. `election = yes` sin `duration` da el aviso. | Hecho en el núcleo; falta desde la interfaz |
| 5 | Unidades terrestres y navales en dos secciones del mismo esquema. «Basada en infantry» crea `units/<id>.txt` y las claves `<id>` y `<id>_short`. | Núcleo hecho; faltan las secciones |
| 6 | Añadir el esquema `event_modifier` no toca ningún archivo de `ui/`, y su prueba es una subclase de 3 líneas | Falta |
| 7 | docgen genera la referencia ES/EN de cada esquema sin claves sin traducir. Capturas ES/EN de las 6 secciones y verificación adversarial. | Falta |

Si un criterio no sale, déjalo con `expectedFailure` y explícalo. No lo marques como hecho.

## Cómo trabajar (lo que aprendimos en las rondas anteriores)

- **Ejecuta antes de dar algo por bueno.** Los dos fallos serios del motor estaban en docstrings que afirmaban
  algo no probado («`list` refleja la vista efectiva»), y un razonamiento con cinco ✓ dejó escapar las líneas del
  CST trasplantado. Cada garantía que escribas en un docstring o en el informe lleva su prueba.
- **Prueba con datos reales, no solo con el minijuego.** Usa el corpus en copias. Cuidado con:
  - archivos grandes (`map/positions.txt`, 1,35 MB): mide el hilo de la interfaz;
  - `\r` sueltos (382 archivos de vanilla);
  - comentarios en línea (VSM: `election = yes  # election = no`);
  - gobiernos con formato `nombre =\r\n{`.
- **La vista efectiva manda (I7):** lo no guardado, lo borrado sin guardar, lo que vuelve con un deshacer y lo que
  hay tras guardar.
- **Rendimiento en el hilo de la interfaz:** nada por encima de 0,5 s sin cursor de espera.
- **Nunca** saltes, borres ni relajes una prueba existente para que pase, ni subas datos de Paradox.

## Cuándo parar y preguntar

- La batería de partida no da `OK (skipped=40)`: para.
- El gasto pasa de **$150**: para, cierra la fase en curso con commit y ve directo a una fase 6 mínima (baterías e
  informe).
- Una decisión que contradice §24 o cambia algo visible que el usuario no ha pedido: pregunta.
- Más de 3 intentos con la misma prueba: anótalo y sigue.

## Informe (`docs/handoff/opencode/INFORME_IT4.md`)

- Entorno y línea base.
- Lo hecho por fase, con sus commits y el gasto aproximado por fase.
- Tus decisiones de diseño 1–4, razonadas.
- La tabla de los 7 criterios: cumple, no o parcial, con la prueba de cada uno.
- Los mutantes y qué prueba mató cada uno.
- Las baterías: las combinaciones y sus resultados exactos.
- Desviaciones de §10 y §13.
- Límites conocidos nuevos.
- Peticiones y dudas para el usuario.
