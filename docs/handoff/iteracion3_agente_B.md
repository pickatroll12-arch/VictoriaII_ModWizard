# Iteración 3 — Agente B: localización editable sincronizada, Validación, panel de problemas y Ctrl+K

Eres el agente B de la iteración 3 de Victoria II Mod Studio. El orquestador ya hizo el commit de contrato (paso 0 de
`docs/diseno/wizard.md` §20). Tú haces `core/locsync.py` y la interfaz; el agente A implementa a la vez el índice
de símbolos y la validación del núcleo contra el mismo contrato. Hasta la integración, `SymbolIndex`, `build_index`,
`Validator`, `build_context`, `compute_baseline`, `explain`, `plan_fix` y `apply_fix` lanzan `NotImplementedError`:
trabaja contra sus firmas con un índice falso en memoria. Trabajáis en copias separadas del repositorio y el
orquestador integra al final.

## Lee antes de empezar

1. `CONTINUAR_EN_CLAUDE_CODE.md` §2 y §3 (decisiones y lo que ya existe), §4 (entorno; cómo probar con PySide6
   6.5.0) y §5 (método).
2. `docs/diseno/wizard.md`:
   - §3 (invariantes) y §4 (sobre todo: ningún widget abre archivos, todo pasa por `Session` → `Project`);
   - §6 (proyecto) y §8 (política de LocSync);
   - §11 y §11.1 (lo que muestra la interfaz de validación);
   - §13.1, §13.4 (Ctrl+K) y §13.9;
   - §22, iteración 3 (entregables y **criterios 6, 7 y 8**).
3. El contrato:
   - `src/vic2studio/core/locsync.py` es tuyo;
   - de `src/vic2studio/core/index/` y `src/vic2studio/core/validate/` consumes `model.py`, los registros y las
     firmas;
   - `LocalisationDB.from_entries` ya está implementado en `core/csvloc/db.py`.
4. Lo que hay de interfaz: `ui/session.py`, `ui/main_window.py`, `ui/halls/` (registro por descubrimiento), las
   secciones de `ui/halls/project/`, `ui/pages/localisation_page.py` y `ui/viewers/localisation_editor.py` (la
   tabla CSV de solo lectura de la iteración 1), `ui/viewers/validation_panel.py` (el «Validar mod» de la
   iteración 1), `ui/shell/`, `ui/tasks.py` (grupos de hilos; lee su docstring y la regla del recolector en
   ARCHITECTURE.md §2.5) y `tools/screenshot.py`. Las pruebas de interfaz usan `tests/_qt.py`, `tests/_layers.py`,
   `tests/_minigame.py`, `tests/_fake_project.py` y `tests/test_ui_real_project.py` (las ventanas contra el
   `Project` real).

## Tus archivos (solo estos)

- `src/vic2studio/core/locsync.py`, y `src/vic2studio/core/csvloc/**` si te hace falta algo más.
- `src/vic2studio/ui/session.py` y `src/vic2studio/ui/main_window.py`: eres su único dueño en esta iteración.
- `src/vic2studio/ui/halls/localisation/**`, `src/vic2studio/ui/halls/project/__init__.py` y el nuevo
  `src/vic2studio/ui/halls/project/validation.py`.
- `src/vic2studio/ui/pages/localisation_page.py` y `src/vic2studio/ui/viewers/localisation_editor.py`.
- Los nuevos `src/vic2studio/ui/shell/command_palette.py` y `src/vic2studio/ui/shell/problems_dock.py`, y
  `src/vic2studio/ui/dialogs/` para diálogos nuevos (el plan de un arreglo, añadir clave).
- `src/vic2studio/ui/style.qss`, los iconos que necesites y `src/vic2studio/ui/tasks.py`, solo para añadir un
  grupo de hilos `POOL_INDEX`.
- `src/vic2studio/i18n/{es,en}/{localisation,validation,palette}.json`, más claves en `shell.json` y
  `project.json` si las necesitas.
- `tools/screenshot.py`.
- Pruebas: `tests/_fake_project.py`, el nuevo `tests/_fake_index.py` y los nuevos `tests/test_locsync.py`,
  `tests/test_loc_effective.py`, `tests/test_ui_loc_edit.py`, `tests/test_ui_validation.py` y
  `tests/test_ui_palette.py`. Ajusta también las pruebas de interfaz existentes que esperaban esas secciones
  «en desarrollo» (`test_ui_smoke`, `test_ui_shell`, `test_ui_roadmap`…).

No toques `core/index/**`, `core/validate/**`, `core/rules/**`, `core/lua_defines.py`, `core/modcheck.py`,
`tests/_minigame.py`, `tests/_corpus.py` ni `tests/test_arch_writes.py`: son de A. Si necesitas un cambio ahí,
descríbelo en tu informe final y no lo hagas.

## Qué entregar

1. **`LocSync` completo** (§8 y su docstring):
   - la política de dónde escribe;
   - el formato de los archivos nuevos;
   - `languages` y `copy_en_to`;
   - `entries()` con los indicadores de los filtros;
   - `localisation_db()` con los documentos sin guardar.
2. **`Session`** (el único puente con Qt).
   - Añade:
     - el índice: `index` y `rebuild_index()`, en segundo plano en `POOL_INDEX`; al abrir el proyecto, con
       `FactsCache`;
     - reindexado incremental: con cada `DocChanged`, a los 300 ms, `extract_bytes` del `snapshot` del documento
       en segundo plano y `SymbolIndex.apply` en el hilo de la interfaz;
     - `locsync`;
     - la validación: `validate()`, en `POOL_VALIDATION` con `build_context` sobre la instantánea y los bytes de
       los documentos sucios, y la línea base calculada en segundo plano con `BaselineCache`;
     - `problems()`, `explain(problem)`, `fixes_for(problem)`, `plan_fix(key, problem)`,
       `apply_fix(key, problem)`, `search(text, …)` y `display(symbol)`;
     - las señales `symbolsChanged` y `problemsChanged`, que ya existen, y las de progreso que necesites.
   - Que el índice, la validación y la línea base se puedan **inyectar** en el constructor (como ya se hace con
     `opener` y `creator`): tus pruebas usan los falsos y la integración, los reales.
   - Llama a las funciones reales del contrato, para que al integrar baste con quitar los falsos.
   - Respeta lo de `ui/tasks.py`: nada que retenga objetos de Qt en un hilo de tarea.
3. **Sala Textos**:
   - la sección «Todos los textos» es una tabla editable de la localización efectiva. Editar una celda hace
     `Session.edit` + `LocSync.set_text`, deshacible con Ctrl+Z;
   - «Añadir clave»;
   - los filtros «creadas por el Studio», «sin traducir», «sustituye a vanilla» y «degradadas»;
   - la sección «Pendientes de traducir» es ese filtro ya puesto;
   - «Archivos CSV», la página de solo lectura actual, se queda.
4. **Proyecto › Validación**:
   - una tabla con gravedad, mensaje, entidad, archivo y línea;
   - el conmutador «Mostrar heredados del juego base (n)»;
   - **[Arreglar]**, que muestra el plan de cambios (archivo · acción · diff) y pide confirmación; los arreglos
     `safe=False`, con confirmación explícita; los demás arreglos, en el desplegable;
   - **[¿Por qué?]**, que abre el panel del explicador con las capas, sus líneas y sus veredictos, la frase final
     y sus arreglos;
   - con doble clic se abre el archivo en esa línea (en Archivos).
   - F7 y el botón «Validar mod» de Archivos usan ya el validador nuevo.
5. **Panel de problemas** (`problems_dock.py`): compacto, con recuentos y la misma navegación.
6. **Paleta Ctrl+K** (`command_palette.py`):
   - busca en el índice con la localización efectiva (`SymbolIndex.search`, `display`);
   - muestra el tipo de cada resultado;
   - Intro abre el archivo en su línea.
7. **i18n ES/EN** de todo, sin claves crudas ni textos cortados. La prueba de paridad y la de claves en tiempo de
   ejecución lo vigilan.
8. **`tools/screenshot.py`** puede capturar, con un índice y un informe de demostración si hace falta: Textos ›
   Todos los textos, Proyecto › Validación (con el explicador abierto) y la paleta.
9. **Pruebas**:
   - de `LocSync`: el **criterio 6** con el minijuego y, con corpus, sobre VSM, que tiene su `text.csv`;
   - de cada pantalla, contra el `Project` real cuando se pueda (como `test_ui_real_project`) y con el índice o
     el validador falsos donde aún no hay real;
   - las que dependan de lo de A, con `skipUnless`, hasta que el orquestador integre;
   - comprueba con mutaciones que las importantes detectan el fallo.

## Reglas del proyecto (obligatorias)

- Identificadores en inglés; docstrings y comentarios en español, concisos. Compatible con Python 3.10 y PySide6
  6.5 (el mínimo).
  - Si puedes, pasa también tus pruebas con
    `/tmp/claude-0/-home-user-VictoriaII-ModWizard/fc57859e-57cd-5f57-a8a9-c0c50763ef14/scratchpad/review/compatibilidad-verificar/v650min/bin/python`
    (sin `XDG_RUNTIME_DIR`) y con `/tmp/py310/bin/python`.
- Todo texto visible pasa por `tr()`, con paridad ES/EN.
- Ningún widget abre ni escribe archivos: todo pasa por `Session` → `Project`. Solo `core/fileio.py` escribe en
  crudo (`test_arch_writes`).
- Todo cambio es deshacible (I5).
- Leer, indexar o validar no escriben nada (I4).
- **Datos de Paradox.** Nunca subas datos de Paradox al repositorio; usa el minijuego o la muestra
  `tests/fixtures/shago_mod_min`.
- **Pruebas:**
  - cada fallo arreglado lleva su prueba de regresión;
  - antes de terminar, pasa la batería entera con
    `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests` desde la raíz, también con
    `VIC2_CORPUS="/home/user/corpus/vanilla:/home/user/corpus/Plantilla Mod:/home/user/corpus/ShagoMod"`.
- **Carga compartida.** El agente A está pasando pruebas a la vez en la misma máquina, así que las pruebas de
  latencia pueden fallar por la carga. Repítelas solas antes de darlas por rotas.
- **Contrato.** Puedes ampliar `core/locsync.py` de forma compatible, pero no cambies las firmas de
  `core/index`/`core/validate`: si te falta algo de A, dilo en el informe.

## Al terminar

- Haz commit en tu copia (worktree), en commits con mensaje en español. **No hagas push.**
- Tu respuesta final es un informe para el orquestador:
  - qué está hecho y qué no;
  - la API que añadiste a `Session`;
  - qué falsos hay que retirar al integrar;
  - las pruebas omitidas a la espera de A;
  - los resultados de las baterías;
  - lo que necesitas de A.
